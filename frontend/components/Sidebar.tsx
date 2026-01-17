"use client";
import React from 'react';
import { Settings, MessageSquare, Database, User, Mic, Moon, Sparkles, Eye, EyeOff, BarChart3 } from 'lucide-react';
import { API_URL } from '@/lib/api';
import { clsx } from 'clsx';

interface SidebarProps {
    activeTab: string;
    setActiveTab: (tab: string) => void;
}

export default function Sidebar({ activeTab, setActiveTab }: SidebarProps) {
    const tabs = [
        { id: 'chat', icon: MessageSquare, label: 'チャット' },
        { id: 'memories', icon: Database, label: '記憶データベース' },
        { id: 'stats', icon: BarChart3, label: '統計' },
        { id: 'profile', icon: User, label: 'プロフィール' },
        { id: 'settings', icon: Settings, label: '設定' },
    ];


    const [visionEnabled, setVisionEnabled] = React.useState(false);

    React.useEffect(() => {
        fetch(`${API_URL}/status`)
            .then(res => res.json())
            .then(data => {
                if (typeof data.vision_enabled === 'boolean') {
                    setVisionEnabled(data.vision_enabled);
                }
            })
            .catch(console.error);
    }, []);

    const toggleVision = async () => {
        const newState = !visionEnabled;
        setVisionEnabled(newState);
        try {
            await fetch(`${API_URL}/system/vision`, {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify({ enabled: newState })
            });
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
                        <button
                            key={tab.id}
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
                    );
                })}
            </nav>

            <div className="w-full px-4 my-2 border-t border-white/5" />

            <div className="w-full px-2 flex flex-col gap-2">
                <button
                    onClick={async () => {
                        if (!confirm("睡眠サイクル（記憶の整理）を開始しますか？\nしばらく応答できなくなります。")) return;
                        try { await fetch(`${API_URL}/system/sleep`, { method: 'POST' }); alert("おやすみなさい。睡眠サイクルを開始しました。"); }
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
                        try { await fetch(`${API_URL}/system/reflect`, { method: 'POST' }); alert("振り返りを開始しました。ログを確認してください。"); }
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
