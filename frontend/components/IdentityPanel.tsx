"use client";
import React, { useEffect, useState } from "react";
import { apiClient } from "@/lib/apiClient";
import { Check, X, RefreshCw, Clock, CheckCircle, XCircle, Zap } from "lucide-react";
import type { IdentityProposal } from "@/lib/types";

export default function IdentityPanel() {
    const [proposals, setProposals] = useState<IdentityProposal[]>([]);
    const [loading, setLoading] = useState(false);
    const [error, setError] = useState<string | null>(null);
    const [tab, setTab] = useState<"pending" | "all">("pending");
    const [noteById, setNoteById] = useState<Record<string, string>>({});

    const fetchProposals = async () => {
        setLoading(true);
        setError(null);
        try {
            const statusFilter = tab === "pending" ? "pending" : undefined;
            const data = await apiClient.fetchIdentityProposals(statusFilter, 100);
            setProposals(data.items);
        } catch {
            setError("提案の取得に失敗しました");
        } finally {
            setLoading(false);
        }
    };

    useEffect(() => {
        fetchProposals();
    }, [tab]); // eslint-disable-line react-hooks/exhaustive-deps

    const handleDecision = async (id: string, decision: "approve" | "reject") => {
        try {
            const note = noteById[id] || undefined;
            if (decision === "approve") {
                await apiClient.approveIdentityProposal(id, note);
            } else {
                await apiClient.rejectIdentityProposal(id, note);
            }
            await fetchProposals();
        } catch {
            setError(`${decision === "approve" ? "承認" : "却下"}に失敗しました`);
        }
    };

    const statusIcon = (status: string) => {
        switch (status) {
            case "pending":      return <Clock size={12} className="text-amber-300" />;
            case "approved":     return <CheckCircle size={12} className="text-emerald-300" />;
            case "rejected":     return <XCircle size={12} className="text-red-300" />;
            case "auto_applied": return <Zap size={12} className="text-sky-300" />;
            default:             return null;
        }
    };

    const statusLabel = (status: string) => {
        switch (status) {
            case "pending":      return "保留中";
            case "approved":     return "承認済";
            case "rejected":     return "却下";
            case "auto_applied": return "自動適用";
            default:             return status;
        }
    };

    const importanceBadge = (imp: number | null) => {
        if (imp == null) return null;
        const color = imp < 0.3
            ? "border-emerald-400/30 text-emerald-200 bg-emerald-900/20"
            : imp < 0.6
            ? "border-amber-400/30 text-amber-200 bg-amber-900/20"
            : "border-red-400/30 text-red-200 bg-red-900/20";
        return (
            <span className={`text-[10px] px-2 py-0.5 rounded-full border ${color}`}>
                imp: {imp.toFixed(2)}
            </span>
        );
    };

    const renderCard = (p: IdentityProposal) => {
        const isPending = p.status === "pending";
        return (
            <div key={p.id} className="rounded-xl border border-white/10 bg-white/5 p-3">
                <div className="flex items-center justify-between gap-2">
                    <div className="flex items-center gap-1.5">
                        {statusIcon(p.status)}
                        <span className="text-[11px] text-gray-300">{statusLabel(p.status)}</span>
                        <span className="text-xs text-gray-500">{p.date}</span>
                    </div>
                    {importanceBadge(p.importance)}
                </div>
                {p.chapter_context && (
                    <div className="mt-1 text-[11px] text-purple-300/80">
                        章: {p.chapter_context}
                    </div>
                )}
                <pre className="mt-2 text-xs text-gray-200 whitespace-pre-wrap font-sans leading-relaxed">
                    {p.proposal}
                </pre>
                {p.review_note && (
                    <div className="mt-1.5 text-[11px] text-sky-200/80">
                        メモ: {p.review_note}
                    </div>
                )}
                {p.resolved_at && (
                    <div className="mt-1 text-[10px] text-gray-500">
                        {new Date(p.resolved_at * 1000).toLocaleString("ja-JP")}
                    </div>
                )}
                {isPending && (
                    <div className="mt-2.5 flex items-center gap-2">
                        <input
                            type="text"
                            value={noteById[p.id] || ""}
                            onChange={(e) =>
                                setNoteById((prev) => ({ ...prev, [p.id]: e.target.value }))
                            }
                            placeholder="メモ（任意）"
                            className="flex-1 rounded-lg bg-black/30 px-2 py-1 text-xs text-gray-100 placeholder:text-gray-500 border border-white/5"
                        />
                        <button
                            onClick={() => handleDecision(p.id, "approve")}
                            className="flex items-center gap-1 rounded-lg border border-emerald-500/40 bg-emerald-500/20 px-2.5 py-1 text-xs text-emerald-100 hover:bg-emerald-500/30 transition-colors"
                        >
                            <Check size={12} /> 承認
                        </button>
                        <button
                            onClick={() => handleDecision(p.id, "reject")}
                            className="flex items-center gap-1 rounded-lg border border-red-500/40 bg-red-500/20 px-2.5 py-1 text-xs text-red-100 hover:bg-red-500/30 transition-colors"
                        >
                            <X size={12} /> 却下
                        </button>
                    </div>
                )}
            </div>
        );
    };

    return (
        <div className="h-full w-full p-4 text-[13px] flex flex-col min-h-0">
            <div className="flex items-center justify-between">
                <div className="text-sm font-semibold text-white/90">
                    Identity Proposals
                </div>
                <button
                    onClick={fetchProposals}
                    disabled={loading}
                    className="flex items-center gap-1 text-xs text-gray-300 hover:text-white transition-colors disabled:opacity-50"
                >
                    <RefreshCw size={14} className={loading ? "animate-spin" : ""} /> 更新
                </button>
            </div>

            <div className="mt-2 flex gap-1.5">
                {(["pending", "all"] as const).map((t) => (
                    <button
                        key={t}
                        onClick={() => setTab(t)}
                        className={`rounded-full border px-3 py-0.5 text-[11px] transition-colors ${
                            tab === t
                                ? "border-sky-400/50 text-sky-200 bg-sky-500/20"
                                : "border-white/10 text-gray-400 hover:border-white/20"
                        }`}
                    >
                        {t === "pending" ? "保留中" : "全て"}
                    </button>
                ))}
            </div>

            {error && <div className="mt-2 text-xs text-red-300">{error}</div>}

            <div className="mt-3 flex-1 min-h-0 overflow-y-auto space-y-2.5 pr-1">
                {proposals.length > 0
                    ? proposals.map((p) => renderCard(p))
                    : !loading && (
                        <div className="text-xs text-gray-500 text-center mt-8">
                            {tab === "pending"
                                ? "保留中の提案はありません"
                                : "提案はまだありません"}
                        </div>
                    )}
            </div>
        </div>
    );
}
