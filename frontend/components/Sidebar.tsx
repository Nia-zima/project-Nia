"use client";
import React from 'react';
import { Settings, MessageSquare, Database, User, Mic, Moon, Sparkles, Eye, EyeOff, BarChart3, AlertTriangle, Brush, Gamepad2, Video } from 'lucide-react';
import { apiClient } from '@/lib/apiClient';
import { clsx } from 'clsx';
import type { ActionIssue } from '@/lib/types';

interface SidebarProps {
    activeTab: string;
    setActiveTab: (tab: string) => void;
}

const SYSTEM_TOKEN = process.env.NEXT_PUBLIC_SYSTEM_TOKEN || "";

export default function Sidebar({ activeTab, setActiveTab }: SidebarProps) {
    const tabs = [
        { id: 'chat', icon: MessageSquare, label: 'チャット' },
        { id: 'memories', icon: Database, label: '記憶データベース' },
        { id: 'stats', icon: BarChart3, label: '統計' },
        { id: 'action_issues', icon: AlertTriangle, label: '失敗/却下' },
        { id: 'draw_lab', icon: Brush, label: 'お絵描きPoC' },
        { id: 'game', icon: Gamepad2, label: 'ゲーム' },
        { id: 'video', icon: Video, label: '動画' },
        { id: 'profile', icon: User, label: 'プロフィール' },
        { id: 'identity', icon: User, label: 'アイデンティティ' },
        { id: 'settings', icon: Settings, label: '設定' },
    ];


    const [visionEnabled, setVisionEnabled] = React.useState(false);
    const [actionIssues, setActionIssues] = React.useState<ActionIssue[]>([]);
    const [systemTokenInput, setSystemTokenInput] = React.useState("");

    React.useEffect(() => {
        const stored =
            typeof window !== "undefined" ? window.localStorage.getItem("system_token") || "" : "";
        const initialToken = (stored || SYSTEM_TOKEN || "").trim();
        setSystemTokenInput(initialToken);
        apiClient.setSystemToken(initialToken || null);

        apiClient.fetchStatus()
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
                const data = await apiClient.fetchActionIssues("default_thread", "ERROR,REJECTED", 20);
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

    const saveSystemToken = () => {
        const token = systemTokenInput.trim();
        if (typeof window !== "undefined") {
            if (token) {
                window.localStorage.setItem("system_token", token);
            } else {
                window.localStorage.removeItem("system_token");
            }
        }
        apiClient.setSystemToken(token || SYSTEM_TOKEN || null);
    };

    const clearSystemToken = () => {
        if (typeof window !== "undefined") {
            window.localStorage.removeItem("system_token");
        }
        setSystemTokenInput("");
        apiClient.setSystemToken(SYSTEM_TOKEN || null);
    };

    const toggleVision = async () => {
        const newState = !visionEnabled;
        setVisionEnabled(newState);
        try {
            await apiClient.systemVision(newState);
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
                            await apiClient.systemSleep();
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
                            await apiClient.systemReflect();
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

            <div className="hidden lg:block w-full px-3 mt-2">
                <div className="rounded-xl border border-white/10 bg-black/30 p-2">
                    <div className="text-[10px] text-gray-400 mb-1">Admin Token</div>
                    <input
                        type="password"
                        value={systemTokenInput}
                        onChange={(e) => setSystemTokenInput(e.target.value)}
                        placeholder="X-System-Token"
                        className="w-full rounded-md bg-black/40 border border-white/10 px-2 py-1 text-[11px] text-gray-200 placeholder:text-gray-500"
                    />
                    <div className="mt-2 flex gap-1">
                        <button
                            onClick={saveSystemToken}
                            className="flex-1 rounded-md border border-sky-400/30 bg-sky-500/20 px-2 py-1 text-[10px] text-sky-100 hover:bg-sky-500/30 transition"
                        >
                            保存
                        </button>
                        <button
                            onClick={clearSystemToken}
                            className="flex-1 rounded-md border border-white/15 bg-white/5 px-2 py-1 text-[10px] text-gray-300 hover:bg-white/10 transition"
                        >
                            クリア
                        </button>
                    </div>
                </div>
            </div>

            <div className="mt-auto p-4 text-xs text-gray-600 hidden lg:block text-center">
                v2.0.0 Alpha
            </div>
        </div>
    );
}
