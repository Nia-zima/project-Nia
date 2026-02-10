"use client";
import React, { useState, useRef, useEffect } from 'react';
import { Send, Mic, Image as ImageIcon, StopCircle } from 'lucide-react';
import { API_URL, ChatMessage, getStaticUrl } from '@/lib/api';
import { motion, AnimatePresence } from 'framer-motion';

interface ChatInterfaceProps {
    onStateChange: (isTalking: boolean, emotion: string, isThinking?: boolean) => void;
    onAgentStateChange?: (state: string) => void;
    agentMode: string;
}

interface ReviewRequestPayload {
    review_token: string;
    hold_kind?: string;
    preview_text?: string;
    reason_codes?: string[];
}

export default function ChatInterface({ onStateChange, onAgentStateChange, agentMode }: ChatInterfaceProps) {
    const [messages, setMessages] = useState<ChatMessage[]>([]);
    const [input, setInput] = useState("");
    const [isLoading, setIsLoading] = useState(false);
    const [threadId, setThreadId] = useState<string>("");
    const [currentEmotion, setCurrentEmotion] = useState("neutral");
    const [isThinking, setIsThinking] = useState(false);
    const [connectionState, setConnectionState] = useState<"ok" | "stale">("ok");
    const [thinkingHint, setThinkingHint] = useState<any | null>(null);
    const [reviewRequest, setReviewRequest] = useState<ReviewRequestPayload | null>(null);
    const [pendingActions, setPendingActions] = useState<any[]>([]);
    const [pendingMeta, setPendingMeta] = useState<{ pending_count: number; dissonance_delta: number } | null>(null);
    const [pendingLoading, setPendingLoading] = useState(false);
    const [pendingError, setPendingError] = useState<string | null>(null);
    const [pendingReasonById, setPendingReasonById] = useState<Record<string, string>>({});
    const [latestCommitLog, setLatestCommitLog] = useState<any | null>(null);

    // Vision State
    const [selectedImage, setSelectedImage] = useState<string | null>(null);
    const fileInputRef = useRef<HTMLInputElement>(null);

    const AFFECT_REGEX = /\[(happy|sad|angry|relaxed|surprised|shy|sigh|neutral|consent|dissonance)\]/g;
    const scrollRef = useRef<HTMLDivElement>(null);

    // Audio Playback Queue
    const audioQueueRef = useRef<string[]>([]);
    const isPlayingRef = useRef(false);
    const audioRef = useRef<HTMLAudioElement | null>(null);

    // Stream Refs
    const aiMsgIdRef = useRef<string | null>(null);
    const aiTextRef = useRef<string>("");
    const isStreamingRef = useRef(false);
    const isThinkingRef = useRef(false);
    const lastEventAtRef = useRef<number>(0);
    const activeStreamIdRef = useRef<number>(0);
    const sseStreamIdRef = useRef<string | null>(null);
    const abortControllerRef = useRef<AbortController | null>(null);
    const currentStateRef = useRef<string>("");
    const ttsEsRef = useRef<EventSource | null>(null);
    const voiceWsRef = useRef<WebSocket | null>(null);
    const mediaRecorderRef = useRef<MediaRecorder | null>(null);
    const mediaStreamRef = useRef<MediaStream | null>(null);
    const voiceChunkSeqRef = useRef<number>(0);
    const voiceSessionIdRef = useRef<string>("");
    const micVadRef = useRef<any>(null);
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
    const sendMessageRef = useRef<(text?: string) => Promise<void>>(async () => {});
    const restartRecorderRef = useRef<() => void>(() => {});

    const [voiceModeEnabled, setVoiceModeEnabled] = useState(false);
    const [voiceWsState, setVoiceWsState] = useState<"idle" | "connecting" | "connected" | "error">("idle");
    const [voiceError, setVoiceError] = useState<string | null>(null);
    const [sttPreview, setSttPreview] = useState<string>("");

    const syncThinking = (next: boolean) => {
        isThinkingRef.current = next;
        setIsThinking(next);
        onStateChange(isPlayingRef.current, currentEmotion, next);
    };

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

    const buildVoiceWsUrl = (sessionId: string, clientId: string) => {
        const wsScheme = window.location.protocol === "https:" ? "wss" : "ws";
        const wsBase = API_URL.startsWith("http")
            ? API_URL.replace(/^http/i, "ws")
            : `${wsScheme}://${window.location.host}${API_URL}`;
        const qs = `session_id=${encodeURIComponent(sessionId)}&client_id=${encodeURIComponent(clientId)}`;
        return `${wsBase}/voice/ws?${qs}`;
    };

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
            } catch { }
        }
        voiceWsRef.current = null;

        const vad = micVadRef.current;
        if (vad) {
            vad.destroy().catch(() => { });
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

    const interruptAudioPlayback = () => {
        const audio = audioRef.current;
        if (audio) {
            try {
                audio.pause();
                audio.currentTime = 0;
            } catch { }
        }
        audioQueueRef.current = [];
        isPlayingRef.current = false;
        onStateChange(false, currentEmotion, isThinkingRef.current);
        // barge-in: TTS停止後にVADを再開
        micVadRef.current?.start().catch(() => {});
    };

    const toNum = (v: string | undefined, fallback: number) => {
        const n = Number(v);
        return Number.isFinite(n) ? n : fallback;
    };
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

    const sendVoiceTurnEnd = (
        ws: WebSocket | null,
        mimeType: string,
        meta?: { source?: string; rms?: number; speechMs?: number; chunks?: number; utteranceId?: string }
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
                })
            );
            vadAwaitingFinalRef.current = true;
        } catch { }
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
        utteranceId: string
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
                })
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

            // vad-web は内部で AudioContext + AudioWorklet を作成する。
            // 同じ MediaStream を共有すると MediaRecorder の録音品質に
            // 干渉するケースがあるため、クローンを渡して隔離する。
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
                        console.log("[VOICE][VAD] max_turn", { chunks: voiceChunkSeqRef.current });
                        sendVoiceTurnEnd(ws, mimeType, {
                            source: "vad_max_turn",
                            utteranceId: voiceCurrentUtteranceIdRef.current || undefined,
                            chunks: voiceChunkSeqRef.current,
                        });
                    }, VAD_MAX_TURN_MS);

                    console.log("[VOICE][VAD] speech_start (silero)");
                },

                onSpeechEnd: (_audio: Float32Array) => {
                    if (!vadSpeechActiveRef.current) return;

                    if (vadMaxTurnTimerRef.current != null) {
                        window.clearTimeout(vadMaxTurnTimerRef.current);
                        vadMaxTurnTimerRef.current = null;
                    }

                    if (voiceChunkSeqRef.current < VAD_MIN_CHUNKS) {
                        console.log("[VOICE][VAD] speech too short, ignoring", { chunks: voiceChunkSeqRef.current });
                        vadSpeechActiveRef.current = false;
                        speechSendingRef.current = false;
                        voiceCurrentUtteranceIdRef.current = "";
                        return;
                    }

                    // speechSending を先に切ってから turn_end を送る。
                    // レコーダーは止めない — stt_final で初めてリスタートする。
                    // こうすると最終チャンク（発話末尾）がサーバーに届く。
                    speechSendingRef.current = false;
                    vadSpeechActiveRef.current = false;
                    vadAwaitingFinalRef.current = true;
                    console.log("[VOICE][VAD] speech_end (silero)", { chunks: voiceChunkSeqRef.current });
                    sendVoiceTurnEnd(ws, mimeType, {
                        source: "vad_silence",
                        utteranceId: voiceCurrentUtteranceIdRef.current || undefined,
                        chunks: voiceChunkSeqRef.current,
                    });
                },

                onVADMisfire: () => {
                    console.log("[VOICE][VAD] misfire (speech too short)");
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
            console.log("[VOICE][VAD] Silero VAD initialized");
        } catch (e) {
            console.warn("[VOICE] VAD setup failed", e);
        }
    };

    const tryAutoSendVoiceText = (raw: string) => {
        const text = String(raw || "").trim();
        if (!text) return;

        const now = Date.now();
        const prev = lastAutoSentTextRef.current;
        const dt = now - lastAutoSentAtRef.current;
        if (text === prev && dt < 4000) {
            console.log("[VOICE] auto-send dedupe skip", { text, dt });
            return;
        }

        if (isLoading) {
            pendingVoiceSendRef.current = text;
            console.log("[VOICE] auto-send queued", { text, isLoading });
            return;
        }

        console.log("[VOICE] auto-send now", { text });
        lastAutoSentTextRef.current = text;
        lastAutoSentAtRef.current = now;
        sendMessage(text);
    };
    tryAutoSendRef.current = tryAutoSendVoiceText;

    const stopVoiceMode = async () => {
        const ws = voiceWsRef.current;
        if (ws && ws.readyState === WebSocket.OPEN && speechSendingRef.current && voiceChunkSeqRef.current > 0) {
            try {
                sendVoiceTurnEnd(ws, "audio/webm", { source: "manual_stop" });
                await new Promise((r) => setTimeout(r, 120));
            } catch { }
        }
        cleanupVoiceRuntime();
        const sid = voiceSessionIdRef.current;
        voiceSessionIdRef.current = "";
        setVoiceModeEnabled(false);
        setVoiceWsState("idle");
        setSttPreview("");
        if (sid) {
            try {
                await fetch(`${API_URL}/voice/session/stop`, {
                    method: "POST",
                    headers: { "Content-Type": "application/json" },
                    body: JSON.stringify({ session_id: sid, reason: "client_stop" }),
                });
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
            const startRes = await fetch(`${API_URL}/voice/session/start`, {
                method: "POST",
                headers: { "Content-Type": "application/json" },
                body: JSON.stringify({
                    thread_id: threadId || "default_thread",
                    client_id: clientId,
                }),
            });
            if (!startRes.ok) {
                throw new Error(`voice session start failed: ${startRes.status}`);
            }
            const startData = await startRes.json();
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
            const mimeType = mimeCandidates.find((m) => {
                try {
                    return MediaRecorder.isTypeSupported(m);
                } catch {
                    return false;
                }
            }) || "";

            const ws = new WebSocket(buildVoiceWsUrl(sid, clientId));
            voiceWsRef.current = ws;
            voiceChunkSeqRef.current = 0;
            voiceCurrentUtteranceIdRef.current = "";
            speechSendingRef.current = false;
            preRollChunksRef.current = [];

            ws.onopen = () => {
                setVoiceWsState("connected");
            };
            ws.onclose = () => {
                cleanupVoiceRuntime();
                setVoiceWsState("idle");
                setVoiceModeEnabled(false);
            };
            ws.onerror = () => {
                setVoiceWsState("error");
                setVoiceError("voice ws 接続でエラーが発生しました");
            };
            ws.onmessage = (ev) => {
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
                            console.log("[VOICE] stale stt_final ignored", { finUtt, activeUtt });
                            return;
                        }
                        vadAwaitingFinalRef.current = false;
                        speechSendingRef.current = false;
                        voiceCurrentUtteranceIdRef.current = "";
                        // Reset chunk counter so VAD minimum-chunk guard works for next turn
                        voiceChunkSeqRef.current = 0;
                        // Restart MediaRecorder to produce a fresh webm container header
                        // for the next turn (continuation chunks lack the header and
                        // cause ffmpeg decode failures).
                        restartRecorderRef.current();
                        const text = String(data?.text || "");
                        if (text) {
                            setSttPreview(text);
                            // Voice mode: auto-submit recognized text (or queue if currently busy/reviewing)
                            tryAutoSendRef.current(text);
                        } else if (data?.reason) {
                            const reason = String(data.reason || "");
                            // decode失敗は一過性のことが多いので、UIエラー表示は抑制
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
                } catch { }
            };

            const makeChunkHandler = () => async (evt: BlobEvent) => {
                if (!evt.data || evt.data.size <= 0) return;
                const socket = voiceWsRef.current;
                if (!socket || socket.readyState !== WebSocket.OPEN) return;
                // Save the very first chunk from this recorder instance as the
                // webm header (EBML + Segment + Tracks).  Pre-roll rotation
                // would discard it, so we keep a separate ref.
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
                const rec = mimeType
                    ? new MediaRecorder(stream, { mimeType })
                    : new MediaRecorder(stream);
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
                // Discard stale pre-roll and header from the old recorder
                preRollChunksRef.current = [];
                webmHeaderBlobRef.current = null;
                const newRec = createRecorder();
                mediaRecorderRef.current = newRec;
                newRec.start(VOICE_CHUNK_MS);
                console.log("[VOICE] recorder restarted for fresh webm container");
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

    useEffect(() => {
        if (isLoading) return;
        const queued = pendingVoiceSendRef.current;
        if (!queued) return;
        pendingVoiceSendRef.current = null;
        const now = Date.now();
        lastAutoSentTextRef.current = queued;
        lastAutoSentAtRef.current = now;
        console.log("[VOICE] auto-send flush queued", { text: queued });
        sendMessageRef.current(queued);
    }, [isLoading]);

    const toggleVoiceMode = async () => {
        if (voiceModeEnabled) {
            await stopVoiceMode();
        } else {
            await startVoiceMode();
        }
    };

    const addSystemMessage = (content: string) => {
        setMessages(prev => [...prev, { id: newId(), role: 'system', content }]);
    };

    const fetchPendingActions = async (opts?: { limit?: number; offset?: number }) => {
        setPendingLoading(true);
        setPendingError(null);
        try {
            const tid = threadId || "default_thread";
            const limit = opts?.limit ?? 50;
            const offset = opts?.offset ?? 0;
            const res = await fetch(
                `${API_URL}/actions/pending?thread_id=${encodeURIComponent(tid)}&limit=${limit}&offset=${offset}`,
                { cache: "no-store" }
            );
            if (!res.ok) {
                throw new Error(`pending_actions fetch failed: ${res.status}`);
            }
            const data = await res.json();
            setPendingActions(Array.isArray(data?.items) ? data.items : []);
            setPendingMeta(data?.meta || null);
        } catch (e: any) {
            console.error("[pending_actions] fetch failed", e);
            setPendingError("保留アクションの取得に失敗しました");
        } finally {
            setPendingLoading(false);
        }
    };

    const fetchLatestCommitLog = async () => {
        try {
            const tid = threadId || "default_thread";
            const res = await fetch(
                `${API_URL}/actions/commit_log/latest?thread_id=${encodeURIComponent(tid)}`,
                { cache: "no-store" }
            );
            if (!res.ok) {
                throw new Error(`commit_log fetch failed: ${res.status}`);
            }
            const data = await res.json();
            setLatestCommitLog(data?.item || null);
        } catch (e) {
            console.warn("[commit_log] fetch failed", e);
        }
    };

    useEffect(() => {
        const timer = setInterval(() => {
            if (!isThinkingRef.current) return;
            const lastAt = lastEventAtRef.current || 0;
            if (Date.now() - lastAt > 30_000) {
                syncThinking(false);
                setConnectionState("stale");
                addSystemMessage("（通信が途切れたため、思考状態を解除しました）");
                const streamId = String(activeStreamIdRef.current || "");
                fetch(`${API_URL}/stream_timeout`, {
                    method: "POST",
                    headers: { "Content-Type": "application/json" },
                    body: JSON.stringify({
                        thread_id: threadId || "default_thread",
                        stream_id: streamId,
                        reason: "SSE timeout / no events for 30s",
                    }),
                }).catch(() => { });
            }
        }, 500);
        return () => clearInterval(timer);
    }, [threadId]);

    // Helper: Ensure IDs exist
    const ensureIds = (msgs: any[]): ChatMessage[] => {
        return msgs.map((m, i) => ({
            id: m.id || `hist-${Date.now()}-${i}`,
            ...m
        }));
    };

    // Helper: Generate new ID
    const newId = () => {
        if (typeof crypto !== 'undefined' && crypto.randomUUID) {
            return crypto.randomUUID();
        }
        return `msg-${Date.now()}-${Math.random().toString(36).slice(2)}`;
    };

    // Initialize Thread & Load History
    useEffect(() => {
        console.log("[ChatInterface] MOUNT", Date.now());
        const savedThreadId = "default_thread";
        setThreadId(savedThreadId);

        // 安全に content を文字列化（確定版）
        function safeContentToText(content: any): string {
            if (content == null) return "";
            if (typeof content === "string") return content;

            // OpenAI/LLMの「contentが配列」パターンを文字に寄せる
            if (Array.isArray(content)) {
                const texts = content
                    .map((p: any) => {
                        if (p?.type === "text") return p?.text ?? "";
                        if (p?.type === "image_url") return "[画像]";
                        return "";
                    })
                    .filter(Boolean);
                return texts.join("\n");
            }

            // オブジェクト1個で来る変種があっても落ちないように
            if (typeof content === "object") {
                if ("text" in content && typeof (content as any).text === "string") return (content as any).text;
                return "[non-string content]";
            }

            return String(content);
        }

        const loadHistory = async () => {
            if (isStreamingRef.current) return;

            console.log("[loadHistory] start");
            const t0 = performance.now();

            try {
                console.log("[loadHistory] fetching...");
                const res = await fetch(`${API_URL}/history/${savedThreadId}`, { cache: "no-store" });
                console.log("[loadHistory] fetched", res.status, "ms", (performance.now() - t0).toFixed(0));

                console.log("[loadHistory] parsing json...");
                const data = await res.json();
                console.log("[loadHistory] json parsed", "ms", (performance.now() - t0).toFixed(0));

                const hist = data?.history;
                console.log("[loadHistory] history type", Array.isArray(hist) ? "array" : typeof hist, "len", hist?.length);

                if (Array.isArray(hist)) {
                    // 非string検出とログ
                    let nonString = 0;
                    for (let i = 0; i < hist.length; i++) {
                        if (typeof hist[i]?.content !== "string") {
                            nonString++;
                            console.warn("[history] non-string content", {
                                index: i,
                                role: hist[i]?.role,
                                contentType: typeof hist[i]?.content,
                                keys: hist[i]?.content ? Object.keys(hist[i].content) : []
                            });
                        }
                    }
                    console.log("[loadHistory] non-string count", nonString);

                    const cleaned = hist.map((m: any) => normalizeHistoryMessage(m));

                    // パフォーマンス: 表示件数を制限（UIだけ軽く、データはDBに全部ある）
                    const MAX_RENDER = 120;
                    console.log("[loadHistory] setting messages...", `(showing last ${Math.min(cleaned.length, MAX_RENDER)} of ${cleaned.length})`);
                    setMessages(ensureIds(cleaned.slice(-MAX_RENDER)));
                    console.log("[loadHistory] done");
                }
            } catch (e) {
                console.error("[loadHistory] FAILED", e);
            } finally {
                console.log("[loadHistory] finally", "ms", (performance.now() - t0).toFixed(0));
            }
        };
        loadHistory();

        return () => {
            cleanupVoiceRuntime();
            console.log("[ChatInterface] UNMOUNT", Date.now());
        };
    }, []);

    useEffect(() => {
        if (scrollRef.current) {
            scrollRef.current.scrollTop = scrollRef.current.scrollHeight;
        }
    }, [messages]);

    const resumeVadAfterPlayback = () => {
        // キューに残りがなければ VAD を再開
        if (audioQueueRef.current.length === 0) {
            micVadRef.current?.start().catch(() => {});
        }
    };

    const processAudioQueue = async () => {
        if (isPlayingRef.current || audioQueueRef.current.length === 0) return;

        isPlayingRef.current = true;
        const audioUrl = audioQueueRef.current.shift();
        if (!audioUrl) {
            isPlayingRef.current = false;
            onStateChange(false, "neutral", isThinkingRef.current);
            resumeVadAfterPlayback();
            return;
        }

        // TTS 再生中は VAD を停止（エコーループ防止）
        micVadRef.current?.pause().catch(() => {});

        onStateChange(true, "happy", isThinkingRef.current);

        console.log("[AUDIO PLAY]", audioUrl);
        const audio = new Audio(audioUrl);
        audioRef.current = audio;

        audio.onended = () => {
            isPlayingRef.current = false;
            resumeVadAfterPlayback();
            setTimeout(processAudioQueue, 100);
        };

        audio.addEventListener("error", () => {
            console.error("[AUDIO ERROR]", audio.error, audioUrl);
            isPlayingRef.current = false;
            resumeVadAfterPlayback();
            setTimeout(processAudioQueue, 100);
        });
        await audio.play().catch((e) => {
            console.error("[PLAY REJECTED]", e, audioUrl);
            isPlayingRef.current = false;
            resumeVadAfterPlayback();
            setTimeout(processAudioQueue, 100);
        });
    };

    // --- Speech Recognition ---
    const [isListening, setIsListening] = useState(false);
    const recognitionRef = useRef<any>(null);

    useEffect(() => {
        if (typeof window !== 'undefined') {
            const SpeechRecognition = (window as any).SpeechRecognition || (window as any).webkitSpeechRecognition;
            if (SpeechRecognition) {
                const recognition = new SpeechRecognition();
                recognition.continuous = true;
                recognition.interimResults = true;
                recognition.lang = 'ja-JP';

                recognition.onresult = (event: any) => {
                    let finalTranscript = '';

                    for (let i = event.resultIndex; i < event.results.length; ++i) {
                        if (event.results[i].isFinal) {
                            finalTranscript += event.results[i][0].transcript;
                        }
                    }

                    if (finalTranscript) {
                        setInput(prev => prev + finalTranscript);
                    }
                };

                recognition.onerror = (event: any) => {
                    console.error("Speech Recognition Error:", event.error);
                    setIsListening(false);
                };

                recognition.onend = () => {
                    if (isListening) {
                        setIsListening(false);
                    }
                };

                recognitionRef.current = recognition;
            }
        }
    }, []);

    const toggleListening = () => {
        if (!recognitionRef.current) {
            alert("このブラウザは音声認識をサポートしていません。Chromeを使用してください。");
            return;
        }

        if (isListening) {
            recognitionRef.current.stop();
            setIsListening(false);
        } else {
            recognitionRef.current.start();
            setIsListening(true);
        }
    };

    const handleImageSelect = (e: React.ChangeEvent<HTMLInputElement>) => {
        const file = e.target.files?.[0];
        if (file) {
            const reader = new FileReader();
            reader.onloadend = () => setSelectedImage(reader.result as string);
            reader.readAsDataURL(file);
        }
    };

    // OpenAI互換 content を文字列に正規化
    type ContentPart =
        | { type: "text"; text?: string }
        | { type: "input_text"; text?: string }
        | { type: "image_url"; image_url?: { url?: string } }
        | { type: string;[k: string]: any };

    function normalizeContent(content: any): string {
        if (content == null) return "";

        // 文字列はそのまま
        if (typeof content === "string") return content;

        // 配列（OpenAI互換content）
        if (Array.isArray(content)) {
            return content
                .map((p: ContentPart) => {
                    if (!p) return "";
                    if (p.type === "text" || p.type === "input_text") return p.text ?? "";
                    if (p.type === "image_url") {
                        const url = p.image_url?.url ?? "";
                        // data: はデカいので表示はプレースホルダーにする
                        return url.startsWith("data:") ? "\n[画像]\n" : `\n[画像: ${url}]\n`;
                    }
                    return ""; // 不明タイプは無視
                })
                .join("")
                .trim();
        }

        // オブジェクト（変則ケース）
        if (typeof content === "object") {
            // よくある形を救済
            if ("text" in content && typeof (content as any).text === "string") return (content as any).text;
            if ("content" in content) return normalizeContent((content as any).content);

            // 最後の砦（巨大ログ化防止で短く）
            try {
                const s = JSON.stringify(content);
                return s.length > 500 ? s.slice(0, 500) + "…" : s;
            } catch {
                return String(content);
            }
        }

        return String(content);
    }

    // extractSpeech: normalizeContent を使って安全に string 化
    function extractSpeech(input: any): string {
        const text = normalizeContent(input);

        const idx = text.indexOf("\n[[");
        if (idx !== -1) return text.slice(0, idx).trim();

        if (text.trimStart().startsWith("[[")) {
            const lines = text.split("\n");
            const speechLines = lines.filter((l) => !l.trim().startsWith("[["));
            return speechLines.join("\n").trim();
        }

        return text.trim();
    }

    // OpenAI multipart 形式対応の normalizeHistoryMessage
    function normalizeHistoryMessage(m: any): ChatMessage {
        // 1) すでに文字列ならそのまま
        if (typeof m?.content === "string") {
            return { ...m, content: extractSpeech(m.content) };
        }

        // 2) OpenAI互換の multipart 形式（今回の原因）
        if (Array.isArray(m?.content)) {
            const parts = m.content;

            const textParts: string[] = [];
            let imageUrl: string | undefined;

            for (const p of parts) {
                if (p?.type === "text") {
                    if (typeof p.text === "string") textParts.push(p.text);
                } else if (p?.type === "image_url") {
                    const url = p?.image_url?.url;
                    if (typeof url === "string") imageUrl = url;
                }
            }

            const text = extractSpeech(textParts.join("\n").trim() || (imageUrl ? "[画像]" : ""));

            // ⚠️ data: のbase64はデカいので、履歴表示だけなら捨てるのが安全
            const safeImage =
                imageUrl && imageUrl.startsWith("data:") ? undefined : imageUrl;

            const role = m?.role === "assistant" ? "ai" : (m?.role === "user" || m?.role === "ai" || m?.role === "system" ? m.role : "system");

            return {
                ...m,
                role,
                content: text,
                type: safeImage ? "image" : "text",
                image: safeImage,
            };
        }

        // 3) object等の変な形は normalizeContent で安全に文字列化
        const role = m?.role === "assistant" ? "ai" : (m?.role === "user" || m?.role === "ai" || m?.role === "system" ? m.role : "system");
        return { ...m, role, content: extractSpeech(normalizeContent(m?.content)) };
    }

    // --- Safe AI Message Updates (ID-based) ---
    function beginAiMessage() {
        const id = newId();
        aiMsgIdRef.current = id;
        aiTextRef.current = "";

        setMessages(prev => [
            ...prev,
            { id, role: 'ai', content: '' }
        ]);
    }

    function normalizeForDedup(s: string): string {
        return String(s || "").replace(/\s+/g, " ").trim();
    }

    function isLikelyDuplicateAppend(current: string, incoming: string): boolean {
        const a = normalizeForDedup(current);
        const b = normalizeForDedup(incoming);
        if (!a || !b) return false;
        if (b.length < 20) return false;
        if (a.endsWith(b)) return true;
        return false;
    }

    function dedupeAdjacentDuplicateParagraphs(text: string): string {
        const raw = String(text || "");
        if (!raw.trim()) return raw;
        const parts = raw.split(/\n+/).map((p) => p.trim()).filter(Boolean);
        if (parts.length <= 1) return raw;

        const filtered: string[] = [];
        for (const p of parts) {
            const prev = filtered.length ? filtered[filtered.length - 1] : "";
            if (normalizeForDedup(prev) === normalizeForDedup(p)) continue;
            filtered.push(p);
        }

        if (filtered.length % 2 === 0) {
            const half = filtered.length / 2;
            const first = filtered.slice(0, half).map(normalizeForDedup).join("\n");
            const second = filtered.slice(half).map(normalizeForDedup).join("\n");
            if (first && first === second) {
                return filtered.slice(0, half).join("\n");
            }
        }
        return filtered.join("\n");
    }

    function appendAiChunk(chunk: string) {
        // if (!chunk) return; // Allow empty chunk to trigger re-render if needed, but text usually comes with content
        if (!chunk) return;
        if (isLikelyDuplicateAppend(aiTextRef.current, chunk)) {
            return;
        }
        const id = aiMsgIdRef.current;
        if (!id) {
            const nextId = newId();
            aiMsgIdRef.current = nextId;
            aiTextRef.current = chunk;
            setMessages(prev => [...prev, { id: nextId, role: 'ai', content: chunk }]);
            return;
        }
        aiTextRef.current += chunk;
        aiTextRef.current = dedupeAdjacentDuplicateParagraphs(aiTextRef.current);

        setMessages(prev =>
            prev.map(m => (m.id === id ? { ...m, content: aiTextRef.current } : m))
        );
    }

    async function backfillLastAssistantMessage(attempt: number = 0) {
        try {
            const res = await fetch(`${API_URL}/history/${threadId || "default_thread"}?limit_turns=10`, { cache: "no-store" });
            const data = await res.json();
            const hist = Array.isArray(data?.history) ? data.history : [];
            const last = [...hist].reverse().find((m: any) => m?.role === "assistant" || m?.role === "ai");
            if (!last) {
                if (attempt < 2) {
                    setTimeout(() => backfillLastAssistantMessage(attempt + 1), 250);
                }
                return;
            }
            const text = extractSpeech(normalizeContent(last.content));
            if (!text) {
                if (attempt < 2) {
                    setTimeout(() => backfillLastAssistantMessage(attempt + 1), 250);
                }
                return;
            }
            if (!aiMsgIdRef.current) {
                beginAiMessage();
            }
            appendAiChunk(text);
        } catch (e) {
            console.warn("[backfillLastAssistantMessage] failed", e);
        }
    }

    const handleMessage = React.useCallback((msg: any) => {
        console.log("HANDLE:", msg.type);
        try {
            if (msg?.stream_id != null) {
                const got = String(msg.stream_id);
                if (!sseStreamIdRef.current) {
                    sseStreamIdRef.current = got;
                } else if (got !== String(sseStreamIdRef.current)) {
                    console.warn("[SSE DROP] stream_id mismatch", {
                        got,
                        expected: String(sseStreamIdRef.current),
                        type: msg.type,
                    });
                    return;
                }
            }
            lastEventAtRef.current = Date.now();
            setConnectionState("ok");

            if (msg.type === "text") {
                const text = String(msg.content ?? "");
                if (text.trim() === "WAIT") {
                    // WAIT is handled as a UI hint; don't render as chat text
                    return;
                }
                if (isThinkingRef.current) {
                    syncThinking(false);
                }
                appendAiChunk(text);
                if (thinkingHint) {
                    setThinkingHint(null);
                }

                // 感情分析 (一時的に無効化)
                /*
                try {
                    if (AFFECT_REGEX.global) {
                        const matches = [...aiTextRef.current.matchAll(AFFECT_REGEX)];
                        if (matches.length > 0) {
                            const lastEmotion = matches[matches.length - 1][1];
                            if (lastEmotion !== currentEmotion) {
                                setCurrentEmotion(lastEmotion);
                                onStateChange(true, lastEmotion);
                            }
                        }
                    }
                } catch (e) {
                    console.error("Affect parse failed:", e);
                }
                */

            } else if (msg.type === "state") {
                const tag = String(msg.tag || "").toLowerCase();
                if (tag) {
                    currentStateRef.current = tag;
                    onAgentStateChange?.(tag);
                    onStateChange(true, currentEmotion, isThinkingRef.current);
                }
            } else if (msg.type === "emotion") {
                const tag = String(msg.tag || "").toLowerCase();
                if (tag) {
                    setCurrentEmotion(tag);
                    onStateChange(true, tag, isThinkingRef.current);
                }
            } else if (msg.type === "thinking") {
                const nextThinking = Boolean(msg.value ?? msg.thinking ?? true);
                syncThinking(nextThinking);
            } else if (msg.type === "audio") {
                // URL-based audio (Phase B)
                console.log("[AUDIO EVT]", msg);
                // Support both msg.url and msg.data?.url
                const url = msg.url || msg.data?.url;
                console.log("[AUDIO URL]", url);
                if (url) {
                    if (String(url).includes("<") || String(url).includes(">")) {
                        console.warn("[AUDIO EVT] invalid url:", url);
                        return;
                    }
                    // getStaticUrlで統一的にURL組み立て
                    const audioUrl = getStaticUrl(url);
                    audioQueueRef.current.push(audioUrl);
                    processAudioQueue();
                } else {
                    console.warn("[AUDIO EVT] missing url:", msg);
                }
            } else if (msg.type === "dream") {
                // 夢イベント（SSE開始直後に1回だけ配信される）
                console.log("[DREAM EVT]", msg);
                const dreamMsg: ChatMessage = {
                    id: msg.dream_id || `dream_${Date.now()}`,
                    role: 'system',
                    content: msg.text || '',
                    kind: 'dream',
                    meta: { mood: msg.mood, created_at: msg.created_at },
                };
                setMessages(prev => [...prev.filter(m => m.id !== dreamMsg.id), dreamMsg]);
            } else if (msg.type === "error") {
                console.error("Stream Error:", msg.content);
                setMessages(prev => [...prev, { id: newId(), role: 'system', content: `エラー: ${msg.content}` }]);
            } else if (msg.type === "event" && msg.name === "final_result") {
                const payload = msg.payload || {};
                const ft = String(payload.final_text ?? "");
                if (ft.trim() && ft.trim() !== "WAIT") {
                    if (!aiTextRef.current.trim()) {
                        if (!aiMsgIdRef.current) {
                            beginAiMessage();
                        }
                        appendAiChunk(ft);
                    }
                }
            } else if (msg.type === "event" && msg.name === "thinking_hint") {
                setThinkingHint(msg.payload || {});
            } else if (msg.type === "event" && msg.name === "hold_request") {
                const payload = msg.payload || {};
                setReviewRequest(payload);
                fetchPendingActions();
                fetchLatestCommitLog();
            } else if (msg.type === "event" && msg.name === "hold_cancelled") {
                const payload = msg.payload || {};
                if (!reviewRequest || payload.review_token === reviewRequest.review_token) {
                    setReviewRequest(null);
                    setPendingActions([]);
                    setPendingMeta(null);
                    setLatestCommitLog(null);
                }
            } else if (
                msg.type === "event" &&
                (msg.name === "action_proposed" || msg.name === "action_approved" || msg.name === "action_blocked")
            ) {
                if (typeof window !== "undefined") {
                    window.dispatchEvent(
                        new CustomEvent("phase5-action-event", {
                            detail: { name: msg.name, payload: msg.payload || {} },
                        })
                    );
                }
            } else if (msg.type === "done") {
                if (isThinkingRef.current) {
                    syncThinking(false);
                }
                if (!aiTextRef.current.trim()) {
                    backfillLastAssistantMessage();
                }
            } else {
                console.warn("[SSE NOTICE] unknown event type", msg?.type, msg);
            }
        } catch (e) {
            console.error("handleMessage crashed:", e, msg);
        }
    }, [
        currentEmotion,
        thinkingHint,
        reviewRequest,
        onAgentStateChange,
        onStateChange,
    ]);

    useEffect(() => {
        const tid = threadId || "default_thread";
        if (typeof EventSource === "undefined") return;

        console.log("[TTS_ES] effect", tid, typeof EventSource);

        if (ttsEsRef.current) {
            ttsEsRef.current.close();
            ttsEsRef.current = null;
        }

        const sseUrl = `${API_URL}/tts_events/${tid}`;
        console.log("[TTS_ES] open", sseUrl);
        const es = new EventSource(sseUrl);
        ttsEsRef.current = es;

        es.onmessage = (e) => {
            try {
                const msg = JSON.parse(e.data);
                console.log("[TTS_ES] msg", msg?.type, msg?.data?.url);
                handleMessage(msg);
            } catch (err) {
                console.warn("[TTS_ES] bad json", e.data);
            }
        };

        es.onerror = (e) => {
            console.warn("[TTS_ES] error", e);
            // EventSource should auto-reconnect, but add manual reconnect as fallback
            if (es.readyState === EventSource.CLOSED) {
                console.log("[TTS_ES] connection closed, scheduling reconnect...");
                es.close();
                if (ttsEsRef.current === es) ttsEsRef.current = null;
                // Reconnect after 2 seconds
                setTimeout(() => {
                    if (!ttsEsRef.current) {
                        console.log("[TTS_ES] reconnecting...");
                        const newEs = new EventSource(sseUrl);
                        ttsEsRef.current = newEs;
                        newEs.onmessage = es.onmessage;
                        newEs.onerror = es.onerror;
                    }
                }, 2000);
            }
        };

        return () => {
            es.close();
            if (ttsEsRef.current === es) ttsEsRef.current = null;
        };
    }, [threadId, handleMessage]);

    const sendMessage = async (overrideText?: string) => {
        const textToSend = overrideText ?? input;
        if (!textToSend.trim() && !selectedImage) return;
        // Voice mode (overrideText) can interrupt an active stream;
        // keyboard input respects the loading guard.
        if (!overrideText && isLoading) return;

        onAgentStateChange?.("");
        syncThinking(false);
        setThinkingHint(null);
        if (abortControllerRef.current) {
            abortControllerRef.current.abort();
        }
        activeStreamIdRef.current += 1;
        sseStreamIdRef.current = null;

        const id = newId();
        const userMsg: ChatMessage = { id, role: 'user', content: textToSend };
        if (selectedImage) userMsg.image = selectedImage;

        setMessages(prev => [...prev, userMsg]);
        setInput("");
        setSelectedImage(null);
        setIsLoading(true);
        isStreamingRef.current = true;
        const controller = new AbortController();
        abortControllerRef.current = controller;
        const streamId = activeStreamIdRef.current;
        lastEventAtRef.current = Date.now();
        setConnectionState("ok");

        try {
            const response = await fetch(`${API_URL}/stream_chat`, {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify({
                    text: userMsg.content,
                    voice_id: "14",
                    image_data: userMsg.image,
                    mode: agentMode,
                    stream_id: String(streamId),
                    message_id: userMsg.id,
                    thread_id: threadId || "default_thread"
                }),
                signal: controller.signal
            });

            if (!response.body) throw new Error("No response body");

            const reader = response.body.getReader();
            const decoder = new TextDecoder("utf-8");
            let buffer = "";

            // Start AI message safely
            beginAiMessage();

            while (true) {
                const { done, value } = await reader.read();
                if (done) break;

                buffer += decoder.decode(value, { stream: true });
                buffer = buffer.replace(/\r\n/g, "\n");

                let idx;
                while ((idx = buffer.indexOf("\n\n")) !== -1) {
                    const rawEvent = buffer.slice(0, idx);
                    buffer = buffer.slice(idx + 2);

                    const dataLines = rawEvent
                        .split("\n")
                        .filter((l) => l.startsWith("data:"))
                        .map((l) => l.slice(5).trim());

                    if (dataLines.length === 0) continue;

                    const jsonStr = dataLines.join("\n");
                    try {
                        let msg: any;
                        try {
                            msg = JSON.parse(jsonStr);

                            if (typeof msg === "string") {
                                msg = { type: "text", content: msg };
                            }

                            if (msg && typeof msg === "object" && !msg.type && typeof msg.text === "string") {
                                msg = { type: "text", content: msg.text, stream_id: msg.stream_id };
                            }
                        } catch {
                            msg = { type: "text", content: jsonStr };
                        }
                        console.log("SSE MSG:", msg?.type, msg);

                        if (msg.type === "text") {
                            console.log("TEXT MSG:", msg);
                            console.log("TEXT jsonStr:", jsonStr);
                        }

                        // Pass ALL events to handleMessage (including audio)
                        handleMessage(msg);

                    } catch (e) {
                        console.error("Bad SSE JSON head:", jsonStr.slice(0, 200));
                        console.error("Bad SSE JSON tail:", jsonStr.slice(-200));
                    }
                }
            }

        } catch (e) {
            console.error("Chat Error:", e);
            setMessages(prev => [...prev, { id: newId(), role: 'system', content: '接続エラーが発生しました' }]);
        } finally {
            // Only clean up if this is still the active stream.
            // A newer sendMessage() call may have incremented activeStreamIdRef.
            if (streamId === activeStreamIdRef.current) {
                setIsLoading(false);
                isStreamingRef.current = false;
                if (isThinkingRef.current) {
                    syncThinking(false);
                }
                onStateChange(false, currentEmotion, isThinkingRef.current);
            }
        }
    };
    sendMessageRef.current = sendMessage;

    const parsePayload = (payloadJson: string) => {
        try {
            return JSON.parse(payloadJson || "{}");
        } catch {
            return {};
        }
    };

    const formatDelta = (v: number) => {
        if (typeof v !== "number" || Number.isNaN(v)) return "+0.00";
        return `+${v.toFixed(2)}`;
    };

    const formatAge = (createdAt: number) => {
        if (!createdAt) return "";
        const elapsed = Math.max(0, Date.now() - createdAt * 1000);
        const secs = Math.floor(elapsed / 1000);
        if (secs < 60) return `${secs}s`;
        const mins = Math.floor(secs / 60);
        if (mins < 60) return `${mins}m`;
        const hours = Math.floor(mins / 60);
        if (hours < 24) return `${hours}h`;
        const days = Math.floor(hours / 24);
        return `${days}d`;
    };

    const updateActionReason = (id: string, value: string) => {
        setPendingReasonById((prev) => ({ ...prev, [id]: value }));
    };

    const postAction = async (id: string, action: "approve" | "reject" | "hold") => {
        try {
            const reason = pendingReasonById[id] || "";
            const res = await fetch(`${API_URL}/actions/${id}/${action}`, {
                method: "POST",
                headers: { "Content-Type": "application/json" },
                body: JSON.stringify({ reason }),
            });
            if (!res.ok) {
                throw new Error(`action failed: ${res.status}`);
            }
            await fetchPendingActions();
            await fetchLatestCommitLog();
        } catch (e) {
            console.error(`[pending_actions] ${action} failed`, e);
            addSystemMessage(`保留アクションの${action}に失敗しました`);
        }
    };

    const clearChat = async () => {
        if (isLoading) return;
        const ok = window.confirm("チャット履歴を削除しますか？");
        if (!ok) return;
        try {
            await fetch(`${API_URL}/history/${threadId || "default_thread"}`, { method: "DELETE" });
        } catch (e) {
            console.error("Clear history failed", e);
        } finally {
            setMessages([]);
            aiMsgIdRef.current = null;
            aiTextRef.current = "";
        }
    };

    return (
        <div className="flex flex-col h-full w-full max-w-4xl mx-auto p-2 sm:p-4 relative overflow-hidden box-border">
            {/* Messages Area */}
            <div className="flex items-center justify-between mb-2 px-1">
                <div className="flex items-center gap-2">
                    <div className="text-xs text-gray-500">Chat</div>
                    {thinkingHint && (
                        <div
                            className="text-[11px] px-2 py-0.5 rounded-full border border-amber-500/30 text-amber-200/80 bg-amber-900/20"
                            title={JSON.stringify(thinkingHint)}
                        >
                            thinking…
                        </div>
                    )}
                </div>
                <button
                    onClick={clearChat}
                    className="text-xs text-red-400 hover:text-red-300 border border-red-500/30 px-2 py-1 rounded-lg"
                >
                    履歴削除
                </button>
            </div>
            {connectionState === "stale" && (
                <div className="mb-2 px-2 py-1 rounded-lg text-xs text-amber-200 bg-amber-900/40 border border-amber-500/30">
                    通信が不安定なため、思考状態を解除しました。再同期中…
                </div>
            )}
            {/* Review Window (一時的に無効化) */}
            {false && reviewRequest && (
                <div className="mb-3 rounded-2xl border border-amber-500/30 bg-amber-900/20 px-3 py-3 text-amber-100/90">
                    <div className="flex items-center justify-between gap-2">
                        <div className="text-sm font-medium">Review Window</div>
                        <div className="text-[11px] px-2 py-0.5 rounded-full border border-amber-400/30 bg-amber-900/30 text-amber-100">
                            HOLD中 / 要承認
                        </div>
                        <div className="text-[11px] text-amber-200/70">
                            token: {(reviewRequest?.review_token || "").slice(0, 8)}
                        </div>
                    </div>
                    {reviewRequest?.hold_kind && (
                        <div className="mt-1 text-[11px] text-amber-200/70">
                            kind: {reviewRequest?.hold_kind}
                        </div>
                    )}
                    <div className="mt-2 whitespace-pre-wrap text-sm leading-relaxed text-amber-50/90">
                        {reviewRequest?.preview_text || "（プレビューなし）"}
                    </div>
                    <div className="mt-2 flex flex-wrap gap-1 text-[11px] text-amber-200/70">
                        {(reviewRequest?.reason_codes || []).map((rc: string) => (
                            <span key={rc} className="rounded-full border border-amber-400/30 px-2 py-0.5">
                                {rc}
                            </span>
                        ))}
                    </div>
                    <div className="mt-3 border-t border-amber-500/20 pt-2">
                        <div className="flex items-center justify-between text-[11px] text-amber-200/70">
                            <span>保留中: {pendingMeta?.pending_count ?? pendingActions.length}件</span>
                            <span>dissonance補正: {formatDelta(pendingMeta?.dissonance_delta ?? 0)}</span>
                        </div>
                        {pendingLoading && (
                            <div className="mt-2 text-xs text-amber-200/70">読み込み中…</div>
                        )}
                        {pendingError && (
                            <div className="mt-2 text-xs text-red-200">{pendingError}</div>
                        )}
                        {latestCommitLog?.line && (
                            <div className="mt-2 text-[11px] text-amber-200/70">
                                最新commit_log: {latestCommitLog.line}
                            </div>
                        )}
                        <div className="mt-2 space-y-3">
                            {pendingActions.map((item: any) => {
                                const kind = item.kind || "unknown";
                                const payload = parsePayload(item.payload_json);
                                const rawText = payload.raw_text || payload.text || payload.summary || "";
                                const subTags = [
                                    payload.state_tag && `state:${payload.state_tag}`,
                                    payload.emotion_tags && `emotion:${payload.emotion_tags}`,
                                    payload.keywords && `kw:${payload.keywords}`,
                                    payload.entities && `ent:${payload.entities}`,
                                    payload.retention != null && `ret:${payload.retention}`,
                                    payload.refs && `refs:${payload.refs}`,
                                ].filter(Boolean);
                                const ageSeconds = item.created_at ? Math.max(0, Date.now() - item.created_at * 1000) / 1000 : 0;
                                const ageLevel =
                                    ageSeconds >= 6 * 3600 ? "border-red-400/40" :
                                        ageSeconds >= 1 * 3600 ? "border-amber-400/40" :
                                            "border-amber-500/20";
                                return (
                                    <div key={item.id} className={`rounded-xl border ${ageLevel} bg-amber-950/30 px-3 py-2`}>
                                        <div className="text-xs text-amber-200/70 flex items-center gap-2">
                                            <span>{item.action_type}</span>
                                            <span>・</span>
                                            <span>{new Date((item.created_at || 0) * 1000).toLocaleString()}</span>
                                            {item.created_at ? (
                                                <span className="rounded-full border border-amber-400/20 px-2 py-0.5">
                                                    滞留 {formatAge(item.created_at)}
                                                </span>
                                            ) : null}
                                            <span className="rounded-full border border-amber-400/20 px-2 py-0.5">
                                                kind:{kind}
                                            </span>
                                        </div>
                                        {kind === "memory_add" ? (
                                            <>
                                                <div className="mt-1 whitespace-pre-wrap text-sm text-amber-50/90">
                                                    {rawText || "（raw_text なし）"}
                                                </div>
                                                <div className="mt-1 text-[11px] text-amber-200/70">
                                                    msg: {item.message_id}
                                                </div>
                                                {subTags.length > 0 && (
                                                    <div className="mt-2 flex flex-wrap gap-1 text-[11px] text-amber-200/70">
                                                        {subTags.map((t: string) => (
                                                            <span key={t} className="rounded-full border border-amber-400/20 px-2 py-0.5">
                                                                {t}
                                                            </span>
                                                        ))}
                                                    </div>
                                                )}
                                            </>
                                        ) : (
                                            <details className="mt-2 text-xs text-amber-200/80">
                                                <summary className="cursor-pointer">raw_json</summary>
                                                <pre className="mt-2 whitespace-pre-wrap text-[11px] text-amber-200/70">
                                                    {JSON.stringify(payload, null, 2)}
                                                </pre>
                                            </details>
                                        )}
                                        <div className="mt-2 flex items-center gap-2">
                                            <input
                                                type="text"
                                                value={pendingReasonById[item.id] || ""}
                                                onChange={(e) => updateActionReason(item.id, e.target.value)}
                                                placeholder="理由（任意）"
                                                className="flex-1 rounded-lg bg-black/30 px-2 py-1 text-xs text-amber-100 placeholder:text-amber-200/40"
                                            />
                                            <div className="flex flex-wrap gap-1 text-[10px] text-amber-200/80">
                                                {["根拠不足", "重複", "意味が薄い"].map((hint) => (
                                                    <button
                                                        key={hint}
                                                        type="button"
                                                        onClick={() => updateActionReason(item.id, hint)}
                                                        className="rounded-full border border-amber-400/20 px-2 py-0.5 hover:bg-amber-500/10"
                                                    >
                                                        {hint}
                                                    </button>
                                                ))}
                                            </div>
                                            <button
                                                onClick={() => postAction(item.id, "approve")}
                                                className="rounded-lg border border-emerald-500/40 bg-emerald-500/20 px-2 py-1 text-xs text-emerald-100"
                                            >
                                                Approve
                                            </button>
                                            <button
                                                onClick={() => postAction(item.id, "reject")}
                                                className="rounded-lg border border-red-500/40 bg-red-500/20 px-2 py-1 text-xs text-red-100"
                                            >
                                                Reject
                                            </button>
                                            <button
                                                onClick={() => postAction(item.id, "hold")}
                                                className="rounded-lg border border-amber-500/40 bg-amber-500/20 px-2 py-1 text-xs text-amber-100"
                                            >
                                                Hold
                                            </button>
                                        </div>
                                    </div>
                                );
                            })}
                            {!pendingLoading && pendingActions.length === 0 && (
                                <div className="text-xs text-amber-200/70">保留中のアクションはありません。</div>
                            )}
                        </div>
                    </div>
                </div>
            )}
            <div className="flex-1 overflow-y-auto overflow-x-hidden mb-4 space-y-4 pr-2" ref={scrollRef}>
                <AnimatePresence>
                    {messages.map((msg) => {
                        // 夢メッセージは特別なUIで表示
                        if (msg.kind === 'dream') {
                            return (
                                <motion.div
                                    key={msg.id}
                                    initial={{ opacity: 0, y: 10 }}
                                    animate={{ opacity: 1, y: 0 }}
                                    className="flex justify-center my-4"
                                >
                                    <div className="max-w-[90%] w-full rounded-2xl border border-indigo-500/30 px-4 py-3 bg-indigo-950/50 backdrop-blur-sm">
                                        <div className="flex items-center gap-2 text-sm text-indigo-300 mb-2">
                                            <span aria-hidden>🌙</span>
                                            <span className="font-medium">Niaの夢</span>
                                            {msg.meta?.mood && (
                                                <span className="text-indigo-400/60 text-xs">({msg.meta.mood})</span>
                                            )}
                                        </div>
                                        <div className="whitespace-pre-wrap text-indigo-100/90 leading-relaxed text-sm">
                                            {msg.content}
                                        </div>
                                    </div>
                                </motion.div>
                            );
                        }

                        // 通常メッセージ
                        return (
                            <div
                                key={msg.id}
                                className={`flex w-full ${msg.role === 'user' ? 'justify-end' : 'justify-start'}`}
                            >
                                <div className={`flex flex-col max-w-[80%] ${msg.role === 'user' ? 'items-end' : 'items-start'}`}>
                                    {msg.image && (
                                        <img src={msg.image} alt="User Upload" className="max-w-full sm:max-w-xs rounded-xl mb-2 border border-white/10" />
                                    )}
                                    <div className={`p-3 sm:p-4 rounded-2xl whitespace-pre-wrap leading-relaxed shadow-lg backdrop-blur-sm break-all
                                        ${msg.role === 'user'
                                            ? 'bg-blue-600/80 text-white rounded-br-none'
                                            : 'bg-gray-800/80 text-gray-100 rounded-bl-none border border-white/5'
                                        }
                                        ${msg.role === 'system' && 'bg-red-900/50 text-red-200 text-sm border-red-500/30'}
                                    `}>
                                        {msg.content}
                                    </div>
                                </div>
                            </div>
                        );
                    })}
                </AnimatePresence>
                {isLoading && <div className="text-gray-500 text-sm animate-pulse ml-2">思考中...</div>}
            </div>

            {/* Input Area */}
            <div className="relative w-full glass p-2 rounded-2xl flex flex-col gap-2">
                {selectedImage && (
                    <div className="relative w-32 h-32 bg-black/50 rounded-xl overflow-hidden group">
                        <img src={selectedImage} alt="Preview" className="w-full h-full object-cover" />
                        <button
                            onClick={() => setSelectedImage(null)}
                            className="absolute top-1 right-1 bg-red-500/80 text-white p-1 rounded-full opacity-0 group-hover:opacity-100 transition-opacity"
                        >
                            <StopCircle size={14} />
                        </button>
                    </div>
                )}

                <div className="flex items-center gap-2 w-full">
                    <input
                        type="file"
                        ref={fileInputRef}
                        hidden
                        accept="image/*"
                        onChange={handleImageSelect}
                    />
                    <button
                        onClick={() => fileInputRef.current?.click()}
                        className={`p-3 rounded-xl transition-colors ${selectedImage ? 'text-blue-400 bg-blue-500/20' : 'hover:bg-white/10 text-gray-400'}`}
                    >
                        <ImageIcon size={20} />
                    </button>
                    <input
                        type="text"
                        value={input}
                        onChange={(e) => setInput(e.target.value)}
                        onKeyDown={(e) => {
                            if (e.key === 'Enter' && !e.shiftKey && !(e.nativeEvent as any).isComposing && !isLoading) {
                                e.preventDefault();
                                sendMessage();
                            }
                        }}
                        placeholder="メッセージを入力..."
                        className="flex-1 bg-transparent border-none outline-none text-white px-2 placeholder-gray-500"
                        disabled={isLoading}
                    />
                    <button
                        onClick={toggleVoiceMode}
                        className={`px-3 py-2 rounded-xl text-xs font-medium transition-all ${voiceModeEnabled
                            ? 'bg-emerald-500 text-white shadow-[0_0_12px_rgba(16,185,129,0.45)]'
                            : 'border border-white/20 text-gray-300 hover:bg-white/10'
                            }`}
                        title={voiceModeEnabled ? "Voice Mode 停止" : "Voice Mode 開始"}
                    >
                        {voiceModeEnabled ? "Voice ON" : "Voice"}
                    </button>
                    <button
                        onClick={toggleListening}
                        className={`p-3 rounded-xl transition-all ${isListening
                            ? 'bg-red-500 text-white animate-pulse shadow-[0_0_15px_rgba(239,68,68,0.5)]'
                            : 'hover:bg-white/10 text-gray-400'
                            }`}
                        title={isListening ? "音声認識停止" : "音声認識開始"}
                    >
                        <Mic size={20} />
                    </button>
                    <button
                        onClick={() => sendMessage()}
                        disabled={isLoading || (!input.trim() && !selectedImage)}
                        className="p-3 rounded-xl bg-blue-600 hover:bg-blue-500 text-white shadow-lg shadow-blue-600/20 disabled:opacity-50 transition-all active:scale-95"
                    >
                        <Send size={20} />
                    </button>
                </div>
                {(voiceModeEnabled || voiceWsState !== "idle" || voiceError) && (
                    <div className="px-2 text-[11px] text-gray-400">
                        <span>voice_ws: {voiceWsState}</span>
                        {sttPreview && <span className="ml-2 text-emerald-300">stt: {sttPreview}</span>}
                        {voiceError && <span className="ml-2 text-red-300">{voiceError}</span>}
                    </div>
                )}
            </div>
        </div>
    );
}
