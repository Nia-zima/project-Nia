// frontend/lib/types.ts — Shared type definitions

/** Voice WebSocket message from server */
export interface VoiceWSMessage {
  type: string;
  text?: string;
  audio_b64?: string;
  speaker_id?: number;
  error?: string;
  [key: string]: unknown;
}

/** Pending action from Phase 5 action system */
export interface PendingAction {
  id?: string;
  kind?: string;
  text?: string;
  risk?: string;
  action_type?: string;
  review_token?: string;
  pending_id?: string;
  action_id?: string;
  name?: string;
  description?: string;
  category?: string;
  risk_level?: string;
  risk_score?: number;
  payload?: Record<string, unknown>;
  payload_json?: string;
  decision?: {
    reason?: string;
    requires_confirmation?: boolean;
    suggested_depth?: number | null;
  };
  requested_at?: number;
  created_at?: number;
  status?: string;
  reason?: string;
  message_id?: string;
  thread_id?: string;
  [key: string]: unknown;
}

/** Action execution result */
export interface ActionResult {
  action_id?: string;
  status?: string;
  result?: Record<string, unknown> | string | null;
  approved_by?: string;
  ts?: number;
  source?: string;
}

/** Action issue (error/rejected) shown in Sidebar */
export interface ActionIssue {
  action_id?: string;
  name?: string;
  status?: string;
  message?: string;
  ts?: number;
}

/** Diagnostics data from /diagnostics endpoint */
export interface DiagnosticsData {
  depth_action?: string;
  confidence?: number;
  context_coverage?: number;
  steering_risk?: number;
  info_sufficiency?: number;
  dissonance?: number;
  emotion?: string;
  inner_monologue?: string;
  thread_id?: string;
  [key: string]: unknown;
}

/** Memory item in MemoryExplorer */
export interface MemoryItem {
  id: string;
  content: string;
  summary?: string;
  category?: string;
  importance?: number;
  confidence?: number;
  surprise?: number;
  timestamp?: string;
  source?: string;
  status?: string;
  refs?: string[];
  tags?: string[];
  metadata?: Record<string, unknown>;
}

/** Minecraft game state data */
export interface GameStateData {
  connected: boolean;
  position: { x: number; y: number; z: number } | null;
  health: number;
  food: number;
  experience: { level: number; points: number };
  inventory: Array<{ name: string; count: number; slot: number }>;
  nearbyEntities: Array<{ name: string; type: string; distance: number }>;
  nearbyBlocks: Array<{ name: string; position: { x: number; y: number; z: number } }>;
  biome: string;
  time: { period: string; ticks: number; isRaining: boolean };
  error?: string;
}

/** Game event from WebSocket */
export interface GameEvent {
  type: string;
  data: Record<string, unknown>;
  ts: number;
}

/** Identity change proposal from Sleep Cycle Layer B */
export interface IdentityProposal {
  id: string;
  created_at: number;
  date: string;
  status: "pending" | "approved" | "rejected" | "auto_applied";
  importance: number | null;
  proposal: string;
  chapter_context: string | null;
  review_note: string | null;
  resolved_at: number | null;
}

// ── Utilities ────────────────────────────────────────────────────

/**
 * Safe JSON.parse with fallback.
 * Returns `fallback` on parse failure instead of throwing.
 */
export function safeJsonParse<T = unknown>(json: string, fallback: T): T {
  try {
    return JSON.parse(json) as T;
  } catch {
    return fallback;
  }
}
