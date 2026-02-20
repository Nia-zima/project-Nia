"use client";

import React, { useState } from 'react';
import useSWR from 'swr';
import { API_URL } from '@/lib/apiClient';
import { motion } from 'framer-motion';
import {
    AlertTriangle,
    CheckCircle2,
    Info,
    Loader2,
    ArrowDownRight,
} from 'lucide-react';

const fetcher = (url: string) => fetch(url).then(res => res.json());

/* ---------- types ---------- */
interface HistogramBin { range: string; count: number; pct: number }
interface ScoreSummary { mean: number; median: number; p90: number; max: number; histogram: HistogramBin[] }
interface DepthRow { depth: number; count: number; pct: number }
interface MergeRow { mode: string; count: number; pct: number }
interface Recommendation { level: "info" | "action" | "ok"; message: string }

interface ReportData {
    total_turns: number;
    period: { start: string; end: string } | null;
    depth_distribution: DepthRow[];
    dissonance: ScoreSummary;
    surprise: ScoreSummary;
    correlation: { r: number; status: "ok" | "warning" };
    external_pipeline: {
        gate_pass_count: number; gate_pass_pct: number;
        external_used_count: number; external_used_pct: number;
        fetch_rate: number | null;
        integration_rate: number | null;
        contradiction_count: number; contradiction_rate: number | null;
    };
    external_confidence: ScoreSummary;
    hold: { count: number; pct: number };
    merge_modes: MergeRow[];
    recommendations: Recommendation[];
}

/* ---------- small components ---------- */

function MiniBar({ value, max, color = "bg-cyan-500" }: { value: number; max: number; color?: string }) {
    const pct = max > 0 ? Math.min(100, (value / max) * 100) : 0;
    return (
        <div className="h-2 bg-gray-800 rounded-full overflow-hidden">
            <motion.div
                className={`h-full rounded-full ${color}`}
                initial={{ width: 0 }}
                animate={{ width: `${pct}%` }}
                transition={{ duration: 0.4 }}
            />
        </div>
    );
}

function ScoreCard({ title, data, color }: { title: string; data: ScoreSummary; color: string }) {
    const maxCount = Math.max(...data.histogram.map(b => b.count), 1);
    return (
        <div className="bg-gray-800/40 rounded-xl border border-gray-700/40 p-4">
            <h4 className="text-sm font-medium text-gray-300 mb-3">{title}</h4>
            <div className="grid grid-cols-4 gap-2 text-center mb-3">
                {([["Mean", data.mean], ["Median", data.median], ["P90", data.p90], ["Max", data.max]] as const).map(([label, v]) => (
                    <div key={label}>
                        <div className="text-[10px] text-gray-500 uppercase">{label}</div>
                        <div className="text-sm font-mono text-gray-200">{v.toFixed(3)}</div>
                    </div>
                ))}
            </div>
            {data.histogram.length > 0 && (
                <div className="space-y-1">
                    {data.histogram.map(bin => (
                        <div key={bin.range} className="flex items-center gap-2 text-[10px]">
                            <span className="w-20 text-gray-500 font-mono shrink-0">{bin.range}</span>
                            <div className="flex-1"><MiniBar value={bin.count} max={maxCount} color={color} /></div>
                            <span className="w-8 text-right text-gray-400 font-mono">{bin.count}</span>
                        </div>
                    ))}
                </div>
            )}
        </div>
    );
}

function FunnelStep({ label, count, pct, total, color, isLast = false }: {
    label: string; count: number; pct: number; total: number; color: string; isLast?: boolean;
}) {
    return (
        <div className="flex items-center gap-3">
            <div className="flex-1">
                <div className="flex justify-between text-xs mb-1">
                    <span className="text-gray-400">{label}</span>
                    <span className="text-gray-300 font-mono">{count} ({pct.toFixed(1)}%)</span>
                </div>
                <MiniBar value={count} max={total} color={color} />
            </div>
            {!isLast && <ArrowDownRight className="w-4 h-4 text-gray-600 shrink-0" />}
        </div>
    );
}

