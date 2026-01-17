// API URL: Use relative path for same-origin access via Next.js rewrites
// This works with Tailscale Serve HTTPS and eliminates CORS issues
export const API_URL = "/api";

export interface ChatMessage {
    id: string;
    role: 'user' | 'ai' | 'system';
    content: string;
    timestamp?: string;
    type?: 'text' | 'audio' | 'image';
    image?: string;
    kind?: 'dream';  // 夢メッセージの識別用
    meta?: Record<string, any>;  // 追加メタデータ
}

export const fetchHistory = async (threadId: string) => {
    const res = await fetch(`${API_URL}/history/${threadId}`);
    return res.json();
};

export const clearHistory = async (threadId: string) => {
    await fetch(`${API_URL}/history/${threadId}`, { method: 'DELETE' });
};

export const fetchConfig = async () => {
    const res = await fetch(`${API_URL}/config`);
    return res.json();
};

/**
 * 静的ファイルのURLを組み立てる。
 * - 絶対URLはそのまま返す
 * - /static/... の相対パスはそのまま返す（Next.js rewriteでバックエンドにプロキシされる）
 * - パスが /static で始まらない場合は /static を付与
 */
export const getStaticUrl = (path: string): string => {
    if (!path) return "";
    // 絶対URL（http://... or https://...）はそのまま
    if (path.startsWith("http://") || path.startsWith("https://")) {
        return path;
    }
    // 既に /static で始まっていればそのまま
    if (path.startsWith("/static")) {
        return path;
    }
    // それ以外は /static を付与
    return `/static${path.startsWith("/") ? "" : "/"}${path}`;
};
