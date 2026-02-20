/**
 * Custom hook encapsulating the full voice mode pipeline:
 * MediaRecorder + VAD + WebSocket + STT auto-submit.
 * Extracted from ChatInterface.tsx.
 */
import { useState, useRef, useEffect } from 'react';
import { apiClient } from '@/lib/apiClient';
import {
    buildVoiceWsUrl,
    normalizeAutoSendText,
    shouldSkipAutoSend,
    toNum,
} from './voiceModeUtils';

export interface UseVoiceModeOptions {
    threadId: string;
    isLoading: boolean;
    interruptAudioPlayback: () => void;
    isPlayingRef: React.MutableRefObject<boolean>;
    sendMessageRef: React.MutableRefObject<(text?: string) => Promise<void>>;
    micVadRef: React.MutableRefObject<any>;
}

export function useVoiceMode({
    threadId,
    isLoading,
    interruptAudioPlayback,
    isPlayingRef,
    sendMessageRef,
    micVadRef,
}: UseVoiceModeOptions) {
    // ── State ──
    const [voiceModeEnabled, setVoiceModeEnabled] = useState(false);
    const [voiceWsState, setVoiceWsState] = useState<"idle" | "connecting" | "connected" | "error">("idle");
    const [voiceError, setVoiceError] = useState<string | null>(null);
    const [sttPreview, setSttPreview] = useState<string>("");

    // ── Refs ──
    const voiceWsRef = useRef<WebSocket | null>(null);
    const mediaRecorderRef = useRef<MediaRecorder | null>(null);
    const mediaStreamRef = useRef<MediaStream | null>(null);
    const voiceChunkSeqRef = useRef<number>(0);
    const voiceSessionIdRef = useRef<string>("");
    const vadStreamRef = useRef<MediaStream | null>(null);
    const vadMaxTurnTimerRef = useRef<number | null>(null);
    const vadAwaitingFinalRef = useRef<boolean>(false);
    const vadSpeechActiveRef = useRef<boolean>(false);
    const voiceCurrentUtteranceIdRef = useRef<string>("");
    const voiceUtteranceCounterRef = useRef<number>(0);
    const speechSendingRef = useRef<boolean>(false);
    const preRollChunksRef = useRef<Blob[]>([]);
    const webmHeaderBlobRef = useRef<Blob | null>(null);
    const pendingVoiceSendRef = useRef<string | null>(null);
    const lastAutoSentTextRef = useRef<string>("");
    const lastAutoSentAtRef = useRef<number>(0);
    const tryAutoSendRef = useRef<(text: string) => void>(() => {});
    const restartRecorderRef = useRef<() => void>(() => {});

    // ── VAD Constants ──
    const VAD_MIN_CHUNKS = toNum(process.env.NEXT_PUBLIC_VAD_MIN_CHUNKS, 3);
    const VAD_MAX_TURN_MS = toNum(process.env.NEXT_PUBLIC_VAD_MAX_TURN_MS, 6000);
    const VAD_POSITIVE_THRESHOLD = toNum(process.env.NEXT_PUBLIC_VAD_POSITIVE_THRESHOLD, 0.5);
    const VAD_NEGATIVE_THRESHOLD = toNum(process.env.NEXT_PUBLIC_VAD_NEGATIVE_THRESHOLD, 0.35);
    const VAD_REDEMPTION_MS = toNum(process.env.NEXT_PUBLIC_VAD_REDEMPTION_MS, 700);
    const VAD_MIN_SPEECH_MS = toNum(process.env.NEXT_PUBLIC_VAD_MIN_SPEECH_MS, 250);
    const VAD_PRE_SPEECH_PAD_MS = toNum(process.env.NEXT_PUBLIC_VAD_PRE_SPEECH_PAD_MS, 300);
    const VOICE_CHUNK_MS = toNum(process.env.NEXT_PUBLIC_VOICE_CHUNK_MS, 500);
    const VAD_PRE_ROLL_MS = toNum(process.env.NEXT_PUBLIC_VAD_PRE_ROLL_MS, 450);
    const VAD_PRE_ROLL_CHUNKS = Math.max(1, Math.ceil(VAD_PRE_ROLL_MS / Math.max(100, VOICE_CHUNK_MS)));
    const AUDIO_ECHO_CANCELLATION = String(process.env.NEXT_PUBLIC_AUDIO_ECHO_CANCELLATION ?? "1") !== "0";
    const AUDIO_NOISE_SUPPRESSION = String(process.env.NEXT_PUBLIC_AUDIO_NOISE_SUPPRESSION ?? "0") === "1";
    const AUDIO_AUTO_GAIN = String(process.env.NEXT_PUBLIC_AUDIO_AUTO_GAIN ?? "1") !== "0";

    // ── Helpers ──

    const blobToBase64 = (blob: Blob): Promise<string> =>
        new Promise((resolve, reject) => {
            const reader = new FileReader();
            reader.onloadend = () => {
                const result = String(reader.result || "");
                const payload = result.includes(",") ? result.split(",")[1] : "";
                resolve(payload);
            };
            reader.onerror = reject;
            reader.readAsDataURL(blob);
        });

    const cleanupVoiceRuntime = () => {
        const rec = mediaRecorderRef.current;
        if (rec && rec.state !== "inactive") {
            rec.stop();
        }
        mediaRecorderRef.current = null;

        const stream = mediaStreamRef.current;
        if (stream) {
            stream.getTracks().forEach((t) => t.stop());
        }
        mediaStreamRef.current = null;

        const ws = voiceWsRef.current;
        if (ws) {
            try {
                ws.close();
            } catch {}
        }
        voiceWsRef.current = null;

        const vad = micVadRef.current;
        if (vad) {
            vad.destroy().catch(() => {});
            micVadRef.current = null;
        }
        const vs = vadStreamRef.current;
        if (vs) {
            vs.getTracks().forEach((t: MediaStreamTrack) => t.stop());
            vadStreamRef.current = null;
        }
        if (vadMaxTurnTimerRef.current != null) {
            window.clearTimeout(vadMaxTurnTimerRef.current);
            vadMaxTurnTimerRef.current = null;
        }
        vadAwaitingFinalRef.current = false;
        vadSpeechActiveRef.current = false;
        voiceCurrentUtteranceIdRef.current = "";
        speechSendingRef.current = false;
        preRollChunksRef.current = [];
    };

    const sendVoiceTurnEnd = (
        ws: WebSocket | null,
        mimeType: string,
        meta?: { source?: string; rms?: number; speechMs?: number; chunks?: number; utteranceId?: string },
    ) => {
        if (!ws || ws.readyState !== WebSocket.OPEN) return;
        try {
            ws.send(
                JSON.stringify({
                    type: "voice_turn_end",
                    utterance_id: meta?.utteranceId || voiceCurrentUtteranceIdRef.current || "default",
                    mime_type: mimeType || "audio/webm",
                    source: meta?.source || "manual",
                    rms: meta?.rms,
                    speech_ms: meta?.speechMs,
                    chunks: meta?.chunks,
                }),
            );
            vadAwaitingFinalRef.current = true;
        } catch (e) {
            console.warn("[VOICE][DBG] turnEnd send error", e);
        }
    };

    const nextUtteranceId = () => {
        voiceUtteranceCounterRef.current += 1;
        return `utt-${Date.now()}-${voiceUtteranceCounterRef.current}`;
    };

    const sendChunkBlob = async (
        blob: Blob,
        ws: WebSocket | null,
        sessionId: string,
        fallbackMime: string,
        utteranceId: string,
    ) => {
        if (!blob || blob.size <= 0) return;
        if (!ws || ws.readyState !== WebSocket.OPEN) return;
        if (!utteranceId) return;
        const seq = ++voiceChunkSeqRef.current;
        try {
            const chunkB64 = await blobToBase64(blob);
            ws.send(
                JSON.stringify({
                    type: "voice_chunk",
                    seq,
                    session_id: sessionId,
                    utterance_id: utteranceId,
                    mime_type: blob.type || fallbackMime || "audio/webm",
                    payload_b64: chunkB64,
                    size: blob.size,
                }),
            );
        } catch (e) {
            console.warn("[VOICE] chunk encode failed", e);
        }
    };

    const setupMicVad = async (stream: MediaStream, ws: WebSocket, mimeType: string) => {
        try {
            const { MicVAD } = await import("@ricky0123/vad-web");

            vadAwaitingFinalRef.current = false;
            vadSpeechActiveRef.current = false;

            const vadStream = stream.clone();
            vadStreamRef.current = vadStream;
            const micVad = await MicVAD.new({
                getStream: async () => vadStream,
                baseAssetPath: "/vad/",
                onnxWASMBasePath: "/vad/",
                positiveSpeechThreshold: VAD_POSITIVE_THRESHOLD,
                negativeSpeechThreshold: VAD_NEGATIVE_THRESHOLD,
                redemptionMs: VAD_REDEMPTION_MS,
                minSpeechMs: VAD_MIN_SPEECH_MS,
                preSpeechPadMs: VAD_PRE_SPEECH_PAD_MS,

                onSpeechStart: () => {
                    if (vadAwaitingFinalRef.current) return;

                    if (isPlayingRef.current) {
                        interruptAudioPlayback();
                    }

                    vadSpeechActiveRef.current = true;
                    const utteranceId = nextUtteranceId();
                    voiceCurrentUtteranceIdRef.current = utteranceId;
                    speechSendingRef.current = true;
                    voiceChunkSeqRef.current = 0;

                    const sid = voiceSessionIdRef.current;
                    const headerBlob = webmHeaderBlobRef.current;
                    if (headerBlob) {
                        void sendChunkBlob(headerBlob, ws, sid, mimeType, utteranceId);
                    }
                    const preRoll = [...preRollChunksRef.current];
                    preRollChunksRef.current = [];
                    for (const chunk of preRoll) {
                        if (chunk === headerBlob) continue;
                        void sendChunkBlob(chunk, ws, sid, mimeType, utteranceId);
                    }

                    if (vadMaxTurnTimerRef.current != null) {
                        window.clearTimeout(vadMaxTurnTimerRef.current);
                    }
                    vadMaxTurnTimerRef.current = window.setTimeout(() => {
                        if (!vadSpeechActiveRef.current) return;
                        speechSendingRef.current = false;
                        vadSpeechActiveRef.current = false;
                        vadAwaitingFinalRef.current = true;
                        sendVoiceTurnEnd(ws, mimeType, {
                            source: "vad_max_turn",
                            utteranceId: voiceCurrentUtteranceIdRef.current || undefined,
                            chunks: voiceChunkSeqRef.current,
                        });
                    }, VAD_MAX_TURN_MS);
                },

                onSpeechEnd: (_audio: Float32Array) => {
                    if (!vadSpeechActiveRef.current) return;

                    if (vadMaxTurnTimerRef.current != null) {
                        window.clearTimeout(vadMaxTurnTimerRef.current);
                        vadMaxTurnTimerRef.current = null;
                    }

                    if (voiceChunkSeqRef.current < VAD_MIN_CHUNKS) {
                        vadSpeechActiveRef.current = false;
                        speechSendingRef.current = false;
                        voiceCurrentUtteranceIdRef.current = "";
                        return;
                    }

                    speechSendingRef.current = false;
                    vadSpeechActiveRef.current = false;
                    vadAwaitingFinalRef.current = true;
                    sendVoiceTurnEnd(ws, mimeType, {
                        source: "vad_silence",
                        utteranceId: voiceCurrentUtteranceIdRef.current || undefined,
                        chunks: voiceChunkSeqRef.current,
                    });
                },

                onVADMisfire: () => {
                    if (vadMaxTurnTimerRef.current != null) {
                        window.clearTimeout(vadMaxTurnTimerRef.current);
                        vadMaxTurnTimerRef.current = null;
                    }
                    vadSpeechActiveRef.current = false;
                    speechSendingRef.current = false;
                    voiceCurrentUtteranceIdRef.current = "";
                },
            });

            micVad.start();
            micVadRef.current = micVad;
        } catch (e) {
            console.warn("[VOICE] VAD setup failed", e);
        }
    };

    // ── Auto-send logic ──

    const tryAutoSendVoiceText = (raw: string) => {
        const text = normalizeAutoSendText(raw);

        const now = Date.now();
        const prev = lastAutoSentTextRef.current;
        const dt = now - lastAutoSentAtRef.current;
        if (shouldSkipAutoSend(text, prev, dt)) return;

        if (isLoading) {
            pendingVoiceSendRef.current = text;
            return;
        }
        lastAutoSentTextRef.current = text;
        lastAutoSentAtRef.current = now;
        sendMessageRef.current(text);
    };
    tryAutoSendRef.current = tryAutoSendVoiceText;

    // ── Start / Stop ──

    const stopVoiceMode = async () => {
        const ws = voiceWsRef.current;
        if (ws && ws.readyState === WebSocket.OPEN && speechSendingRef.current && voiceChunkSeqRef.current > 0) {
            try {
                sendVoiceTurnEnd(ws, "audio/webm", { source: "manual_stop" });
                await new Promise((r) => setTimeout(r, 120));
            } catch {}
        }
        cleanupVoiceRuntime();
        const sid = voiceSessionIdRef.current;
        voiceSessionIdRef.current = "";
        setVoiceModeEnabled(false);
        setVoiceWsState("idle");
        setSttPreview("");
        if (sid) {
            try {
                await apiClient.stopVoiceSession(sid);
            } catch (e) {
                console.warn("[VOICE] session stop failed", e);
            }
        }
    };

    const startVoiceMode = async () => {
        if (voiceModeEnabled) return;
        setVoiceError(null);
        setSttPreview("");
        setVoiceWsState("connecting");

        const clientId = `web-${threadId || "default_thread"}`;
        try {
            const startData = await apiClient.startVoiceSession(
                threadId || "default_thread",
                clientId,
            );
            const sid = String(startData?.session?.session_id || "");
            if (!sid) throw new Error("voice session_id missing");
            voiceSessionIdRef.current = sid;

            const stream = await navigator.mediaDevices.getUserMedia({
                audio: {
                    echoCancellation: AUDIO_ECHO_CANCELLATION,
                    noiseSuppression: AUDIO_NOISE_SUPPRESSION,
                    autoGainControl: AUDIO_AUTO_GAIN,
                    channelCount: 1,
                },
            });
            mediaStreamRef.current = stream;

            const mimeCandidates = ["audio/webm;codecs=opus", "audio/webm", "audio/ogg;codecs=opus"];
            const mimeType =
                mimeCandidates.find((m) => {
                    try {
                        return MediaRecorder.isTypeSupported(m);
                    } catch {
                        return false;
                    }
                }) || "";

            const wsUrl = buildVoiceWsUrl({
                sessionId: sid,
                clientId,
                explicitBase: process.env.NEXT_PUBLIC_VOICE_WS_BASE || "",
                protocol: window.location.protocol,
                hostname: window.location.hostname,
                backendPort: process.env.NEXT_PUBLIC_BACKEND_PORT || "8000",
            });
            const ws = new WebSocket(wsUrl);
            voiceWsRef.current = ws;
            voiceChunkSeqRef.current = 0;
            voiceCurrentUtteranceIdRef.current = "";
            speechSendingRef.current = false;
            preRollChunksRef.current = [];

            let wsReconnectAttempt = 0;
            const WS_MAX_RECONNECT = 3;
            const WS_NO_RECONNECT_CODES = new Set([1000, 1008]);

            // Named handlers to avoid stale closure on reconnect
            const handleOpen = () => {
                setVoiceWsState("connected");
            };
            const handleClose = (ev: CloseEvent) => {
                if (
                    !WS_NO_RECONNECT_CODES.has(ev.code) &&
                    wsReconnectAttempt < WS_MAX_RECONNECT &&
                    voiceModeEnabled
                ) {
                    wsReconnectAttempt++;
                    const delay = Math.min(1000 * Math.pow(2, wsReconnectAttempt - 1), 4000);
                    setVoiceWsState("connecting");
                    setTimeout(() => {
                        if (!voiceModeEnabled) return;
                        try {
                            const newWs = new WebSocket(wsUrl);
                            voiceWsRef.current = newWs;
                            newWs.onopen = handleOpen;
                            newWs.onclose = handleClose;
                            newWs.onerror = handleError;
                            newWs.onmessage = handleMessage;
                        } catch (e) {
                            console.error("[VOICE][WS] reconnect failed", e);
                            cleanupVoiceRuntime();
                            setVoiceWsState("error");
                            setVoiceModeEnabled(false);
                            setVoiceError("WebSocket 再接続に失敗しました");
                        }
                    }, delay);
                } else {
                    cleanupVoiceRuntime();
                    setVoiceWsState("idle");
                    setVoiceModeEnabled(false);
                    if (wsReconnectAttempt >= WS_MAX_RECONNECT) {
                        setVoiceError("WebSocket 接続が不安定です。再度お試しください。");
                    }
                }
            };
            const handleError = () => {
                setVoiceWsState("error");
                setVoiceError("voice ws 接続でエラーが発生しました");
            };
            const handleMessage = (ev: MessageEvent) => {
                try {
                    const data = JSON.parse(ev.data);
                    if (data?.type === "voice_session_state") return;
                    if (data?.type === "stt_partial") {
                        const text = String(data?.text || "");
                        setSttPreview(text);
                        return;
                    }
                    if (data?.type === "stt_final") {
                        const finUtt = String(data?.utterance_id || "");
                        const activeUtt = voiceCurrentUtteranceIdRef.current;
                        if (finUtt && activeUtt && finUtt !== activeUtt) {
                            return;
                        }
                        vadAwaitingFinalRef.current = false;
                        speechSendingRef.current = false;
                        voiceCurrentUtteranceIdRef.current = "";
                        voiceChunkSeqRef.current = 0;
                        restartRecorderRef.current();
                        const text = String(data?.text || "");
                        if (text) {
                            setSttPreview(text);
                            tryAutoSendRef.current(text);
                        } else if (data?.reason) {
                            const reason = String(data.reason || "");
                            if (reason !== "audio decode failed") {
                                setVoiceError(reason);
                            } else {
                                console.warn("[VOICE] transient decode failure", data);
                            }
                        }
                        return;
                    }
                    if (data?.type === "voice_session_closed") {
                        cleanupVoiceRuntime();
                        setVoiceModeEnabled(false);
                        setVoiceWsState("idle");
                        return;
                    }
                } catch {}
            };

            ws.onopen = handleOpen;
            ws.onclose = handleClose;
            ws.onerror = handleError;
            ws.onmessage = handleMessage;

            const makeChunkHandler = () => async (evt: BlobEvent) => {
                if (!evt.data || evt.data.size <= 0) return;
                const socket = voiceWsRef.current;
                if (!socket || socket.readyState !== WebSocket.OPEN) return;
                if (!webmHeaderBlobRef.current) {
                    webmHeaderBlobRef.current = evt.data;
                }
                preRollChunksRef.current.push(evt.data);
                if (preRollChunksRef.current.length > VAD_PRE_ROLL_CHUNKS) {
                    preRollChunksRef.current = preRollChunksRef.current.slice(-VAD_PRE_ROLL_CHUNKS);
                }
                if (!speechSendingRef.current) return;
                const utteranceId = voiceCurrentUtteranceIdRef.current;
                if (!utteranceId) return;
                await sendChunkBlob(evt.data, socket, sid, mimeType || "audio/webm", utteranceId);
            };
            const makeRecorderErrorHandler = () => (evt: any) => {
                console.error("[VOICE] recorder error", evt);
                setVoiceWsState("error");
            };

            const createRecorder = () => {
                const rec = mimeType ? new MediaRecorder(stream, { mimeType }) : new MediaRecorder(stream);
                rec.ondataavailable = makeChunkHandler();
                rec.onerror = makeRecorderErrorHandler();
                return rec;
            };

            const recorder = createRecorder();
            mediaRecorderRef.current = recorder;

            restartRecorderRef.current = () => {
                const oldRec = mediaRecorderRef.current;
                if (oldRec) {
                    oldRec.ondataavailable = null;
                    if (oldRec.state !== "inactive") oldRec.stop();
                }
                preRollChunksRef.current = [];
                webmHeaderBlobRef.current = null;
                const newRec = createRecorder();
                mediaRecorderRef.current = newRec;
                newRec.start(VOICE_CHUNK_MS);
            };

            recorder.start(VOICE_CHUNK_MS);
            await setupMicVad(stream, ws, mimeType || "audio/webm");
            setVoiceModeEnabled(true);
        } catch (e: any) {
            console.error("[VOICE] start failed", e);
            setVoiceError(e?.message || "voice mode start failed");
            setVoiceWsState("error");
            await stopVoiceMode();
        }
    };

    // ── Pending voice send (when isLoading clears) ──
    useEffect(() => {
        if (isLoading) return;
        const queued = pendingVoiceSendRef.current;
        if (!queued) return;
        pendingVoiceSendRef.current = null;
        const now = Date.now();
        lastAutoSentTextRef.current = queued;
        lastAutoSentAtRef.current = now;
        sendMessageRef.current(queued);
    }, [isLoading]);

    const toggleVoiceMode = async () => {
        if (voiceModeEnabled) {
            await stopVoiceMode();
        } else {
            await startVoiceMode();
        }
    };

    return {
        voiceModeEnabled,
        voiceWsState,
        voiceError,
        sttPreview,
        toggleVoiceMode,
        cleanupVoiceRuntime,
    };
}
