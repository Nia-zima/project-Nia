"use client";
import React, { useState, useEffect, useRef, useCallback } from "react";
import {
  neroClient,
  type NeroMeetingSession,
  type NeroMeetingDetail,
  type NeroMeetingTurn,
} from "@/lib/neroClient";
import {
  Shield,
  Play,
  Loader2,
  RefreshCw,
  ArrowLeft,
  Clock,
  MessageSquare,
  Eye,
  Users,
} from "lucide-react";

type View = "list" | "live" | "detail";

interface LiveTurn {
  nero: string;
  nia: string | null;
  verdict: string;
}

export default function NeroMeetingsPanel() {
  const [view, setView] = useState<View>("list");
  const [sessions, setSessions] = useState<NeroMeetingSession[]>([]);
  const [loading, setLoading] = useState(true);
  const [neroAvailable, setNeroAvailable] = useState<boolean | null>(null);

  // Start meeting
  const [topicInput, setTopicInput] = useState("");
  const [starting, setStarting] = useState(false);

  // Live meeting
  const [liveSessionId, setLiveSessionId] = useState<string | null>(null);
  const [liveTopic, setLiveTopic] = useState("");
  const [liveTurns, setLiveTurns] = useState<LiveTurn[]>([]);
  const [liveStatus, setLiveStatus] = useState<string>("running");
  const liveScrollRef = useRef<HTMLDivElement>(null);
  const esRef = useRef<EventSource | null>(null);

  // Detail view
  const [detailData, setDetailData] = useState<NeroMeetingDetail | null>(null);
  const [detailLoading, setDetailLoading] = useState(false);

  // Error state
  const [startError, setStartError] = useState<string | null>(null);

  useEffect(() => {
    checkAndLoad();
    return () => {
      esRef.current?.close();
    };
  }, []);

  useEffect(() => {
    if (liveScrollRef.current) {
      liveScrollRef.current.scrollTop = liveScrollRef.current.scrollHeight;
    }
  }, [liveTurns]);

  const checkAndLoad = useCallback(async () => {
    setLoading(true);
    neroClient.resetAvailability();
    const available = await neroClient.isAvailable();
    setNeroAvailable(available);
    if (available) {
      try {
        const list = await neroClient.listSessions();
        setSessions(list);
      } catch {
        // ignore
      }
    }
    setLoading(false);
  }, []);

  const startMeeting = useCallback(async () => {
    setStarting(true);
    setStartError(null);
    try {
      const result = await neroClient.startMeeting(
        topicInput.trim() || undefined,
      );
      setLiveSessionId(result.session_id);
      setLiveTopic(result.topic);
      setLiveTurns([]);
      setLiveStatus("running");
      setTopicInput("");
      setView("live");

      // Close previous EventSource if any
      esRef.current?.close();

      // Connect SSE
      const es = neroClient.meetingStream(result.session_id);
      esRef.current = es;

      es.onmessage = (ev) => {
        try {
          const event = JSON.parse(ev.data);
          if (event.type === "turn") {
            const t = event.data;
            setLiveTurns((prev) => [
              ...prev,
              {
                nero: t.nero || t.nero_text || "",
                nia: t.nia || t.nia_text || null,
                verdict: t.verdict || "",
              },
            ]);
          } else if (event.type === "done") {
            setLiveStatus("completed");
            es.close();
            // Refresh sessions list
            neroClient.listSessions().then(setSessions).catch(() => {});
          } else if (event.type === "error") {
            setLiveStatus("failed");
            es.close();
          }
        } catch {
          // ignore parse errors
        }
      };

      es.onerror = () => {
        setLiveStatus("disconnected");
        es.close();
      };
    } catch (e) {
      console.error("Failed to start meeting:", e);
      setStartError(
        e instanceof Error ? e.message : "ミーティングの開始に失敗しました",
      );
    } finally {
      setStarting(false);
    }
  }, [topicInput]);

  const viewDetail = useCallback(async (filename: string) => {
    setDetailLoading(true);
    setView("detail");
    try {
      const data = await neroClient.getSession(filename);
      setDetailData(data);
    } catch (e) {
      console.error("Failed to load session:", e);
      setDetailData(null);
    } finally {
      setDetailLoading(false);
    }
  }, []);

  const goBackToList = useCallback(() => {
    if (liveStatus === "running" && view === "live") {
      if (!window.confirm("ミーティング進行中です。一覧に戻りますか？")) return;
    }
    esRef.current?.close();
    setView("list");
    setDetailData(null);
    setLiveSessionId(null);
    setStartError(null);
    checkAndLoad();
  }, [checkAndLoad, liveStatus, view]);

  // ── Unavailable state ──
  if (neroAvailable === false) {
    return (
      <div className="flex-1 flex items-center justify-center p-4">
        <div className="text-center space-y-3">
          <Shield className="w-10 h-10 mx-auto text-gray-500" />
          <p className="text-gray-400">Nero サーバーに接続できません</p>
          <button
            onClick={checkAndLoad}
            className="px-3 py-1.5 rounded-lg bg-blue-600 hover:bg-blue-500 text-sm"
          >
            <RefreshCw className="w-3 h-3 inline mr-1" />
            再接続
          </button>
        </div>
      </div>
    );
  }

  // ── Loading ──
  if (loading || neroAvailable === null) {
    return (
      <div className="flex-1 flex items-center justify-center">
        <Loader2 className="w-6 h-6 animate-spin text-gray-400" />
      </div>
    );
  }

  // ── Detail view ──
  if (view === "detail") {
    return (
      <div className="flex flex-col h-full">
        <div className="flex items-center gap-2 px-2 sm:px-4 py-2 sm:py-3 border-b border-white/10">
          <button
            onClick={goBackToList}
            className="p-1.5 rounded-lg hover:bg-white/5 text-gray-400 shrink-0"
            title="一覧に戻る"
          >
            <ArrowLeft className="w-4 h-4" />
          </button>
          <span className="font-semibold text-xs sm:text-sm truncate">
            {detailData?.topic || "Loading..."}
          </span>
        </div>
        <div className="flex-1 overflow-y-auto px-2 sm:px-4 py-3 sm:py-4 space-y-3 min-h-0">
          {detailLoading ? (
            <div className="flex justify-center py-8">
              <Loader2 className="w-5 h-5 animate-spin text-gray-400" />
            </div>
          ) : detailData ? (
            <>
              {detailData.turns.map((turn, i) => (
                <MeetingTurnCard key={i} turn={turn} index={i} />
              ))}
              {detailData.discoveries.length > 0 && (
                <div className="mt-3 sm:mt-4 p-2 sm:p-3 rounded-xl bg-amber-900/10 border border-amber-500/20">
                  <h4 className="text-[10px] sm:text-xs font-semibold text-amber-300 mb-1.5 sm:mb-2">
                    Discoveries
                  </h4>
                  {detailData.discoveries.map((d, i) => (
                    <p key={i} className="text-[10px] sm:text-xs text-gray-300 mb-1 break-words">
                      <span className="text-amber-400">[{d.category}]</span>{" "}
                      {d.discovery}
                    </p>
                  ))}
                </div>
              )}
            </>
          ) : (
            <p className="text-gray-500 text-center">
              データの読み込みに失敗しました
            </p>
          )}
        </div>
      </div>
    );
  }

  // ── Live view ──
  if (view === "live") {
    return (
      <div className="flex flex-col h-full">
        <div className="flex items-center gap-1.5 sm:gap-2 px-2 sm:px-4 py-2 sm:py-3 border-b border-white/10">
          <button
            onClick={goBackToList}
            className="p-1 sm:p-1.5 rounded-lg hover:bg-white/5 text-gray-400 shrink-0"
            title="一覧に戻る"
          >
            <ArrowLeft className="w-4 h-4" />
          </button>
          <Users className="w-4 h-4 text-blue-400 shrink-0 hidden sm:block" />
          <span className="font-semibold text-xs sm:text-sm truncate min-w-0">{liveTopic}</span>
          <span
            className={`ml-auto text-[10px] px-1.5 sm:px-2 py-0.5 rounded-full border shrink-0 ${
              liveStatus === "running"
                ? "border-emerald-500/30 text-emerald-300 bg-emerald-900/20"
                : liveStatus === "completed"
                  ? "border-blue-500/30 text-blue-300 bg-blue-900/20"
                  : "border-red-500/30 text-red-300 bg-red-900/20"
            }`}
          >
            {liveStatus === "running"
              ? `Turn ${liveTurns.length}`
              : liveStatus}
          </span>
        </div>

        <div
          ref={liveScrollRef}
          className="flex-1 overflow-y-auto px-2 sm:px-4 py-3 sm:py-4 space-y-3 min-h-0"
        >
          {liveTurns.length === 0 && liveStatus === "running" && (
            <div className="flex justify-center py-8">
              <Loader2 className="w-5 h-5 animate-spin text-gray-400" />
              <span className="ml-2 text-sm text-gray-400">
                ミーティング開始中...
              </span>
            </div>
          )}

          {liveTurns.map((turn, i) => (
            <MeetingTurnCard
              key={i}
              turn={turn}
              index={i}
            />
          ))}

          {liveStatus === "completed" && (
            <div className="text-center py-4">
              <span className="text-xs text-blue-400 bg-blue-900/20 border border-blue-500/20 rounded-lg px-3 py-1">
                ミーティング完了
              </span>
            </div>
          )}
        </div>
      </div>
    );
  }

  // ── List view (default) ──
  return (
    <div className="flex flex-col h-full">
      {/* Header */}
      <div className="flex items-center justify-between px-2 sm:px-4 py-2 sm:py-3 border-b border-white/10">
        <div className="flex items-center gap-2">
          <Users className="w-5 h-5 text-blue-400 shrink-0" />
          <span className="font-semibold text-sm sm:text-base">ミーティング</span>
        </div>
        <button
          onClick={checkAndLoad}
          className="p-1.5 rounded-lg hover:bg-white/5 text-gray-400"
          title="更新"
        >
          <RefreshCw className="w-4 h-4" />
        </button>
      </div>

      {/* Start meeting error */}
      {startError && (
        <div className="px-2 sm:px-4 pt-2">
          <span className="text-xs text-red-400 bg-red-900/20 border border-red-500/20 rounded-lg px-3 py-1">
            {startError}
          </span>
        </div>
      )}

      {/* Start meeting */}
      <div className="px-2 sm:px-4 py-2 sm:py-3 border-b border-white/10">
        <div className="flex gap-2">
          <input
            type="text"
            value={topicInput}
            onChange={(e) => setTopicInput(e.target.value)}
            onKeyDown={(e) => {
              if (e.key === "Enter" && !starting) startMeeting();
            }}
            placeholder="トピック（空欄で自動生成）"
            className="flex-1 min-w-0 bg-white/5 border border-white/10 rounded-lg px-2 sm:px-3 py-2 text-sm focus:outline-none focus:ring-2 focus:ring-blue-500/50 placeholder-gray-500"
          />
          <button
            onClick={startMeeting}
            disabled={starting}
            className="px-3 sm:px-4 py-2 bg-blue-600 hover:bg-blue-500 disabled:opacity-30 rounded-lg text-sm transition-colors flex items-center gap-1 sm:gap-1.5 shrink-0"
          >
            {starting ? (
              <Loader2 className="w-4 h-4 animate-spin" />
            ) : (
              <Play className="w-4 h-4" />
            )}
            <span className="hidden sm:inline">開始</span>
          </button>
        </div>
      </div>

      {/* Sessions list */}
      <div className="flex-1 overflow-y-auto px-2 sm:px-4 py-2 sm:py-3 space-y-2 min-h-0">
        {sessions.length === 0 ? (
          <div className="text-center text-gray-500 mt-8">
            <Users className="w-8 h-8 mx-auto mb-2 opacity-30" />
            <p className="text-sm">ミーティング履歴はまだありません</p>
          </div>
        ) : (
          sessions.map((session) => (
            <button
              key={session.filename}
              onClick={() => viewDetail(session.filename)}
              className="w-full text-left p-2 sm:p-3 rounded-xl bg-white/5 border border-white/10 hover:bg-white/10 transition-colors"
            >
              <div className="flex items-start justify-between gap-1.5 sm:gap-2">
                <div className="flex-1 min-w-0">
                  <p className="text-xs sm:text-sm font-medium text-gray-200 truncate">
                    {session.topic || "(no topic)"}
                  </p>
                  <div className="flex items-center gap-2 sm:gap-3 mt-1 text-[10px] sm:text-xs text-gray-500">
                    <span className="flex items-center gap-1">
                      <MessageSquare className="w-3 h-3" />
                      {session.turn_count}t
                    </span>
                    {session.saved_at && (
                      <span className="flex items-center gap-1">
                        <Clock className="w-3 h-3" />
                        {session.saved_at.slice(5, 10)}
                      </span>
                    )}
                  </div>
                </div>
                {session.final_verdict && (
                  <VerdictBadge verdict={session.final_verdict} />
                )}
                <Eye className="w-4 h-4 text-gray-500 mt-0.5 shrink-0 hidden sm:block" />
              </div>
            </button>
          ))
        )}
      </div>
    </div>
  );
}

