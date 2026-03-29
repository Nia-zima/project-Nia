"use client";
import React, { useEffect, useState } from "react";
import { AlertTriangle, RefreshCw } from "lucide-react";
import { apiClient } from "@/lib/apiClient";

type LegacyPendingIssue = {
  id?: string;
  action_type?: string;
  status?: string;
  reason?: string;
  message_id?: string;
  created_at?: number;
  updated_at?: number;
};

interface ActionIssuesPanelProps {
  threadId?: string;
}

const statusLabel = (status?: string) => {
  switch ((status || "").toUpperCase()) {
    case "REJECTED":
      return "却下";
    case "ERROR":
      return "失敗";
    case "ARCHIVED":
      return "アーカイブ";
    default:
      return status || "不明";
  }
};

export default function ActionIssuesPanel({ threadId = "default_thread" }: ActionIssuesPanelProps) {
  const [items, setItems] = useState<LegacyPendingIssue[]>([]);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [pendingDeleteId, setPendingDeleteId] = useState<string | null>(null);
  const [showArchived, setShowArchived] = useState(false);

  const fetchIssues = async () => {
    setLoading(true);
    setError(null);
    try {
      const statusParam = showArchived ? "ERROR,REJECTED,ARCHIVED" : "ERROR,REJECTED";
      const data = await apiClient.fetchActionIssues(threadId, statusParam, 100);
      setItems(Array.isArray(data?.items) ? data.items as LegacyPendingIssue[] : []);
    } catch (e) {
      console.error(e);
      setError("失敗/却下の取得に失敗しました");
    } finally {
      setLoading(false);
    }
  };

  useEffect(() => {
    fetchIssues();
  }, [threadId, showArchived]);

  const deleteIssue = async (id?: string) => {
    if (!id) return;
    const ok = window.confirm("この失敗/却下アクションを削除しますか？");
    if (!ok) return;
    setPendingDeleteId(id);
    try {
      await apiClient.archiveAction(id);
      setItems((prev) => prev.filter((item) => item.id !== id));
    } catch (e) {
      console.error(e);
      setError("削除に失敗しました");
    } finally {
      setPendingDeleteId(null);
    }
  };

  return (
    <div className="h-full w-full p-4 md:p-6">
      <div className="flex items-center justify-between">
        <div className="flex items-center gap-2 text-sm font-semibold text-white/90">
          <AlertTriangle size={16} className="text-rose-300" />
          失敗/却下アクション
        </div>
        <div className="flex items-center gap-3">
          <label className="flex items-center gap-2 text-[11px] text-gray-300">
            <input
              type="checkbox"
              checked={showArchived}
              onChange={(e) => setShowArchived(e.target.checked)}
              className="h-3 w-3 accent-rose-400"
            />
            アーカイブも表示
          </label>
          <button
            onClick={fetchIssues}
            className="flex items-center gap-1 text-xs text-gray-300 hover:text-white"
            title="再読み込み"
          >
            <RefreshCw size={14} />
            更新
          </button>
        </div>
      </div>

      <div className="mt-1 text-[11px] text-gray-400">件数: {items.length}</div>
      {error && <div className="mt-2 text-xs text-red-300">{error}</div>}

      <div className="mt-4 space-y-3">
        {items.map((item) => (
          <div key={item.id} className="rounded-xl border border-rose-500/30 bg-rose-900/20 p-3">
            <div className="flex items-center justify-between text-xs text-rose-100">
              <span className="flex items-center gap-1">
                <AlertTriangle size={12} />
                {statusLabel(item.status)}
              </span>
              <span className="text-rose-200/80">{item.action_type || item.id}</span>
            </div>
            <div className="mt-1 text-[11px] text-rose-100/90">理由: {item.reason || "理由なし"}</div>
            {item.created_at && (
              <div className="mt-1 text-[10px] text-rose-200/70">
                登録: {new Date(item.created_at * 1000).toLocaleString()}
              </div>
            )}
            <div className="mt-2">
              <button
                onClick={() => deleteIssue(item.id)}
                disabled={pendingDeleteId === item.id}
                className="rounded-md border border-rose-400/40 bg-rose-500/20 px-2 py-1 text-[10px] text-rose-100 hover:bg-rose-500/30 disabled:opacity-60"
              >
                削除
              </button>
            </div>
          </div>
        ))}
        {!loading && items.length === 0 && (
          <div className="text-xs text-gray-400">失敗・却下の履歴はありません。</div>
        )}
        {loading && (
          <div className="text-xs text-gray-400">読み込み中…</div>
        )}
      </div>
    </div>
  );
}
