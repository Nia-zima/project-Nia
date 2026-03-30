"use client";
import React, { useState, useEffect, useCallback } from "react";
import { apiClient } from "@/lib/apiClient";
import { RefreshCw, AlertTriangle, ChevronLeft } from "lucide-react";

type TraceItem = {
    drawing_id: string;
    version: number;
    element_count: number;
    because_tags: string[];
    palette_used: string[];
    relations_used: string[];
    created_at: string;
};

type AttemptItem = {
    drawing_id: string;
    dsl_code: string;
    status: string;
    error_message: string;
    error_phase: string;
    thread_id: string | null;
    created_at: string;
};

type TraceDetail = {
    drawing_id: string;
    version: number;
    dsl_code: string;
    ast: Record<string, unknown>;
    scene_graph: Record<string, unknown>;
    resolved_layout: Record<string, [number, number]>;
    because_tags: string[];
    because_texts: string[];
    seeds_used: number[];
    palette_used: string[];
    relations_used: string[];
    element_count: number;
    svg_url: string | null;
    svg_missing?: boolean;
    internal_state_snapshot: Record<string, unknown> | null;
    created_at: string;
    updated_at: string;
    error?: string;
};

export default function DrawingViewer() {
    const [tab, setTab] = useState<"traces" | "attempts">("traces");
    const [traces, setTraces] = useState<TraceItem[]>([]);
    const [attempts, setAttempts] = useState<AttemptItem[]>([]);
    const [selected, setSelected] = useState<TraceDetail | null>(null);
    const [loading, setLoading] = useState(false);
    const [error, setError] = useState<string | null>(null);

    const refreshTraces = useCallback(async () => {
        setLoading(true);
        setError(null);
        try {
            const data = await apiClient.fetchDrawingTraces(50);
            setTraces((data.items || []) as TraceItem[]);
        } catch (e) {
            const msg = e instanceof Error ? e.message : String(e);
            setError(`Traces: ${msg}`);
            console.error("fetchDrawingTraces failed", e);
        }
        setLoading(false);
    }, []);

    const refreshAttempts = useCallback(async () => {
        setLoading(true);
        setError(null);
        try {
            const data = await apiClient.fetchDrawingAttempts(50);
            setAttempts((data.items || []) as AttemptItem[]);
        } catch (e) {
            const msg = e instanceof Error ? e.message : String(e);
            setError(`Attempts: ${msg}`);
            console.error("fetchDrawingAttempts failed", e);
        }
        setLoading(false);
    }, []);

    useEffect(() => {
        if (tab === "traces") refreshTraces();
        else refreshAttempts();
    }, [tab, refreshTraces, refreshAttempts]);

    const selectTrace = async (drawingId: string) => {
        setLoading(true);
        setError(null);
        try {
            const data = (await apiClient.fetchDrawingTrace(drawingId)) as TraceDetail;
            setSelected(data);
        } catch (e) {
            const msg = e instanceof Error ? e.message : String(e);
            setError(`Trace detail: ${msg}`);
            setSelected(null);
            console.error("fetchDrawingTrace failed", e);
        }
        setLoading(false);
    };

    // Detail view
    if (selected) {
        return (
            <div className="flex flex-col h-full overflow-hidden p-3 gap-3">
                <div className="flex items-center gap-2">
                    <button
                        onClick={() => setSelected(null)}
                        className="p-1.5 rounded-lg hover:bg-white/10 transition"
                    >
                        <ChevronLeft size={16} />
                    </button>
                    <span className="text-sm font-medium text-gray-200 truncate">
                        {selected.drawing_id}
                    </span>
                    <span className="text-xs text-gray-500">v{selected.version}</span>
                </div>

                <div className="flex-1 overflow-y-auto space-y-3 min-h-0">
                    {/* SVG Preview (via <img> to prevent stored XSS) */}
                    {selected.svg_missing && (
                        <div className="rounded-xl border border-yellow-500/20 bg-yellow-950/30 px-3 py-2 text-xs text-yellow-300">
                            SVG file missing (trace exists but static file was not saved)
                        </div>
                    )}
                    {selected.svg_url && (
                        <div className="rounded-xl border border-amber-500/20 bg-[#FAFAF7] p-2">
                            <div className="flex justify-center">
                                <img
                                    src={selected.svg_url}
                                    alt={`Drawing ${selected.drawing_id}`}
                                    className="max-w-full max-h-[300px]"
                                />
                            </div>
                        </div>
                    )}

                    {/* Metadata */}
                    <div className="grid grid-cols-2 gap-2 text-xs">
                        <div className="rounded-lg bg-white/5 p-2">
                            <div className="text-gray-500 mb-1">Elements</div>
                            <div className="text-gray-200">{selected.element_count}</div>
                        </div>
                        <div className="rounded-lg bg-white/5 p-2">
                            <div className="text-gray-500 mb-1">Created</div>
                            <div className="text-gray-200">{formatDate(selected.created_at)}</div>
                        </div>
                    </div>

                    {/* Because tags */}
                    {selected.because_tags.length > 0 && (
                        <div className="rounded-lg bg-white/5 p-2">
                            <div className="text-xs text-gray-500 mb-1">Because tags</div>
                            <div className="flex flex-wrap gap-1">
                                {selected.because_tags.map((t) => (
                                    <span key={t} className="text-xs px-1.5 py-0.5 rounded bg-amber-800/40 text-amber-300/80">
                                        {t}
                                    </span>
                                ))}
                            </div>
                        </div>
                    )}

                    {selected.because_texts.length > 0 && (
                        <div className="rounded-lg bg-white/5 p-2">
                            <div className="text-xs text-gray-500 mb-1">Because texts</div>
                            {selected.because_texts.map((t, i) => (
                                <div key={i} className="text-xs text-gray-300">{t}</div>
                            ))}
                        </div>
                    )}

                    {/* Palette & Relations */}
                    <div className="grid grid-cols-2 gap-2">
                        <div className="rounded-lg bg-white/5 p-2">
                            <div className="text-xs text-gray-500 mb-1">Palette</div>
                            <div className="flex flex-wrap gap-1">
                                {selected.palette_used.map((c) => (
                                    <span key={c} className="text-xs px-1 py-0.5 rounded bg-white/10 text-gray-300">{c}</span>
                                ))}
                            </div>
                        </div>
                        <div className="rounded-lg bg-white/5 p-2">
                            <div className="text-xs text-gray-500 mb-1">Relations</div>
                            <div className="flex flex-wrap gap-1">
                                {selected.relations_used.map((r) => (
                                    <span key={r} className="text-xs px-1 py-0.5 rounded bg-white/10 text-gray-300">{r}</span>
                                ))}
                            </div>
                        </div>
                    </div>

                    {/* DSL Code */}
                    <div className="rounded-lg bg-white/5 p-2">
                        <div className="text-xs text-gray-500 mb-1">DSL Code</div>
                        <pre className="text-xs text-gray-300 whitespace-pre-wrap font-mono bg-black/30 rounded p-2 max-h-48 overflow-y-auto">
                            {selected.dsl_code}
                        </pre>
                    </div>

                    {/* Scene Graph Nodes */}
                    <div className="rounded-lg bg-white/5 p-2">
                        <div className="text-xs text-gray-500 mb-1">Scene Graph</div>
                        <div className="space-y-1 max-h-48 overflow-y-auto">
                            {(
                                (selected.scene_graph as { nodes?: Array<Record<string, unknown>> })
                                    ?.nodes || []
                            ).map((node, i) => (
                                <div key={i} className="text-xs text-gray-400 font-mono flex gap-2">
                                    <span className="text-gray-200">{String(node.name)}</span>
                                    <span>{String(node.type)}</span>
                                    <span>({String(node.x)}, {String(node.y)})</span>
                                    <span className="text-amber-400/60">{String(node.color)}</span>
                                    {Array.isArray(node.because_tags) && (node.because_tags as string[]).length > 0 && (
                                        <span className="text-amber-300/50">
                                            [{(node.because_tags as string[]).join(",")}]
                                        </span>
                                    )}
                                </div>
                            ))}
                        </div>
                    </div>

                    {/* Resolved Layout */}
                    <div className="rounded-lg bg-white/5 p-2">
                        <div className="text-xs text-gray-500 mb-1">Resolved Layout</div>
                        <div className="text-xs text-gray-400 font-mono space-y-0.5 max-h-32 overflow-y-auto">
                            {Object.entries(selected.resolved_layout).map(([name, pos]) => (
                                <div key={name}>
                                    {name}: ({pos[0]}, {pos[1]})
                                </div>
                            ))}
                        </div>
                    </div>

                    {/* Seeds */}
                    {selected.seeds_used.length > 0 && (
                        <div className="rounded-lg bg-white/5 p-2">
                            <div className="text-xs text-gray-500 mb-1">Seeds</div>
                            <div className="text-xs text-gray-300">{selected.seeds_used.join(", ")}</div>
                        </div>
                    )}
                </div>
            </div>
        );
    }

    // List view
    return (
        <div className="flex flex-col h-full overflow-hidden p-3 gap-3">
            {/* Header */}
            <div className="flex items-center justify-between">
                <div className="flex gap-1">
                    <button
                        onClick={() => setTab("traces")}
                        className={`px-3 py-1 text-xs rounded-lg transition ${
                            tab === "traces" ? "bg-amber-700/40 text-amber-200" : "text-gray-400 hover:bg-white/5"
                        }`}
                    >
                        Traces ({traces.length})
                    </button>
                    <button
                        onClick={() => setTab("attempts")}
                        className={`px-3 py-1 text-xs rounded-lg transition ${
                            tab === "attempts" ? "bg-red-700/40 text-red-200" : "text-gray-400 hover:bg-white/5"
                        }`}
                    >
                        Attempts ({attempts.length})
                    </button>
                </div>
                <button
                    onClick={tab === "traces" ? refreshTraces : refreshAttempts}
                    className="p-1.5 rounded-lg hover:bg-white/10 transition"
                    disabled={loading}
                >
                    <RefreshCw size={14} className={loading ? "animate-spin" : ""} />
                </button>
            </div>

            {/* Error */}
            {error && (
                <div className="rounded-lg bg-red-950/40 border border-red-500/30 px-3 py-2 text-xs text-red-300">
                    {error}
                </div>
            )}

            {/* List */}
            <div className="flex-1 overflow-y-auto min-h-0 space-y-1">
                {tab === "traces" && traces.map((t) => (
                    <button
                        key={`${t.drawing_id}:${t.version}`}
                        onClick={() => selectTrace(t.drawing_id)}
                        className="w-full text-left rounded-lg bg-white/5 hover:bg-white/10 p-2 transition"
                    >
                        <div className="flex items-center justify-between">
                            <span className="text-xs text-gray-200 truncate max-w-[70%]">
                                {t.drawing_id}
                            </span>
                            <span className="text-xs text-gray-500">
                                {t.element_count} el
                            </span>
                        </div>
                        <div className="flex items-center gap-1 mt-1">
                            {t.because_tags.slice(0, 3).map((tag) => (
                                <span key={tag} className="text-[10px] px-1 py-0.5 rounded bg-amber-800/30 text-amber-300/70">
                                    {tag}
                                </span>
                            ))}
                            <span className="text-[10px] text-gray-600 ml-auto">
                                {formatDate(t.created_at)}
                            </span>
                        </div>
                    </button>
                ))}

                {tab === "attempts" && attempts.map((a, i) => (
                    <div
                        key={`${a.drawing_id}:${i}`}
                        className="rounded-lg bg-red-950/30 border border-red-500/20 p-2"
                    >
                        <div className="flex items-center gap-2">
                            <AlertTriangle size={12} className="text-red-400" />
                            <span className="text-xs text-red-300">{a.error_phase}</span>
                            <span className="text-[10px] text-gray-500 ml-auto">
                                {formatDate(a.created_at)}
                            </span>
                        </div>
                        <div className="text-xs text-red-200/70 mt-1 truncate">
                            {a.error_message}
                        </div>
                        <div className="text-[10px] text-gray-500 mt-1 truncate">
                            {a.drawing_id}
                        </div>
                    </div>
                ))}

                {tab === "traces" && traces.length === 0 && !loading && (
                    <div className="text-center text-xs text-gray-500 py-8">
                        まだ描画 trace がありません
                    </div>
                )}

                {tab === "attempts" && attempts.length === 0 && !loading && (
                    <div className="text-center text-xs text-gray-500 py-8">
                        失敗記録はありません
                    </div>
                )}
            </div>
        </div>
    );
}

function formatDate(iso: string): string {
    try {
        return new Date(iso).toLocaleString("ja-JP", {
            month: "numeric",
            day: "numeric",
            hour: "2-digit",
            minute: "2-digit",
        });
    } catch {
        return iso;
    }
}
