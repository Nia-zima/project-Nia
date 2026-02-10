"use client";
import React, { useEffect, useMemo, useState } from "react";
import { API_URL } from "@/lib/api";
import { Check, X, RefreshCw } from "lucide-react";

type Phase5Pending = {
  kind?: string;
  text?: string;
  risk?: string;
  review_token?: string;
  pending_id?: string;
  action_id?: string;
  name?: string;
  description?: string;
  category?: string;
  risk_level?: string;
  risk_score?: number;
  payload?: Record<string, any>;
  decision?: {
    reason?: string;
    requires_confirmation?: boolean;
    suggested_depth?: number | null;
  };
  requested_at?: number;
};

type Phase5Result = {
  action_id?: string;
  status?: string;
  result?: any;
  approved_by?: string;
  ts?: number;
  source?: string;
};

interface ActionPanelProps {
  threadId?: string;
}

const riskBadge = (risk?: string) => {
  const key = (risk || "").toUpperCase();
  switch (key) {
    case "SAFE":
      return "border-emerald-400/30 text-emerald-200 bg-emerald-900/20";
    case "LOW":
      return "border-sky-400/30 text-sky-200 bg-sky-900/20";
    case "MEDIUM":
    case "MED":
      return "border-amber-400/30 text-amber-200 bg-amber-900/20";
    case "HIGH":
      return "border-orange-400/30 text-orange-200 bg-orange-900/20";
    case "CRITICAL":
      return "border-red-400/40 text-red-200 bg-red-900/30";
    default:
      return "border-white/10 text-gray-300 bg-white/5";
  }
};