// ── Sub-components ──

function VerdictBadge({ verdict }: { verdict: string }) {
  const colors: Record<string, string> = {
    ANSWER: "border-emerald-500/30 text-emerald-300 bg-emerald-900/20",
    MIRRORING: "border-amber-500/30 text-amber-300 bg-amber-900/20",
    ASK: "border-blue-500/30 text-blue-300 bg-blue-900/20",
    WAIT: "border-gray-500/30 text-gray-300 bg-gray-900/20",
    CLOSE: "border-purple-500/30 text-purple-300 bg-purple-900/20",
  };
  return (
    <span
      className={`text-[10px] px-2 py-0.5 rounded-full border shrink-0 ${colors[verdict] || colors.WAIT}`}
    >
      {verdict}
    </span>
  );
}

function MeetingTurnCard({
  turn,
  index,
}: {
  turn: { nero: string; nia: string | null; verdict: string };
  index: number;
}) {
  return (
    <div className="space-y-2">
      {/* Nero's message */}
      <div className="flex justify-start">
        <div className="max-w-full sm:max-w-[85%] rounded-2xl px-3 sm:px-4 py-2 sm:py-2.5 bg-blue-900/20 border border-blue-500/10">
          <div className="flex items-center gap-1.5 mb-1">
            <Shield className="w-3 h-3 text-blue-400 shrink-0" />
            <span className="text-[10px] text-blue-400 font-medium">
              Nero #{index + 1}
            </span>
            <VerdictBadge verdict={turn.verdict} />
          </div>
          <p className="text-xs sm:text-sm text-gray-200 whitespace-pre-wrap break-words">
            {turn.nero}
          </p>
        </div>
      </div>

      {/* Nia's response */}
      {turn.nia && (
        <div className="flex justify-end">
          <div className="max-w-full sm:max-w-[85%] rounded-2xl px-3 sm:px-4 py-2 sm:py-2.5 bg-white/5 border border-white/10">
            <div className="flex items-center gap-1.5 mb-1">
              <span className="text-[10px] text-gray-400 font-medium">
                Nia
              </span>
            </div>
            <p className="text-xs sm:text-sm text-gray-300 whitespace-pre-wrap break-words">
              {turn.nia}
            </p>
          </div>
        </div>
      )}
    </div>
  );
}
