/**
 * Unified API Client for AI_Buddy frontend.
 * Centralizes all fetch() calls with typed responses.
 */

import type { PendingAction } from './types';

export const API_URL = "/api";

// ─── Types ───────────────────────────────────────────────────────

export interface ChatMessage {
    id: string;
    role: 'user' | 'ai' | 'system';
    content: string;
    timestamp?: string;
    type?: 'text' | 'audio' | 'image';
    image?: string;
    kind?: 'dream';
    meta?: { mood?: string; created_at?: string; [key: string]: unknown };
}

export interface TTSGenerateResult {
    ok: boolean;
    skipped?: boolean;
    reason?: string;
    data?: {
        url: string;
        text_content: string;
        is_silence: boolean;
        gen_ms: number;
    };
}

export interface VoiceSessionStartResult {
    session?: { session_id: string };
}

export interface PendingActionsResult {
    items: PendingAction[];
    meta?: { pending_count: number; dissonance_delta: number };
}

export interface CommitLogResult {
    item?: { line: string };
}

export interface HistoryResult {
    history: ChatMessage[];
}

// ─── Client ──────────────────────────────────────────────────────

class APIClient {
    private baseUrl: string;

    constructor(baseUrl: string = API_URL) {
        this.baseUrl = baseUrl;
    }

    private async request<T>(
        path: string,
        options?: RequestInit,
    ): Promise<T> {
        const res = await fetch(`${this.baseUrl}${path}`, {
            ...options,
            headers: {
                "Content-Type": "application/json",
                ...options?.headers,
            },
        });
        if (!res.ok) {
            throw new Error(`API error: ${res.status} ${res.statusText} [${path}]`);
        }
        return res.json();
    }

    // ── History ──

    async fetchHistory(threadId: string): Promise<HistoryResult> {
        return this.request<HistoryResult>(`/history/${threadId}`);
    }

    async fetchRecentHistory(threadId: string, limitTurns: number = 10): Promise<HistoryResult> {
        return this.request<HistoryResult>(
            `/history/${threadId}?limit_turns=${limitTurns}`,
        );
    }

    async clearHistory(threadId: string): Promise<void> {
        const res = await fetch(`${this.baseUrl}/history/${threadId}`, { method: "DELETE" });
        if (!res.ok) {
            throw new Error(`API error: ${res.status} ${res.statusText} [DELETE /history/${threadId}]`);
        }
    }

    // ── Config ──

    async fetchConfig(): Promise<Record<string, unknown>> {
        return this.request<Record<string, unknown>>("/config");
    }

    // ── Stream Chat ──

    streamChat(
        params: {
            text: string;
            threadId: string;
            voiceId?: string;
            imageData?: string;
            mode?: string;
            streamId?: string;
            messageId?: string;
        },
        signal?: AbortSignal,
    ): Promise<Response> {
        return fetch(`${this.baseUrl}/stream_chat`, {
            method: "POST",
            headers: { "Content-Type": "application/json" },
            body: JSON.stringify({
                text: params.text,
                voice_id: params.voiceId ?? "14",
                image_data: params.imageData,
                mode: params.mode,
                stream_id: params.streamId,
                message_id: params.messageId,
                thread_id: params.threadId,
            }),
            signal,
        });
    }

    // ── Voice Session ──

    async startVoiceSession(threadId: string, clientId: string): Promise<VoiceSessionStartResult> {
        return this.request<VoiceSessionStartResult>("/voice/session/start", {
            method: "POST",
            body: JSON.stringify({ thread_id: threadId, client_id: clientId }),
        });
    }

    async stopVoiceSession(sessionId: string, reason: string = "client_stop"): Promise<void> {
        await this.request("/voice/session/stop", {
            method: "POST",
            body: JSON.stringify({ session_id: sessionId, reason }),
        });
    }

    // ── Actions (Pending / Commit Log) ──

    async fetchPendingActions(
        threadId: string,
        limit: number = 50,
        offset: number = 0,
    ): Promise<PendingActionsResult> {
        return this.request<PendingActionsResult>(
            `/actions/pending?thread_id=${encodeURIComponent(threadId)}&limit=${limit}&offset=${offset}`,
        );
    }

