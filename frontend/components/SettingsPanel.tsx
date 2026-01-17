import React from 'react';
import { Settings, Gamepad2, Terminal, User } from 'lucide-react';

interface SettingsPanelProps {
    currentMode: string;
    onModeChange: (mode: string) => void;
}

export default function SettingsPanel({ currentMode, onModeChange }: SettingsPanelProps) {
    const modes = [
        {
            id: 'normal',
            name: '通常モード',
            description: 'いつものニアです。自然体で接します。',
            icon: <User size={24} className="text-blue-400" />
        },
        {
            id: 'stream',
            name: '配信モード',
            description: '配信者向け。呼び名を「Origin」に統一します。',
            icon: <Gamepad2 size={24} className="text-purple-400" />
        },
        {
            id: 'dev',
            name: '開発者モード',
            description: '開発者向け。感情を排し、技術的な正確さを優先します。',
            icon: <Terminal size={24} className="text-green-400" />
        }
    ];

    return (
        <div className="h-full flex flex-col gap-6 text-white p-4">
            <header className="flex items-center gap-3 border-b border-white/10 pb-4">
                <Settings className="w-6 h-6 text-gray-400" />
                <h2 className="text-xl font-bold">システム設定</h2>
            </header>

            <section>
                <h3 className="text-sm font-medium text-gray-400 mb-4 uppercase tracking-wider">エージェントモード</h3>
                <div className="grid grid-cols-1 gap-4">
                    {modes.map((mode) => (
                        <button
                            key={mode.id}
                            onClick={() => onModeChange(mode.id)}
                            className={`
                relative flex items-center gap-4 p-4 rounded-xl text-left transition-all duration-200
                border border-white/5 hover:border-white/20
                ${currentMode === mode.id
                                    ? 'bg-blue-600/20 ring-2 ring-blue-500/50'
                                    : 'bg-white/5 hover:bg-white/10'
                                }
              `}
                        >
                            <div className={`p-3 rounded-lg bg-black/30 ${currentMode === mode.id ? 'bg-blue-500/20' : ''}`}>
                                {mode.icon}
                            </div>
                            <div className="flex-1">
                                <div className="flex items-center justify-between">
                                    <span className={`font-semibold ${currentMode === mode.id ? 'text-blue-200' : 'text-gray-200'}`}>
                                        {mode.name}
                                    </span>
                                    {currentMode === mode.id && (
                                        <span className="text-xs bg-blue-500/80 text-white px-2 py-0.5 rounded-full">Active</span>
                                    )}
                                </div>
                                <p className="text-xs text-gray-400 mt-1">{mode.description}</p>
                            </div>
                        </button>
                    ))}
                </div>
            </section>

            {/* 将来的にここに他の設定（API Key設定、音声設定など）を追加可能 */}
        </div>
    );
}
