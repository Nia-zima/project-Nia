/**
 * Pure functions for normalizing chat message content.
 * Extracted from ChatInterface.tsx — no React dependencies.
 */
import type { ChatMessage } from '@/lib/apiClient';

// OpenAI-compatible content part types
type ContentPart =
    | { type: "text"; text?: string }
    | { type: "input_text"; text?: string }
    | { type: "image_url"; image_url?: { url?: string } }
    | { type: string; [k: string]: any };

/** Normalize OpenAI-compatible content (string | array | object) to a plain string. */
export function normalizeContent(content: any): string {
    if (content == null) return "";

    if (typeof content === "string") return content;

    // Array (OpenAI-compatible multipart content)
    if (Array.isArray(content)) {
        return content
            .map((p: ContentPart) => {
                if (!p) return "";
                if (p.type === "text" || p.type === "input_text") return p.text ?? "";
                if (p.type === "image_url") {
                    const url = p.image_url?.url ?? "";
                    return url.startsWith("data:") ? "\n[画像]\n" : `\n[画像: ${url}]\n`;
                }
                return "";
            })
            .join("")
            .trim();
    }

    // Object (edge cases)
    if (typeof content === "object") {
        if ("text" in content && typeof (content as any).text === "string") return (content as any).text;
        if ("content" in content) return normalizeContent((content as any).content);
        try {
            const s = JSON.stringify(content);
            return s.length > 500 ? s.slice(0, 500) + "…" : s;
        } catch {
            return String(content);
        }
    }

    return String(content);
}

/** Strip `[[...]]` metadata blocks from content, returning only the speech portion. */
export function extractSpeech(input: any): string {
    const text = normalizeContent(input);

    if (text.trimStart().startsWith("[[")) {
        const lines = text.split("\n");
        const speechLines = lines.filter((l) => !l.trim().startsWith("[["));
        return speechLines.join("\n").trim();
    }

    const idx = text.indexOf("\n[[");
    if (idx !== -1) return text.slice(0, idx).trim();

    return text.trim();
}

/** Normalize a history message from the backend into a frontend ChatMessage. */
export function normalizeHistoryMessage(m: any): ChatMessage {
    const normalizeRole = (r: string | undefined) =>
        r === "assistant" ? "ai" : (r === "user" || r === "ai" || r === "system" ? r : "system");

    // 1) Already a string
    if (typeof m?.content === "string") {
        return { ...m, role: normalizeRole(m?.role), content: extractSpeech(m.content) };
    }

    // 2) OpenAI-compatible multipart content
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
        const safeImage =
            imageUrl && imageUrl.startsWith("data:") ? undefined : imageUrl;

        const role = normalizeRole(m?.role);

        return {
            ...m,
            role,
            content: text,
            type: safeImage ? "image" : "text",
            image: safeImage,
        };
    }

    // 3) Other object forms
    const role = normalizeRole(m?.role);
    return { ...m, role, content: extractSpeech(normalizeContent(m?.content)) };
}

/** Collapse whitespace for deduplication comparison. */
export function normalizeForDedup(s: string): string {
    return String(s || "").replace(/\s+/g, " ").trim();
}

/** Check if `incoming` is a duplicate suffix of `current`. */
export function isLikelyDuplicateAppend(current: string, incoming: string): boolean {
    const a = normalizeForDedup(current);
    const b = normalizeForDedup(incoming);
    if (!a || !b) return false;
    if (b.length < 20) return false;
    if (a.endsWith(b)) return true;
    return false;
}

/** Remove adjacent duplicate paragraphs and detect full-text repetition. */
export function dedupeAdjacentDuplicateParagraphs(text: string): string {
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
