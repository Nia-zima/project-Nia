"use client";
import React from 'react';
import { Settings, MessageSquare, Database, User, Mic, Moon, Sparkles, Eye, EyeOff, BarChart3, AlertTriangle, Brush, Gamepad2, Video } from 'lucide-react';
import { API_URL } from '@/lib/api';
import { clsx } from 'clsx';
import type { ActionIssue } from '@/lib/types';

interface SidebarProps {
    activeTab: string;
    setActiveTab: (tab: string) => void;
}

const SYSTEM_TOKEN = process.env.NEXT_PUBLIC_SYSTEM_TOKEN || "";

const buildSystemHeaders = (withJson: boolean): Record<string, string> => {
    const headers: Record<string, string> = {};
    if (withJson) {
        headers["Content-Type"] = "application/json";
    }
    if (SYSTEM_TOKEN) {
        headers["x-system-token"] = SYSTEM_TOKEN;
    }
    return headers;
};

export default function Sidebar({ activeTab, setActiveTab }: SidebarProps) {
    const tabs = [
        { id: 'chat', icon: MessageSquare, label: 'チャット' },
        { id: 'memories', icon: Database, label: '記憶データベース' },
        { id: 'stats', icon: BarChart3, label: '統計' },
        { id: 'action_issues', icon: AlertTriangle, label: '失敗/却下' },
        { id: 'draw_lab', icon: Brush, label: 'お絵描きPoC' },
        { id: 'game', icon: Gamepad2, label: 'ゲーム' },
        { id: 'video', icon: Video, label: '動画' },
        // { id: 'profile', icon: User, label: 'プロフィール' },
        { id: 'settings', icon: Settings, label: '設定' },
    ];


    const [visionEnabled, setVisionEnabled] = React.useState(false);
    const [actionIssues, setActionIssues] = React.useState<ActionIssue[]>([]);

    React.useEffect(() => {
        fetch(`${API_URL}/status`)
            .then(res => { if (!res.ok) throw new Error(`status: ${res.status}`); return res.json(); })
            .then(data => {
                if (typeof data.vision_enabled === 'boolean') {
                    setVisionEnabled(data.vision_enabled);
                }
            })
            .catch(console.error);
    }, []);

    React.useEffect(() => {
        let cancelled = false;
        const fetchIssues = async () => {
            try {
                const res = await fetch(
                    `${API_URL}/actions/pending?thread_id=default_thread&status=ERROR,REJECTED&limit=5`,
                    { cache: "no-store" }
                );
                if (!res.ok) return;
                const data = await res.json();
                if (!cancelled) {
                    setActionIssues(Array.isArray(data?.items) ? data.items : []);
                }
            } catch (e) {
                if (!cancelled) {
                    setActionIssues([]);
                }
            }
        };
        fetchIssues();

        const handler = (ev: Event) => {
            const detail = (ev as CustomEvent).detail || {};
            if (!detail?.name) return;
            fetchIssues();
        };
        if (typeof window !== "undefined") {
            window.addEventListener("phase5-action-event", handler as EventListener);
        }

        return () => {
            cancelled = true;
            if (typeof window !== "undefined") {
                window.removeEventListener("phase5-action-event", handler as EventListener);
            }
        };
    }, []);

    const toggleVision = async () => {
        const newState = !visionEnabled;
        setVisionEnabled(newState);
        try {
            const res = await fetch(`${API_URL}/system/vision`, {
                method: 'POST',
                headers: buildSystemHeaders(true),
                body: JSON.stringify({ enabled: newState })
            });
            if (!res.ok) {
                throw new Error(`vision toggle failed: ${res.status}`);
            }
        } catch (e) {
            console.error(e);
            setVisionEnabled(!newState);
        }
    };

    return (
        <div className="w-20 lg:w-64 h-full glass-panel flex flex-col items-center lg:items-start py-6 gap-2 z-20 transition-all duration-300">
            <div className="mb-8 px-0 lg:px-6 w-full flex items-center justify-center lg:justify-start gap-3">
                <div className="w-10 h-10 rounded-xl bg-gradient-to-tr from-blue-500 to-cyan-400 flex items-center justify-center shadow-lg shadow-blue-500/30">
                    <Mic className="text-white w-6 h-6" />
                </div>
                <h1 className="hidden lg:block font-bold text-xl tracking-wide bg-gradient-to-r from-white to-gray-400 bg-clip-text text-transparent">
                    AI Nia(ニア)
                </h1>
            </div>

            <nav className="flex-1 w-full px-2 flex flex-col gap-2">
                {tabs.map((tab) => {
                    const Icon = tab.icon;
                    const isActive = activeTab === tab.id;
                    return (
                        <React.Fragment key={tab.id}>
                            <button
                                onClick={() => setActiveTab(tab.id)}
                                className={clsx(
                                    "w-full flex items-center gap-3 p-3 rounded-xl transition-all duration-200 group active:scale-95",
                                    isActive
                                        ? "bg-primary/20 text-primary border border-primary/20 shadow-[0_0_15px_rgba(59,130,246,0.2)]"
                                        : "text-gray-400 hover:bg-white/5 hover:text-gray-200"
                                )}
                            >
                                <Icon className={clsx("w-6 h-6", isActive && "text-blue-400")} />
                                <span className="hidden lg:block font-medium">{tab.label}</span>
                                {isActive && (
                                    <div className="lg:hidden absolute left-1 w-1 h-8 bg-blue-500 rounded-r-full" />
                                )}
                            </button>
                            {tab.id === "stats" && actionIssues.length > 0 && (
                                <div className="mx-1 my-1 rounded-xl border border-rose-500/20 bg-rose-900/10 px-2 py-1 text-[10px] text-rose-200/80">
                                    失敗/却下: {actionIssues.length}件
                                </div>
                            )}
                        </React.Fragment>
                    );
                })}
            </nav>

            <div className="w-full px-4 my-2 border-t border-white/5" />

            <div className="w-full px-2 flex flex-col gap-2">
                <button
                    onClick={async () => {
                        if (!confirm("睡眠サイクル（記憶の整理）を開始しますか？\nしばらく応答できなくなります。")) return;
                        try {
                            const res = await fetch(`${API_URL}/system/sleep`, {
                                method: 'POST',
                                headers: buildSystemHeaders(false),
                            });
                            if (!res.ok) throw new Error(`sleep failed: ${res.status}`);
                            alert("おやすみなさい。睡眠サイクルを開始しました。");
                        }
                        catch (e) { console.error(e); alert("失敗しました。"); }
                    }}
                    className="w-full flex items-center gap-3 p-3 rounded-xl text-gray-400 hover:bg-purple-500/10 hover:text-purple-300 transition-all active:scale-95"
                    title="睡眠モード"
                >
                    <Moon className="w-6 h-6 text-purple-400" />
                    <span className="hidden lg:block font-medium">睡眠 (Sleep)</span>
                </button>

                <button
                    onClick={toggleVision}
                    className={clsx(
                        "w-full flex items-center gap-3 p-3 rounded-xl transition-all active:scale-95",
                        visionEnabled
                            ? "text-green-400 bg-green-500/10 hover:bg-green-500/20"
                            : "text-gray-400 hover:bg-white/5 hover:text-gray-200"
                    )}
                    title={visionEnabled ? "視覚ON" : "視覚OFF"}
                >
                    {visionEnabled ? <Eye className="w-6 h-6" /> : <EyeOff className="w-6 h-6" />}
                    <span className="hidden lg:block font-medium">視覚 (Vision)</span>
                </button>

                <button
                    onClick={async () => {
                        if (!confirm("週次定例（進化プロセス）を開始しますか？\n直近1週間のログを分析します。")) return;
                        try {
                            const res = await fetch(`${API_URL}/system/reflect`, {
                                method: 'POST',
                                headers: buildSystemHeaders(false),
                            });
                            if (!res.ok) throw new Error(`reflect failed: ${res.status}`);
                            alert("振り返りを開始しました。ログを確認してください。");
                        }
                        catch (e) { console.error(e); alert("失敗しました。"); }
                    }}
                    className="w-full flex items-center gap-3 p-3 rounded-xl text-gray-400 hover:bg-yellow-500/10 hover:text-yellow-300 transition-all active:scale-95"
                    title="進化プロセス"
                >
                    <Sparkles className="w-6 h-6 text-yellow-400" />
                    <span className="hidden lg:block font-medium">進化 (Evolve)</span>
                </button>
            </div>

            <div className="mt-auto p-4 text-xs text-gray-600 hidden lg:block text-center">
                v2.0.0 Alpha
            </div>
        </div>
    );
}
