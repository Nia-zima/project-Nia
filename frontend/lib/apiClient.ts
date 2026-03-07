/**
 * Unified API Client for project-nia frontend.
 * Centralizes all fetch() calls with typed responses.
 */

import type { ActionIssue, PendingAction, IdentityProposal } from './types';

export const API_URL = "/api";
const SYSTEM_TOKEN_STORAGE_KEY = "system_token";

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
    private systemToken: string | null = null;

    constructor(baseUrl: string = API_URL) {
        this.baseUrl = baseUrl;
        // Auto-load system token from env if available
        if (typeof process !== "undefined" && process.env?.NEXT_PUBLIC_SYSTEM_TOKEN) {
            this.systemToken = process.env.NEXT_PUBLIC_SYSTEM_TOKEN;
        }
        // Browser override (persisted from UI settings)
        if (typeof window !== "undefined") {
            const stored = window.localStorage.getItem(SYSTEM_TOKEN_STORAGE_KEY);
            if (stored && stored.trim()) {
                this.systemToken = stored.trim();
            }
        }
    }

    /** Set the system token for admin endpoints (game, video, system). */
    setSystemToken(token: string | null): void {
        this.systemToken = token;
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

    /** Like request(), but includes X-System-Token for admin endpoints. */
    private async adminRequest<T>(
        path: string,
        options?: RequestInit,
    ): Promise<T> {
        const headers: Record<string, string> = {
            "Content-Type": "application/json",
            ...(options?.headers as Record<string, string>),
        };
        if (this.systemToken) {
            headers["X-System-Token"] = this.systemToken;
        }
        const res = await fetch(`${this.baseUrl}${path}`, {
            ...options,
            headers,
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

        const headers: Record<string, string> = {};
        if (this.systemToken) {
            headers["X-System-Token"] = this.systemToken;
        }

        const res = await fetch(`${this.baseUrl}/video/analyze`, {
            method: "POST",
            headers,
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
        return this.adminRequest("/video/analyze_url", {
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

    // ── Review (Phase2 review window) ──

    async postReviewDecision(
        decision: "approve" | "reject",
        threadId: string,
        reviewToken: string,
    ): Promise<void> {
        await this.request(`/review/${decision}`, {
            method: "POST",
            body: JSON.stringify({ thread_id: threadId, review_token: reviewToken }),
        });
    }

    // ── Actions (Phase5) ──

    async postPhase5Decision(
        actionId: string,
        decision: "approve" | "reject",
        body: { thread_id: string; pending_id: string; reason?: string },
    ): Promise<void> {
        await this.request(`/actions/phase5/${encodeURIComponent(actionId)}/${decision}`, {
            method: "POST",
            body: JSON.stringify(body),
        });
    }

    async fetchPhase5Pending(threadId: string): Promise<{ items: unknown[]; review_token?: string }> {
        return this.request(`/actions/phase5/pending?thread_id=${encodeURIComponent(threadId)}`);
    }

    async fetchPhase5Results(threadId: string): Promise<{ items: unknown[] }> {
        return this.request(`/actions/phase5/results?thread_id=${encodeURIComponent(threadId)}`);
    }

    async fetchPhase5ResultsHistory(threadId: string, limit: number = 50): Promise<{ items: unknown[] }> {
        return this.request(`/actions/phase5/results/history?thread_id=${encodeURIComponent(threadId)}&limit=${limit}`);
    }

    async archiveAction(actionId: string): Promise<void> {
        await this.request(`/actions/${encodeURIComponent(actionId)}/archive`, {
            method: "POST",
            body: JSON.stringify({}),
        });
    }

    async fetchActionIssues(threadId: string, status: string, limit: number = 100): Promise<{ items: ActionIssue[] }> {
        return this.request(`/actions/pending?thread_id=${encodeURIComponent(threadId)}&status=${encodeURIComponent(status)}&limit=${limit}`);
    }

    // ── Memory ──

    async fetchCaptures(threadId: string = "default_thread", limit: number = 50): Promise<Record<string, unknown>> {
        return this.request(`/memory/captures?limit=${limit}&thread_id=${encodeURIComponent(threadId)}`);
    }

    async fetchLongTerm(threadId: string = "default_thread", limit: number = 50): Promise<Record<string, unknown>> {
        return this.request(`/memory/long_term?limit=${limit}&thread_id=${encodeURIComponent(threadId)}`);
    }

    async deleteCapture(id: string, threadId: string = "default_thread"): Promise<boolean> {
        const res = await fetch(`${this.baseUrl}/memory/captures/${encodeURIComponent(id)}?thread_id=${encodeURIComponent(threadId)}`, {
            method: "DELETE",
        });
        return res.ok || res.status === 404;
    }

    async deleteLongTerm(id: string, threadId: string = "default_thread"): Promise<boolean> {
        const res = await fetch(`${this.baseUrl}/memory/long_term/${encodeURIComponent(id)}?thread_id=${encodeURIComponent(threadId)}`, {
            method: "DELETE",
        });
        return res.ok || res.status === 404;
    }

    // ── Stats ──

    async fetchStatsSummary(): Promise<Record<string, unknown>> {
        return this.request("/stats/summary");
    }

    async fetchInternalState(): Promise<Record<string, unknown>> {
        return this.request("/stats/internal_state");
    }

    async fetchCheckpointerStats(): Promise<{
        size_mb: number; threads: number; checkpoints: number; retention_days: number;
    }> {
        return this.request("/stats/checkpointer");
    }

    async fetchMemoryGraph(threshold: number = 0.5, limit: number = 100): Promise<Record<string, unknown>> {
        return this.request(`/stats/memory_graph?threshold=${threshold}&limit=${limit}`);
    }

    async fetchMemoryTimeline(): Promise<Record<string, unknown>> {
        return this.request("/stats/memory_timeline");
    }

    async fetchInnerMonologue(limit: number = 100): Promise<Record<string, unknown>> {
        return this.request(`/stats/inner_monologue?limit=${limit}`);
    }

    async fetchDiagnostics(threadId: string): Promise<Record<string, unknown>> {
        return this.request(`/diagnostics?thread_id=${encodeURIComponent(threadId)}`);
    }

    async fetchObservationReport(lastN?: string): Promise<Record<string, unknown>> {
        const params = lastN && lastN !== "all" ? `?last=${lastN}` : "";
        return this.request(`/stats/observation_report${params}`);
    }

    // ── Profile ──

    async fetchProfile(): Promise<Record<string, unknown>> {
        return this.request("/profile");
    }

    async updateProfile(data: Record<string, unknown>): Promise<void> {
        await this.request("/profile", {
            method: "POST",
            body: JSON.stringify(data),
        });
    }

    // ── Status ──

    async fetchStatus(): Promise<Record<string, unknown>> {
        return this.request("/status");
    }

    // ── System (admin) ──

    async systemVision(enabled: boolean): Promise<void> {
        await this.adminRequest("/system/vision", {
            method: "POST",
            body: JSON.stringify({ enabled }),
        });
    }

    async systemSleep(): Promise<void> {
        await this.adminRequest("/system/sleep", { method: "POST" });
    }

    // ── Draw ──

    async drawSessionStart(params: {
        prompt: string; width: number; height: number;
        interval_sec?: number; max_strokes?: number; timeout_sec?: number;
    }): Promise<Record<string, unknown>> {
        return this.request("/draw/session/start", {
            method: "POST",
            body: JSON.stringify(params),
        });
    }

    async drawSessionStop(sessionId: string, emergency: boolean = false): Promise<void> {
        await this.request("/draw/session/stop", {
            method: "POST",
            body: JSON.stringify({ session_id: sessionId, emergency }),
        });
    }

    async drawSessionState(): Promise<Record<string, unknown>> {
        return this.request("/draw/session/state");
    }

    async drawObserve(sessionId: string, imageData: string): Promise<void> {
        await this.request("/draw/observe", {
            method: "POST",
            body: JSON.stringify({ session_id: sessionId, image_data: imageData }),
        });
    }

    async drawCommands(sessionId: string, sinceSeq: number, limit: number = 100): Promise<Record<string, unknown>> {
        return this.request(
            `/draw/commands?session_id=${encodeURIComponent(sessionId)}&since_seq=${sinceSeq}&limit=${limit}`,
        );
    }

    // ── Game (Minecraft) ──

    async fetchGameState(): Promise<Record<string, unknown>> {
        return this.request("/game/state");
    }

    async fetchGameStatus(): Promise<{ connected: boolean; enabled: boolean; game?: string }> {
        return this.request("/game/status");
    }

    async executeGameAction(action: string, params: Record<string, unknown> = {}): Promise<Record<string, unknown>> {
        return this.adminRequest("/game/action", {
            method: "POST",
            body: JSON.stringify({ action, params }),
        });
    }

    async connectGame(host: string = "localhost", port: number = 25565): Promise<Record<string, unknown>> {
        return this.adminRequest("/game/connect", {
            method: "POST",
            body: JSON.stringify({ host, port }),
        });
    }

    async disconnectGame(): Promise<void> {
        await this.adminRequest("/game/disconnect", { method: "POST" });
    }

    // ── Identity Proposals (admin) ──

    async fetchIdentityProposals(
        status?: string,
        limit: number = 50,
    ): Promise<{ items: IdentityProposal[]; total: number }> {
        const params = new URLSearchParams();
        if (status) params.set("status", status);
        params.set("limit", String(limit));
        return this.adminRequest(`/identity/proposals?${params.toString()}`);
    }

    async approveIdentityProposal(
        proposalId: string,
        reviewNote?: string,
    ): Promise<{ ok: boolean; applied?: boolean }> {
        return this.adminRequest(`/identity/proposals/${encodeURIComponent(proposalId)}/approve`, {
            method: "POST",
            body: JSON.stringify({ review_note: reviewNote || null }),
        });
    }

    async rejectIdentityProposal(
        proposalId: string,
        reviewNote?: string,
    ): Promise<{ ok: boolean }> {
        return this.adminRequest(`/identity/proposals/${encodeURIComponent(proposalId)}/reject`, {
            method: "POST",
            body: JSON.stringify({ review_note: reviewNote || null }),
        });
    }

    // ── Diary ──

    async fetchDiaries(limit: number = 14): Promise<Array<{
        date: string;
        content: { text: string; mood: string; topics: string[] };
        created_at: number;
    }>> {
        return this.request(`/diary/recent?limit=${limit}`);
    }

    // ── Twitter (X) ──

    async fetchPendingTweet(): Promise<{ proposal: { tweet_text: string; proposed_at: number; id: string; thread_id: string } | null }> {
        return this.request("/actions/tweet/pending");
    }

    async approveTweet(tweetText: string, threadId: string = "default_thread"): Promise<{ ok: boolean; tweet_id?: string }> {
        return this.request("/actions/tweet/approve", {
            method: "POST",
            body: JSON.stringify({ tweet_text: tweetText, thread_id: threadId }),
        });
    }

    async rejectTweet(): Promise<{ ok: boolean }> {
        return this.request("/actions/tweet/reject", { method: "POST" });
    }

    async generateTweet(style: string = "casual", context: string = ""): Promise<{ tweet_text: string; char_count: number }> {
        return this.request("/actions/tweet/generate", {
            method: "POST",
            body: JSON.stringify({ style, context }),
        });
    }

    async fetchTweetHistory(limit: number = 20): Promise<{ items: Array<{ tweet_text: string; tweet_id: string; char_count: number; created_at: number }> }> {
        return this.request(`/actions/tweet/history?limit=${limit}`);
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
