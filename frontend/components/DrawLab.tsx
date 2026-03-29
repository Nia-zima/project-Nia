"use client";

import React, { useCallback, useEffect, useRef, useState } from "react";
import { apiClient } from "@/lib/apiClient";

type DrawCommand =
  | { cmd: "fill"; color: string }
  | { cmd: "line"; x1: number; y1: number; x2: number; y2: number; brush: number; color: string };

type SessionState = {
  active: boolean;
  session_id?: string | null;
  planned_count?: number;
  sent_count?: number;
  rejected_count?: number;
  stop_reason?: string | null;
  max_strokes?: number;
};

const CANVAS_W = 800;
const CANVAS_H = 500;

export default function DrawLab() {
  const canvasRef = useRef<HTMLCanvasElement>(null);
  const observeTimerRef = useRef<number | null>(null);
  const pollTimerRef = useRef<number | null>(null);
  const sessionIdRef = useRef<string | null>(null);
  const sinceSeqRef = useRef(0);
  const [prompt, setPrompt] = useState("抽象的で静かな夜の線画");
  const [sessionId, setSessionId] = useState<string | null>(null);
  const [running, setRunning] = useState(false);
  const [sinceSeq, setSinceSeq] = useState(0);
  const [status, setStatus] = useState<SessionState>({ active: false });
  const [error, setError] = useState<string | null>(null);

  const getCtx = useCallback(() => {
    const canvas = canvasRef.current;
    if (!canvas) return null;
    const ctx = canvas.getContext("2d");
    return ctx;
  }, []);

  const clearCanvas = useCallback(() => {
    const ctx = getCtx();
    if (!ctx) return;
    ctx.fillStyle = "#0b1020";
    ctx.fillRect(0, 0, CANVAS_W, CANVAS_H);
  }, [getCtx]);

  useEffect(() => {
    clearCanvas();
  }, [clearCanvas]);

  const applyCommand = useCallback(
    (command: DrawCommand) => {
      const ctx = getCtx();
      if (!ctx) return;
      if (command.cmd === "fill") {
        ctx.fillStyle = command.color;
        ctx.fillRect(0, 0, CANVAS_W, CANVAS_H);
        return;
      }
      if (command.cmd === "line") {
        ctx.lineCap = "round";
        ctx.lineJoin = "round";
        ctx.strokeStyle = command.color;
        ctx.lineWidth = Math.max(1, Math.min(64, command.brush));
        ctx.beginPath();
        ctx.moveTo(command.x1, command.y1);
        ctx.lineTo(command.x2, command.y2);
        ctx.stroke();
      }
    },
    [getCtx]
  );

  const stopLoopTimers = useCallback(() => {
    if (observeTimerRef.current) {
      window.clearInterval(observeTimerRef.current);
      observeTimerRef.current = null;
    }
    if (pollTimerRef.current) {
      window.clearInterval(pollTimerRef.current);
      pollTimerRef.current = null;
    }
  }, []);

  const stopSession = useCallback(
    async (emergency = false) => {
      stopLoopTimers();
      setRunning(false);
      const sid = sessionIdRef.current;
      try {
        if (sid) await apiClient.drawSessionStop(sid, emergency);
      } catch (_e) {
        // noop
      }
      try {
        const st = await apiClient.drawSessionState();
        setStatus(st as SessionState);
      } catch { /* ignore */ }
    },
    [stopLoopTimers]
  );

  const postObservation = useCallback(async () => {
    const sid = sessionIdRef.current;
    if (!sid) return;
    const canvas = canvasRef.current;
    if (!canvas) return;
    try {
      const imageData = canvas.toDataURL("image/jpeg", 0.55);
      await apiClient.drawObserve(sid, imageData);
    } catch (_e) {
      // noop
    }
  }, []);

  const pollCommands = useCallback(async () => {
    const sid = sessionIdRef.current;
    if (!sid) return;
    try {
      const payload = await apiClient.drawCommands(sid, sinceSeqRef.current, 100) as Record<string, any>;
      const items = Array.isArray(payload.items) ? payload.items : [];
      for (const item of items) {
        applyCommand((item?.command || {}) as DrawCommand);
      }
      if (typeof payload.next_seq === "number") {
        sinceSeqRef.current = payload.next_seq;
        setSinceSeq(payload.next_seq);
      }
      setStatus((prev) => ({
        ...prev,
        active: Boolean(payload.active),
        stop_reason: payload.stop_reason || null,
        planned_count: payload.planned_count as number | undefined,
        sent_count: payload.sent_count as number | undefined,
        rejected_count: payload.rejected_count as number | undefined,
      }));
      if (payload.active === false) {
        stopLoopTimers();
        setRunning(false);
      }
    } catch (_e) {
      // noop
    }
  }, [applyCommand, stopLoopTimers]);

  const startSession = useCallback(async () => {
    setError(null);
    stopLoopTimers();
    setSinceSeq(0);
    clearCanvas();
    try {
      const state = (await apiClient.drawSessionStart({
        prompt,
        width: CANVAS_W,
        height: CANVAS_H,
        interval_sec: 1.2,
        max_strokes: 48,
        timeout_sec: 180,
      })) as SessionState;
      const sid = state.session_id ? String(state.session_id) : null;
      if (!sid) throw new Error("session_id missing");
      sessionIdRef.current = sid;
      sinceSeqRef.current = 0;
      setSessionId(sid);
      setStatus(state);
      setRunning(Boolean(state.active));

      observeTimerRef.current = window.setInterval(() => {
        void postObservation();
      }, 1200);
      pollTimerRef.current = window.setInterval(() => {
        void pollCommands();
      }, 350);
    } catch (e: any) {
      setError(e?.message || "start failed");
      setRunning(false);
    }
  }, [clearCanvas, pollCommands, postObservation, prompt, stopLoopTimers]);

  useEffect(() => {
    const onKeyDown = (e: KeyboardEvent) => {
      if (e.key === "Escape" && running) {
        e.preventDefault();
        void stopSession(true);
      }
    };
    window.addEventListener("keydown", onKeyDown);
    return () => window.removeEventListener("keydown", onKeyDown);
  }, [running, stopSession]);

  useEffect(() => {
    return () => {
      stopLoopTimers();
    };
  }, [stopLoopTimers]);

  return (
    <div className="h-full w-full p-4 space-y-3">
      <div className="flex flex-wrap items-center gap-2">
        <input
          value={prompt}
          onChange={(e) => setPrompt(e.target.value)}
          placeholder="ニアに描いてほしい方向性"
          className="min-w-[260px] flex-1 rounded-lg border border-white/10 bg-black/30 px-3 py-2 text-sm text-gray-100 placeholder:text-gray-500"
        />
        <button
          onClick={() => void startSession()}
          className="rounded-lg border border-cyan-500/40 bg-cyan-500/20 px-3 py-2 text-xs text-cyan-100"
        >
          開始
        </button>
        <button
          onClick={() => void stopSession(false)}
          className="rounded-lg border border-amber-500/40 bg-amber-500/20 px-3 py-2 text-xs text-amber-100"
        >
          停止
        </button>
        <button
          onClick={clearCanvas}
          className="rounded-lg border border-white/10 bg-white/5 px-3 py-2 text-xs text-gray-200"
        >
          キャンバス初期化
        </button>
      </div>

      <div className="text-xs text-gray-400 flex flex-wrap gap-4">
        <span>session: {sessionId || "-"}</span>
        <span>active: {running ? "yes" : "no"}</span>
        <span>planned/sent/rejected: {status.planned_count || 0}/{status.sent_count || 0}/{status.rejected_count || 0}</span>
        <span>max_strokes: {status.max_strokes || 0}</span>
        <span>stop_reason: {status.stop_reason || "-"}</span>
        <span className="text-rose-300">Escで緊急停止</span>
      </div>
      {error && <div className="text-xs text-rose-300">{error}</div>}

      <div className="rounded-xl border border-white/10 bg-black/20 p-2">
        <canvas
          ref={canvasRef}
          width={CANVAS_W}
          height={CANVAS_H}
          className="w-full max-w-[960px] rounded-lg bg-[#0b1020]"
        />
      </div>

      <div className="text-xs text-gray-500">
        命令層: draw planner（backend）/ 安全実行: 別プロセス validator / 観測: 1.2秒ごと / 停止: Esc・上限・タイムアウト
      </div>
    </div>
  );
}
