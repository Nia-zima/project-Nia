"use client";
import React, { useEffect, useState } from 'react';
import { apiClient } from '@/lib/apiClient';
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

const TONE_STYLES: Record<string, { icon: string; value: string; border: string; bg: string; glow: string; text: string }> = {
    cyan: {
        icon: 'text-cyan-200', value: 'text-cyan-100', border: 'border-cyan-400/30',
        bg: 'from-cyan-400/15 via-cyan-500/5 to-transparent', glow: 'shadow-[0_0_30px_rgba(34,211,238,0.12)]', text: 'text-cyan-100/80'
    },
    blue: {
        icon: 'text-blue-200', value: 'text-blue-100', border: 'border-blue-400/30',
        bg: 'from-blue-400/15 via-blue-500/5 to-transparent', glow: 'shadow-[0_0_30px_rgba(59,130,246,0.12)]', text: 'text-blue-100/80'
    },
    purple: {
        icon: 'text-violet-200', value: 'text-violet-100', border: 'border-violet-400/30',
        bg: 'from-violet-400/15 via-violet-500/5 to-transparent', glow: 'shadow-[0_0_30px_rgba(139,92,246,0.12)]', text: 'text-violet-100/80'
    },
    gray: {
        icon: 'text-slate-200', value: 'text-slate-100', border: 'border-slate-500/30',
        bg: 'from-slate-400/10 via-slate-500/5 to-transparent', glow: 'shadow-[0_0_30px_rgba(148,163,184,0.08)]', text: 'text-slate-100/70'
    },
    yellow: {
        icon: 'text-amber-200', value: 'text-amber-100', border: 'border-amber-400/30',
        bg: 'from-amber-400/15 via-amber-500/5 to-transparent', glow: 'shadow-[0_0_30px_rgba(251,191,36,0.12)]', text: 'text-amber-100/80'
    },
    orange: {
        icon: 'text-orange-200', value: 'text-orange-100', border: 'border-orange-400/30',
        bg: 'from-orange-400/15 via-orange-500/5 to-transparent', glow: 'shadow-[0_0_30px_rgba(249,115,22,0.12)]', text: 'text-orange-100/80'
    },
    green: {
        icon: 'text-emerald-200', value: 'text-emerald-100', border: 'border-emerald-400/30',
        bg: 'from-emerald-400/15 via-emerald-500/5 to-transparent', glow: 'shadow-[0_0_30px_rgba(16,185,129,0.12)]', text: 'text-emerald-100/80'
    },
    red: {
        icon: 'text-rose-200', value: 'text-rose-100', border: 'border-rose-400/30',
        bg: 'from-rose-400/15 via-rose-500/5 to-transparent', glow: 'shadow-[0_0_30px_rgba(244,63,94,0.12)]', text: 'text-rose-100/80'
    },
    pink: {
        icon: 'text-pink-200', value: 'text-pink-100', border: 'border-pink-400/30',
        bg: 'from-pink-400/15 via-pink-500/5 to-transparent', glow: 'shadow-[0_0_30px_rgba(236,72,153,0.12)]', text: 'text-pink-100/80'
    },
    indigo: {
        icon: 'text-indigo-200', value: 'text-indigo-100', border: 'border-indigo-400/30',
        bg: 'from-indigo-400/15 via-indigo-500/5 to-transparent', glow: 'shadow-[0_0_30px_rgba(99,102,241,0.12)]', text: 'text-indigo-100/80'
    },
};

function StatCard({
    icon: Icon, label, value, tone = "blue", subtext, delay = 0
}: {
    icon: React.ElementType; label: string; value: number | string;
    tone?: keyof typeof TONE_STYLES; subtext?: string; delay?: number;
}) {
    const styles = TONE_STYLES[tone] ?? TONE_STYLES.blue;
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
}

