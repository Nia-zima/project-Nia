"use client";
import React, { useEffect, useState } from 'react';
import { API_URL } from '@/lib/api';
import { Loader2, Calendar, ChevronDown, ChevronRight, Clock } from 'lucide-react';

interface MemoryItem {
    id: string;
    text: string;
    full_text: string;
    timestamp: string;
    source: string;
    confidence: number;
}

interface TimelineDay {
    date: string;
    count: number;
    memories: MemoryItem[];
}

interface TimelineData {
    timeline: TimelineDay[];
    total: number;
    error?: string;
}

export default function MemoryTimeline() {
    const [data, setData] = useState<TimelineData | null>(null);
    const [loading, setLoading] = useState(true);
    const [expandedDays, setExpandedDays] = useState<Set<string>>(new Set());

    useEffect(() => {
        const fetchData = async () => {
            try {
                const res = await fetch(`${API_URL}/stats/memory_timeline`);
                if (res.ok) {
                    setData(await res.json());
                }
            } catch (e) {
                console.error('Failed to fetch timeline:', e);
            }
            setLoading(false);
        };
        fetchData();
    }, []);

    const toggleDay = (date: string) => {
        const newExpanded = new Set(expandedDays);
        if (newExpanded.has(date)) {
            newExpanded.delete(date);
        } else {
            newExpanded.add(date);
        }
        setExpandedDays(newExpanded);
    };

    const formatDate = (dateStr: string) => {
        if (dateStr === 'unknown') return '日付不明';
        try {
            const date = new Date(dateStr);
            return date.toLocaleDateString('ja-JP', {
                year: 'numeric',
                month: 'short',
                day: 'numeric',
                weekday: 'short'
            });
        } catch {
            return dateStr;
        }
    };

    if (loading) {
        return (
            <div className="flex items-center justify-center h-64">
                <Loader2 className="w-8 h-8 animate-spin text-blue-400" />
            </div>
        );
    }

    if (!data || data.timeline.length === 0) {
        return (
            <div className="flex items-center justify-center h-64 text-gray-500">
                記憶データがありません
            </div>
        );
    }

    return (
        <div className="h-full p-6 overflow-y-auto">
            <div className="flex items-center justify-between mb-6">
                <h2 className="text-xl font-bold text-blue-300 flex items-center gap-2">
                    <Calendar className="w-6 h-6" />
                    記憶タイムライン
                </h2>
                <span className="text-sm text-gray-500">
                    総記憶数: {data.total}
                </span>
            </div>

            <div className="space-y-3">
                {data.timeline.map((day) => (
                    <div key={day.date} className="glass rounded-xl overflow-hidden">
                        {/* Day Header */}
                        <button
                            onClick={() => toggleDay(day.date)}
                            className="w-full flex items-center justify-between p-4 hover:bg-white/5 transition-colors"
                        >
                            <div className="flex items-center gap-3">
                                {expandedDays.has(day.date) ? (
                                    <ChevronDown className="w-5 h-5 text-blue-400" />
                                ) : (
                                    <ChevronRight className="w-5 h-5 text-gray-500" />
                                )}
                                <span className="font-medium text-white">
                                    {formatDate(day.date)}
                                </span>
                            </div>
                            <span className="px-3 py-1 rounded-full bg-blue-500/20 text-blue-300 text-sm">
                                {day.count} 件
                            </span>
                        </button>

                        {/* Memories */}
                        {expandedDays.has(day.date) && (
                            <div className="border-t border-white/10">
                                {day.memories.map((memory) => (
                                    <div
                                        key={memory.id}
                                        className="p-4 border-b border-white/5 last:border-b-0 hover:bg-white/5"
                                    >
                                        <p className="text-sm text-gray-300 mb-2">
                                            {memory.full_text}
                                        </p>
                                        <div className="flex items-center gap-4 text-xs text-gray-500">
                                            <span className="flex items-center gap-1">
                                                <Clock className="w-3 h-3" />
                                                {memory.timestamp ? new Date(memory.timestamp).toLocaleTimeString('ja-JP', { hour: '2-digit', minute: '2-digit' }) : '--'}
                                            </span>
                                            <span className="px-2 py-0.5 rounded bg-gray-700/50">
                                                {memory.source}
                                            </span>
                                            {memory.confidence > 0 && (
                                                <span className="text-green-400">
                                                    信頼度: {(memory.confidence * 100).toFixed(0)}%
                                                </span>
                                            )}
                                        </div>
                                    </div>
                                ))}
                            </div>
                        )}
                    </div>
                ))}
            </div>
        </div>
    );
}
