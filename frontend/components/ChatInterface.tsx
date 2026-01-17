"use client";
import React, { useState, useRef, useEffect } from 'react';
import { Send, Mic, Image as ImageIcon, StopCircle } from 'lucide-react';
import { API_URL, ChatMessage, getStaticUrl } from '@/lib/api';
import { motion, AnimatePresence } from 'framer-motion';

interface ChatInterfaceProps {
    onStateChange: (isTalking: boolean, emotion: string) => void;
    agentMode: string;
}

export default function ChatInterface({ onStateChange, agentMode }: ChatInterfaceProps) {
    const [messages, setMessages] = useState<ChatMessage[]>([]);
    const [input, setInput] = useState("");
    const [isLoading, setIsLoading] = useState(false);
    const [threadId, setThreadId] = useState<string>("");
    const [currentEmotion, setCurrentEmotion] = useState("neutral");

    // Vision State
    const [selectedImage, setSelectedImage] = useState<string | null>(null);
    const fileInputRef = useRef<HTMLInputElement>(null);

    const AFFECT_REGEX = /\[(happy|sad|angry|relaxed|surprised|shy|sigh|neutral)\]/g;
    const scrollRef = useRef<HTMLDivElement>(null);

    // Audio Playback Queue
    const audioQueueRef = useRef<string[]>([]);
    const isPlayingRef = useRef(false);
    const audioRef = useRef<HTMLAudioElement | null>(null);

    // Stream Refs
    const aiMsgIdRef = useRef<string | null>(null);
    const aiTextRef = useRef<string>("");
    const isStreamingRef = useRef(false);

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

                    const cleaned = hist.map((m: any) => {
                        const text = safeContentToText(m?.content); // 必ず string へ
                        return {
                            ...m,
                            content: extractSpeech(text), // extractSpeech は string 前提でOK
                        };
                    });

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

        return () => console.log("[ChatInterface] UNMOUNT", Date.now());
    }, []);

    useEffect(() => {
        if (scrollRef.current) {
            scrollRef.current.scrollTop = scrollRef.current.scrollHeight;
        }
    }, [messages]);

    const processAudioQueue = async () => {
        if (isPlayingRef.current || audioQueueRef.current.length === 0) return;

        isPlayingRef.current = true;
        const audioUrl = audioQueueRef.current.shift();
        if (!audioUrl) {
            isPlayingRef.current = false;
            onStateChange(false, "neutral");
            return;
        }

        onStateChange(true, "happy");

        // Use URL directly (from static/audio/...)
        console.log("[AUDIO PLAY]", audioUrl);
        const audio = new Audio(audioUrl);
        audioRef.current = audio;

        audio.onended = () => {
            isPlayingRef.current = false;
            setTimeout(processAudioQueue, 100);
        };

        audio.addEventListener("error", () => console.error("[AUDIO ERROR]", audio.error));
        await audio.play().catch(e => console.error("[PLAY REJECTED]", e));
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

            const role = m?.role === "user" || m?.role === "ai" || m?.role === "system" ? m.role : "system";

            return {
                ...m,
                role,
                content: text,
                type: safeImage ? "image" : "text",
                image: safeImage,
            };
        }

        // 3) object等の変な形は文字列化して最低限落ちないように
        const role = m?.role === "user" || m?.role === "ai" || m?.role === "system" ? m.role : "system";
        return { ...m, role, content: extractSpeech(String(m?.content ?? "")) };
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

    function appendAiChunk(chunk: string) {
        // if (!chunk) return; // Allow empty chunk to trigger re-render if needed, but text usually comes with content
        const id = aiMsgIdRef.current;
        if (!id) {
            console.error("appendAiChunk: missing aiMsgId");
            return;
        }
        aiTextRef.current += chunk;

        setMessages(prev =>
            prev.map(m => (m.id === id ? { ...m, content: aiTextRef.current } : m))
        );
    }

    const sendMessage = async () => {
        if ((!input.trim() && !selectedImage) || isLoading) return;

        const id = newId();
        const userMsg: ChatMessage = { id, role: 'user', content: input };
        if (selectedImage) userMsg.image = selectedImage;

        setMessages(prev => [...prev, userMsg]);
        setInput("");
        setSelectedImage(null);
        setIsLoading(true);
        isStreamingRef.current = true;
        const controller = new AbortController();

        try {
            const response = await fetch(`${API_URL}/stream_chat`, {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify({
                    text: userMsg.content,
                    voice_id: "14",
                    image_data: userMsg.image,
                    mode: agentMode
                }),
                signal: controller.signal
            });

            if (!response.body) throw new Error("No response body");

            const reader = response.body.getReader();
            const decoder = new TextDecoder("utf-8");
            let buffer = "";
            let gotDone = false;

            // Start AI message safely
            beginAiMessage();

            function handleMessage(msg: any) {
                console.log("HANDLE:", msg.type);
                try {
                    if (msg.type === "text") {
                        appendAiChunk(msg.content ?? "");

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

                    } else if (msg.type === "audio") {
                        // URL-based audio (Phase B)
                        console.log("[AUDIO EVT]", msg);
                        // Support both msg.url and msg.data?.url
                        const url = msg.url || msg.data?.url;
                        console.log("[AUDIO URL]", url);
                        if (url) {
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
                    } else if (msg.type === "done") {
                        gotDone = true;
                    }
                } catch (e) {
                    console.error("handleMessage crashed:", e, msg);
                }
            }

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
                        const msg = JSON.parse(jsonStr);
                        console.log("SSE MSG:", msg.type, msg);

                        if (msg.type === "text") {
                            console.log("TEXT MSG:", msg);
                            console.log("TEXT jsonStr:", jsonStr);
                        }

                        // Pass ALL events to handleMessage (including audio)
                        handleMessage(msg);

                        if (gotDone) break; // Inner loop break
                    } catch (e) {
                        console.error("Bad SSE JSON head:", jsonStr.slice(0, 200));
                        console.error("Bad SSE JSON tail:", jsonStr.slice(-200));
                    }
                }
                if (gotDone) break; // Outer loop break
            }

        } catch (e) {
            console.error("Chat Error:", e);
            setMessages(prev => [...prev, { id: newId(), role: 'system', content: '接続エラーが発生しました' }]);
        } finally {
            setIsLoading(false);
            isStreamingRef.current = false;
            onStateChange(false, currentEmotion);
        }
    };

    return (
        <div className="flex flex-col h-full w-full max-w-4xl mx-auto p-2 sm:p-4 relative overflow-hidden box-border">
            {/* Messages Area */}
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
                        onClick={sendMessage}
                        disabled={isLoading || (!input.trim() && !selectedImage)}
                        className="p-3 rounded-xl bg-blue-600 hover:bg-blue-500 text-white shadow-lg shadow-blue-600/20 disabled:opacity-50 transition-all active:scale-95"
                    >
                        <Send size={20} />
                    </button>
                </div>
            </div>
        </div>
    );
}
