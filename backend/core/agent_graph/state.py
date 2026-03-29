from typing import Annotated, Sequence, TypedDict, Optional, Dict, Any
from langchain_core.messages import BaseMessage
from langgraph.graph.message import add_messages


class AgentState(TypedDict, total=False):
    """LangGraph agent state.

    Fields are grouped logically but kept flat for LangGraph compatibility.
    Do NOT nest TypedDicts — LangGraph's checkpoint serializer requires
    a single-level TypedDict.
    """

    # ── Core Messages ────────────────────────────────────────────
    messages: Annotated[Sequence[BaseMessage], add_messages]
    has_user_text: bool
    user_text: Optional[str]
    thread_id: Optional[str]
    turn_id: Optional[str]
    message_id: Optional[str]
    stream_id: Optional[str]
    trace_id: Optional[str]
    test_mode: Optional[bool]  # Skip memory saving for model testing

    # ── Safety ───────────────────────────────────────────────────
    safety_route: Optional[str]
    safety_text: Optional[str]

    # ── Dissonance & Surprise ────────────────────────────────────
    dissonance: Optional[float]
    dissonance_on: Optional[bool]
    surprise_score: Optional[float]
    surprise_reasons: Optional[list]

    # ── Depth Selection ──────────────────────────────────────────
    need_depth1: Optional[bool]
    need_depth2: Optional[bool]
    selected_depth: Optional[int]  # 0, 1, or 2
    depth_action: Optional[str]  # "depth0", "depth1", "ask", "wait"
    depth_recommendation_reason: Optional[str]
    depth2_gate_met: Optional[bool]
    depth2_mode: Optional[str]  # "risk" | "reflective" | None
    self_scope: Optional[bool]
    force_ab_followup: Optional[bool]
    requires_direct_stance: Optional[bool]
    turn_intent: Optional[str]  # "direct_answer" | "correction_response" | "open_reflection"

    # ── Confidence ───────────────────────────────────────────────
    confidence: Optional[float]  # 0.0-1.0
    confidence_metrics: Optional[Dict[str, float]]
    reason_codes: Optional[list]

    # ── Draft & Output ───────────────────────────────────────────
    draft: Optional[str]
    depth1_text: Optional[str]
    depth1_contract_ok: Optional[bool]
    depth2_text: Optional[str]
    depth2_fallback_used: Optional[bool]
    merge_mode: Optional[str]
    final_text: Optional[str]

    # ── Review Window ────────────────────────────────────────────
    hold_required: Optional[bool]
    hold_kind: Optional[str]
    review_token: Optional[str]
    review_pending_actions: Optional[list]
    review_rejected_actions: Optional[list]
    suppressed_actions: Optional[list]

    # ── Phase 5: Action System ───────────────────────────────────
    proposed_actions: Optional[list]
    approved_actions: Optional[list]
    pending_actions: Optional[list]
    rejected_actions: Optional[list]
    action_results: Optional[list]

    # ── External Data ────────────────────────────────────────────
    external_reason: Optional[str]
    external_used: Optional[bool]
    external_confidence: Optional[float]
    contradiction_flag: Optional[bool]

    # ── Memory & Context ─────────────────────────────────────────
    memory_context: Optional[str]
    memory_sections: Optional[Dict[str, str]]
    cumulative_turn_count: Optional[int]

    # ── Orchestrator ─────────────────────────────────────────────
    orchestrator_stage: Optional[str]  # "S0"〜"S5"
    commit_result: Optional[Dict[str, Any]]
    pre_thought_action: Optional[str]  # "WAIT" / "short_ack" / None

    # ── Game Integration ─────────────────────────────────────────
    game_context: Optional[str]
    game_active: Optional[bool]

    # ── N.1: Metacognitive Check ─────────────────────────────────
    metacog_result: Optional[Dict[str, Any]]

    # ── N.0: Awareness Core ──────────────────────────────────────
    awareness_signal: Optional[Dict[str, Any]]

    # ── S.1a: Somatic Self-Awareness ─────────────────────────────
    somatic_senses: Optional[list]  # list[{"text": str, "intensity": float}]
    retrieval_top_similarity: Optional[float]  # best cosine sim from retrieval

    # ── NiaCore: Shadow Inference ────────────────────────────────
    niacore_shadow: Optional[Dict[str, Any]]

    # ── NiaCore vNext: Shadow Observation ─────────────────────────
    niacore_vnext_shadow: Optional[Dict[str, Any]]

    # ── SkeletonCore: Conversation Skeleton ──────────────────────
    conversation_skeleton: Optional[Dict[str, Any]]
    turn_role: Optional[str]
    turn_role_source: Optional[str]

    # ── Contract 1/2: RuntimeFacts & Atmosphere ────────────────
    runtime_facts_text: Optional[str]
    atmosphere_text: Optional[str]
    nero_references_text: Optional[str]
