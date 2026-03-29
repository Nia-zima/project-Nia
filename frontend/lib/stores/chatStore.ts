import { create } from 'zustand';
import type { ChatMessage } from '@/lib/apiClient';

interface ReviewRequestPayload {
    review_token: string;
    hold_kind?: string;
    preview_text?: string;
    reason_codes?: string[];
}

interface ChatStore {
    // ── Messages ──
    messages: ChatMessage[];
    setMessages: (msgs: ChatMessage[]) => void;
    addMessage: (msg: ChatMessage) => void;
    updateMessageContent: (id: string, content: string) => void;
    upsertMessage: (msg: ChatMessage) => void;
    appendInput: (text: string) => void;
    clearMessages: () => void;

    // ── Thread ──
    threadId: string;
    setThreadId: (id: string) => void;

    // ── Loading / Connection ──
    isLoading: boolean;
    setIsLoading: (v: boolean) => void;
    connectionState: 'ok' | 'stale';
    setConnectionState: (s: 'ok' | 'stale') => void;

    // ── Emotion / Thinking ──
    currentEmotion: string;
    setCurrentEmotion: (e: string) => void;
    isThinking: boolean;
    setIsThinking: (v: boolean) => void;
    thinkingHint: any | null;
    setThinkingHint: (v: any | null) => void;

    // ── Voice ──
    voiceModeEnabled: boolean;
    setVoiceModeEnabled: (v: boolean) => void;
    voiceWsState: 'idle' | 'connecting' | 'connected' | 'error';
    setVoiceWsState: (s: 'idle' | 'connecting' | 'connected' | 'error') => void;
    voiceError: string | null;
    setVoiceError: (e: string | null) => void;
    sttPreview: string;
    setSttPreview: (s: string) => void;

    // ── Review Window ──
    reviewRequest: ReviewRequestPayload | null;
    setReviewRequest: (r: ReviewRequestPayload | null) => void;
    pendingActions: any[];
    setPendingActions: (a: any[]) => void;
    pendingMeta: { pending_count: number; dissonance_delta: number } | null;
    setPendingMeta: (m: { pending_count: number; dissonance_delta: number } | null) => void;
    pendingLoading: boolean;
    setPendingLoading: (v: boolean) => void;
    pendingError: string | null;
    setPendingError: (e: string | null) => void;
    pendingReasonById: Record<string, string>;
    updateActionReason: (id: string, value: string) => void;
    latestCommitLog: any | null;
    setLatestCommitLog: (v: any | null) => void;

    // ── Input ──
    input: string;
    setInput: (v: string) => void;
    selectedImage: string | null;
    setSelectedImage: (v: string | null) => void;
    isListening: boolean;
    setIsListening: (v: boolean) => void;
}

export const useChatStore = create<ChatStore>((set) => ({
    // Messages
    messages: [],
    setMessages: (msgs) => set({ messages: msgs }),
    addMessage: (msg) => set((s) => ({ messages: [...s.messages, msg] })),
    updateMessageContent: (id, content) =>
        set((s) => ({
            messages: s.messages.map((m) => (m.id === id ? { ...m, content } : m)),
        })),
    upsertMessage: (msg) =>
        set((s) => ({
            messages: [...s.messages.filter((m) => m.id !== msg.id), msg],
        })),
    appendInput: (text) => set((s) => ({ input: s.input + text })),
    clearMessages: () => set({ messages: [] }),

    // Thread
    threadId: '',
    setThreadId: (id) => set({ threadId: id }),

    // Loading / Connection
    isLoading: false,
    setIsLoading: (v) => set({ isLoading: v }),
    connectionState: 'ok',
    setConnectionState: (s) => set({ connectionState: s }),

    // Emotion / Thinking
    currentEmotion: 'neutral',
    setCurrentEmotion: (e) => set({ currentEmotion: e }),
    isThinking: false,
    setIsThinking: (v) => set({ isThinking: v }),
    thinkingHint: null,
    setThinkingHint: (v) => set({ thinkingHint: v }),

    // Voice
    voiceModeEnabled: false,
    setVoiceModeEnabled: (v) => set({ voiceModeEnabled: v }),
    voiceWsState: 'idle',
    setVoiceWsState: (s) => set({ voiceWsState: s }),
    voiceError: null,
    setVoiceError: (e) => set({ voiceError: e }),
    sttPreview: '',
    setSttPreview: (s) => set({ sttPreview: s }),

    // Review
    reviewRequest: null,
    setReviewRequest: (r) => set({ reviewRequest: r }),
    pendingActions: [],
    setPendingActions: (a) => set({ pendingActions: a }),
    pendingMeta: null,
    setPendingMeta: (m) => set({ pendingMeta: m }),
    pendingLoading: false,
    setPendingLoading: (v) => set({ pendingLoading: v }),
    pendingError: null,
    setPendingError: (e) => set({ pendingError: e }),
    pendingReasonById: {},
    updateActionReason: (id, value) =>
        set((s) => ({ pendingReasonById: { ...s.pendingReasonById, [id]: value } })),
    latestCommitLog: null,
    setLatestCommitLog: (v) => set({ latestCommitLog: v }),

    // Input
    input: '',
    setInput: (v) => set({ input: v }),
    selectedImage: null,
    setSelectedImage: (v) => set({ selectedImage: v }),
    isListening: false,
    setIsListening: (v) => set({ isListening: v }),
}));

export type { ReviewRequestPayload, ChatStore };
