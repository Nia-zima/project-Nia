"use client";
import React, { useEffect, useMemo, useState } from 'react';
import { API_URL } from '@/lib/api';
import {
    MessageSquare,
    Brain,
    CheckCircle,
    XCircle,
    Clock,
    Database,
    TrendingUp,
    Loader2,
    Network,
    BarChart3,
    Calendar,
    HeartPulse
} from 'lucide-react';
import MemoryGraph from './MemoryGraph';
import MemoryTimeline from './MemoryTimeline';
import InnerMonologue from './InnerMonologue';
import ObservationReport from './ObservationReport';

interface Stats {
    total_events: number;
    today_chats: number;
    total_chats: number;
    memory_candidates: number;
    memory_pending: number;
    memory_approved: number;
    memory_rejected: number;
    memory_written: number;
    last_chat_time: string | null;
}

interface InternalState {
    vector_docs: number;
    last_sleep: string | null;
    mood: string;
}

export default function StatsPanel() {
    const [stats, setStats] = useState<Stats | null>(null);
    const [internalState, setInternalState] = useState<InternalState | null>(null);
    const [loading, setLoading] = useState(true);
    const [view, setView] = useState<'stats' | 'graph' | 'timeline' | 'monologue' | 'observation'>('stats');

    useEffect(() => {
        const fetchData = async () => {
            try {
                const [statsRes, stateRes] = await Promise.all([
                    fetch(`${API_URL}/stats/summary`),
                    fetch(`${API_URL}/stats/internal_state`)
                ]);

                if (statsRes.ok) setStats(await statsRes.json());
                if (stateRes.ok) setInternalState(await stateRes.json());
            } catch (e) {
                console.error('Failed to fetch stats:', e);
            }
            setLoading(false);
        };

        fetchData();
        const interval = setInterval(fetchData, 30000);
        return () => clearInterval(interval);
    }, []);

    const toneStyles = useMemo<Record<string, { icon: string; value: string; border: string; bg: string; glow: string; text: string }>>(() => ({
        cyan: {
            icon: 'text-cyan-200',
            value: 'text-cyan-100',
            border: 'border-cyan-400/30',
            bg: 'from-cyan-400/15 via-cyan-500/5 to-transparent',
            glow: 'shadow-[0_0_30px_rgba(34,211,238,0.12)]',
            text: 'text-cyan-100/80'
        },
        blue: {
            icon: 'text-sky-200',
            value: 'text-sky-100',
            border: 'border-sky-400/30',
            bg: 'from-sky-400/12 via-sky-500/5 to-transparent',
            glow: 'shadow-[0_0_30px_rgba(14,165,233,0.12)]',
            text: 'text-sky-100/80'
        },
        purple: {
            icon: 'text-violet-200',
            value: 'text-violet-100',
            border: 'border-violet-400/30',
            bg: 'from-violet-400/12 via-violet-500/5 to-transparent',
            glow: 'shadow-[0_0_30px_rgba(139,92,246,0.12)]',
            text: 'text-violet-100/80'
        },
        gray: {
            icon: 'text-slate-200',
            value: 'text-slate-100',
            border: 'border-slate-500/30',
            bg: 'from-slate-400/10 via-slate-500/5 to-transparent',
            glow: 'shadow-[0_0_30px_rgba(148,163,184,0.08)]',
            text: 'text-slate-100/70'
        },
        yellow: {
            icon: 'text-amber-200',
            value: 'text-amber-100',
            border: 'border-amber-400/30',
            bg: 'from-amber-400/15 via-amber-500/5 to-transparent',
            glow: 'shadow-[0_0_30px_rgba(251,191,36,0.12)]',
            text: 'text-amber-100/80'
        },
        orange: {
            icon: 'text-orange-200',
            value: 'text-orange-100',
            border: 'border-orange-400/30',
            bg: 'from-orange-400/15 via-orange-500/5 to-transparent',
            glow: 'shadow-[0_0_30px_rgba(249,115,22,0.12)]',
            text: 'text-orange-100/80'
        },
        green: {
            icon: 'text-emerald-200',
            value: 'text-emerald-100',
            border: 'border-emerald-400/30',
            bg: 'from-emerald-400/15 via-emerald-500/5 to-transparent',
            glow: 'shadow-[0_0_30px_rgba(16,185,129,0.12)]',
            text: 'text-emerald-100/80'
        },
        red: {
            icon: 'text-rose-200',
            value: 'text-rose-100',
            border: 'border-rose-400/30',
            bg: 'from-rose-400/15 via-rose-500/5 to-transparent',
            glow: 'shadow-[0_0_30px_rgba(244,63,94,0.12)]',
            text: 'text-rose-100/80'
        },
        pink: {
            icon: 'text-pink-200',
            value: 'text-pink-100',
            border: 'border-pink-400/30',
            bg: 'from-pink-400/15 via-pink-500/5 to-transparent',
            glow: 'shadow-[0_0_30px_rgba(236,72,153,0.12)]',
            text: 'text-pink-100/80'
        },
        indigo: {
            icon: 'text-indigo-200',
            value: 'text-indigo-100',
            border: 'border-indigo-400/30',
            bg: 'from-indigo-400/15 via-indigo-500/5 to-transparent',
            glow: 'shadow-[0_0_30px_rgba(99,102,241,0.12)]',
            text: 'text-indigo-100/80'
        }
    }), []);

    const StatCard = ({
        icon: Icon,
        label,
        value,
        tone = "blue",
        subtext,
        delay = 0
    }: {
        icon: React.ElementType;
        label: string;
        value: number | string;
        tone?: keyof typeof toneStyles;
        subtext?: string;
        delay?: number;
    }) => {
        const styles = toneStyles[tone] ?? toneStyles.blue;
        return (
            <div
                className={`relative overflow-hidden rounded-2xl border ${styles.border} bg-[rgba(15,18,24,0.92)] p-4 animate-rise`}
                style={{ animationDelay: `${delay}ms` }}
            >
                <div className={`flex items-center gap-2 text-xs uppercase tracking-[0.3em] ${styles.text}`}>
                    <Icon className={`w-4 h-4 ${styles.icon}`} />
                    <span>{label}</span>
                </div>
                <div className={`mt-3 text-2xl font-semibold ${styles.value}`}>{value}</div>
                {subtext && <div className="mt-2 text-xs text-slate-400">{subtext}</div>}
            </div>
        );
    };

    return (
        <div className="relative h-full flex flex-col overflow-hidden">
            {/* Tab Header */}
            <div className="flex items-center gap-2 p-4 border-b border-white/10 bg-black/40">
                <button
                    onClick={() => setView('stats')}
                    className={`flex items-center gap-2 px-4 py-2 rounded-xl border transition-all ${view === 'stats'
                        ? 'border-cyan-400/40 bg-cyan-500/10 text-cyan-100'
                        : 'border-transparent text-slate-400 hover:text-slate-100'
                        }`}
                >
                    <BarChart3 className="w-4 h-4" />
                    統計
                </button>
                <button
                    onClick={() => setView('graph')}
                    className={`flex items-center gap-2 px-4 py-2 rounded-xl border transition-all ${view === 'graph'
                        ? 'border-violet-400/40 bg-violet-500/10 text-violet-100'
                        : 'border-transparent text-slate-400 hover:text-slate-100'
                        }`}
                >
                    <Network className="w-4 h-4" />
                    記憶グラフ
                </button>
                <button
                    onClick={() => setView('timeline')}
                    className={`flex items-center gap-2 px-4 py-2 rounded-xl border transition-all ${view === 'timeline'
                        ? 'border-emerald-400/40 bg-emerald-500/10 text-emerald-100'
                        : 'border-transparent text-slate-400 hover:text-slate-100'
                        }`}
                >
                    <Calendar className="w-4 h-4" />
                    タイムライン
                </button>
                <button
                    onClick={() => setView('monologue')}
                    className={`flex items-center gap-2 px-4 py-2 rounded-xl border transition-all ${view === 'monologue'
                        ? 'border-indigo-400/40 bg-indigo-500/10 text-indigo-100'
                        : 'border-transparent text-slate-400 hover:text-slate-100'
                        }`}
                >
                    <Brain className="w-4 h-4" />
                    内部思考
                </button>
                <button
                    onClick={() => setView('observation')}
                    className={`flex items-center gap-2 px-4 py-2 rounded-xl border transition-all ${view === 'observation'
                        ? 'border-amber-400/40 bg-amber-500/10 text-amber-100'
                        : 'border-transparent text-slate-400 hover:text-slate-100'
                        }`}
                >
                    <TrendingUp className="w-4 h-4" />
                    観測
                </button>
            </div>

            {/* Content */}
            {view === 'stats' && (
                <div className="flex-1 p-6 overflow-y-auto">
                    {loading ? (
                        <div className="flex items-center justify-center h-full">
                            <Loader2 className="w-8 h-8 animate-spin text-blue-400" />
                        </div>
                    ) : (
                        <>
                            <div className="rounded-3xl border border-white/10 bg-[rgba(15,18,24,0.92)] p-6 animate-fade">
                                <p className="text-[11px] uppercase tracking-[0.4em] text-cyan-200/70">NIA Telemetry</p>
                                <h2 className="mt-2 text-3xl font-semibold text-white">統計ダッシュボード</h2>
                                <p className="mt-2 text-sm text-slate-300/80">
                                    会話・記憶・内部状態の変化をリアルタイムに追跡します。
                                </p>
                            </div>

                            {/* 会話統計 */}
                            <div className="mt-8 mb-8">
                                <h3 className="text-lg font-semibold text-slate-200 mb-4">💬 会話統計</h3>
                                <div className="grid grid-cols-2 md:grid-cols-4 gap-4">
                                    <StatCard icon={MessageSquare} label="今日の会話" value={stats?.today_chats ?? 0} tone="cyan" delay={0} />
                                    <StatCard icon={TrendingUp} label="総会話数" value={stats?.total_chats ?? 0} tone="blue" delay={40} />
                                    <StatCard icon={Clock} label="最後の会話" value={stats?.last_chat_time ? new Date(stats.last_chat_time).toLocaleTimeString('ja-JP', { hour: '2-digit', minute: '2-digit' }) : '--'} tone="purple" delay={80} />
                                    <StatCard icon={Database} label="総イベント" value={stats?.total_events ?? 0} tone="gray" delay={120} />
                                </div>
                            </div>

                            {/* 記憶統計 */}
                            <div className="mb-8">
                                <h3 className="text-lg font-semibold text-slate-200 mb-4">🧠 記憶システム</h3>
                                <div className="grid grid-cols-2 md:grid-cols-5 gap-4">
                                    <StatCard icon={Brain} label="候補" value={stats?.memory_candidates ?? 0} tone="yellow" delay={0} />
                                    <StatCard icon={Clock} label="保留中" value={stats?.memory_pending ?? 0} tone="orange" delay={40} />
                                    <StatCard icon={CheckCircle} label="承認済" value={stats?.memory_approved ?? 0} tone="green" delay={80} />
                                    <StatCard icon={XCircle} label="却下" value={stats?.memory_rejected ?? 0} tone="red" delay={120} />
                                    <StatCard icon={Database} label="記録済" value={stats?.memory_written ?? 0} tone="blue" delay={160} />
                                </div>
                            </div>

                            {/* 内部状態 */}
                            <div>
                                <h3 className="text-lg font-semibold text-slate-200 mb-4">🔮 内部状態</h3>
                                <div className="grid grid-cols-2 md:grid-cols-3 gap-4">
                                    <StatCard icon={Database} label="ベクトル記憶" value={`${internalState?.vector_docs ?? 0} docs`} tone="purple" delay={0} />
                                    <StatCard icon={HeartPulse} label="現在の気分" value={internalState?.mood || 'neutral'} tone="pink" delay={40} />
                                    <StatCard icon={Clock} label="最後の睡眠" value={internalState?.last_sleep ?? '--'} tone="indigo" delay={80} />
                                </div>
                            </div>

                            <div className="mt-8 text-center text-xs text-slate-500">
                                自動更新: 30秒ごと | 最終更新: {new Date().toLocaleTimeString('ja-JP')}
                            </div>
                        </>
                    )}
                </div>
            )}

            {view === 'graph' && (
                <div className="flex-1 min-h-0 overflow-hidden">
                    <MemoryGraph />
                </div>
            )}

            {view === 'timeline' && (
                <div className="flex-1 min-h-0 overflow-hidden">
                    <MemoryTimeline />
                </div>
            )}

            {view === 'monologue' && (
                <div className="flex-1 min-h-0 overflow-hidden">
                    <InnerMonologue />
                </div>
            )}

            {view === 'observation' && (
                <div className="flex-1 min-h-0 overflow-hidden">
                    <ObservationReport />
                </div>
            )}
        </div>
    );
}