    async postAction(actionId: string, action: "approve" | "reject" | "hold", reason: string = ""): Promise<void> {
        await this.request(`/actions/${actionId}/${action}`, {
            method: "POST",
            body: JSON.stringify({ reason }),
        });
    }

    async fetchLatestCommitLog(threadId: string): Promise<CommitLogResult> {
        return this.request<CommitLogResult>(
            `/actions/commit_log/latest?thread_id=${encodeURIComponent(threadId)}`,
        );
    }

    // ── Stream Timeout ──

    async reportStreamTimeout(threadId: string, streamId: string, reason: string): Promise<void> {
        await fetch(`${this.baseUrl}/stream_timeout`, {
            method: "POST",
            headers: { "Content-Type": "application/json" },
            body: JSON.stringify({ thread_id: threadId, stream_id: streamId, reason }),
        }).catch(() => {});
    }

    // ── TTS ──

    async ttsGenerate(text: string, speakerId: number = 3): Promise<TTSGenerateResult> {
        return this.request<TTSGenerateResult>("/tts/generate", {
            method: "POST",
            body: JSON.stringify({ text, speaker_id: speakerId }),
        });
    }

    async ttsSpeakers(): Promise<Array<{ id: number; name: string }>> {
        return this.request("/tts/speakers");
    }

    // ── Video ──

    async analyzeVideo(
        file: File,
        mode: "learn" | "react" = "react",
        intervalSec?: number,
        maxFrames?: number,
    ): Promise<{
        mode: string;
        scenes?: string[];
        frame_count?: number;
        strategies?: string[];
        memory_ids?: string[];
        success?: boolean;
    }> {
        const form = new FormData();
        form.append("file", file);
        form.append("mode", mode);
        if (intervalSec != null) form.append("interval_sec", String(intervalSec));
        if (maxFrames != null) form.append("max_frames", String(maxFrames));

        const res = await fetch(`${this.baseUrl}/video/analyze`, {
            method: "POST",
            body: form,
        });
        if (!res.ok) {
            throw new Error(`API error: ${res.status} ${res.statusText} [/video/analyze]`);
        }
        return res.json();
    }

    async analyzeVideoUrl(
        url: string,
        mode: "learn" | "react" = "react",
        intervalSec?: number,
        maxFrames?: number,
    ): Promise<{
        mode: string;
        title?: string;
        duration?: number;
        scenes?: string[];
        frame_count?: number;
        strategies?: string[];
        memory_ids?: string[];
        success?: boolean;
    }> {
        return this.request("/video/analyze_url", {
            method: "POST",
            body: JSON.stringify({
                url,
                mode,
                interval_sec: intervalSec,
                max_frames: maxFrames,
            }),
        });
    }

    async fetchVideoStatus(): Promise<{
        enabled: boolean;
        frame_interval_sec: number;
        max_frames: number;
        concurrency: number;
    }> {
        return this.request("/video/status");
    }

    // ── Game (Minecraft) ──

    async fetchGameState(): Promise<Record<string, unknown>> {
        return this.request("/game/state");
    }

    async fetchGameStatus(): Promise<{ connected: boolean; enabled: boolean; game?: string }> {
        return this.request("/game/status");
    }

    async executeGameAction(action: string, params: Record<string, unknown> = {}): Promise<Record<string, unknown>> {
        return this.request("/game/action", {
            method: "POST",
            body: JSON.stringify({ action, params }),
        });
    }

    async connectGame(host: string = "localhost", port: number = 25565): Promise<Record<string, unknown>> {
        return this.request("/game/connect", {
            method: "POST",
            body: JSON.stringify({ host, port }),
        });
    }

    async disconnectGame(): Promise<void> {
        await this.request("/game/disconnect", { method: "POST" });
    }
}

/**
 * Static file URL builder (same logic as original api.ts).
 */
export function getStaticUrl(path: string): string {
    if (!path) return "";
    if (path.startsWith("http://") || path.startsWith("https://")) return path;
    if (path.startsWith("/static")) return path;
    return `/static${path.startsWith("/") ? "" : "/"}${path}`;
}

/** Singleton API client instance */
export const apiClient = new APIClient();
