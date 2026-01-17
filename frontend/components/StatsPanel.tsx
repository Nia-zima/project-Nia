"use client";
import React, { useEffect, useState } from 'react';
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
    const [view, setView] = useState<'stats' | 'graph' | 'timeline' | 'monologue'>('stats');

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

    const StatCard = ({
        icon: Icon,
        label,
        value,
        color = "blue",
        subtext
    }: {
        icon: React.ElementType;
        label: string;
        value: number | string;
        color?: string;
        subtext?: string;
    }) => (
        <div className="glass p-4 rounded-xl flex flex-col gap-2">
            <div className="flex items-center gap-2 text-gray-400">
                <Icon className={`w-5 h-5 text-${color}-400`} />
                <span className="text-sm">{label}</span>
            </div>
            <div className={`text-2xl font-bold text-${color}-300`}>{value}</div>
            {subtext && <div className="text-xs text-gray-500">{subtext}</div>}
        </div>
    );

    return (
        <div className="h-full flex flex-col overflow-hidden">
            {/* Tab Header */}
            <div className="flex items-center gap-2 p-4 border-b border-white/10">
                <button
                    onClick={() => setView('stats')}
                    className={`flex items-center gap-2 px-4 py-2 rounded-lg transition-all ${view === 'stats' ? 'bg-blue-500/20 text-blue-400' : 'text-gray-400 hover:text-white'
                        }`}
                >
                    <BarChart3 className="w-4 h-4" />
                    統計
                </button>
                <button
                    onClick={() => setView('graph')}
                    className={`flex items-center gap-2 px-4 py-2 rounded-lg transition-all ${view === 'graph' ? 'bg-purple-500/20 text-purple-400' : 'text-gray-400 hover:text-white'
                        }`}
                >
                    <Network className="w-4 h-4" />
                    記憶グラフ
                </button>
                <button
                    onClick={() => setView('timeline')}
                    className={`flex items-center gap-2 px-4 py-2 rounded-lg transition-all ${view === 'timeline' ? 'bg-green-500/20 text-green-400' : 'text-gray-400 hover:text-white'
                        }`}
                >
                    <Calendar className="w-4 h-4" />
                    タイムライン
                </button>
                <button
                    onClick={() => setView('monologue')}
                    className={`flex items-center gap-2 px-4 py-2 rounded-lg transition-all ${view === 'monologue' ? 'bg-indigo-500/20 text-indigo-400' : 'text-gray-400 hover:text-white'
                        }`}
                >
                    <Brain className="w-4 h-4" />
                    内部思考
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
                            <h2 className="text-2xl font-bold mb-6 bg-gradient-to-r from-blue-400 to-cyan-400 bg-clip-text text-transparent">
                                📊 統計ダッシュボード
                            </h2>

                            {/* 会話統計 */}
                            <div className="mb-8">
                                <h3 className="text-lg font-semibold text-gray-300 mb-4">💬 会話統計</h3>
                                <div className="grid grid-cols-2 md:grid-cols-4 gap-4">
                                    <StatCard icon={MessageSquare} label="今日の会話" value={stats?.today_chats ?? 0} color="cyan" />
                                    <StatCard icon={TrendingUp} label="総会話数" value={stats?.total_chats ?? 0} color="blue" />
                                    <StatCard icon={Clock} label="最後の会話" value={stats?.last_chat_time ? new Date(stats.last_chat_time).toLocaleTimeString('ja-JP', { hour: '2-digit', minute: '2-digit' }) : '--'} color="purple" />
                                    <StatCard icon={Database} label="総イベント" value={stats?.total_events ?? 0} color="gray" />
                                </div>
                            </div>

                            {/* 記憶統計 */}
                            <div className="mb-8">
                                <h3 className="text-lg font-semibold text-gray-300 mb-4">🧠 記憶システム</h3>
                                <div className="grid grid-cols-2 md:grid-cols-5 gap-4">
                                    <StatCard icon={Brain} label="候補" value={stats?.memory_candidates ?? 0} color="yellow" />
                                    <StatCard icon={Clock} label="保留中" value={stats?.memory_pending ?? 0} color="orange" />
                                    <StatCard icon={CheckCircle} label="承認済" value={stats?.memory_approved ?? 0} color="green" />
                                    <StatCard icon={XCircle} label="却下" value={stats?.memory_rejected ?? 0} color="red" />
                                    <StatCard icon={Database} label="記録済" value={stats?.memory_written ?? 0} color="blue" />
                                </div>
                            </div>

                            {/* 内部状態 */}
                            <div>
                                <h3 className="text-lg font-semibold text-gray-300 mb-4">🔮 内部状態</h3>
                                <div className="grid grid-cols-2 md:grid-cols-3 gap-4">
                                    <StatCard icon={Database} label="ベクトル記憶" value={`${internalState?.vector_docs ?? 0} docs`} color="purple" />
                                    <StatCard icon={HeartPulse} label="現在の気分" value={internalState?.mood || 'neutral'} color="pink" />
                                    <StatCard icon={Clock} label="最後の睡眠" value={internalState?.last_sleep ?? '--'} color="indigo" />
                                </div>
                            </div>

                            <div className="mt-8 text-center text-xs text-gray-600">
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
        </div>
    );
}
