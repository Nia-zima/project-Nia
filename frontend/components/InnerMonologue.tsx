"use client";
import React, { useEffect, useState } from 'react';
import { apiClient } from '@/lib/apiClient';
import { Loader2, Brain, Eye, Wind, MessageCircle, Clock } from 'lucide-react';

interface MonologueEntry {
    timestamp: string;
    intent: string;
    interpretation: string;
    inner_reflection: string;
    express: boolean;
    confidence: number;
}

interface MonologueData {
    entries: MonologueEntry[];
    total: number;
    error?: string;
}

const intentIcons: Record<string, React.ElementType> = {
    observe: Eye,
    breathe: Wind,
    support_quietly: MessageCircle,
};

const intentColors: Record<string, string> = {
    observe: 'text-blue-400',
    breathe: 'text-purple-400',
    support_quietly: 'text-green-400',
};

const intentLabels: Record<string, string> = {
    observe: '観察',
    breathe: '呼吸',
    support_quietly: '静かに見守る',
};

export default function InnerMonologue() {
    const [data, setData] = useState<MonologueData | null>(null);
    const [loading, setLoading] = useState(true);

    useEffect(() => {
        const fetchData = async () => {
            try {
                const result = await apiClient.fetchInnerMonologue(100);
                setData(result as unknown as MonologueData);
            } catch (e) {
                console.error('Failed to fetch monologue:', e);
            }
            setLoading(false);
        };
        fetchData();
    }, []);

    if (loading) {
        return (
            <div className="flex items-center justify-center h-64">
                <Loader2 className="w-8 h-8 animate-spin text-purple-400" />
            </div>
        );
    }

    if (!data || data.entries.length === 0) {
        return (
            <div className="flex items-center justify-center h-64 text-gray-500">
                内部モノローグがありません
            </div>
        );
    }

    return (
        <div className="h-full p-6 overflow-y-auto">
            <div className="flex items-center justify-between mb-6">
                <h2 className="text-xl font-bold text-purple-300 flex items-center gap-2">
                    <Brain className="w-6 h-6" />
                    ニアの内部モノローグ
                </h2>
                <span className="text-sm text-gray-500">
                    最新 {data.total} 件
                </span>
            </div>

            <div className="space-y-3">
                {data.entries.map((entry, index) => {
                    const Icon = intentIcons[entry.intent] || Brain;
                    const colorClass = intentColors[entry.intent] || 'text-gray-400';
                    const label = intentLabels[entry.intent] || entry.intent;

                    return (
                        <div key={index} className="glass p-4 rounded-xl">
                            <div className="flex items-center gap-3 mb-2">
                                <Icon className={`w-5 h-5 ${colorClass}`} />
                                <span className={`font-medium ${colorClass}`}>{label}</span>
                                <span className="text-xs text-gray-500 flex items-center gap-1 ml-auto">
                                    <Clock className="w-3 h-3" />
                                    {entry.timestamp ? new Date(entry.timestamp).toLocaleString('ja-JP', {
                                        month: 'short',
                                        day: 'numeric',
                                        hour: '2-digit',
                                        minute: '2-digit'
                                    }) : '--'}
                                </span>
                            </div>

                            {entry.interpretation && (
                                <p className="text-sm text-gray-300 mb-2">
                                    {entry.interpretation}
                                </p>
                            )}

                            {entry.inner_reflection && entry.inner_reflection !== '...' && (
                                <p className="text-xs text-gray-500 italic border-l-2 border-purple-500/30 pl-3">
                                    {entry.inner_reflection}
                                </p>
                            )}

                            <div className="flex items-center gap-3 mt-2 text-xs">
                                {entry.express && (
                                    <span className="px-2 py-0.5 rounded bg-blue-500/20 text-blue-300">
                                        発言可能
                                    </span>
                                )}
                                <span className="text-gray-600">
                                    信頼度: {(entry.confidence * 100).toFixed(0)}%
                                </span>
                            </div>
                        </div>
                    );
                })}
            </div>
        </div>
    );
}