function ReasonListCard({
    title,
    items,
    emptyLabel,
}: {
    title: string;
    items: ReasonCount[];
    emptyLabel: string;
}) {
    return (
        <div className="rounded-2xl border border-white/10 bg-[rgba(15,18,24,0.92)] p-4">
            <div className="text-xs uppercase tracking-[0.3em] text-slate-400">{title}</div>
            <div className="mt-4 flex flex-wrap gap-2">
                {items.length > 0 ? items.map((item) => (
                    <span
                        key={`${title}-${item.code}`}
                        className="rounded-full border border-cyan-400/20 bg-cyan-500/10 px-3 py-1 text-xs text-cyan-100"
                    >
                        {item.code} x{item.count}
                    </span>
                )) : (
                    <span className="text-sm text-slate-500">{emptyLabel}</span>
                )}
            </div>
        </div>
    );
}

interface ReasonCount {
    code: string;
    count: number;
}

interface ScopeMeta {
    thread_id: string | null;
    scope_label: string;
}

interface DecisionAnomalies {
    review_token_mismatch: number;
    hold_cancelled: number;
    legacy_schema: number;
    missing_actor: number;
    missing_message_id: number;
    missing_stream_id: number;
}

interface DecisionDataQuality {
    schema_current: string;
    decision_events_total: number;
    v2_events: number;
    legacy_events: number;
    recommended_baseline_ts: string | null;
    recommended_baseline_reason: string;
}

interface DecisionAnalytics {
    review_window: {
        hold: number;
        approve: number;
        reject: number;
        cancel: number;
        open_estimate?: number;
    };
    phase5: {
        propose: number;
        hold: number;
        approve: number;
        reject: number;
        pending_estimate?: number;
    };
    top_reason_codes: ReasonCount[];
    top_hold_reasons: ReasonCount[];
    top_reject_reasons: ReasonCount[];
    actor_breakdown: Record<string, number>;
    anomalies: DecisionAnomalies;
    data_quality: DecisionDataQuality;
    scope: ScopeMeta;
}

interface DatasetJoinCompleteness {
    eligible_join_samples: number;
    turn_id_present: number;
    message_id_present: number;
    stream_id_present: number;
    full_triplet_present: number;
}

interface DatasetAnalytics {
    total_samples: number;
    eligible_samples: number;
    high_confidence_samples: number;
    low_confidence_samples: number;
    excluded_samples: number;
    high_confidence_baseline_ts: number | null;
    baseline_reason: string;
    sample_kind_breakdown: Record<string, number>;
    source_breakdown: Record<string, number>;
    label_breakdown: Record<string, number>;
    exclude_reasons: ReasonCount[];
    confidence_issues: ReasonCount[];
    join_completeness: DatasetJoinCompleteness;
    x_post_status_breakdown: Record<string, number>;
    x_post_source_breakdown: Record<string, number>;
    scope: ScopeMeta;
}

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
    scope?: ScopeMeta;
    decision_analytics?: DecisionAnalytics;
    dataset_analytics?: DatasetAnalytics;
}

interface ReviewState {
    thread_id: string;
    hold_required: boolean;
    review_token_active: boolean;
    review_pending_count: number;
    phase5_pending_count: number;
    suppressed_actions_count: number;
    review_rejected_count: number;
    phase5_rejected_count: number;
    active_reason_codes: string[];
    latest_suppressed_reason_codes: string[];
}

interface InternalState {
    vector_docs: number;
    last_sleep: string | null;
    mood: string;
    review_state?: ReviewState;
}

interface CheckpointerStats {
    size_mb: number;
    threads: number;
    checkpoints: number;
    retention_days: number;
}

