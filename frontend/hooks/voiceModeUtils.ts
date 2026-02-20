export const AUTO_SEND_DEDUPE_MS = 4000;

export function toNum(v: string | undefined, fallback: number): number {
    const n = Number(v);
    return Number.isFinite(n) ? n : fallback;
}

interface BuildVoiceWsUrlParams {
    sessionId: string;
    clientId: string;
    explicitBase?: string;
    protocol: string;
    hostname: string;
    backendPort?: string;
}

export function buildVoiceWsUrl({
    sessionId,
    clientId,
    explicitBase = "",
    protocol,
    hostname,
    backendPort = "8000",
}: BuildVoiceWsUrlParams): string {
    const qs = `session_id=${encodeURIComponent(sessionId)}&client_id=${encodeURIComponent(clientId)}`;
    if (explicitBase) {
        return `${explicitBase.replace(/\/+$/, "")}/voice/ws?${qs}`;
    }
    const wsScheme = protocol === "https:" ? "wss" : "ws";
    return `${wsScheme}://${hostname}:${backendPort}/api/voice/ws?${qs}`;
}

export function normalizeAutoSendText(raw: string): string {
    return String(raw || "").trim();
}

export function shouldSkipAutoSend(
    text: string,
    previousText: string,
    elapsedMs: number,
    dedupeMs: number = AUTO_SEND_DEDUPE_MS,
): boolean {
    if (!text) return true;
    return text === previousText && elapsedMs < dedupeMs;
}
