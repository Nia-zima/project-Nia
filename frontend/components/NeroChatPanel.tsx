"use client";
import React, { useState, useEffect, useRef, useCallback } from "react";
import { neroClient, type NeroChatMessage } from "@/lib/neroClient";
import { Shield, Send, Loader2, RefreshCw, Trash2 } from "lucide-react";

export default function NeroChatPanel() {
  const [messages, setMessages] = useState<NeroChatMessage[]>([]);
  const [input, setInput] = useState("");
  const [isLoading, setIsLoading] = useState(false);
  const [neroStatus, setNeroStatus] = useState<
    "checking" | "online" | "offline"
  >("checking");
  const [error, setError] = useState<string | null>(null);
  const scrollRef = useRef<HTMLDivElement>(null);
  const inputRef = useRef<HTMLTextAreaElement>(null);

  // Check availability on mount
  useEffect(() => {
    checkStatus();
  }, []);

  // Auto-scroll on new messages
  useEffect(() => {
    if (scrollRef.current) {
      scrollRef.current.scrollTop = scrollRef.current.scrollHeight;
    }
  }, [messages]);

  const checkStatus = useCallback(async () => {
    setNeroStatus("checking");
    neroClient.resetAvailability();
    const available = await neroClient.isAvailable();
    setNeroStatus(available ? "online" : "offline");
    if (available) {
      // Load existing chat history
      try {
        const { messages: hist } = await neroClient.chatHistory();
        setMessages(hist);
      } catch {
        // ignore — fresh session
      }
    }
  }, []);

  const sendMessage = useCallback(async () => {
    const text = input.trim();
    if (!text || isLoading) return;

    setInput("");
    setError(null);

    const userMsg: NeroChatMessage = {
      role: "user",
      text,
      ts: new Date().toISOString(),
    };
    setMessages((prev) => [...prev, userMsg]);
    setIsLoading(true);

    try {
      const { response } = await neroClient.chat(text);
      const neroMsg: NeroChatMessage = {
        role: "nero",
        text: response,
        ts: new Date().toISOString(),
      };
      setMessages((prev) => [...prev, neroMsg]);
    } catch (e) {
      setError(e instanceof Error ? e.message : "Unknown error");
    } finally {
      setIsLoading(false);
      inputRef.current?.focus();
    }
  }, [input, isLoading]);

  const handleKeyDown = useCallback(
    (e: React.KeyboardEvent) => {
      if (e.key === "Enter" && !e.shiftKey) {
        e.preventDefault();
        sendMessage();
      }
    },
    [sendMessage],
  );

  const clearChat = useCallback(async () => {
    try {
      await neroClient.chatClear();
      setMessages([]);
    } catch {
      // ignore
    }
  }, []);

  // ── Offline state ──
  if (neroStatus === "checking") {
    return (
      <div className="flex-1 flex items-center justify-center">
        <Loader2 className="w-6 h-6 animate-spin text-gray-400" />
        <span className="ml-2 text-gray-400">Nero に接続中...</span>
      </div>
    );
  }

  if (neroStatus === "offline") {
    return (
      <div className="flex-1 flex items-center justify-center">
        <div className="text-center space-y-4">
          <Shield className="w-12 h-12 mx-auto text-gray-500" />
          <h3 className="text-lg font-semibold text-gray-300">
            Nero サーバーに接続できません
          </h3>
          <p className="text-sm text-gray-500">
            ポート 8001 で Nero サーバーが起動しているか確認してください
          </p>
          <code className="block text-xs text-gray-600 bg-white/5 rounded px-3 py-2">
            cd Nero && run_server.bat
          </code>
          <button
            onClick={checkStatus}
            className="px-4 py-2 rounded-lg bg-blue-600 hover:bg-blue-500 text-sm transition-colors"
          >
            <RefreshCw className="w-4 h-4 inline mr-1" />
            再接続
          </button>
        </div>
      </div>
    );
  }

  // ── Online state ──
  return (
    <div className="flex flex-col h-full">
      {/* Header */}
      <div className="flex items-center justify-between px-2 sm:px-4 py-2 sm:py-3 border-b border-white/10">
        <div className="flex items-center gap-2">
          <Shield className="w-5 h-5 text-blue-400 shrink-0" />
          <span className="font-semibold text-sm sm:text-base">Nero</span>
          <span className="text-[10px] px-2 py-0.5 rounded-full border border-emerald-500/30 text-emerald-300 bg-emerald-900/20">
            online
          </span>
        </div>
        <button
          onClick={clearChat}
          className="p-1.5 rounded-lg hover:bg-white/5 text-gray-400 hover:text-gray-200 transition-colors"
          title="会話をクリア"
        >
          <Trash2 className="w-4 h-4" />
        </button>
      </div>

      {/* Messages */}
      <div ref={scrollRef} className="flex-1 overflow-y-auto px-2 sm:px-4 py-3 sm:py-4 space-y-3 sm:space-y-4 min-h-0">
        {messages.length === 0 && (
          <div className="text-center text-gray-500 mt-8">
            <Shield className="w-8 h-8 mx-auto mb-2 opacity-30" />
            <p className="text-sm">Nero と直接話せます</p>
            <p className="text-xs text-gray-600 mt-1">
              ニアの状態、ミーティングの相談、設計の議論など
            </p>
          </div>
        )}

        {messages.map((msg, i) => (
          <div
            key={i}
            className={`flex ${msg.role === "user" ? "justify-end" : "justify-start"}`}
          >
            <div
              className={`max-w-full sm:max-w-[80%] rounded-2xl px-3 sm:px-4 py-2 sm:py-2.5 text-xs sm:text-sm leading-relaxed ${
                msg.role === "user"
                  ? "bg-blue-600/30 border border-blue-500/20 text-blue-50"
                  : "bg-white/5 border border-white/10 text-gray-200"
              }`}
            >
              {msg.role === "nero" && (
                <div className="flex items-center gap-1.5 mb-1">
                  <Shield className="w-3 h-3 text-blue-400 shrink-0" />
                  <span className="text-[10px] text-blue-400 font-medium">
                    Nero
                  </span>
                </div>
              )}
              <div className="whitespace-pre-wrap break-words">{msg.text}</div>
            </div>
          </div>
        ))}

        {isLoading && (
          <div className="flex justify-start">
            <div className="bg-white/5 border border-white/10 rounded-2xl px-4 py-3">
              <div className="flex items-center gap-2 text-gray-400">
                <Loader2 className="w-4 h-4 animate-spin" />
                <span className="text-sm">考え中...</span>
              </div>
            </div>
          </div>
        )}

        {error && (
          <div className="text-center">
            <span className="text-xs text-red-400 bg-red-900/20 border border-red-500/20 rounded-lg px-3 py-1">
              {error}
            </span>
          </div>
        )}
      </div>

      {/* Input */}
      <div className="px-2 sm:px-4 py-2 sm:py-3 border-t border-white/10">
        <div className="flex gap-2">
          <textarea
            ref={inputRef}
            value={input}
            onChange={(e) => setInput(e.target.value)}
            onKeyDown={handleKeyDown}
            placeholder="Nero に話しかける..."
            rows={1}
            className="flex-1 min-w-0 bg-white/5 border border-white/10 rounded-xl px-3 sm:px-4 py-2 sm:py-2.5 text-sm resize-none focus:outline-none focus:ring-2 focus:ring-blue-500/50 placeholder-gray-500"
          />
          <button
            onClick={sendMessage}
            disabled={!input.trim() || isLoading}
            className="px-3 sm:px-4 py-2 sm:py-2.5 bg-blue-600 hover:bg-blue-500 disabled:opacity-30 disabled:hover:bg-blue-600 rounded-xl transition-colors shrink-0"
          >
            <Send className="w-4 h-4" />
          </button>
        </div>
      </div>
    </div>
  );
}
