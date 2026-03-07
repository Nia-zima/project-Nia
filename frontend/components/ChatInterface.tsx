"use client";
import React, { useRef, useEffect } from 'react';
import { API_URL, apiClient, getStaticUrl, type ChatMessage } from '@/lib/apiClient';
import { ChatMessages, ChatInput } from '@/components/chat';
import { safeJsonParse } from '@/lib/types';
import {
    normalizeContent,
    extractSpeech,
    normalizeHistoryMessage,
    isLikelyDuplicateAppend,
    dedupeAdjacentDuplicateParagraphs,
} from '@/components/chat/messageNormalization';
import { useAudioPlayback } from '@/hooks/useAudioPlayback';
import { useVoiceMode } from '@/hooks/useVoiceMode';
import { useChatStore } from '@/lib/stores/chatStore';
import { useAvatarStore } from '@/lib/stores/avatarStore';

interface ChatInterfaceProps {
    agentMode: string;
}

export default function ChatInterface({ agentMode }: ChatInterfaceProps) {
    const {
        messages, setMessages, addMessage, updateMessageContent, upsertMessage, clearMessages,
        input, setInput, appendInput,
        isLoading, setIsLoading,
        threadId, setThreadId,
        currentEmotion, setCurrentEmotion,
        connectionState, setConnectionState,
        thinkingHint, setThinkingHint,
        selectedImage, setSelectedImage,
        isListening, setIsListening,
    } = useChatStore();

    // Refs to avoid stale closures in handleMessage callback
    const currentEmotionRef = useRef(currentEmotion);
    currentEmotionRef.current = currentEmotion;
    const thinkingHintRef = useRef(thinkingHint);
    thinkingHintRef.current = thinkingHint;

    // Stream Refs
    const aiMsgIdRef = useRef<string | null>(null);
    const aiTextRef = useRef<string>("");
    const isStreamingRef = useRef(false);
    const isThinkingRef = useRef(false);
    const lastEventAtRef = useRef<number>(0);
    const activeStreamIdRef = useRef<number>(0);
    const sseStreamIdRef = useRef<string | null>(null);
    const finalTextLockedRef = useRef<boolean>(false);
    const turnStartedAtMsRef = useRef<number>(0);
    const abortControllerRef = useRef<AbortController | null>(null);
    const currentStateRef = useRef<string>("");
    const ttsEsRef = useRef<EventSource | null>(null);
    const sendMessageRef = useRef<(text?: string) => Promise<void>>(async () => { });
    const micVadRef = useRef<any>(null);

    const {
        audioQueueRef,
        isPlayingRef,
        audioRef,
        interruptAudioPlayback,
        processAudioQueue,
    } = useAudioPlayback({
        currentEmotionRef,
        isThinkingRef,
        micVadRef,
    });

    const {
        voiceModeEnabled,
        voiceWsState,
        voiceError,
        sttPreview,
        toggleVoiceMode,
        cleanupVoiceRuntime,
    } = useVoiceMode({
        threadId,
        isLoading,
        interruptAudioPlayback,
        isPlayingRef,
        sendMessageRef,
        micVadRef,
    });

    const syncThinking = (next: boolean) => {
        isThinkingRef.current = next;
        useAvatarStore.getState().updateState(isPlayingRef.current, currentEmotion, next);
    };

    const addSystemMessage = (content: string) => {
        addMessage({ id: newId(), role: 'system', content });
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
                apiClient.reportStreamTimeout(
                    threadId || "default_thread",
                    streamId,
                    "SSE timeout / no events for 30s",
                );
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
        const savedThreadId = "default_thread";
        setThreadId(savedThreadId);

        const loadHistory = async () => {
            if (isStreamingRef.current) return;

            try {
                const data = await apiClient.fetchHistory(savedThreadId);

                const hist = data?.history;
                if (Array.isArray(hist)) {
                    const cleaned = hist.map((m: any) => normalizeHistoryMessage(m));

                    // パフォーマンス: 表示件数を制限（UIだけ軽く、データはDBに全部ある）
                    const MAX_RENDER = 120;
                    setMessages(ensureIds(cleaned.slice(-MAX_RENDER)));
                }
            } catch (e) {
                console.error("[loadHistory] failed", e);
            }
        };
        loadHistory();

        return () => {
            cleanupVoiceRuntime();
        };
    }, []);

    // Scroll is handled inside ChatMessages component


    // --- Speech Recognition ---
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
                        appendInput(finalTranscript);
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

    // --- Safe AI Message Updates (ID-based) ---
    function beginAiMessage() {
        const id = newId();
        aiMsgIdRef.current = id;
        aiTextRef.current = "";
        addMessage({ id, role: 'ai', content: '' });
    }

    function appendAiChunk(chunk: string) {
        if (!chunk) return;
        if (isLikelyDuplicateAppend(aiTextRef.current, chunk)) {
            return;
        }
        const id = aiMsgIdRef.current;
        if (!id) {
            const nextId = newId();
            aiMsgIdRef.current = nextId;
            aiTextRef.current = chunk;
            addMessage({ id: nextId, role: 'ai', content: chunk });
            return;
        }
        aiTextRef.current += chunk;
        aiTextRef.current = dedupeAdjacentDuplicateParagraphs(aiTextRef.current);
        updateMessageContent(id, aiTextRef.current);
    }

    async function backfillLastAssistantMessage(attempt: number = 0) {
        try {
            const data = await apiClient.fetchRecentHistory(threadId || "default_thread", 10);
            const hist = Array.isArray(data?.history) ? data.history : [];
            const sinceMs = Number(turnStartedAtMsRef.current || 0);
            const last = [...hist].reverse().find((m: any) => {
                const role = String(m?.role || "");
                if (role !== "assistant" && role !== "ai") {
                    return false;
                }
                const ts = Number(m?.ts ?? 0);
                if (!Number.isFinite(ts)) {
                    return false;
                }
                // Guard against stale replay: only backfill assistant messages
                // created after this turn started.
                return ts >= sinceMs;
            });
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
                if (finalTextLockedRef.current) {
                    // Authoritative final_result already arrived for this turn.
                    // Ignore trailing text chunks to keep UI aligned with committed final_text.
                    return;
                }
                const text = String(msg.content ?? "");
                if (text.trim() === "WAIT") {
                    // WAIT is handled as a UI hint; don't render as chat text
                    return;
                }
                if (isThinkingRef.current) {
                    syncThinking(false);
                }
                appendAiChunk(text);
                if (thinkingHintRef.current) {
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
                    useAvatarStore.getState().setAgentState(tag);
                    useAvatarStore.getState().updateState(true, currentEmotionRef.current, isThinkingRef.current);
                }
            } else if (msg.type === "emotion") {
                const tag = String(msg.tag || "").toLowerCase();
                if (tag) {
                    setCurrentEmotion(tag);
                    useAvatarStore.getState().updateState(true, tag, isThinkingRef.current);
                }
            } else if (msg.type === "gesture") {
                const tag = String(msg.tag || "").toLowerCase();
                if (tag) {
                    useAvatarStore.getState().triggerGesture(tag);
                }
            } else if (msg.type === "thinking") {
                const nextThinking = Boolean(msg.value ?? msg.thinking ?? true);
                syncThinking(nextThinking);
            } else if (msg.type === "audio") {
                // Accept audio only from the active main stream.
                // Legacy /tts_events payloads can arrive without stream_id and replay stale audio.
                if (msg?.stream_id == null) {
                    console.warn("[AUDIO EVT] dropped: missing stream_id", msg);
                    return;
                }
                // Support both msg.url and msg.data?.url
                const url = msg.url || msg.data?.url;
                const audioText = String(msg?.data?.text_content ?? "").trim();
                if (!finalTextLockedRef.current && audioText) {
                    if (!aiMsgIdRef.current) {
                        beginAiMessage();
                    }
                    const id = aiMsgIdRef.current;
                    aiTextRef.current = audioText;
                    if (id) updateMessageContent(id, audioText);
                    finalTextLockedRef.current = true;
                }
                if (url) {
                    if (String(url).includes("<") || String(url).includes(">")) {
                        console.warn("[AUDIO EVT] invalid url:", url);
                        return;
                    }
                    // getStaticUrlで統一的にURL組み立て
                    let audioUrl = getStaticUrl(url);
                    // Cache buster
                    audioUrl = audioUrl.includes("?")
                        ? `${audioUrl}&t=${Date.now()}`
                        : `${audioUrl}?t=${Date.now()}`;
                    audioQueueRef.current.push(audioUrl);
                    processAudioQueue();
                } else {
                    console.warn("[AUDIO EVT] missing url:", msg);
                }
            } else if (msg.type === "dream") {
                const dreamMsg: ChatMessage = {
                    id: msg.dream_id || `dream_${Date.now()}`,
                    role: 'system',
                    content: msg.text || '',
                    kind: 'dream',
                    meta: { mood: msg.mood, created_at: msg.created_at },
                };
                upsertMessage(dreamMsg);
            } else if (msg.type === "error") {
                console.error("Stream Error:", msg.content);
                addMessage({ id: newId(), role: 'system', content: `エラー: ${msg.content}` });
            } else if (msg.type === "event" && msg.name === "final_result") {
                const payload = msg.payload || {};
                const ft = String(payload.final_text ?? "");
                console.info("[SSE final_result] len=%d merge_mode=%s", ft.length, payload.merge_mode);
                if (ft.trim() && ft.trim() !== "WAIT") {
                    if (!aiMsgIdRef.current) {
                        beginAiMessage();
                    }
                    const id = aiMsgIdRef.current;
                    aiTextRef.current = ft;
                    if (id) updateMessageContent(id, ft);
                    finalTextLockedRef.current = true;
                }
            } else if (msg.type === "event" && msg.name === "thinking_hint") {
                setThinkingHint(msg.payload || {});
            } else if (
                msg.type === "event" &&
                (
                    msg.name === "hold_request" ||
                    msg.name === "hold_cancelled" ||
                    msg.name === "action_proposed" ||
                    msg.name === "action_approved" ||
                    msg.name === "action_blocked"
                )
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
                    console.warn("[SSE done] aiText is empty — triggering backfill. finalTextLocked=", finalTextLockedRef.current);
                    backfillLastAssistantMessage();
                }
            } else {
                console.warn("[SSE NOTICE] unknown event type", msg?.type, msg);
            }
        } catch (e) {
            console.error("handleMessage crashed:", e, msg);
        }
    }, []);

    useEffect(() => {
        const tid = threadId || "default_thread";
        if (typeof EventSource === "undefined") return;
        // Audio now arrives on the main /stream_chat SSE.
        // Keep legacy /tts_events disabled by default to avoid stale backlog playback.
        const enableLegacyTtsEvents = String(process.env.NEXT_PUBLIC_ENABLE_TTS_EVENTS ?? "0") === "1";
        if (!enableLegacyTtsEvents) {
            if (ttsEsRef.current) {
                ttsEsRef.current.close();
                ttsEsRef.current = null;
            }
            return;
        }

        if (ttsEsRef.current) {
            ttsEsRef.current.close();
            ttsEsRef.current = null;
        }

        const sseUrl = `${API_URL}/tts_events/${tid}`;
        const es = new EventSource(sseUrl);
        ttsEsRef.current = es;

        es.onmessage = (e) => {
            try {
                const msg = JSON.parse(e.data);
                handleMessage(msg);
            } catch (err) {
                console.warn("[TTS_ES] bad json", e.data);
            }
        };

        let reconnectTimer: ReturnType<typeof setTimeout> | null = null;

        es.onerror = (e) => {
            console.warn("[TTS_ES] error", e);
            // EventSource should auto-reconnect, but add manual reconnect as fallback
            if (es.readyState === EventSource.CLOSED) {
                es.close();
                if (ttsEsRef.current === es) ttsEsRef.current = null;
                // Reconnect after 2 seconds
                reconnectTimer = setTimeout(() => {
                    reconnectTimer = null;
                    if (!ttsEsRef.current) {
                        const newEs = new EventSource(sseUrl);
                        ttsEsRef.current = newEs;
                        newEs.onmessage = (ev) => {
                            try {
                                const msg = JSON.parse(ev.data);
                                handleMessage(msg);
                            } catch (err) {
                                console.warn("[TTS_ES] bad json", ev.data);
                            }
                        };
                        newEs.onerror = es.onerror;
                    }
                }, 2000);
            }
        };

        return () => {
            if (reconnectTimer) clearTimeout(reconnectTimer);
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

        useAvatarStore.getState().setAgentState("");
        syncThinking(false);
        setThinkingHint(null);
        finalTextLockedRef.current = false;
        if (abortControllerRef.current) {
            abortControllerRef.current.abort();
        }

        // Stop current audio and clear queue
        if (audioRef.current) {
            audioRef.current.pause();
            audioRef.current = null;
        }
        isPlayingRef.current = false;
        audioQueueRef.current = [];

        activeStreamIdRef.current += 1;
        sseStreamIdRef.current = null;
        turnStartedAtMsRef.current = Date.now();

        const id = newId();
        const userMsg: ChatMessage = { id, role: 'user', content: textToSend };
        if (selectedImage) userMsg.image = selectedImage;

        addMessage(userMsg);
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
            const response = await apiClient.streamChat({
                text: userMsg.content,
                threadId: threadId || "default_thread",
                voiceId: "14",
                imageData: userMsg.image,
                mode: agentMode,
                streamId: String(streamId),
                messageId: userMsg.id,
            }, controller.signal);

            if (!response.body) throw new Error("No response body");

            const reader = response.body.getReader();
            const decoder = new TextDecoder("utf-8");
            let buffer = "";
            let chunkCount = 0;

            // Start AI message safely
            beginAiMessage();

            while (true) {
                const { done, value } = await reader.read();
                if (done) break;

                chunkCount++;
                const decoded = decoder.decode(value, { stream: true });
                buffer += decoded;
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
                        let msg: Record<string, unknown>;
                        const parsed = safeJsonParse<unknown>(jsonStr, null);
                        if (parsed === null || typeof parsed !== "object") {
                            msg = { type: "text", content: typeof parsed === "string" ? parsed : jsonStr };
                        } else {
                            msg = parsed as Record<string, unknown>;
                            if (!msg.type && typeof msg.text === "string") {
                                msg = { type: "text", content: msg.text, stream_id: msg.stream_id };
                            }
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
            addMessage({ id: newId(), role: 'system', content: '接続エラーが発生しました' });
        } finally {
            // Only clean up if this is still the active stream.
            // A newer sendMessage() call may have incremented activeStreamIdRef.
            if (streamId === activeStreamIdRef.current) {
                setIsLoading(false);
                isStreamingRef.current = false;
                if (isThinkingRef.current) {
                    syncThinking(false);
                }
                useAvatarStore.getState().updateState(false, currentEmotionRef.current, isThinkingRef.current);
            }
        }
    };
    sendMessageRef.current = sendMessage;

    const clearChat = async () => {
        if (isLoading) return;
        const ok = window.confirm("チャット履歴を削除しますか？");
        if (!ok) return;
        try {
            await apiClient.clearHistory(threadId || "default_thread");
        } catch (e) {
            console.error("Clear history failed", e);
        } finally {
            clearMessages();
            aiMsgIdRef.current = null;
            aiTextRef.current = "";
        }
    };

    return (
        <div className="flex flex-col h-full w-full max-w-4xl mx-auto p-2 sm:p-4 relative overflow-hidden box-border">
            {/* Header */}
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
            {/* Messages */}
            <ChatMessages />

            {/* Input */}
            <ChatInput
                onToggleListening={toggleListening}
                onSendMessage={() => sendMessage()}
                onImageSelect={handleImageSelect}
                voiceModeEnabled={voiceModeEnabled}
                voiceWsState={voiceWsState}
                voiceError={voiceError}
                sttPreview={sttPreview}
                onToggleVoiceMode={toggleVoiceMode}
            />
        </div>
    );
}
