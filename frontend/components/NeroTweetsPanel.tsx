"use client";
import React, { useState, useEffect, useCallback } from "react";
import { neroClient, type NeroTweetLog } from "@/lib/neroClient";
import { Shield, RefreshCw, Loader2, Twitter, CheckCircle2, XCircle } from "lucide-react";

const TRIGGER_COLORS: Record<string, string> = {
  sleep_cycle: "border-purple-500/30 text-purple-300 bg-purple-900/20",
  post_meeting: "border-blue-500/30 text-blue-300 bg-blue-900/20",
  manual: "border-gray-500/30 text-gray-300 bg-gray-900/20",
  cli: "border-gray-500/30 text-gray-300 bg-gray-900/20",
};

function TriggerBadge({ trigger }: { trigger: string }) {
  const cls = TRIGGER_COLORS[trigger] || TRIGGER_COLORS.manual;
  const label: Record<string, string> = {
    sleep_cycle: "Sleep",
    post_meeting: "Meeting",
    manual: "Manual",
    cli: "CLI",
  };
  return (
    <span className={`text-[10px] px-2 py-0.5 rounded-full border ${cls}`}>
      {label[trigger] || trigger}
    </span>
  );
}

function formatDate(iso: string): string {
  try {
    const d = new Date(iso);
    return d.toLocaleString("ja-JP", {
      month: "numeric",
      day: "numeric",
      hour: "2-digit",
      minute: "2-digit",
    });
  } catch {
    return iso;
  }
}

export default function NeroTweetsPanel() {
  const [tweets, setTweets] = useState<NeroTweetLog[]>([]);
  const [isLoading, setIsLoading] = useState(true);
  const [neroStatus, setNeroStatus] = useState<"checking" | "online" | "offline">("checking");

  const checkStatus = useCallback(async () => {
    setNeroStatus("checking");
    neroClient.resetAvailability();
    const available = await neroClient.isAvailable();
    setNeroStatus(available ? "online" : "offline");
    if (available) {
      await loadTweets();
    }
  }, []);

  const loadTweets = useCallback(async () => {
    setIsLoading(true);
    try {
      const data = await neroClient.listTweets(50);
      setTweets(data);
    } catch {
      // ignore
    } finally {
      setIsLoading(false);
    }
  }, []);

  useEffect(() => {
    checkStatus();
  }, [checkStatus]);

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

  return (
    <div className="flex flex-col h-full">
      {/* Header */}
      <div className="flex items-center justify-between px-2 sm:px-4 py-2 sm:py-3 border-b border-white/10">
        <div className="flex items-center gap-2">
          <Twitter className="w-5 h-5 text-blue-400 shrink-0" />
          <span className="font-semibold text-sm sm:text-base">ツイート履歴</span>
          <span className="text-[10px] text-gray-500">{tweets.length}件</span>
        </div>
        <button
          onClick={loadTweets}
          disabled={isLoading}
          className="p-1.5 rounded-lg hover:bg-white/5 text-gray-400 hover:text-gray-200 transition-colors disabled:opacity-30"
          title="更新"
        >
          <RefreshCw className={`w-4 h-4 ${isLoading ? "animate-spin" : ""}`} />
        </button>
      </div>

      {/* Tweet list */}
      <div className="flex-1 overflow-y-auto px-2 sm:px-4 py-3 sm:py-4 space-y-2 sm:space-y-3 min-h-0">
        {tweets.length === 0 && !isLoading && (
          <div className="text-center text-gray-500 mt-8">
            <Twitter className="w-8 h-8 mx-auto mb-2 opacity-30" />
            <p className="text-sm">まだツイートはありません</p>
          </div>
        )}

        {tweets.map((tweet, i) => {
          const isSuccess = !!tweet.tweet_id;
          return (
            <div
              key={`${tweet.posted_at}-${i}`}
              className="rounded-xl border border-white/10 bg-white/[0.03] p-3 sm:p-4 space-y-2"
            >
              {/* Meta row */}
              <div className="flex items-center gap-2 flex-wrap">
                {isSuccess ? (
                  <CheckCircle2 className="w-3.5 h-3.5 text-emerald-400 shrink-0" />
                ) : (
                  <XCircle className="w-3.5 h-3.5 text-red-400 shrink-0" />
                )}
                <TriggerBadge trigger={tweet.trigger} />
                <span className="text-[10px] text-gray-500 ml-auto">
                  {formatDate(tweet.posted_at)}
                </span>
              </div>

              {/* Tweet text */}
              <p className="text-xs sm:text-sm text-gray-200 whitespace-pre-wrap break-words leading-relaxed">
                {tweet.tweet_text}
              </p>

              {/* Footer */}
              <div className="flex items-center gap-2 text-[10px] text-gray-500">
                <span>{tweet.char_count}文字</span>
                <span className="opacity-30">|</span>
                <span>{tweet.style}</span>
                {tweet.tweet_id && (
                  <>
                    <span className="opacity-30">|</span>
                    <span className="font-mono">id:{tweet.tweet_id}</span>
                  </>
                )}
              </div>
            </div>
          );
        })}
      </div>
    </div>
  );
}