function RecommendationBadge({ rec }: { rec: Recommendation }) {
    const styles = {
        ok: { icon: CheckCircle2, border: "border-emerald-500/30", bg: "bg-emerald-500/10", text: "text-emerald-300" },
        info: { icon: Info, border: "border-sky-500/30", bg: "bg-sky-500/10", text: "text-sky-300" },
        action: { icon: AlertTriangle, border: "border-amber-500/30", bg: "bg-amber-500/10", text: "text-amber-300" },
    }[rec.level];
    const Icon = styles.icon;
    return (
        <div className={`flex items-start gap-2 p-3 rounded-lg border ${styles.border} ${styles.bg}`}>
            <Icon className={`w-4 h-4 mt-0.5 shrink-0 ${styles.text}`} />
            <span className={`text-sm ${styles.text}`}>{rec.message}</span>
        </div>
    );
}

/* ---------- main component ---------- */

export default function ObservationReport() {
    const [lastN, setLastN] = useState<string>("all");

    const params = lastN !== "all" ? `?last=${lastN}` : "";
    const { data, error, isLoading } = useSWR<ReportData>(
        `${API_URL}/stats/observation_report${params}`,
        fetcher,
        { refreshInterval: 30000 }
    );

    if (isLoading) {
        return (
            <div className="flex items-center justify-center h-full">
                <Loader2 className="w-8 h-8 animate-spin text-cyan-400" />
            </div>
        );
    }

    if (error) {
        return (
            <div className="flex items-center justify-center h-full text-red-400 text-sm">
                Failed to load observation report
            </div>
        );
    }

    if (!data || data.total_turns === 0) {
        return (
            <div className="flex flex-col items-center justify-center h-full gap-3 text-gray-400">
                <Info className="w-8 h-8" />
                <p className="text-sm">観測データがまだありません</p>
                <p className="text-xs text-gray-500">会話を行うとターンごとに観測ログが蓄積されます</p>
            </div>
        );
    }

    const ep = data.external_pipeline;

    return (
        <div className="flex-1 p-6 overflow-y-auto space-y-6">
            {/* Header & filter */}
            <div className="flex items-center justify-between">
                <div>
                    <h2 className="text-lg font-semibold text-white">観測レポート</h2>
                    {data.period && (
                        <p className="text-xs text-gray-500 mt-1">
                            {data.period.start.slice(0, 16)} ~ {data.period.end.slice(0, 16)} / {data.total_turns} turns
                        </p>
                    )}
                </div>
                <select
                    value={lastN}
                    onChange={e => setLastN(e.target.value)}
                    className="bg-gray-800 border border-gray-700 rounded-lg px-3 py-1.5 text-sm text-gray-300 focus:outline-none focus:ring-1 focus:ring-cyan-500"
                >
                    <option value="all">全件</option>
                    <option value="100">直近 100</option>
                    <option value="50">直近 50</option>
                </select>
            </div>

            {/* Recommendations */}
            {data.recommendations.length > 0 && (
                <div className="space-y-2">
                    {data.recommendations.map((rec, i) => (
                        <RecommendationBadge key={i} rec={rec} />
                    ))}
                </div>
            )}

            {/* Depth distribution */}
            <div className="bg-gray-800/40 rounded-xl border border-gray-700/40 p-4">
                <h4 className="text-sm font-medium text-gray-300 mb-3">Depth 分布</h4>
                <div className="space-y-2">
                    {data.depth_distribution.map(row => (
                        <div key={row.depth} className="flex items-center gap-3">
                            <span className="w-16 text-xs text-gray-500 font-mono shrink-0">Depth {row.depth}</span>
                            <div className="flex-1"><MiniBar value={row.count} max={data.total_turns} color={row.depth === 0 ? "bg-cyan-500" : row.depth === 1 ? "bg-violet-500" : "bg-amber-500"} /></div>
                            <span className="w-20 text-right text-xs text-gray-400 font-mono">{row.count} ({row.pct}%)</span>
                        </div>
                    ))}
                </div>
            </div>

            {/* Score distributions */}
            <div className="grid grid-cols-1 md:grid-cols-2 gap-4">
                <ScoreCard title="Dissonance" data={data.dissonance} color="bg-rose-500" />
                <ScoreCard title="Surprise" data={data.surprise} color="bg-amber-500" />
            </div>

            {/* Correlation */}
            <div className="bg-gray-800/40 rounded-xl border border-gray-700/40 p-4 flex items-center justify-between">
                <div>
                    <h4 className="text-sm font-medium text-gray-300">Surprise-Dissonance 相関</h4>
                    <p className="text-xs text-gray-500 mt-1">r &lt; 0.5 で十分に分離されている</p>
                </div>
                <div className="flex items-center gap-2">
                    <span className={`text-2xl font-mono font-bold ${data.correlation.status === "ok" ? "text-emerald-400" : "text-amber-400"}`}>
                        {data.correlation.r >= 0 ? "+" : ""}{data.correlation.r.toFixed(3)}
                    </span>
                    {data.correlation.status === "ok"
                        ? <CheckCircle2 className="w-5 h-5 text-emerald-400" />
                        : <AlertTriangle className="w-5 h-5 text-amber-400" />
                    }
                </div>
            </div>

            {/* External pipeline funnel */}
            <div className="bg-gray-800/40 rounded-xl border border-gray-700/40 p-4">
                <h4 className="text-sm font-medium text-gray-300 mb-4">外部データパイプライン</h4>
                <div className="space-y-3">
                    <FunnelStep label="Total" count={data.total_turns} pct={100} total={data.total_turns} color="bg-gray-500" />
                    <FunnelStep label="Gate Pass" count={ep.gate_pass_count} pct={ep.gate_pass_pct} total={data.total_turns} color="bg-sky-500" />
                    <FunnelStep label="External Used" count={ep.external_used_count} pct={ep.external_used_pct} total={data.total_turns} color="bg-cyan-500" />
                    <FunnelStep label="Integrated (no contradiction)" count={ep.external_used_count - ep.contradiction_count} pct={ep.integration_rate ?? 0} total={data.total_turns} color="bg-emerald-500" isLast />
                </div>
                <div className="mt-4 grid grid-cols-3 gap-3 text-center">
                    <div>
                        <div className="text-[10px] text-gray-500 uppercase">Fetch Rate</div>
                        <div className="text-sm font-mono text-gray-200">{ep.fetch_rate != null ? `${ep.fetch_rate}%` : "N/A"}</div>
                    </div>
                    <div>
                        <div className="text-[10px] text-gray-500 uppercase">Integration Rate</div>
                        <div className="text-sm font-mono text-gray-200">{ep.integration_rate != null ? `${ep.integration_rate}%` : "N/A"}</div>
                    </div>
                    <div>
                        <div className="text-[10px] text-gray-500 uppercase">Contradiction</div>
                        <div className={`text-sm font-mono ${ep.contradiction_rate != null && ep.contradiction_rate > 15 ? "text-amber-400" : "text-gray-200"}`}>
                            {ep.contradiction_rate != null ? `${ep.contradiction_rate}%` : "N/A"}
                        </div>
                    </div>
                </div>
            </div>

            {/* External confidence */}
            {data.external_confidence.histogram.length > 0 && (
                <ScoreCard title="External Confidence (外部使用時)" data={data.external_confidence} color="bg-cyan-500" />
            )}

            {/* Hold & Merge modes */}
            <div className="grid grid-cols-1 md:grid-cols-2 gap-4">
                <div className="bg-gray-800/40 rounded-xl border border-gray-700/40 p-4">
                    <h4 className="text-sm font-medium text-gray-300 mb-2">Hold / Review</h4>
                    <div className="text-2xl font-mono font-bold text-white">{data.hold.count}</div>
                    <div className="text-xs text-gray-500">{data.hold.pct}% of total turns</div>
                </div>
                <div className="bg-gray-800/40 rounded-xl border border-gray-700/40 p-4">
                    <h4 className="text-sm font-medium text-gray-300 mb-2">Merge Mode</h4>
                    <div className="space-y-1">
                        {data.merge_modes.slice(0, 5).map(row => (
                            <div key={row.mode} className="flex justify-between text-xs">
                                <span className="text-gray-400 font-mono">{row.mode}</span>
                                <span className="text-gray-300">{row.count} ({row.pct}%)</span>
                            </div>
                        ))}
                    </div>
                </div>
            </div>

            <div className="text-center text-xs text-gray-600 pb-4">
                自動更新: 30秒ごと
            </div>
        </div>
    );
}
