"use client";
import React, { useRef } from 'react';
import { Send, Mic, Image as ImageIcon, StopCircle } from 'lucide-react';
import { useChatStore } from '@/lib/stores/chatStore';

interface ChatInputProps {
    onToggleListening: () => void;
    onSendMessage: () => void;
    onImageSelect: (e: React.ChangeEvent<HTMLInputElement>) => void;
    // Voice (from useVoiceMode hook — not in store)
    voiceModeEnabled: boolean;
    voiceWsState: 'idle' | 'connecting' | 'connected' | 'error';
    voiceError: string | null;
    sttPreview: string;
    onToggleVoiceMode: () => void;
}

export default function ChatInput({
    onToggleListening,
    onSendMessage,
    onImageSelect,
    voiceModeEnabled,
    voiceWsState,
    voiceError,
    sttPreview,
    onToggleVoiceMode,
}: ChatInputProps) {
    const input = useChatStore((s) => s.input);
    const setInput = useChatStore((s) => s.setInput);
    const isLoading = useChatStore((s) => s.isLoading);
    const selectedImage = useChatStore((s) => s.selectedImage);
    const setSelectedImage = useChatStore((s) => s.setSelectedImage);
    const isListening = useChatStore((s) => s.isListening);

    const fileInputRef = useRef<HTMLInputElement>(null);

    return (
        <div className="relative w-full glass p-2 rounded-2xl flex flex-col gap-2">
            {selectedImage && (
                <div className="relative w-32 h-32 bg-black/50 rounded-xl overflow-hidden group">
                    <img src={selectedImage} alt="Preview" className="w-full h-full object-cover" />
                    <button
                        onClick={() => setSelectedImage(null)}
                        className="absolute top-1 right-1 bg-red-500/80 text-white p-1 rounded-full opacity-0 group-hover:opacity-100 transition-opacity"
                    >
                        <StopCircle size={14} />
                    </button>
                </div>
            )}

            <div className="flex items-center gap-1 sm:gap-2 w-full">
                <input
                    type="file"
                    ref={fileInputRef}
                    hidden
                    accept="image/*"
                    onChange={onImageSelect}
                />
                <button
                    onClick={() => fileInputRef.current?.click()}
                    className={`shrink-0 p-2 sm:p-3 rounded-xl transition-colors ${selectedImage ? 'text-blue-400 bg-blue-500/20' : 'hover:bg-white/10 text-gray-400'}`}
                >
                    <ImageIcon size={18} className="sm:hidden" />
                    <ImageIcon size={20} className="hidden sm:block" />
                </button>
                <textarea
                    value={input}
                    onChange={(e) => setInput(e.target.value)}
                    onKeyDown={(e) => {
                        if (e.key === 'Enter' && !e.shiftKey && !(e.nativeEvent as any).isComposing && !isLoading) {
                            e.preventDefault();
                            onSendMessage();
                        }
                    }}
                    placeholder="メッセージを入力..."
                    className="flex-1 min-w-0 bg-transparent border-none outline-none text-white px-1 sm:px-2 placeholder-gray-500 resize-none"
                    disabled={isLoading}
                    rows={1}
                    style={{ maxHeight: '6rem', overflowY: 'auto' }}
                    onInput={(e) => {
                        const el = e.currentTarget;
                        el.style.height = 'auto';
                        el.style.height = `${Math.min(el.scrollHeight, 96)}px`;
                    }}
                />
                <button
                    onClick={onToggleVoiceMode}
                    className={`shrink-0 px-2 py-1.5 sm:px-3 sm:py-2 rounded-xl text-[10px] sm:text-xs font-medium transition-all ${voiceModeEnabled
                        ? 'bg-emerald-500 text-white shadow-[0_0_12px_rgba(16,185,129,0.45)]'
                        : 'border border-white/20 text-gray-300 hover:bg-white/10'
                        }`}
                    title={voiceModeEnabled ? "Voice Mode 停止" : "Voice Mode 開始"}
                >
                    {voiceModeEnabled ? "ON" : "VC"}
                </button>
                <button
                    onClick={onToggleListening}
                    className={`shrink-0 p-2 sm:p-3 rounded-xl transition-all ${isListening
                        ? 'bg-red-500 text-white animate-pulse shadow-[0_0_15px_rgba(239,68,68,0.5)]'
                        : 'hover:bg-white/10 text-gray-400'
                        }`}
                    title={isListening ? "音声認識停止" : "音声認識開始"}
                >
                    <Mic size={18} className="sm:hidden" />
                    <Mic size={20} className="hidden sm:block" />
                </button>
                <button
                    onClick={onSendMessage}
                    disabled={isLoading || (!input.trim() && !selectedImage)}
                    className="shrink-0 p-2 sm:p-3 rounded-xl bg-blue-600 hover:bg-blue-500 text-white shadow-lg shadow-blue-600/20 disabled:opacity-50 transition-all active:scale-95"
                >
                    <Send size={18} className="sm:hidden" />
                    <Send size={20} className="hidden sm:block" />
                </button>
            </div>
            {(voiceModeEnabled || voiceWsState !== "idle" || voiceError) && (
                <div className="px-2 text-[11px] text-gray-400">
                    <span>voice_ws: {voiceWsState}</span>
                    {sttPreview && <span className="ml-2 text-emerald-300">stt: {sttPreview}</span>}
                    {voiceError && <span className="ml-2 text-red-300">{voiceError}</span>}
                </div>
            )}
        </div>
    );
}
