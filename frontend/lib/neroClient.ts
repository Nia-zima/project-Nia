/**
 * Nero API Client — connects to Nero's server via /nero/* proxy.
 *
 * Separate from apiClient.ts to maintain the architectural boundary:
 * Nero is an independent system with its own server.
 */

const NERO_BASE = "";

// ── Types ──────────────────────────────────────────────────────

export interface NeroChatMessage {
  role: "user" | "nero";
  text: string;
  ts: string;
}

export interface NeroHealthResult {
  status: string;
  nia_reachable: boolean;
  gemini_configured: boolean;
  anthropic_configured: boolean;
}

export interface NeroMeetingSession {
  session_id: string;
  topic: string;
  turn_count: number;
  final_verdict: string;
  saved_at: string;
  filename: string;
}

export interface NeroMeetingTurn {
  nero: string;
  nia: string | null;
  verdict: string;
  observations?: Array<{
    type: string;
    aspect: string;
    description: string;
  }>;
  coherence?: string;
}

export interface NeroMeetingDetail {
  topic: string;
  thread_id: string;
  turns: NeroMeetingTurn[];
  discoveries: Array<{ discovery: string; category: string; date: string }>;
  final_verdict: string;
  saved_at: string;
}

export interface NeroTweetLog {
  tweet_text: string;
  tweet_id: string | null;
  style: string;
  trigger: string;
  char_count: number;
  posted_at: string;
}

// ── Client ─────────────────────────────────────────────────────

class NeroClient {
  private _available: boolean | null = null;

  private async request<T>(
    path: string,
    options?: RequestInit,
  ): Promise<T> {
    const res = await fetch(`${NERO_BASE}${path}`, {
      ...options,
      headers: {
        "Content-Type": "application/json",
        ...options?.headers,
      },
    });
    if (!res.ok) {
      const body = await res.text().catch(() => "");
      throw new Error(
        `Nero API error: ${res.status} [${path}] ${body}`,
      );
    }
    return res.json();
  }

  /** Check if Nero server is reachable. Caches result until reset. */
  async isAvailable(): Promise<boolean> {
    if (this._available !== null) return this._available;
    try {
      const res = await fetch(`${NERO_BASE}/nero/health`, {
        signal: AbortSignal.timeout(3000),
      });
      this._available = res.ok;
    } catch {
      this._available = false;
    }
    return this._available;
  }

  /** Reset cached availability — forces re-check on next call. */
  resetAvailability(): void {
    this._available = null;
  }

  // ── Health ──

  async health(): Promise<NeroHealthResult> {
    return this.request("/nero/health");
  }

  // ── Direct Chat ──

  async chat(
    text: string,
    threadId: string = "nero_chat",
  ): Promise<{ response: string; thread_id: string }> {
    return this.request("/nero/chat", {
      method: "POST",
      body: JSON.stringify({ text, thread_id: threadId }),
    });
  }

  async chatHistory(
    threadId: string = "nero_chat",
  ): Promise<{ thread_id: string; messages: NeroChatMessage[] }> {
    return this.request(
      `/nero/chat/history?thread_id=${encodeURIComponent(threadId)}`,
    );
  }

  async chatClear(threadId: string = "nero_chat"): Promise<void> {
    await this.request(
      `/nero/chat/clear?thread_id=${encodeURIComponent(threadId)}`,
      { method: "POST" },
    );
  }

  // ── Meetings (Phase 2) ──

  async startMeeting(
    topic?: string,
    maxTurns?: number,
  ): Promise<{
    session_id: string;
    topic: string;
    category: string;
    status: string;
  }> {
    return this.request("/nero/meet", {
      method: "POST",
      body: JSON.stringify({ topic, max_turns: maxTurns }),
    });
  }

  /** Returns an EventSource for live meeting updates. */
  meetingStream(sessionId: string): EventSource {
    return new EventSource(
      `${NERO_BASE}/nero/meet/${encodeURIComponent(sessionId)}/stream`,
    );
  }

  async listSessions(limit: number = 20): Promise<NeroMeetingSession[]> {
    return this.request(`/nero/sessions?limit=${limit}`);
  }

  async getSession(filename: string): Promise<NeroMeetingDetail> {
    return this.request(
      `/nero/sessions/${encodeURIComponent(filename)}`,
    );
  }
  // ── Tweets ──

  async listTweets(limit: number = 20): Promise<NeroTweetLog[]> {
    return this.request(`/nero/tweets?limit=${limit}`);
  }
}

export const neroClient = new NeroClient();
