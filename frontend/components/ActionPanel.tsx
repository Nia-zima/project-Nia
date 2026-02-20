"use client";
import React, { useEffect, useMemo, useState } from "react";
import { apiClient } from "@/lib/apiClient";
import { Check, X, RefreshCw } from "lucide-react";
import type { PendingAction, ActionResult } from "@/lib/types";

type Phase5Pending = PendingAction;
type Phase5Result = ActionResult;

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

type TweetProposal = {
  tweet_text: string;
  proposed_at: number;
  id: string;
  thread_id: string;
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
  const [tweetProposal, setTweetProposal] = useState<TweetProposal | null>(null);

  const fetchPending = async () => {
    try {
      const data = await apiClient.fetchPhase5Pending(threadId);
      const token = typeof data?.review_token === "string" ? data.review_token : null;
      setReviewToken(token);
      const items = (Array.isArray(data?.items) ? data.items : []) as Phase5Pending[];
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
      const data = await apiClient.fetchPhase5Results(threadId);
      setResults((Array.isArray(data?.items) ? data.items : []) as Phase5Result[]);
    } catch (e) {
      console.error(e);
      setError("action_results の取得に失敗しました");
    }
  };

  const fetchHistoryResults = async () => {
    try {
      const data = await apiClient.fetchPhase5ResultsHistory(threadId, 50);
      setHistoryResults((Array.isArray(data?.items) ? data.items : []) as Phase5Result[]);
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

  // Poll for autonomous tweet proposals (from Reflection Engine)
  useEffect(() => {
    const pollTweet = async () => {
      try {
        const data = await apiClient.fetchPendingTweet();
        setTweetProposal(data?.proposal ?? null);
      } catch {
        // Silently ignore polling errors
      }
    };
    pollTweet();
    const interval = setInterval(pollTweet, 30_000);
    return () => clearInterval(interval);
  }, []);

  const handleTweetDecision = async (decision: "approve" | "reject") => {
    try {
      if (decision === "approve" && tweetProposal) {
        await apiClient.approveTweet(tweetProposal.tweet_text, tweetProposal.thread_id || threadId);
      } else {
        await apiClient.rejectTweet();
      }
      setTweetProposal(null);
    } catch (e) {
      console.error(e);
      setError(`ツイートの${decision}に失敗しました`);
    }
  };

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
      if (kind === "say") {
        const token = item.review_token || reviewToken;
        if (!token) {
          setError("review_token が見つからないため、承認/拒否できません");
          return;
        }
        await apiClient.postReviewDecision(decision, threadId, token);
      } else {
        const actionId = item.action_id;
        const pendingId = item.pending_id;
        if (!actionId || !pendingId) {
          setError("action_id または pending_id が不足しているため、承認/拒否できません");
          return;
        }
        const reason = reasonById[pendingId] || "";
        await apiClient.postPhase5Decision(actionId, decision, {
          thread_id: threadId,
          pending_id: pendingId,
          reason,
        });
      }
      await refreshAll();
    } catch (e) {
      console.error(e);
      setError(`アクションの${decision}に失敗しました`);
    }
  };

  const pendingCount = pending.length;
  const hasPending = pendingCount > 0;
  const recentResults = useMemo(() => results.slice(-6).reverse(), [results]);
  const recentHistoryResults = useMemo(() => historyResults.slice(0, 10), [historyResults]);

  return (
    <div className="h-full w-full p-2.5 text-[13px] flex flex-col min-h-0">
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
      <div className="mt-0.5 text-[11px] text-gray-400">pending: {pendingCount}</div>
      {error && <div className="mt-1 text-xs text-red-300">{error}</div>}

      <div
        className={`mt-2.5 space-y-2.5 pr-1 ${
          hasPending || tweetProposal ? "flex-1 min-h-0 overflow-y-auto" : ""
        }`}
      >
        {/* Autonomous tweet proposal (from Reflection Engine) */}
        {tweetProposal && (
          <div className="rounded-xl border border-blue-400/30 bg-blue-900/20 p-2.5">
            <div className="flex items-center justify-between gap-2">
              <div className="text-sm text-blue-100 flex items-center gap-1.5">
                <span className="text-base">𝕏</span> Tweet Proposal
              </div>
              <span className="text-[10px] px-2 py-0.5 rounded-full border border-blue-400/30 text-blue-200 bg-blue-900/30">
                {tweetProposal.tweet_text.length}/280
              </span>
            </div>
            <div className="mt-2 text-xs text-gray-200 bg-black/30 rounded-lg p-2 whitespace-pre-wrap">
              {tweetProposal.tweet_text}
            </div>
            <div className="mt-1.5 flex items-center gap-2">
              <button
                onClick={() => handleTweetDecision("approve")}
                className="flex items-center gap-1 rounded-lg border border-emerald-500/40 bg-emerald-500/20 px-2 py-1 text-xs text-emerald-100"
              >
                <Check size={12} /> 投稿する
              </button>
              <button
                onClick={() => handleTweetDecision("reject")}
                className="flex items-center gap-1 rounded-lg border border-red-500/40 bg-red-500/20 px-2 py-1 text-xs text-red-100"
              >
                <X size={12} /> 却下
              </button>
            </div>
          </div>
        )}
        {pending.map((item, idx) => {
          const pendingId = item.pending_id;
          const actionId = item.action_id;
          const decision = item.decision || {};
          const isSayPreview = (item.kind || "").toLowerCase() === "say";
          const isTweetPreview = actionId === "post_tweet";
          const title = isSayPreview ? "Speech Preview" : isTweetPreview ? "Tweet Preview" : item.name || actionId;
          const risk = item.risk_level || item.risk;
          const itemKey =
            pendingId ||
            `${actionId || item.kind || "unknown-action"}:${item.requested_at || "no-ts"}:${item.name || "no-name"}:${idx}`;
          return (
            <div key={itemKey} className="rounded-xl border border-white/10 bg-white/5 p-2.5">
              <div className="flex items-center justify-between gap-2">
                <div className="text-sm text-white/90">{title}</div>
                <span className={`text-[10px] px-2 py-0.5 rounded-full border ${riskBadge(risk)}`}>
                  {risk || "UNKNOWN"}
                </span>
              </div>
              {item.description && <div className="mt-1 text-xs text-gray-400">{item.description}</div>}
              {isSayPreview && item.text && (
                <div className="mt-2 text-xs text-gray-300 line-clamp-3">{item.text}</div>
              )}
              {isTweetPreview && item.payload?.tweet_text && (
                <div className="mt-2">
                  <div className="text-[10px] text-blue-300 flex items-center gap-1">
                    <span>𝕏</span>
                    <span>{String(item.payload.tweet_text).length}/280</span>
                  </div>
                  <div className="mt-1 text-xs text-gray-200 bg-black/30 rounded-lg p-2 whitespace-pre-wrap">
                    {String(item.payload.tweet_text)}
                  </div>
                </div>
              )}
              {decision.reason && (
                <div className="mt-2 text-[11px] text-amber-200/80">理由: {decision.reason}</div>
              )}
              {decision.requires_confirmation && (
                <div className="mt-1 text-[11px] text-amber-200/70">要確認</div>
              )}
              <div className="mt-1.5 flex items-center gap-2">
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

      <div className="mt-1.5 border-t border-white/10 pt-1 flex flex-col min-h-0 shrink-0">
        <div className="flex items-center justify-between">
          <div className="text-[10px] text-gray-300">実行結果</div>
          <div className="flex items-center gap-1.5 text-[10px]">
            <button
              onClick={() => setResultTab("state")}
              className={`rounded-full border px-1 py-0 ${
                resultTab === "state"
                  ? "border-sky-400/50 text-sky-200 bg-sky-500/20"
                  : "border-white/10 text-gray-400"
              }`}
            >
              最新（state）
            </button>
            <button
              onClick={() => setResultTab("history")}
              className={`rounded-full border px-1 py-0 ${
                resultTab === "history"
                  ? "border-rose-400/50 text-rose-200 bg-rose-500/20"
                  : "border-white/10 text-gray-400"
              }`}
            >
              履歴（永続）
            </button>
          </div>
        </div>
        <div className="mt-0.5 space-y-0.5 overflow-y-auto pr-1 min-h-0 max-h-16">
          {(resultTab === "state" ? recentResults : recentHistoryResults).map((r, idx) => (
            <div key={`${r.action_id}-${idx}`} className="rounded-lg border border-white/10 bg-white/5 px-1 py-0.5">
              <div className="flex items-center justify-between text-[11px]">
                <span className="text-gray-200">{r.action_id}</span>
                <span className={`text-[10px] ${r.status === "success" ? "text-emerald-200" : "text-red-200"}`}>
                  {r.status}
                </span>
              </div>
              {r.source && (
                <div className="mt-0.5 text-[10px] text-gray-500">source: {r.source}</div>
              )}
              {r.result && typeof r.result === "object" && "message" in r.result && (
                <div className="mt-0.5 text-[10px] text-gray-400">{String(r.result.message)}</div>
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
