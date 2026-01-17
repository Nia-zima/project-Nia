"use client";
import React, { useEffect, useState } from 'react';
import { API_URL } from '@/lib/api';
import { Check, X, AlertCircle, Clock, Database, Brain } from 'lucide-react';

interface Memory {
    id: number;
    summary: string;
    details: string;
    category: string;
    created_at: string;
    metadata: any;
}

interface PendingMemory {
    id: number;
    timestamp: string;
    thread_id: string;
    summary: string;
    details: any;
    confidence: number;
}

export default function MemoryExplorer() {
    const [activeTab, setActiveTab] = useState<'approved' | 'pending'>('pending');

    // Approved State
    const [memories, setMemories] = useState<Memory[]>([]);

    // Pending State
    const [pendingItems, setPendingItems] = useState<PendingMemory[]>([]);
    const [reviewingId, setReviewingId] = useState<number | null>(null); // カード展開用
    const [reviewAction, setReviewAction] = useState<'APPROVE' | 'REJECT' | null>(null);
    const [confirmText, setConfirmText] = useState("");
    const [note, setNote] = useState("");

    const [loading, setLoading] = useState(false);
    const [actionLoading, setActionLoading] = useState(false);

    const fetchData = async () => {
        setLoading(true);

        // Fetch Approved
        if (activeTab === 'approved') {
            try {
                const res = await fetch(`${API_URL}/memories?limit=50`);
                if (res.ok) setMemories(await res.json());
            } catch (e) {
                console.error("Failed to fetch memories", e);
            }
        }

        // Fetch Pending (Separate try-catch)
        if (activeTab === 'pending') {
            try {
                // Remove trailing slash
                const res = await fetch(`${API_URL}/pending_memories?limit=50`);
                if (res.ok) {
                    setPendingItems(await res.json());
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
        setReviewingId(null); // タブ切り替えでリセット
    }, [activeTab]);

    const handleReviewSubmit = async (item: PendingMemory) => {
        if (!reviewAction) return;
        if (confirmText !== reviewAction) {
            alert(`確認のため、"${reviewAction}" と入力してください。`);
            return;
        }

        setActionLoading(true);
        try {
            const endpoint = reviewAction === 'APPROVE' ? '/pending_memories/approve' : '/pending_memories/reject';
            const body = {
                event_id: item.id,
                confirm: reviewAction,
                note: note,
                tags_override: reviewAction === 'APPROVE' ? ['manual_approval'] : undefined
            };

            const res = await fetch(`${API_URL}${endpoint}`, {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify(body)
            });

            if (res.ok) {
                // リストから削除
                setPendingItems(prev => prev.filter(p => p.id !== item.id));
                setReviewingId(null);
                setConfirmText("");
                setNote("");
            } else {
                alert("エラーが発生しました。");
            }
        } catch (e) {
            console.error(e);
            alert("通信エラー");
        } finally {
            setActionLoading(false);
        }
    };

    if (loading && memories.length === 0 && pendingItems.length === 0) {
        return <div className="p-8 text-gray-400 animate-pulse font-mono">データ取得中...</div>;
    }

    return (
        <div className="space-y-6 pb-20">
            {/* Header & Tabs */}
            <div className="flex flex-col gap-4">
                <div className="flex justify-between items-end">
                    <h2 className="text-3xl font-bold bg-gradient-to-r from-purple-400 to-blue-400 bg-clip-text text-transparent">
                        Memory System
                    </h2>
                </div>

                <div className="flex bg-white/5 p-1 rounded-xl w-full max-w-md">
                    <button
                        onClick={() => setActiveTab('pending')}
                        className={`flex-1 py-2 px-4 rounded-lg text-sm font-medium transition-all ${activeTab === 'pending' ? 'bg-blue-500 text-white shadow-lg' : 'text-gray-400 hover:text-white'
                            }`}
                    >
                        <div className="flex items-center justify-center gap-2">
                            <Clock size={16} />
                            保留中 (Pending)
                            {pendingItems.length > 0 && (
                                <span className="bg-red-500 text-white text-[10px] px-1.5 rounded-full">{pendingItems.length}</span>
                            )}
                        </div>
                    </button>
                    <button
                        onClick={() => setActiveTab('approved')}
                        className={`flex-1 py-2 px-4 rounded-lg text-sm font-medium transition-all ${activeTab === 'approved' ? 'bg-purple-600 text-white shadow-lg' : 'text-gray-400 hover:text-white'
                            }`}
                    >
                        <div className="flex items-center justify-center gap-2">
                            <Database size={16} />
                            確定記憶 (Approved)
                        </div>
                    </button>
                </div>
            </div>

            {/* Content: Pending List */}
            {activeTab === 'pending' && (
                <div className="grid gap-4">
                    {pendingItems.length === 0 && (
                        <div className="text-gray-500 italic p-4 text-center border border-white/5 rounded-2xl">
                            承認待ちの記憶はありません。
                        </div>
                    )}
                    {pendingItems.map((item) => (
                        <div key={item.id} className="group p-5 rounded-2xl bg-white/5 border border-white/5 hover:border-blue-500/30 transition-all duration-300 shadow-lg relative overflow-hidden">
                            <div className="absolute top-0 left-0 w-1 h-full bg-blue-500/30"></div>

                            <div className="flex justify-between items-start mb-2">
                                <span className="text-xs text-blue-400 font-mono">{new Date(item.timestamp).toLocaleString()}</span>
                                <div className="flex gap-2">
                                    <span className="text-xs font-mono bg-white/10 px-2 py-1 rounded text-gray-300">
                                        Confidence: {(item.confidence * 100).toFixed(0)}%
                                    </span>
                                </div>
                            </div>

                            <h3 className="font-bold text-lg text-gray-100 mb-3">{item.summary}</h3>

                            {/* Review UI */}
                            {reviewingId === item.id ? (
                                <div className="mt-4 p-4 bg-black/40 rounded-xl border border-white/10 animate-in fade-in slide-in-from-top-2">
                                    <div className="flex items-center gap-2 mb-3">
                                        {reviewAction === 'APPROVE' ? <Check className="text-green-400" size={18} /> : <X className="text-red-400" size={18} />}
                                        <span className={`font-bold ${reviewAction === 'APPROVE' ? 'text-green-400' : 'text-red-400'}`}>
                                            {reviewAction}MEMORY?
                                        </span>
                                    </div>

                                    <p className="text-xs text-gray-400 mb-2">
                                        確認のため <strong>{reviewAction}</strong> と入力してください。
                                    </p>
                                    <input
                                        type="text"
                                        value={confirmText}
                                        onChange={(e) => setConfirmText(e.target.value)}
                                        className="w-full bg-white/5 border border-white/10 rounded-lg p-2 text-sm text-white focus:outline-none focus:border-blue-500 mb-2"
                                        placeholder={reviewAction || ""}
                                    />

                                    <input
                                        type="text"
                                        value={note}
                                        onChange={(e) => setNote(e.target.value)}
                                        className="w-full bg-white/5 border border-white/10 rounded-lg p-2 text-sm text-white focus:outline-none focus:border-blue-500 mb-4"
                                        placeholder="メモ (任意)"
                                    />

                                    <div className="flex gap-2 mt-2">
                                        <button
                                            onClick={() => handleReviewSubmit(item)}
                                            disabled={actionLoading || confirmText !== reviewAction}
                                            className={`flex-1 py-2 rounded-lg font-bold text-sm transition-all
                                                ${confirmText === reviewAction
                                                    ? (reviewAction === 'APPROVE' ? 'bg-green-600 hover:bg-green-500' : 'bg-red-600 hover:bg-red-500')
                                                    : 'bg-gray-700 text-gray-500 cursor-not-allowed'}
                                            `}
                                        >
                                            {actionLoading ? '処理中...' : '確定 (Confirm)'}
                                        </button>
                                        <button
                                            onClick={() => setReviewingId(null)}
                                            className="px-4 py-2 rounded-lg text-sm bg-white/5 hover:bg-white/10 text-gray-300"
                                        >
                                            キャンセル
                                        </button>
                                    </div>
                                </div>
                            ) : (
                                <div className="flex gap-2 mt-4">
                                    <button
                                        onClick={() => { setReviewingId(item.id); setReviewAction('APPROVE'); setConfirmText(""); }}
                                        className="flex-1 bg-green-500/10 hover:bg-green-500/20 text-green-400 border border-green-500/30 py-2 rounded-lg text-sm font-medium transition-colors flex items-center justify-center gap-2"
                                    >
                                        <Check size={16} /> 承認 (Approve)
                                    </button>
                                    <button
                                        onClick={() => { setReviewingId(item.id); setReviewAction('REJECT'); setConfirmText(""); }}
                                        className="flex-1 bg-red-500/10 hover:bg-red-500/20 text-red-400 border border-red-500/30 py-2 rounded-lg text-sm font-medium transition-colors flex items-center justify-center gap-2"
                                    >
                                        <X size={16} /> 却下 (Reject)
                                    </button>
                                </div>
                            )}

                            {/* Metadata Toggle */}
                            <div className="mt-4 pt-4 border-t border-white/5">
                                <details className="group">
                                    <summary className="text-xs text-gray-600 cursor-pointer list-none flex items-center gap-2 hover:text-gray-400">
                                        <Brain size={12} /> 詳細データ (JSON)
                                    </summary>
                                    <pre className="mt-2 text-[10px] text-gray-500 font-mono p-3 bg-black/40 rounded-lg overflow-x-auto">
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
                        <div className="text-gray-500 italic">まだ記憶が記録されていません。</div>
                    )}
                    {memories.map((m) => (
                        <div key={m.id} className="p-5 rounded-2xl bg-white/5 border border-white/5 hover:border-purple-500/30 transition-all duration-300 shadow-lg">
                            <div className="flex justify-between items-center mb-3">
                                <span className="text-xs text-blue-400 font-mono tracking-wider">{new Date(m.created_at).toLocaleString()}</span>
                                <span className={`text-xs px-2 py-1 rounded-md font-medium uppercase tracking-widest
                                    ${m.category === 'episode' ? 'bg-purple-500/20 text-purple-300' : 'bg-gray-700/50 text-gray-400'}
                                `}>
                                    {m.category}
                                </span>
                            </div>
                            <h3 className="font-bold text-lg text-gray-100 mb-2 leading-tight">{m.summary}</h3>
                            <p className="text-sm text-gray-400 whitespace-pre-wrap leading-relaxed">{m.details || "(詳細なし)"}</p>

                            {m.metadata && Object.keys(m.metadata).length > 0 && (
                                <div className="mt-4 pt-4 border-t border-white/5">
                                    <details className="group">
                                        <summary className="text-xs text-gray-600 cursor-pointer list-none flex items-center gap-2 group-hover:text-gray-400 transition-colors">
                                            <span className="w-1.5 h-1.5 rounded-full bg-gray-600 group-hover:bg-blue-400 transition-colors"></span>
                                            METADATA
                                        </summary>
                                        <pre className="mt-2 text-[10px] text-gray-500 font-mono p-3 bg-black/40 rounded-lg overflow-x-auto">
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
