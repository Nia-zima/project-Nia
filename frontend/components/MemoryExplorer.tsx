"use client";
import React, { useEffect, useState } from 'react';
import { API_URL } from '@/lib/api';
import { Clock, Database, Brain } from 'lucide-react';

interface Memory {
    id: string;
    summary: string;
    details: {
        raw_text?: string;
        state_tag?: string;
        retention?: number;
        stage?: string;
        stream_id?: string;
        message_id?: string;
        origin_message_id?: string;
        refs?: any;
        tags?: any;
    };
    timestamp: string;
    thread_id: string;
}

interface LongTermMemory {
    id: string;
    summary: string;
    details: string;
    category: string;
    created_at: string;
    metadata: any;
}

interface PendingMemory {
    id: string;
    summary: string;
    details: {
        raw_text?: string;
        state_tag?: string;
        retention?: number;
        stage?: string;
        stream_id?: string;
        message_id?: string;
        origin_message_id?: string;
        refs?: any;
        tags?: any;
    };
    timestamp: string;
    thread_id: string;
    status?: string;
    reason?: string;
}

export default function MemoryExplorer() {
    const [activeTab, setActiveTab] = useState<'approved' | 'pending' | 'long_term'>('pending');
    const statusLabel = (status?: string) => {
        switch ((status || "").toUpperCase()) {
            case "PENDING":
                return "承認待ち";
            case "APPROVED":
                return "承認済み";
            case "APPLIED":
                return "保存済み";
            case "REJECTED":
                return "却下";
            case "ERROR":
                return "失敗";
            default:
                return status || "不明";
        }
    };

    const stageLabel = (stage?: string) => {
        switch ((stage || "").toLowerCase()) {
            case "capture":
                return "記憶（確定）";
            case "background":
                return "記憶（保留）";
            case "shadow":
                return "未確定記憶";
            case "long_term":
                return "長期記憶";
            default:
                return stage || "不明";
        }
    };

    // Approved State
    const [memories, setMemories] = useState<Memory[]>([]);
    const [longTermMemories, setLongTermMemories] = useState<LongTermMemory[]>([]);

    // Pending State
    const [pendingItems, setPendingItems] = useState<PendingMemory[]>([]);
    const [loading, setLoading] = useState(false);

    const deleteApproved = async (id: string) => {
        const ok = confirm("この確定記憶を削除しますか？");
        if (!ok) return;
        try {
            const res = await fetch(`${API_URL}/memory/captures/${id}?thread_id=default_thread`, {
                method: "DELETE",
            });
            if (res.ok || res.status === 404) {
                setMemories(prev => prev.filter(item => String(item.id) !== String(id)));
            } else {
                console.error("Delete approved failed status:", res.status);
            }
        } catch (e) {
            console.error("Failed to delete long_term", e);
        }
    };

    const deleteLongTerm = async (id: string) => {
        const ok = confirm("この長期記憶を削除しますか？");
        if (!ok) return;
        try {
            const res = await fetch(`${API_URL}/memory/long_term/${id}?thread_id=default_thread`, {
                method: "DELETE",
            });
            if (res.ok || res.status === 404) {
                setLongTermMemories(prev => prev.filter(item => String(item.id) !== String(id)));
            } else {
                console.error("Delete long_term failed status:", res.status);
            }
        } catch (e) {
            console.error("Failed to delete long_term", e);
        }
    };

    const deletePending = async (id: string) => {
        const ok = confirm("この保留記憶を削除しますか？");
        if (!ok) return;
        try {
            const res = await fetch(`${API_URL}/actions/${id}/reject`, {
                method: "POST",
                headers: {
                    "Content-Type": "application/json",
                },
                body: JSON.stringify({ reason: "ui_delete" }),
            });
            if (res.ok || res.status === 404) {
                setPendingItems(prev => prev.filter(item => item.id !== id));
            } else {
                console.error("Reject failed status:", res.status);
            }
        } catch (e) {
            console.error("Failed to reject pending action", e);
        }
    };

    const approvePending = async (id: string) => {
        const ok = confirm("この保留記憶を了承しますか？");
        if (!ok) return;
        try {
            const res = await fetch(`${API_URL}/actions/${id}/approve`, {
                method: "POST",
                headers: {
                    "Content-Type": "application/json",
                },
                body: JSON.stringify({ reason: "ui_approve" }),
            });
            if (res.ok) {
                setPendingItems(prev => prev.filter(item => item.id !== id));
            } else {
                console.error("Approve failed status:", res.status);
            }
        } catch (e) {
            console.error("Failed to approve pending action", e);
        }
    };

    const fetchData = async () => {
        setLoading(true);

        // Fetch Approved (episodic captures)
        if (activeTab === 'approved') {
            try {
                const res = await fetch(`${API_URL}/memory/captures?limit=50&thread_id=default_thread&stage=capture`);
                if (res.ok) {
                    const items = await res.json();
                    setMemories(items || []);
                }
            } catch (e) {
                console.error("Failed to fetch memories", e);
            }
        }

        if (activeTab === 'long_term') {
            try {
                const res = await fetch(`${API_URL}/memory/long_term?limit=50&thread_id=default_thread`);
                if (res.ok) {
                    const items = await res.json();
                    setLongTermMemories(items || []);
                }
            } catch (e) {
                console.error("Failed to fetch long_term memories", e);
            }
        }

        // Fetch Pending (Phase3 pending_actions)
        if (activeTab === 'pending') {
            try {
                const res = await fetch(`${API_URL}/actions/pending?limit=50&thread_id=default_thread`);
                if (res.ok) {
                    const payload = await res.json();
                    const rawItems = Array.isArray(payload?.items) ? payload.items : [];
                    const mapped = rawItems.map((item: any) => {
                        let parsed: any = {};
                        try {
                            parsed = item?.payload_json ? JSON.parse(item.payload_json) : {};
                        } catch {
                            parsed = {};
                        }
                        const rawText = String(parsed?.raw_text ?? "");
                        const summary = rawText ? rawText.trim().split("\n")[0].slice(0, 120) : "(no text)";
                        const createdAt = item?.created_at ? Number(item.created_at) : 0;
                        const tsIso = createdAt ? new Date(createdAt * 1000).toISOString() : "";
                        return {
                            id: String(item?.id ?? ""),
                            timestamp: tsIso,
                            thread_id: String(item?.thread_id ?? ""),
                            summary,
                            details: {
                                raw_text: rawText,
                                state_tag: parsed?.state_tag,
                                retention: parsed?.retention,
                                stage: parsed?.stage,
                                stream_id: parsed?.stream_id,
                                message_id: parsed?.message_id,
                                origin_message_id: parsed?.origin_message_id,
                                refs: parsed?.refs,
                                tags: parsed?.tags,
                            },
                            status: item?.status ? String(item.status) : undefined,
                            reason: item?.reason ? String(item.reason) : undefined,
                        };
                    });
                    setPendingItems(mapped);
                } else {
                    console.error("Pending fetch failed status:", res.status);
                }
            } catch (e) {
                console.error("Failed to fetch pending_memories", e);
            }
        }

        setLoading(false);
    };

    useEffect(() => {
        fetchData();
    }, [activeTab]);

    if (loading && memories.length === 0 && pendingItems.length === 0) {
        return <div className="p-8 text-gray-400 animate-pulse font-mono">データ取得中...</div>;
    }

    return (
        <div className="relative space-y-6 pb-20">

            {/* Header & Tabs */}
            <div className="flex flex-col gap-4">
                <div className="rounded-3xl border border-white/10 bg-[rgba(15,18,24,0.92)] p-6">
                    <div className="flex flex-col gap-4 md:flex-row md:items-end md:justify-between">
                        <div>
                            <p className="text-[11px] uppercase tracking-[0.4em] text-cyan-200/70">Memory Database</p>
                            <h2 className="text-3xl md:text-4xl font-semibold text-white">
                                記憶アーカイブ
                            </h2>
                            <p className="text-sm text-slate-300/80 mt-2">
                                保留・承認・記録の流れを一枚のボードで把握します。
                            </p>
                        </div>
                        <div className="flex flex-wrap gap-3 text-xs text-slate-200/80">
                            <div className="rounded-2xl border border-cyan-400/20 bg-cyan-500/10 px-3 py-2">
                                承認待ち <span className="ml-1 text-cyan-200">{pendingItems.length}</span>
                            </div>
                            <div className="rounded-2xl border border-emerald-400/20 bg-emerald-500/10 px-3 py-2">
                                記憶（確定） <span className="ml-1 text-emerald-200">{memories.length}</span>
                            </div>
                            <div className="rounded-2xl border border-sky-400/20 bg-sky-500/10 px-3 py-2">
                                長期記憶 <span className="ml-1 text-sky-200">{longTermMemories.length}</span>
                            </div>
                        </div>
                    </div>
                </div>

                <div className="flex w-full max-w-lg rounded-2xl border border-white/10 bg-black/40 p-1">
                    <button
                        onClick={() => setActiveTab('pending')}
                        className={`flex-1 rounded-xl px-4 py-2 text-sm font-medium transition-all ${activeTab === 'pending'
                            ? 'bg-amber-500/10 text-amber-100 border border-amber-400/30'
                            : 'text-slate-400 hover:text-slate-200'
                            }`}
                    >
                        <div className="flex items-center justify-center gap-2">
                            <Clock size={16} />
                            承認待ち
                            {pendingItems.length > 0 && (
                                <span className="rounded-full bg-amber-400/20 px-2 py-0.5 text-[10px] text-amber-100">
                                    {pendingItems.length}
                                </span>
                            )}
                        </div>
                    </button>
                    <button
                        onClick={() => setActiveTab('approved')}
                        className={`flex-1 rounded-xl px-4 py-2 text-sm font-medium transition-all ${activeTab === 'approved'
                            ? 'bg-emerald-500/10 text-emerald-100 border border-cyan-400/30'
                            : 'text-slate-400 hover:text-slate-200'
                            }`}
                    >
                        <div className="flex items-center justify-center gap-2">
                            <Database size={16} />
                            記憶（確定）
                        </div>
                    </button>
                    <button
                        onClick={() => setActiveTab('long_term')}
                        className={`flex-1 rounded-xl px-4 py-2 text-sm font-medium transition-all ${activeTab === 'long_term'
                            ? 'bg-sky-500/10 text-sky-100 border border-sky-400/30'
                            : 'text-slate-400 hover:text-slate-200'
                            }`}
                    >
                        <div className="flex items-center justify-center gap-2">
                            <Database size={16} />
                            長期記憶
                        </div>
                    </button>
                </div>
            </div>

            {/* Content: Pending List */}
            {activeTab === 'pending' && (
                <div className="grid gap-4">
                    {pendingItems.length === 0 && (
                        <div className="text-slate-400 italic p-6 text-center border border-white/10 rounded-2xl bg-white/5">
                            承認待ちの記憶はありません。
                        </div>
                    )}
                    {pendingItems.map((item, index) => (
                        <div
                            key={item.id}
                            className="group relative overflow-hidden rounded-2xl border border-white/10 bg-[rgba(15,18,24,0.92)] p-5 transition-all duration-300 hover:border-amber-400/40 animate-rise"
                            style={{ animationDelay: `${index * 40}ms` }}
                        >
                            <div className="absolute left-0 top-0 h-full w-1 bg-gradient-to-b from-amber-300/80 via-amber-500/40 to-transparent" />

                            <div className="flex justify-between items-start mb-2">
                                <span className="text-xs text-cyan-200/80 font-mono">{item.timestamp ? new Date(item.timestamp).toLocaleString() : "--"}</span>
                                <div className="flex gap-2">
                                    <span className="text-xs font-mono bg-white/10 px-2 py-1 rounded text-slate-300">
                                        Retention: {Math.round((item.details?.retention ?? 0) * 100)}%
                                    </span>
                                    {item.details?.state_tag && (
                                        <span className="text-[10px] px-2 py-1 rounded-md font-medium uppercase tracking-[0.2em] bg-slate-700/40 text-slate-200 border border-white/10">
                                            {item.details.state_tag}
                                        </span>
                                    )}
                                <span className="text-[10px] px-2 py-1 rounded-md font-medium tracking-[0.2em] bg-amber-500/20 text-amber-200 border border-amber-400/30">
                                    {statusLabel(item.status)}
                                </span>
                                {item.reason && (
                                    <span className="text-[10px] px-2 py-1 rounded-md font-medium tracking-[0.2em] bg-rose-500/20 text-rose-200 border border-rose-400/30">
                                        理由: {item.reason}
                                    </span>
                                )}
                                    <button
                                        onClick={() => approvePending(item.id)}
                                        className="text-[10px] px-2 py-1 rounded-md font-medium uppercase tracking-[0.2em] bg-emerald-500/20 text-emerald-200 border border-emerald-400/30 hover:bg-emerald-500/30 transition"
                                    >
                                        了承
                                    </button>
                                    <button
                                        onClick={() => deletePending(item.id)}
                                        className="text-[10px] px-2 py-1 rounded-md font-medium uppercase tracking-[0.2em] bg-rose-500/20 text-rose-200 border border-rose-400/30 hover:bg-rose-500/30 transition"
                                    >
                                        削除
                                    </button>
                                </div>
                            </div>

                            <h3 className="font-semibold text-lg text-slate-100 mb-3">{item.summary}</h3>

                            {/* Metadata Toggle */}
                            <div className="mt-4 pt-4 border-t border-white/5">
                                <details className="group">
                                    <summary className="text-xs text-slate-500 cursor-pointer list-none flex items-center gap-2 hover:text-slate-300">
                                        <Brain size={12} /> 詳細データ (JSON)
                                    </summary>
                                    <pre className="mt-2 text-[10px] text-slate-400 font-mono p-3 bg-black/40 rounded-lg overflow-x-auto">
                                        {JSON.stringify(item.details, null, 2)}
                                    </pre>
                                </details>
                            </div>
                        </div>
                    ))}
                </div>
            )}

            {/* Content: Approved List */}
            {activeTab === 'approved' && (
                <div className="grid gap-4">
                    {memories.length === 0 && (
                        <div className="text-slate-400 italic">まだ記憶が記録されていません。</div>
                    )}
                    {memories.map((m, index) => (
                        <div
                            key={m.id}
                            className="relative overflow-hidden rounded-2xl border border-white/10 bg-[rgba(16,20,26,0.92)] p-5 transition-all duration-300 hover:border-emerald-400/30 animate-rise"
                            style={{ animationDelay: `${index * 40}ms` }}
                        >
                            <div className="flex justify-between items-center mb-3">
                                <span className="text-xs text-cyan-200/80 font-mono tracking-wider">
                                    {m.timestamp ? new Date(m.timestamp).toLocaleString() : "--"}
                                </span>
                                <div className="flex items-center gap-2">
                                    {m.details?.stage && (
                                        <span className="text-[10px] px-2 py-1 rounded-md font-medium tracking-[0.2em] bg-emerald-500/20 text-emerald-200 border border-emerald-400/30">
                                            {stageLabel(m.details.stage)}
                                        </span>
                                    )}
                                    {m.details?.state_tag && (
                                        <span className="text-[10px] px-2 py-1 rounded-md font-medium uppercase tracking-[0.2em] bg-slate-600/40 text-slate-300 border border-white/10">
                                            {m.details.state_tag}
                                        </span>
                                    )}
                                    <button
                                        onClick={() => deleteApproved(String(m.id))}
                                        className="text-[10px] px-2 py-1 rounded-md font-medium uppercase tracking-[0.2em] bg-rose-500/20 text-rose-200 border border-rose-400/30 hover:bg-rose-500/30 transition"
                                    >
                                        削除
                                    </button>
                                </div>
                            </div>
                            <h3 className="font-semibold text-lg text-slate-100 mb-2 leading-tight">{m.summary}</h3>
                            <p className="text-sm text-slate-300/80 whitespace-pre-wrap leading-relaxed">
                                {m.details?.raw_text || "(詳細なし)"}
                            </p>

                            {m.details && Object.keys(m.details).length > 0 && (
                                <div className="mt-4 pt-4 border-t border-white/5">
                                    <details className="group">
                                        <summary className="text-xs text-slate-500 cursor-pointer list-none flex items-center gap-2 group-hover:text-slate-300 transition-colors">
                                            <span className="w-1.5 h-1.5 rounded-full bg-slate-600 group-hover:bg-emerald-300 transition-colors"></span>
                                            詳細データ
                                        </summary>
                                        <pre className="mt-2 text-[10px] text-slate-400 font-mono p-3 bg-black/40 rounded-lg overflow-x-auto">
                                            {JSON.stringify(m.details, null, 2)}
                                        </pre>
                                    </details>
                                </div>
                            )}
                        </div>
                    ))}
                </div>
            )}

            {activeTab === 'long_term' && (
                <div className="grid gap-4">
                    {longTermMemories.length === 0 && (
                        <div className="text-slate-400 italic">まだ長期記憶が記録されていません。</div>
                    )}
                    {longTermMemories.map((m, index) => (
                        <div
                            key={m.id}
                            className="relative overflow-hidden rounded-2xl border border-white/10 bg-[rgba(16,20,26,0.92)] p-5 transition-all duration-300 hover:border-sky-400/30 animate-rise"
                            style={{ animationDelay: `${index * 40}ms` }}
                        >
                            <div className="flex justify-between items-center mb-3">
                                <span className="text-xs text-cyan-200/80 font-mono tracking-wider">
                                    {m.created_at ? new Date(m.created_at).toLocaleString() : "--"}
                                </span>
                                <div className="flex items-center gap-2">
                                    <span className="text-[10px] px-2 py-1 rounded-md font-medium tracking-[0.2em] bg-sky-500/20 text-sky-200 border border-sky-400/30">
                                        長期記憶
                                    </span>
                                    {m.metadata?.state_tag && (
                                        <span className="text-[10px] px-2 py-1 rounded-md font-medium uppercase tracking-[0.2em] bg-slate-600/40 text-slate-300 border border-white/10">
                                            {m.metadata.state_tag}
                                        </span>
                                    )}
                                    <button
                                        onClick={() => deleteLongTerm(String(m.id))}
                                        className="text-[10px] px-2 py-1 rounded-md font-medium uppercase tracking-[0.2em] bg-rose-500/20 text-rose-200 border border-rose-400/30 hover:bg-rose-500/30 transition"
                                    >
                                        削除
                                    </button>
                                </div>
                            </div>
                            <h3 className="font-semibold text-lg text-slate-100 mb-2 leading-tight">{m.summary}</h3>
                            <p className="text-sm text-slate-300/80 whitespace-pre-wrap leading-relaxed">{m.details || "(詳細なし)"}</p>

                            {m.metadata && Object.keys(m.metadata).length > 0 && (
                                <div className="mt-4 pt-4 border-t border-white/5">
                                    <details className="group">
                                        <summary className="text-xs text-slate-500 cursor-pointer list-none flex items-center gap-2 group-hover:text-slate-300 transition-colors">
                                            <span className="w-1.5 h-1.5 rounded-full bg-slate-600 group-hover:bg-sky-300 transition-colors"></span>
                                            METADATA
                                        </summary>
                                        <pre className="mt-2 text-[10px] text-slate-400 font-mono p-3 bg-black/40 rounded-lg overflow-x-auto">
                                            {JSON.stringify(m.metadata, null, 2)}
                                        </pre>
                                    </details>
                                </div>
                            )}
                        </div>
                    ))}
                </div>
            )}
        </div>
    );
}
