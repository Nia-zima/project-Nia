"use client";
import React, { useEffect, useState } from 'react';
import { apiClient } from '@/lib/apiClient';
import { BookOpen, Calendar } from 'lucide-react';

interface DiaryEntry {
    date: string;
    content: { text: string; mood: string; topics: string[] };
    created_at: number;
}

const MOOD_COLORS: Record<string, string> = {
    happy: "border-emerald-400/40 bg-emerald-500/10 text-emerald-200",
    excited: "border-amber-400/40 bg-amber-500/10 text-amber-200",
    thoughtful: "border-sky-400/40 bg-sky-500/10 text-sky-200",
    calm: "border-indigo-400/40 bg-indigo-500/10 text-indigo-200",
    melancholic: "border-violet-400/40 bg-violet-500/10 text-violet-200",
    neutral: "border-slate-400/40 bg-slate-500/10 text-slate-300",
};

const MOOD_BORDER: Record<string, string> = {
    happy: "from-emerald-400/60",
    excited: "from-amber-400/60",
    thoughtful: "from-sky-400/60",
    calm: "from-indigo-400/60",
    melancholic: "from-violet-400/60",
    neutral: "from-slate-400/40",
};

function getMoodStyle(mood: string) {
    const key = mood?.toLowerCase() || "neutral";
    return {
        badge: MOOD_COLORS[key] || MOOD_COLORS.neutral,
        border: MOOD_BORDER[key] || MOOD_BORDER.neutral,
    };
}

function formatDate(dateStr: string): string {
    try {
        const d = new Date(dateStr + "T00:00:00");
        return d.toLocaleDateString("ja-JP", {
            year: "numeric",
            month: "long",
            day: "numeric",
            weekday: "short",
        });
    } catch {
        return dateStr;
    }
}

export default function DiaryViewer() {
    const [entries, setEntries] = useState<DiaryEntry[]>([]);
    const [loading, setLoading] = useState(true);

    useEffect(() => {
        let cancelled = false;
        (async () => {
            try {
                const data = await apiClient.fetchDiaries(14);
                if (!cancelled) setEntries(Array.isArray(data) ? data : []);
            } catch (e) {
                console.error("Failed to fetch diaries", e);
            } finally {
                if (!cancelled) setLoading(false);
            }
        })();
        return () => { cancelled = true; };
    }, []);

    if (loading) {
        return (
            <div className="space-y-4 p-6">
                {[...Array(3)].map((_, i) => (
                    <div key={i} className="rounded-2xl border border-white/10 bg-white/5 p-6 animate-pulse">
                        <div className="h-4 w-32 bg-white/10 rounded mb-4" />
                        <div className="h-3 w-full bg-white/5 rounded mb-2" />
                        <div className="h-3 w-3/4 bg-white/5 rounded" />
                    </div>
                ))}
            </div>
        );
    }

    return (
        <div className="relative space-y-6 pb-10">
            {/* Header */}
            <div className="rounded-3xl border border-white/10 bg-[rgba(15,18,24,0.92)] p-6">
                <div className="flex flex-col gap-2 md:flex-row md:items-end md:justify-between">
                    <div>
                        <p className="text-[11px] uppercase tracking-[0.4em] text-cyan-200/70">Nia&apos;s Diary</p>
                        <h2 className="text-3xl md:text-4xl font-semibold text-white">
                            日記
                        </h2>
                        <p className="text-sm text-slate-300/80 mt-2">
                            ニアが毎日の振り返りを自分の言葉で綴ります。
                        </p>
                    </div>
                    <div className="flex items-center gap-2 text-xs text-slate-400">
                        <BookOpen size={14} />
                        <span>{entries.length} エントリ</span>
                    </div>
                </div>
            </div>

            {/* Entries */}
            {entries.length === 0 ? (
                <div className="rounded-2xl border border-white/10 bg-white/5 p-12 text-center">
                    <BookOpen className="w-12 h-12 text-slate-600 mx-auto mb-4" />
                    <p className="text-slate-400 text-lg">まだ日記がありません</p>
                    <p className="text-slate-500 text-sm mt-2">Sleep Cycle を実行すると、ニアが日記を書きます。</p>
                </div>
            ) : (
                <div className="grid gap-4">
                    {entries.map((entry, index) => {
                        const style = getMoodStyle(entry.content.mood);
                        return (
                            <div
                                key={entry.date}
                                className="relative overflow-hidden rounded-2xl border border-white/10 bg-[rgba(15,18,24,0.92)] p-6 transition-all duration-300 hover:border-white/20 animate-rise"
                                style={{ animationDelay: `${index * 50}ms` }}
                            >
                                {/* Left accent border */}
                                <div className={`absolute left-0 top-0 h-full w-1 bg-gradient-to-b ${style.border} to-transparent`} />

                                {/* Date & Mood */}
                                <div className="flex items-center gap-3 mb-4">
                                    <Calendar size={14} className="text-slate-500" />
                                    <span className="text-sm font-medium text-slate-200">
                                        {formatDate(entry.date)}
                                    </span>
                                    <span className={`text-[10px] px-2 py-0.5 rounded-full border font-medium ${style.badge}`}>
                                        {entry.content.mood}
                                    </span>
                                </div>

                                {/* Diary Text */}
                                <p className="text-sm text-slate-200/90 leading-relaxed whitespace-pre-wrap pl-1">
                                    {entry.content.text}
                                </p>

                                {/* Topics */}
                                {entry.content.topics && entry.content.topics.length > 0 && (
                                    <div className="flex flex-wrap gap-2 mt-4 pt-3 border-t border-white/5">
                                        {entry.content.topics.map((topic) => (
                                            <span
                                                key={topic}
                                                className="text-[10px] px-2 py-1 rounded-lg bg-white/5 text-slate-400 border border-white/10"
                                            >
                                                {topic}
                                            </span>
                                        ))}
                                    </div>
                                )}
                            </div>
                        );
                    })}
                </div>
            )}
        </div>
    );
}