export default function StatsPanel({ threadId = 'default_thread' }: { threadId?: string }) {
    const [stats, setStats] = useState<Stats | null>(null);
    const [internalState, setInternalState] = useState<InternalState | null>(null);
    const [cpStats, setCpStats] = useState<CheckpointerStats | null>(null);
    const [loading, setLoading] = useState(true);
    const [view, setView] = useState<'stats' | 'graph' | 'timeline' | 'monologue' | 'observation'>('stats');

    useEffect(() => {
        const fetchData = async () => {
            try {
                const [statsData, stateData, cpData] = await Promise.all([
                    apiClient.fetchStatsSummary(threadId).catch(() => null),
                    apiClient.fetchInternalState(threadId).catch(() => null),
                    apiClient.fetchCheckpointerStats().catch(() => null),
                ]);

                if (statsData) setStats(statsData as unknown as Stats);
                if (stateData) setInternalState(stateData as unknown as InternalState);
                if (cpData) setCpStats(cpData);
            } catch (e) {
                console.error('Failed to fetch stats:', e);
            }
            setLoading(false);
        };

        fetchData();
        const interval = setInterval(fetchData, 30000);
        return () => clearInterval(interval);
    }, [threadId]);

    const baselineTs = stats?.decision_analytics?.data_quality?.recommended_baseline_ts ?? null;
    const datasetBaselineTs = stats?.dataset_analytics?.high_confidence_baseline_ts ?? null;
    const actorBreakdownItems = Object.entries(stats?.decision_analytics?.actor_breakdown ?? {}).map(
        ([code, count]) => ({ code, count }),
    );
    const datasetXStatusItems = Object.entries(stats?.dataset_analytics?.x_post_status_breakdown ?? {}).map(
        ([code, count]) => ({ code, count }),
    );

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
                                <p className="mt-3 text-xs text-slate-400">
                                    scope: {stats?.scope?.scope_label ?? threadId}
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

                            {/* レビュー分析 */}
                            <div className="mb-8">
                                <h3 className="text-lg font-semibold text-slate-200 mb-4">🪟 レビュー分析</h3>
                                <div className="grid grid-cols-2 md:grid-cols-3 gap-4">
                                    <StatCard
                                        icon={Clock}
                                        label="現在 suppressed"
                                        value={internalState?.review_state?.suppressed_actions_count ?? 0}
                                        tone="orange"
                                        delay={0}
                                        subtext={`thread: ${internalState?.review_state?.thread_id ?? threadId}`}
                                    />
                                    <StatCard
                                        icon={MessageSquare}
                                        label="現在 review hold"
                                        value={internalState?.review_state?.review_pending_count ?? 0}
                                        tone="yellow"
                                        delay={40}
                                        subtext={internalState?.review_state?.hold_required ? 'hold active' : 'hold inactive'}
                                    />
                                    <StatCard
                                        icon={BarChart3}
                                        label="現在 phase5 pending"
                                        value={internalState?.review_state?.phase5_pending_count ?? 0}
                                        tone="indigo"
                                        delay={80}
                                        subtext={internalState?.review_state?.review_token_active ? 'review token active' : 'review token idle'}
                                    />
                                    <StatCard
                                        icon={Clock}
                                        label="履歴 review hold"
                                        value={stats?.decision_analytics?.review_window?.hold ?? 0}
                                        tone="cyan"
                                        delay={120}
                                        subtext={`open est. ${stats?.decision_analytics?.review_window?.open_estimate ?? 0}`}
                                    />
                                    <StatCard
                                        icon={XCircle}
                                        label="履歴 review reject"
                                        value={stats?.decision_analytics?.review_window?.reject ?? 0}
                                        tone="red"
                                        delay={160}
                                        subtext={`cancel ${stats?.decision_analytics?.review_window?.cancel ?? 0}`}
                                    />
                                    <StatCard
                                        icon={BarChart3}
                                        label="履歴 phase5 hold"
                                        value={stats?.decision_analytics?.phase5?.hold ?? 0}
                                        tone="blue"
                                        delay={200}
                                        subtext={`reject ${stats?.decision_analytics?.phase5?.reject ?? 0} | pending est. ${stats?.decision_analytics?.phase5?.pending_estimate ?? 0}`}
                                    />
                                </div>

                                <div className="mt-4 grid gap-4 md:grid-cols-3">
                                    <ReasonListCard
                                        title="Active Reasons"
                                        items={(
                                            (internalState?.review_state?.active_reason_codes?.length
                                                ? internalState.review_state.active_reason_codes
                                                : internalState?.review_state?.latest_suppressed_reason_codes) ?? []
                                        ).map((code) => ({ code, count: 1 }))}
                                        emptyLabel="active reasonなし"
                                    />
                                    <ReasonListCard
                                        title="Top Hold Reasons"
                                        items={stats?.decision_analytics?.top_hold_reasons ?? []}
                                        emptyLabel="hold reasonなし"
                                    />
                                    <ReasonListCard
                                        title="Top Reject Reasons"
                                        items={stats?.decision_analytics?.top_reject_reasons ?? []}
                                        emptyLabel="reject reasonなし"
                                    />
                                </div>

                                <div className="mt-4 grid grid-cols-2 gap-4 md:grid-cols-4">
                                    <StatCard
                                        icon={XCircle}
                                        label="Token Mismatch"
                                        value={stats?.decision_analytics?.anomalies?.review_token_mismatch ?? 0}
                                        tone="red"
                                        delay={0}
                                    />
                                    <StatCard
                                        icon={Clock}
                                        label="Hold Cancel"
                                        value={stats?.decision_analytics?.anomalies?.hold_cancelled ?? 0}
                                        tone="orange"
                                        delay={40}
                                    />
                                    <StatCard
                                        icon={Database}
                                        label="Legacy Events"
                                        value={stats?.decision_analytics?.data_quality?.legacy_events ?? 0}
                                        tone="gray"
                                        delay={80}
                                        subtext={stats?.decision_analytics?.data_quality?.schema_current ?? 'decision_event'}
                                    />
                                    <StatCard
                                        icon={BarChart3}
                                        label="Actor Missing"
                                        value={stats?.decision_analytics?.anomalies?.missing_actor ?? 0}
                                        tone="yellow"
                                        delay={120}
                                        subtext={`gate msg miss ${stats?.decision_analytics?.anomalies?.missing_message_id ?? 0}`}
                                    />
                                </div>

                                <div className="mt-4 grid gap-4 md:grid-cols-2">
                                    <ReasonListCard
                                        title="Actors"
                                        items={actorBreakdownItems}
                                        emptyLabel="actor dataなし"
                                    />
                                    <div className="rounded-2xl border border-white/10 bg-[rgba(15,18,24,0.92)] p-4">
                                        <div className="text-xs uppercase tracking-[0.3em] text-slate-400">Data Quality</div>
                                        <div className="mt-4 space-y-2 text-sm text-slate-300">
                                            <div>decision events: {stats?.decision_analytics?.data_quality?.decision_events_total ?? 0}</div>
                                            <div>v2 events: {stats?.decision_analytics?.data_quality?.v2_events ?? 0}</div>
                                            <div>
                                                baseline: {baselineTs
                                                    ? new Date(baselineTs).toLocaleString('ja-JP')
                                                    : '--'}
                                            </div>
                                            <div className="text-xs text-slate-500">
                                                {stats?.decision_analytics?.data_quality?.recommended_baseline_reason ?? 'legacy policy not set'}
                                            </div>
                                        </div>
                                    </div>
                                </div>
                            </div>

                            <div className="mb-8">
                                <h3 className="text-lg font-semibold text-slate-200 mb-4">📚 学習データ</h3>
                                <div className="grid grid-cols-2 gap-4 md:grid-cols-5">
                                    <StatCard
                                        icon={Database}
                                        label="canonical"
                                        value={stats?.dataset_analytics?.total_samples ?? 0}
                                        tone="blue"
                                        delay={0}
                                    />
                                    <StatCard
                                        icon={CheckCircle}
                                        label="high confidence"
                                        value={stats?.dataset_analytics?.high_confidence_samples ?? 0}
                                        tone="green"
                                        delay={40}
                                        subtext={`eligible ${stats?.dataset_analytics?.eligible_samples ?? 0}`}
                                    />
                                    <StatCard
                                        icon={Clock}
                                        label="low confidence"
                                        value={stats?.dataset_analytics?.low_confidence_samples ?? 0}
                                        tone="yellow"
                                        delay={80}
                                        subtext={`excluded ${stats?.dataset_analytics?.excluded_samples ?? 0}`}
                                    />
                                    <StatCard
                                        icon={Network}
                                        label="join complete"
                                        value={stats?.dataset_analytics?.join_completeness?.full_triplet_present ?? 0}
                                        tone="cyan"
                                        delay={120}
                                        subtext={`eligible join ${stats?.dataset_analytics?.join_completeness?.eligible_join_samples ?? 0}`}
                                    />
                                    <StatCard
                                        icon={BarChart3}
                                        label="X posted"
                                        value={stats?.dataset_analytics?.x_post_status_breakdown?.posted ?? 0}
                                        tone="pink"
                                        delay={160}
                                        subtext={`rejected ${stats?.dataset_analytics?.x_post_status_breakdown?.rejected ?? 0}`}
                                    />
                                </div>

                                <div className="mt-4 grid gap-4 md:grid-cols-3">
                                    <ReasonListCard
                                        title="Exclude Reasons"
                                        items={stats?.dataset_analytics?.exclude_reasons ?? []}
                                        emptyLabel="excludeなし"
                                    />
                                    <ReasonListCard
                                        title="Confidence Issues"
                                        items={stats?.dataset_analytics?.confidence_issues ?? []}
                                        emptyLabel="issueなし"
                                    />
                                    <ReasonListCard
                                        title="X Status"
                                        items={datasetXStatusItems}
                                        emptyLabel="x proposalなし"
                                    />
                                </div>

                                <div className="mt-4 rounded-2xl border border-white/10 bg-[rgba(15,18,24,0.92)] p-4">
                                    <div className="text-xs uppercase tracking-[0.3em] text-slate-400">High-Confidence Baseline</div>
                                    <div className="mt-4 space-y-2 text-sm text-slate-300">
                                        <div>
                                            baseline: {datasetBaselineTs
                                                ? new Date(datasetBaselineTs).toLocaleString('ja-JP')
                                                : '--'}
                                        </div>
                                        <div>
                                            turn/message/stream: {stats?.dataset_analytics?.join_completeness?.turn_id_present ?? 0}
                                            {' / '}
                                            {stats?.dataset_analytics?.join_completeness?.message_id_present ?? 0}
                                            {' / '}
                                            {stats?.dataset_analytics?.join_completeness?.stream_id_present ?? 0}
                                        </div>
                                        <div className="text-xs text-slate-500">
                                            {stats?.dataset_analytics?.baseline_reason ?? 'baseline policy not set'}
                                        </div>
                                    </div>
                                </div>
                            </div>

                            {/* 内部状態 */}
                            <div>
                                <h3 className="text-lg font-semibold text-slate-200 mb-4">🔮 内部状態</h3>
                                <div className="grid grid-cols-2 md:grid-cols-3 gap-4">
                                    <StatCard icon={Database} label="ベクトル記憶" value={`${internalState?.vector_docs ?? 0} docs`} tone="purple" delay={0} />
                                    <StatCard icon={HeartPulse} label="現在の気分" value={internalState?.mood || 'neutral'} tone="pink" delay={40} />
                                    <StatCard icon={Clock} label="最後の睡眠" value={internalState?.last_sleep ?? '--'} tone="indigo" delay={80} />
                                    <StatCard icon={Database} label="CP DB" value={`${cpStats?.size_mb ?? 0} MB`} tone="cyan" delay={120} />
                                    <StatCard icon={Network} label="CP スレッド" value={cpStats?.threads ?? 0} tone="blue" delay={160} />
                                    <StatCard icon={BarChart3} label="CP 数" value={cpStats?.checkpoints ?? 0} tone="yellow" delay={200} />
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
