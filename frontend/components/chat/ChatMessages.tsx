"use client";
import React, { useRef, useEffect } from 'react';
import { motion, AnimatePresence } from 'framer-motion';
import { useChatStore } from '@/lib/stores/chatStore';

export default function ChatMessages() {
    const messages = useChatStore((s) => s.messages);
    const isLoading = useChatStore((s) => s.isLoading);
    const scrollRef = useRef<HTMLDivElement>(null);

    useEffect(() => {
        if (scrollRef.current) {
            scrollRef.current.scrollTop = scrollRef.current.scrollHeight;
        }
    }, [messages]);

    return (
        <div className="flex-1 overflow-y-auto overflow-x-hidden mb-4 space-y-4 px-2" ref={scrollRef}>
            <AnimatePresence>
                {messages.map((msg) => {
                    if (msg.kind === 'dream') {
                        return (
                            <motion.div
                                key={msg.id}
                                initial={{ opacity: 0, y: 10 }}
                                animate={{ opacity: 1, y: 0 }}
                                className="flex justify-center my-4"
                            >
                                <div className="max-w-[90%] w-full rounded-2xl border border-indigo-500/30 px-4 py-3 bg-indigo-950/50 backdrop-blur-sm">
                                    <div className="flex items-center gap-2 text-sm text-indigo-300 mb-2">
                                        <span aria-hidden>🌙</span>
                                        <span className="font-medium">Niaの夢</span>
                                        {msg.meta?.mood && (
                                            <span className="text-indigo-400/60 text-xs">({msg.meta.mood})</span>
                                        )}
                                    </div>
                                    <div className="whitespace-pre-wrap text-indigo-100/90 leading-relaxed text-sm">
                                        {msg.content}
                                    </div>
                                </div>
                            </motion.div>
                        );
                    }

                    if (msg.kind === 'drawing') {
                        const tags = (msg.meta?.because_tags as string[] | undefined) || [];
                        return (
                            <motion.div
                                key={msg.id}
                                initial={{ opacity: 0, y: 10 }}
                                animate={{ opacity: 1, y: 0 }}
                                className="flex justify-center my-4"
                            >
                                <div className="max-w-[90%] w-full rounded-2xl border border-amber-500/30 px-4 py-3 bg-amber-950/40 backdrop-blur-sm">
                                    <div className="flex items-center gap-2 text-sm text-amber-300 mb-2">
                                        <span className="font-medium">Niaの絵</span>
                                        {msg.meta?.element_count != null && (
                                            <span className="text-amber-400/60 text-xs">
                                                {String(msg.meta.element_count)} elements
                                            </span>
                                        )}
                                        {Boolean(msg.meta?.replay) && (
                                            <span className="text-amber-400/40 text-xs">(replay)</span>
                                        )}
                                    </div>
                                    <div
                                        className="bg-[#FAFAF7] rounded-lg p-2 flex justify-center"
                                        dangerouslySetInnerHTML={{ __html: msg.content }}
                                    />
                                    {tags.length > 0 && (
                                        <div className="flex flex-wrap gap-1 mt-2">
                                            {tags.map((t) => (
                                                <span
                                                    key={t}
                                                    className="text-xs px-1.5 py-0.5 rounded bg-amber-800/40 text-amber-300/80"
                                                >
                                                    {t}
                                                </span>
                                            ))}
                                        </div>
                                    )}
                                    {typeof msg.meta?.drawing_id === 'string' && (
                                        <div className="text-xs text-amber-500/40 mt-1 truncate">
                                            {msg.meta.drawing_id}
                                        </div>
                                    )}
                                </div>
                            </motion.div>
                        );
                    }

                    if (msg.kind === 'drawing_error') {
                        return (
                            <motion.div
                                key={msg.id}
                                initial={{ opacity: 0, y: 10 }}
                                animate={{ opacity: 1, y: 0 }}
                                className="flex justify-center my-4"
                            >
                                <div className="max-w-[90%] w-full rounded-2xl border border-red-500/30 px-4 py-3 bg-red-950/40 backdrop-blur-sm">
                                    <div className="flex items-center gap-2 text-sm text-red-300 mb-2">
                                        <span className="font-medium">描画エラー</span>
                                    </div>
                                    <div className="text-red-200/80 text-sm break-words">
                                        {msg.content}
                                    </div>
                                </div>
                            </motion.div>
                        );
                    }

                    return (
                        <div
                            key={msg.id}
                            className={`flex w-full ${msg.role === 'user' ? 'justify-end' : 'justify-start'}`}
                        >
                            <div className={`flex flex-col max-w-[85%] sm:max-w-[80%] ${msg.role === 'user' ? 'items-end' : 'items-start'}`}>
                                {msg.image && (
                                    <img src={msg.image} alt="User Upload" className="max-w-full sm:max-w-xs rounded-xl mb-2 border border-white/10" />
                                )}
                                <div className={`p-3 sm:p-4 rounded-2xl whitespace-pre-wrap leading-relaxed shadow-lg backdrop-blur-sm break-words
                                    ${msg.role === 'user'
                                        ? 'bg-blue-600/80 text-white rounded-br-none'
                                        : 'bg-gray-800/80 text-gray-100 rounded-bl-none border border-white/5'
                                    }
                                    ${msg.role === 'system' && 'bg-red-900/50 text-red-200 text-sm border-red-500/30'}
                                `}>
                                    {msg.content}
                                </div>
                            </div>
                        </div>
                    );
                })}
            </AnimatePresence>
            {isLoading && <div className="text-gray-500 text-sm animate-pulse ml-2">思考中...</div>}
        </div>
    );
}
