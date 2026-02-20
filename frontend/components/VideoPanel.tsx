"use client";
import React, { useState, useRef, useCallback } from "react";
import {
  Video,
  Upload,
  Play,
  BookOpen,
  MessageCircle,
  Loader2,
  X,
  CheckCircle,
  AlertCircle,
  Link,
  FileVideo,
} from "lucide-react";
import { apiClient } from "@/lib/apiClient";

type Mode = "react" | "learn";
type Source = "file" | "url";

interface AnalyzeResult {
  mode: string;
  title?: string;
  duration?: number;
  scenes?: string[];
  frame_count?: number;
  strategies?: string[];
  memory_ids?: string[];
  success?: boolean;
}

export default function VideoPanel() {
  const [source, setSource] = useState<Source>("url");
  const [file, setFile] = useState<File | null>(null);
  const [url, setUrl] = useState("");
  const [mode, setMode] = useState<Mode>("react");
  const [loading, setLoading] = useState(false);
  const [result, setResult] = useState<AnalyzeResult | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [dragOver, setDragOver] = useState(false);
  const inputRef = useRef<HTMLInputElement>(null);

  const handleFile = useCallback((f: File) => {
    const ext = f.name.split(".").pop()?.toLowerCase();
    if (!ext || !["mp4", "webm", "mkv", "avi", "mov"].includes(ext)) {
      setError(`非対応の形式: .${ext}`);
      return;
    }
    if (f.size > 200 * 1024 * 1024) {
      setError("ファイルサイズが大きすぎます（上限200MB）");
      return;
    }
    setFile(f);
    setError(null);
    setResult(null);
  }, []);

  const onDrop = useCallback(
    (e: React.DragEvent) => {
      e.preventDefault();
      setDragOver(false);
      const f = e.dataTransfer.files[0];
      if (f) handleFile(f);
    },
    [handleFile],
  );

  const canAnalyze =
    source === "file" ? !!file : url.trim().length > 0;

  const analyze = async () => {
    if (!canAnalyze) return;
    setLoading(true);
    setError(null);
    setResult(null);
    try {
      let res: AnalyzeResult;
      if (source === "url") {
        res = await apiClient.analyzeVideoUrl(url.trim(), mode);
      } else {
        res = await apiClient.analyzeVideo(file!, mode);
      }
      setResult(res);
    } catch (e: any) {
      setError(e?.message || "解析に失敗しました");
    } finally {
      setLoading(false);
    }
  };

  const clear = () => {
    setFile(null);
    setUrl("");
    setResult(null);
    setError(null);
  };

  return (
    <div className="flex flex-col h-full p-4 gap-4 overflow-y-auto">
      {/* Header */}
      <div className="flex items-center gap-3">
        <Video className="w-6 h-6 text-purple-400" />
        <h2 className="text-lg font-bold">動画解析</h2>
      </div>

      {/* Mode Toggle */}
      <div className="flex gap-2">
        <button
          onClick={() => setMode("react")}
          className={`flex items-center gap-2 px-4 py-2 rounded-lg text-sm transition ${
            mode === "react"
              ? "bg-purple-600/20 text-purple-300 border border-purple-500/30"
              : "bg-white/5 text-gray-400 hover:bg-white/10"
          }`}
        >
          <MessageCircle className="w-4 h-4" />
          リアクション
        </button>
        <button
          onClick={() => setMode("learn")}
          className={`flex items-center gap-2 px-4 py-2 rounded-lg text-sm transition ${
            mode === "learn"
              ? "bg-blue-600/20 text-blue-300 border border-blue-500/30"
              : "bg-white/5 text-gray-400 hover:bg-white/10"
          }`}
        >
          <BookOpen className="w-4 h-4" />
          学習
        </button>
      </div>

      <p className="text-xs text-gray-500">
        {mode === "react"
          ? "動画を見てニアが感想を返します"
          : "ゲームプレイ動画から戦略を抽出し、記憶に保存します"}
      </p>

      {/* Source Toggle: URL / File */}
      <div className="flex gap-2">
        <button
          onClick={() => { setSource("url"); setError(null); }}
          className={`flex items-center gap-2 px-3 py-1.5 rounded-lg text-xs transition ${
            source === "url"
              ? "bg-white/10 text-white border border-white/20"
              : "text-gray-500 hover:text-gray-300"
          }`}
        >
          <Link className="w-3.5 h-3.5" />
          URL (YouTube等)
        </button>
        <button
          onClick={() => { setSource("file"); setError(null); }}
          className={`flex items-center gap-2 px-3 py-1.5 rounded-lg text-xs transition ${
            source === "file"
              ? "bg-white/10 text-white border border-white/20"
              : "text-gray-500 hover:text-gray-300"
          }`}
        >
          <FileVideo className="w-3.5 h-3.5" />
          ファイル
        </button>
      </div>

      {/* URL Input */}
      {source === "url" && (
        <div className="space-y-2">
          <div className="flex gap-2">
            <input
              type="text"
              value={url}
              onChange={(e) => { setUrl(e.target.value); setError(null); setResult(null); }}
              onKeyDown={(e) => e.key === "Enter" && canAnalyze && !loading && analyze()}
              placeholder="https://www.youtube.com/watch?v=..."
              className="flex-1 bg-white/5 border border-white/10 rounded-lg px-3 py-2.5 text-sm outline-none focus:border-purple-500/50 placeholder:text-gray-600"
            />
            {url && (
              <button
                onClick={() => { setUrl(""); setResult(null); }}
                className="px-2 text-gray-500 hover:text-red-400 transition"
              >
                <X className="w-4 h-4" />
              </button>
            )}
          </div>
          <p className="text-xs text-gray-600">
            YouTube, ニコニコ動画等に対応（最大10分）
          </p>
        </div>
      )}

      {/* File Drop Zone */}
      {source === "file" && (
        <div
          onDragOver={(e) => {
            e.preventDefault();
            setDragOver(true);
          }}
          onDragLeave={() => setDragOver(false)}
          onDrop={onDrop}
          onClick={() => inputRef.current?.click()}
          className={`border-2 border-dashed rounded-xl p-8 flex flex-col items-center gap-3 cursor-pointer transition ${
            dragOver
              ? "border-purple-400 bg-purple-500/10"
              : file
              ? "border-green-500/30 bg-green-500/5"
              : "border-white/10 hover:border-white/20 hover:bg-white/5"
          }`}
        >
          <input
            ref={inputRef}
            type="file"
            accept=".mp4,.webm,.mkv,.avi,.mov"
            className="hidden"
            onChange={(e) => {
              const f = e.target.files?.[0];
              if (f) handleFile(f);
            }}
          />
          {file ? (
            <>
              <CheckCircle className="w-8 h-8 text-green-400" />
              <div className="text-sm text-green-300">{file.name}</div>
              <div className="text-xs text-gray-500">
                {(file.size / 1024 / 1024).toFixed(1)} MB
              </div>
              <button
                onClick={(e) => {
                  e.stopPropagation();
                  clear();
                }}
                className="text-xs text-gray-500 hover:text-red-400 transition flex items-center gap-1"
              >
                <X className="w-3 h-3" /> 取り消し
              </button>
            </>
          ) : (
            <>
              <Upload className="w-8 h-8 text-gray-500" />
              <div className="text-sm text-gray-400">
                ここにドラッグ&ドロップ、またはクリックして選択
              </div>
              <div className="text-xs text-gray-600">
                MP4, WebM, MKV, AVI, MOV（最大200MB）
              </div>
            </>
          )}
        </div>
      )}

      {/* Analyze Button */}
      <button
        onClick={analyze}
        disabled={!canAnalyze || loading}
        className={`flex items-center justify-center gap-2 px-4 py-3 rounded-xl text-sm font-medium transition ${
          !canAnalyze || loading
            ? "bg-white/5 text-gray-600 cursor-not-allowed"
            : "bg-purple-600/20 text-purple-300 hover:bg-purple-600/30 border border-purple-500/20"
        }`}
      >
        {loading ? (
          <>
            <Loader2 className="w-5 h-5 animate-spin" />
            {source === "url"
              ? "ダウンロード＋解析中..."
              : "解析中...（フレーム抽出＋Vision処理）"}
          </>
        ) : (
          <>
            <Play className="w-5 h-5" />
            {mode === "react" ? "リアクションを生成" : "戦略を抽出"}
          </>
        )}
      </button>

      {/* Error */}
      {error && (
        <div className="flex items-center gap-2 p-3 bg-red-500/10 border border-red-500/20 rounded-xl text-sm text-red-300">
          <AlertCircle className="w-5 h-5 shrink-0" />
          {error}
        </div>
      )}

      {/* Results */}
      {result && (
        <div className="glass-panel rounded-xl p-4 space-y-3">
          <div className="flex items-center gap-2 text-sm font-medium">
            <CheckCircle className="w-5 h-5 text-green-400" />
            解析完了
            {result.frame_count != null && (
              <span className="text-xs text-gray-500 ml-auto">
                {result.frame_count} フレーム
              </span>
            )}
          </div>

          {/* Video title & duration (URL mode) */}
          {result.title && (
            <div className="text-xs text-gray-400">
              {result.title}
              {result.duration != null && result.duration > 0 && (
                <span className="ml-2 text-gray-500">
                  ({Math.floor(result.duration / 60)}:{String(result.duration % 60).padStart(2, "0")})
                </span>
              )}
            </div>
          )}

          {/* Scenes (react mode) */}
          {result.scenes && result.scenes.length > 0 && (
            <div className="space-y-2">
              <div className="text-xs text-gray-400 font-medium">
                {mode === "react" ? "場面の説明" : "検出された場面"}
              </div>
              {result.scenes.map((scene, i) => (
                <div
                  key={i}
                  className="text-sm bg-white/5 rounded-lg p-3 text-gray-300"
                >
                  <span className="text-xs text-purple-400 mr-2">#{i + 1}</span>
                  {scene}
                </div>
              ))}
            </div>
          )}

          {/* Strategies (learn mode) */}
          {result.strategies && result.strategies.length > 0 && (
            <div className="space-y-2">
              <div className="text-xs text-gray-400 font-medium">
                抽出された戦略
              </div>
              {result.strategies.map((strategy, i) => (
                <div
                  key={i}
                  className="text-sm bg-blue-500/5 border border-blue-500/10 rounded-lg p-3 text-blue-200"
                >
                  {strategy}
                </div>
              ))}
              {result.memory_ids && result.memory_ids.length > 0 && (
                <div className="text-xs text-green-400">
                  {result.memory_ids.length} 件の記憶に保存しました
                </div>
              )}
            </div>
          )}
        </div>
      )}
    </div>
  );
}
