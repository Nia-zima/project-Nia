"use client";

import React from 'react';
import useSWR from 'swr';
import { API_URL } from '@/lib/apiClient';
import { Activity, Radio, Database, ShieldAlert, ShieldCheck, Compass } from 'lucide-react';
import { motion } from 'framer-motion';

const fetcher = (url: string) => fetch(url).then(res => res.json());

interface ScalarBarProps {
    label: string;
    value: number;
    color?: string;
}

function ScalarBar({ label, value, color = "bg-blue-500" }: ScalarBarProps) {
    return (
        <div className="mb-3">
            <div className="flex justify-between text-xs mb-1">
                <span className="text-gray-400">{label}</span>
                <span className="text-gray-300 font-mono">{(value * 100).toFixed(0)}%</span>
            </div>
            <div className="h-2 bg-gray-800 rounded-full overflow-hidden">
                <motion.div
                    className={`h-full ${color}`}
                    initial={{ width: 0 }}
                    animate={{ width: `${Math.min(100, Math.max(0, value * 100))}%` }}
                    transition={{ duration: 0.5 }}
                />
            </div>
        </div>
    );
}

interface StatBoxProps {
    label: string;
    value: string | number;
    icon?: React.ReactNode;
}

function StatBox({ label, value, icon }: StatBoxProps) {
    return (
        <div className="bg-gray-800/50 p-3 rounded-lg border border-gray-700/50">
            <div className="flex items-center gap-2 text-xs text-gray-400 mb-1">
                {icon}
                <span>{label}</span>
            </div>
            <div className="text-xl font-bold font-mono text-white">
                {value}
            </div>
        </div>
    );
}

interface LivestreamDashboardProps {
    threadId?: string;
}

export default function LivestreamDashboard({ threadId = "default_thread" }: LivestreamDashboardProps) {
    const { data, error } = useSWR(
        `${API_URL}/diagnostics?thread_id=${encodeURIComponent(threadId)}`,
        fetcher,
        {
            refreshInterval: 10_000,
            fallbackData: {
                scalars: { steering_risk: 0, info_sufficiency: 0, question_clarity: 0 },
                queue: { pending: 0, processed_last_minute: 0, rejected_last_minute: 0 },
                depth: { current: 1 },
                external: { used: false, confidence: 0, contradiction_flag: false, reason: null, surprise_score: 0 }
            }
        });

    if (error) return <div className="text-red-500 text-xs">Connection Error</div>;
    if (!data) return <div className="text-gray-500 text-xs">Loading...</div>;

    const scalars = data.scalars || {};
    const queue = data.queue || {};
    const external = data.external || {};
    const externalUsed = Boolean(external.used);
    const contradiction = Boolean(external.contradiction_flag);
    const externalConfidence = Number(external.confidence || 0);
    const surpriseScore = Number(external.surprise_score || 0);

    return (
        <div className="flex flex-col gap-4 p-4 bg-gray-900/90 border border-gray-700 rounded-xl backdrop-blur-sm shadow-xl w-full max-w-sm">
            {/* Header */}
            <div className="flex items-center justify-between border-b border-gray-800 pb-3">
                <div className="flex items-center gap-2 text-green-400 font-bold">
                    <Radio className="w-4 h-4 animate-pulse" />
                    <span>LIVE Diagnostics</span>
                </div>
                <div className="text-xs text-gray-500 font-mono">
                    Depth: {data.depth?.current ?? '-'}
                </div>
            </div>

            {/* 3 Scalars */}
            <div className="space-y-1">
                <ScalarBar
                    label="Steering Risk (誘導リスク)"
                    value={scalars.steering_risk}
                    color="bg-red-500"
                />
                <ScalarBar
                    label="Info Sufficiency (情報充足)"
                    value={scalars.info_sufficiency}
                    color="bg-green-500"
                />
                <ScalarBar
                    label="Question Clarity (質問明確性)"
                    value={scalars.question_clarity}
                    color="bg-blue-500"
                />
                <ScalarBar
                    label="Surprise Score (不確実性)"
                    value={surpriseScore}
                    color="bg-amber-500"
                />
                <ScalarBar
                    label="External Confidence (外部信頼度)"
                    value={externalConfidence}
                    color={contradiction ? "bg-red-500" : "bg-cyan-500"}
                />
            </div>

            {/* Queue Stats */}
            <div className="grid grid-cols-2 gap-3">
                <StatBox
                    label="Pending Queue"
                    value={queue.pending}
                    icon={<Database className="w-3 h-3" />}
                />
                <StatBox
                    label="Processed / min"
                    value={queue.processed_last_minute}
                    icon={<Activity className="w-3 h-3" />}
                />
                <StatBox
                    label="External Used"
                    value={externalUsed ? "YES" : "NO"}
                    icon={externalUsed ? <ShieldCheck className="w-3 h-3" /> : <ShieldAlert className="w-3 h-3" />}
                />
                <StatBox
                    label="Contradiction"
                    value={contradiction ? "FLAGGED" : "CLEAR"}
                    icon={<Compass className="w-3 h-3" />}
                />
            </div>

            {external.reason && (
                <div className="text-[11px] text-gray-300 bg-gray-800/40 border border-gray-700/60 rounded-md px-3 py-2">
                    <div className="text-gray-500 mb-1">External Reason</div>
                    <div className="line-clamp-2">{String(external.reason)}</div>
                </div>
            )}

            {/* Connection Status Mock (Optional) */}
            <div className="pt-2 border-t border-gray-800 flex justify-between text-[10px] text-gray-500">
                <span>Backend: Connected</span>
                <span>Latency: ~15ms</span>
            </div>
        </div>
    );
}
