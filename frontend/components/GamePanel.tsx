"use client";
import React, { useEffect, useState, useCallback, useRef } from "react";
import {
  Gamepad2,
  Heart,
  Drumstick,
  MapPin,
  Package,
  Users,
  Cloud,
  CloudRain,
  Sun,
  Moon,
  Sunrise,
  Sunset,
  Wifi,
  WifiOff,
  Send,
  ChevronDown,
  ChevronRight,
} from "lucide-react";
import { apiClient } from "@/lib/apiClient";
import type { GameStateData, GameEvent } from "@/lib/types";

export default function GamePanel() {
  const [state, setState] = useState<GameStateData | null>(null);
  const [events, setEvents] = useState<GameEvent[]>([]);
  const [loading, setLoading] = useState(true);
  const [chatMsg, setChatMsg] = useState("");
  const [invOpen, setInvOpen] = useState(false);
  const eventsEndRef = useRef<HTMLDivElement>(null);

  // Poll game state
  const fetchState = useCallback(async () => {
    try {
      const data = await apiClient.fetchGameState();
      setState(data as unknown as GameStateData);
    } catch {
      setState(null);
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => {
    fetchState();
    const interval = setInterval(fetchState, 2000);
    return () => clearInterval(interval);
  }, [fetchState]);

  // WebSocket for events
  useEffect(() => {
    let ws: WebSocket | null = null;
    let mounted = true;

    const connect = () => {
      // バックエンド直結（Next.js proxy は WS 非対応）
      const wsScheme = window.location.protocol === "https:" ? "wss" : "ws";
      const backendPort = process.env.NEXT_PUBLIC_BACKEND_PORT || "8000";
      const wsUrl = `${wsScheme}://${window.location.hostname}:${backendPort}/api/game/ws`;
      ws = new WebSocket(wsUrl);

      ws.onmessage = (ev) => {
        try {
          const event = JSON.parse(ev.data) as GameEvent;
          if (event.type === "ping") return;
          if (mounted) {
            setEvents((prev) => [...prev.slice(-49), event]);
          }
        } catch { /* ignore */ }
      };

      ws.onclose = () => {
        if (mounted) setTimeout(connect, 5000);
      };

      ws.onerror = () => ws?.close();
    };

    connect();
    return () => {
      mounted = false;
      ws?.close();
    };
  }, []);

  // Auto-scroll events
  useEffect(() => {
    eventsEndRef.current?.scrollIntoView({ behavior: "smooth" });
  }, [events]);

  const sendChat = async () => {
    if (!chatMsg.trim()) return;
    await apiClient.executeGameAction("chat", { message: chatMsg });
    setChatMsg("");
  };

  if (loading) {
    return (
      <div className="flex items-center justify-center h-full text-gray-400">
        <Gamepad2 className="w-8 h-8 animate-pulse mr-3" />
        Loading...
      </div>
    );
  }

  const connected = state?.connected ?? false;

  if (!connected) {
    return (
      <div className="flex flex-col items-center justify-center h-full gap-4 text-gray-400">
        <WifiOff className="w-12 h-12" />
        <p className="text-lg">Minecraft Bot 未接続</p>
        <p className="text-sm text-gray-500">
          minecraft-bot を起動して、Minecraft サーバーに接続してください
        </p>
        <button
          onClick={() => apiClient.connectGame()}
          className="px-4 py-2 bg-green-600/20 text-green-400 rounded-lg hover:bg-green-600/30 transition"
        >
          接続
        </button>
      </div>
    );
  }

  const pos = state?.position;
  const timePeriod = state?.time?.period ?? "unknown";
  const isRaining = state?.time?.isRaining ?? false;

  const TimeIcon =
    timePeriod === "night" ? Moon :
    timePeriod === "sunrise" ? Sunrise :
    timePeriod === "sunset" ? Sunset : Sun;

  return (
    <div className="flex flex-col h-full p-4 gap-3 overflow-y-auto">
      {/* Header */}
      <div className="flex items-center gap-3">
        <Gamepad2 className="w-6 h-6 text-green-400" />
        <h2 className="text-lg font-bold">Minecraft</h2>
        <div className="flex items-center gap-1 ml-auto text-xs text-green-400">
          <Wifi className="w-4 h-4" />
          Connected
        </div>
      </div>

      {/* Status Grid */}
      <div className="grid grid-cols-2 gap-3">
        {/* Health */}
        <div className="glass-panel rounded-xl p-3">
          <div className="flex items-center gap-2 text-sm text-gray-400 mb-1">
            <Heart className="w-4 h-4 text-red-400" />
            HP
          </div>
          <div className="flex items-center gap-2">
            <div className="flex-1 bg-gray-700/50 rounded-full h-2">
              <div
                className="bg-red-500 rounded-full h-2 transition-all"
                style={{ width: `${((state?.health ?? 20) / 20) * 100}%` }}
              />
            </div>
            <span className="text-sm font-mono">{state?.health ?? 20}/20</span>
          </div>
        </div>

        {/* Food */}
        <div className="glass-panel rounded-xl p-3">
          <div className="flex items-center gap-2 text-sm text-gray-400 mb-1">
            <Drumstick className="w-4 h-4 text-amber-400" />
            Food
          </div>
          <div className="flex items-center gap-2">
            <div className="flex-1 bg-gray-700/50 rounded-full h-2">
              <div
                className="bg-amber-500 rounded-full h-2 transition-all"
                style={{ width: `${((state?.food ?? 20) / 20) * 100}%` }}
              />
            </div>
            <span className="text-sm font-mono">{state?.food ?? 20}/20</span>
          </div>
        </div>
      </div>

      {/* Position & Environment */}
      <div className="glass-panel rounded-xl p-3">
        <div className="flex items-center gap-4 text-sm">
          <div className="flex items-center gap-1">
            <MapPin className="w-4 h-4 text-blue-400" />
            <span className="font-mono">
              {pos ? `${pos.x}, ${pos.y}, ${pos.z}` : "???"}
            </span>
          </div>
          <div className="text-gray-400">{state?.biome ?? "unknown"}</div>
          <div className="flex items-center gap-1 ml-auto">
            <TimeIcon className="w-4 h-4 text-yellow-400" />
            <span className="text-gray-400">{timePeriod}</span>
            {isRaining && <CloudRain className="w-4 h-4 text-blue-400 ml-1" />}
          </div>
        </div>
      </div>

      {/* Inventory */}
      <div className="glass-panel rounded-xl p-3">
        <button
          onClick={() => setInvOpen(!invOpen)}
          className="flex items-center gap-2 text-sm w-full"
        >
          <Package className="w-4 h-4 text-purple-400" />
          <span>Inventory ({state?.inventory?.length ?? 0})</span>
          {invOpen ? (
            <ChevronDown className="w-4 h-4 ml-auto" />
          ) : (
            <ChevronRight className="w-4 h-4 ml-auto" />
          )}
        </button>
        {invOpen && (
          <div className="mt-2 grid grid-cols-2 gap-1 text-xs text-gray-300 max-h-40 overflow-y-auto">
            {(state?.inventory ?? []).map((item, i) => (
              <div key={i} className="flex justify-between px-2 py-1 bg-white/5 rounded">
                <span>{item.name}</span>
                <span className="text-gray-500">x{item.count}</span>
              </div>
            ))}
            {(!state?.inventory || state.inventory.length === 0) && (
              <div className="col-span-2 text-center text-gray-500 py-2">Empty</div>
            )}
          </div>
        )}
      </div>

      {/* Nearby Entities */}
      {state?.nearbyEntities && state.nearbyEntities.length > 0 && (
        <div className="glass-panel rounded-xl p-3">
          <div className="flex items-center gap-2 text-sm mb-2">
            <Users className="w-4 h-4 text-cyan-400" />
            <span>Nearby ({state.nearbyEntities.length})</span>
          </div>
          <div className="space-y-1 text-xs max-h-32 overflow-y-auto">
            {state.nearbyEntities.slice(0, 8).map((e, i) => (
              <div key={i} className="flex justify-between px-2 py-1 bg-white/5 rounded">
                <span className={e.type === "player" ? "text-green-400" : "text-gray-300"}>
                  {e.name}
                </span>
                <span className="text-gray-500">{e.distance}m</span>
              </div>
            ))}
          </div>
        </div>
      )}

      {/* Event Feed */}
      <div className="glass-panel rounded-xl p-3 flex-1 min-h-[120px]">
        <div className="text-sm text-gray-400 mb-2">Events</div>
        <div className="space-y-1 text-xs max-h-40 overflow-y-auto">
          {events.length === 0 && (
            <div className="text-gray-500 text-center py-4">No events yet</div>
          )}
          {events.map((ev, i) => (
            <div key={i} className="flex gap-2 px-2 py-1 bg-white/5 rounded">
              <span className="text-gray-500 font-mono">
                {new Date(ev.ts).toLocaleTimeString()}
              </span>
              <span className="text-yellow-400">{ev.type}</span>
              <span className="text-gray-300 truncate">
                {formatEventData(ev)}
              </span>
            </div>
          ))}
          <div ref={eventsEndRef} />
        </div>
      </div>

      {/* Quick Chat */}
      <div className="flex gap-2">
        <input
          type="text"
          value={chatMsg}
          onChange={(e) => setChatMsg(e.target.value)}
          onKeyDown={(e) => e.key === "Enter" && sendChat()}
          placeholder="ゲーム内チャット..."
          className="flex-1 bg-white/5 border border-white/10 rounded-lg px-3 py-2 text-sm outline-none focus:border-blue-500/50"
        />
        <button
          onClick={sendChat}
          className="px-3 py-2 bg-blue-600/20 text-blue-400 rounded-lg hover:bg-blue-600/30 transition"
        >
          <Send className="w-4 h-4" />
        </button>
      </div>
    </div>
  );
}

function formatEventData(ev: GameEvent): string {
  const d = ev.data || {};
  switch (ev.type) {
    case "chat":
      return `[${d.username}] ${d.message}`;
    case "health_change":
      return `HP: ${d.health} Food: ${d.food}`;
    case "damage":
      return `Took damage (HP: ${d.health})`;
    case "death":
      return "Died!";
    case "collect":
      return `Collected ${d.item}`;
    case "entity_spawn":
      return `${d.name} appeared (${d.distance}m)`;
    case "entity_gone":
      return `${d.name} left`;
    case "weather":
      return d.isRaining ? "Rain started" : "Rain stopped";
    default:
      return JSON.stringify(d).slice(0, 60);
  }
}
