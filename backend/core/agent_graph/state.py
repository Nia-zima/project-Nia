from typing import Annotated, Sequence, TypedDict, Optional, Dict, Any
from langchain_core.messages import BaseMessage
from langgraph.graph.message import add_messages


class AgentState(TypedDict):
    messages: Annotated[Sequence[BaseMessage], add_messages]
    has_user_text: bool
    user_text: Optional[str]
    safety_route: Optional[str]
    safety_text: Optional[str]
    dissonance: Optional[float]
    dissonance_on: Optional[bool]
    surprise_score: Optional[float]
    surprise_reasons: Optional[list]
    need_depth1: Optional[bool]
    need_depth2: Optional[bool]
    reason_codes: Optional[list]
    draft: Optional[str]
    depth1_text: Optional[str]
    depth2_text: Optional[str]
    merge_mode: Optional[str]
    final_text: Optional[str]
    hold_required: Optional[bool]
    hold_kind: Optional[str]
    review_token: Optional[str]
    suppressed_actions: Optional[list]
    # Phase 2: 確信度システム
    confidence: Optional[float]  # 複合確信度 (0.0-1.0)
    confidence_metrics: Optional[Dict[str, float]]  # 各メトリクスの詳細
    depth_action: Optional[str]  # "depth0", "depth1", "ask", "wait"
    depth_recommendation_reason: Optional[str]  # 推奨理由
    # Phase 5: アクションシステム
    proposed_actions: Optional[list]  # LLMが提案したアクション
    approved_actions: Optional[list]  # ゲートを通過したアクション
    pending_actions: Optional[list]  # 確認待ちのアクション
    rejected_actions: Optional[list]  # 拒否されたアクション
    action_results: Optional[list]  # 実行結果
    selected_depth: Optional[int]  # 選択されたDepth (0, 1, or 2)
    self_scope: Optional[bool]  # 質問対象が「ニア自身/AI自身」か
    force_ab_followup: Optional[bool]  # Depth2直後のA/B確認を強制するか
    external_reason: Optional[str]  # 外部データ取得理由（観測用）
    external_used: Optional[bool]  # 外部データを実際に統合したか
    external_confidence: Optional[float]  # 外部データ信頼度
    contradiction_flag: Optional[bool]  # 外部データ矛盾フラグ