export default function ActionPanel({ threadId = "default_thread" }: ActionPanelProps) {
  const [pending, setPending] = useState<Phase5Pending[]>([]);
  const [reviewToken, setReviewToken] = useState<string | null>(null);
  const [results, setResults] = useState<Phase5Result[]>([]);
  const [historyResults, setHistoryResults] = useState<Phase5Result[]>([]);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [reasonById, setReasonById] = useState<Record<string, string>>({});
  const [resultTab, setResultTab] = useState<"state" | "history">("state");

  const fetchPending = async () => {
    try {
      const res = await fetch(
        `${API_URL}/actions/phase5/pending?thread_id=${encodeURIComponent(threadId)}`,
        { cache: "no-store" }
      );
      if (!res.ok) throw new Error(`pending fetch failed: ${res.status}`);
      const data = await res.json();
      const token = typeof data?.review_token === "string" ? data.review_token : null;
      setReviewToken(token);
      const items = Array.isArray(data?.items) ? data.items : [];
      const normalized = items.map((item: Phase5Pending) => {
        if ((item?.kind || "").toLowerCase() === "say") {
          return { ...item, review_token: item.review_token || token || undefined };
        }
        return item;
      });
      setPending(normalized);
    } catch (e) {
      console.error(e);
      setError("pending_actions の取得に失敗しました");
    }
  };

  const fetchResults = async () => {
    try {
      const res = await fetch(
        `${API_URL}/actions/phase5/results?thread_id=${encodeURIComponent(threadId)}`,
        { cache: "no-store" }
      );
      if (!res.ok) throw new Error(`results fetch failed: ${res.status}`);
      const data = await res.json();
      setResults(Array.isArray(data?.items) ? data.items : []);
    } catch (e) {
      console.error(e);
      setError("action_results の取得に失敗しました");
    }
  };

  const fetchHistoryResults = async () => {
    try {
      const res = await fetch(
        `${API_URL}/actions/phase5/results/history?thread_id=${encodeURIComponent(threadId)}&limit=50`,
        { cache: "no-store" }
      );
      if (!res.ok) throw new Error(`results history fetch failed: ${res.status}`);
      const data = await res.json();
      setHistoryResults(Array.isArray(data?.items) ? data.items : []);
    } catch (e) {
      console.error(e);
      setError("action_results 履歴の取得に失敗しました");
    }
  };

  const refreshAll = async () => {
    setLoading(true);
    setError(null);
    await Promise.all([fetchPending(), fetchResults(), fetchHistoryResults()]);
    setLoading(false);
  };

  useEffect(() => {
    refreshAll();
  }, [threadId]);

  useEffect(() => {
    const handler = (ev: Event) => {
      const detail = (ev as CustomEvent).detail || {};
      if (!detail?.name) return;
      // action_proposed / action_approved / action_blocked
      refreshAll();
    };
    if (typeof window !== "undefined") {
      window.addEventListener("phase5-action-event", handler as EventListener);
      return () => window.removeEventListener("phase5-action-event", handler as EventListener);
    }
  }, []);

  const updateReason = (pendingId: string | undefined, value: string) => {
    if (!pendingId) return;
    setReasonById((prev) => ({ ...prev, [pendingId]: value }));
  };

  const postDecision = async (item: Phase5Pending, decision: "approve" | "reject") => {
    const kind = (item.kind || "").toLowerCase();
    try {
      let res: Response;
      if (kind === "say") {
        const token = item.review_token || reviewToken;
        if (!token) {
          setError("review_token が見つからないため、承認/拒否できません");
          return;
        }
        res = await fetch(`${API_URL}/review/${decision}`, {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({ thread_id: threadId, review_token: token }),
        });
      } else {
        const actionId = item.action_id;
        const pendingId = item.pending_id;
        if (!actionId || !pendingId) {
          setError("action_id または pending_id が不足しているため、承認/拒否できません");
          return;
        }
        const reason = reasonById[pendingId] || "";
        res = await fetch(`${API_URL}/actions/phase5/${encodeURIComponent(actionId)}/${decision}`, {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({ thread_id: threadId, pending_id: pendingId, reason }),
        });
      }
      if (!res.ok) throw new Error(`${decision} failed: ${res.status}`);
      await refreshAll();
    } catch (e) {
      console.error(e);
      setError(`アクションの${decision}に失敗しました`);
    }
  };

  const pendingCount = pending.length;
  const recentResults = useMemo(() => results.slice(-6).reverse(), [results]);
  const recentHistoryResults = useMemo(() => historyResults.slice(0, 10), [historyResults]);

  return (
    <div className="h-full w-full p-3">
      <div className="flex items-center justify-between">
        <div className="text-sm font-semibold text-white/90">Phase5 Actions</div>
        <button
          onClick={refreshAll}
          className="flex items-center gap-1 text-xs text-gray-300 hover:text-white"
          title="再読み込み"
        >
          <RefreshCw size={14} />
          更新
        </button>
      </div>
      <div className="mt-1 text-[11px] text-gray-400">pending: {pendingCount}</div>
      {error && <div className="mt-2 text-xs text-red-300">{error}</div>}

      <div className="mt-3 space-y-3">
        {pending.map((item, idx) => {
          const pendingId = item.pending_id;
          const actionId = item.action_id;
          const decision = item.decision || {};
          const isSayPreview = (item.kind || "").toLowerCase() === "say";
          const title = isSayPreview ? "Speech Preview" : item.name || actionId;
          const risk = item.risk_level || item.risk;
          const itemKey =
            pendingId ||
            `${actionId || item.kind || "unknown-action"}:${item.requested_at || "no-ts"}:${item.name || "no-name"}:${idx}`;
          return (
            <div key={itemKey} className="rounded-xl border border-white/10 bg-white/5 p-3">
              <div className="flex items-center justify-between gap-2">
                <div className="text-sm text-white/90">{title}</div>
                <span className={`text-[10px] px-2 py-0.5 rounded-full border ${riskBadge(risk)}`}>
                  {risk || "UNKNOWN"}
                </span>
              </div>
              {item.description && (
                <div className="mt-1 text-xs text-gray-400">{item.description}</div>
              )}
              {isSayPreview && item.text && (
                <div className="mt-2 text-xs text-gray-300 line-clamp-3">{item.text}</div>
              )}
              {decision.reason && (
                <div className="mt-2 text-[11px] text-amber-200/80">理由: {decision.reason}</div>
              )}
              {decision.requires_confirmation && (
                <div className="mt-1 text-[11px] text-amber-200/70">要確認</div>
              )}
              <div className="mt-2 flex items-center gap-2">
                {!isSayPreview && (
                  <input
                    type="text"
                    value={pendingId ? (reasonById[pendingId] || "") : ""}
                    onChange={(e) => updateReason(pendingId, e.target.value)}
                    placeholder="理由（任意）"
                    className="flex-1 rounded-lg bg-black/30 px-2 py-1 text-xs text-gray-100 placeholder:text-gray-500"
                  />
                )}
                <button
                  onClick={() => postDecision(item, "approve")}
                  className="flex items-center gap-1 rounded-lg border border-emerald-500/40 bg-emerald-500/20 px-2 py-1 text-xs text-emerald-100"
                >
                  <Check size={12} /> 承認
                </button>
                <button
                  onClick={() => postDecision(item, "reject")}
                  className="flex items-center gap-1 rounded-lg border border-red-500/40 bg-red-500/20 px-2 py-1 text-xs text-red-100"
                >
                  <X size={12} /> 拒否
                </button>
              </div>
            </div>
          );
        })}
        {!loading && pending.length === 0 && (
          <div className="text-xs text-gray-400">保留中のアクションはありません。</div>
        )}
      </div>

      <div className="mt-4 border-t border-white/10 pt-3">
        <div className="flex items-center justify-between">
          <div className="text-xs text-gray-300">実行結果</div>
          <div className="flex items-center gap-2 text-[10px]">
            <button
              onClick={() => setResultTab("state")}
              className={`rounded-full border px-2 py-0.5 ${
                resultTab === "state"
                  ? "border-sky-400/50 text-sky-200 bg-sky-500/20"
                  : "border-white/10 text-gray-400"
              }`}
            >
              最新（state）
            </button>
            <button
              onClick={() => setResultTab("history")}
              className={`rounded-full border px-2 py-0.5 ${
                resultTab === "history"
                  ? "border-rose-400/50 text-rose-200 bg-rose-500/20"
                  : "border-white/10 text-gray-400"
              }`}
            >
              履歴（永続）
            </button>
          </div>
        </div>
        <div className="mt-2 space-y-2">
          {(resultTab === "state" ? recentResults : recentHistoryResults).map((r, idx) => (
            <div key={`${r.action_id}-${idx}`} className="rounded-lg border border-white/10 bg-white/5 px-2 py-2">
              <div className="flex items-center justify-between text-xs">
                <span className="text-gray-200">{r.action_id}</span>
                <span className={`text-[10px] ${r.status === "success" ? "text-emerald-200" : "text-red-200"}`}>
                  {r.status}
                </span>
              </div>
              {r.source && (
                <div className="mt-1 text-[10px] text-gray-500">source: {r.source}</div>
              )}
              {r.result?.message && (
                <div className="mt-1 text-[11px] text-gray-400">{r.result.message}</div>
              )}
            </div>
          ))}
          {resultTab === "state" && recentResults.length === 0 && (
            <div className="text-xs text-gray-400">まだ実行結果はありません。</div>
          )}
          {resultTab === "history" && recentHistoryResults.length === 0 && (
            <div className="text-xs text-gray-400">履歴はまだありません。</div>
          )}
        </div>
      </div>
    </div>
  );
}
