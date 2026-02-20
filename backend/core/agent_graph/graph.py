from langgraph.graph import StateGraph, END
from langgraph.checkpoint.memory import MemorySaver

from backend.core.agent_graph.state import AgentState
from backend.core.agent_graph.nodes import (
    safety_interrupt,
    dissonance_check,
    depth_selector,
    depth0_reflex,
    depth1_organize_and_ask,
    depth2_value_align_and_preview,
    merge_output,
    action_processing,  # Phase 5: アクション処理ノード
    s5_commit,  # Phase F: S5 Commit ノード
)

# --- Graph Definition ---
# Phase 2: 確信度ベースのDepth選択を統合
# Phase 5: アクション処理を統合
#
# グラフ構造:
#   Safety → Dissonance → [Depth Selector] → Depth0 or Depth1 → Merge → Action Processing → END
#
# Depth Selectorは確信度を計算し、適切なDepthを選択します:
#   - 確信度 >= 0.8 → DEPTH0（即答OK）
#   - 確信度 >= 0.5 → DEPTH1（整理必要）
#   - 確信度 >= 0.3 → DEPTH1 + ASK（確認質問）
#   - 確信度 <  0.3 → DEPTH0 + WAIT（保留）
#
# Action Processingはアクション提案を処理します:
#   - Depth0: SAFE（読み取り専用）のみ許可
#   - Depth1: HIGH（高リスク）まで許可（確認必須）
#   - 確信度によるフィルタリング

workflow = StateGraph(AgentState)

# Add Nodes
workflow.add_node("safety", safety_interrupt)
workflow.add_node("dissonance", dissonance_check)
workflow.add_node("depth_selector", depth_selector)  # Phase 2: 新規追加
workflow.add_node("depth0", depth0_reflex)
workflow.add_node("depth1", depth1_organize_and_ask)
workflow.add_node("depth2", depth2_value_align_and_preview)
workflow.add_node("merge", merge_output)
workflow.add_node("action_processing", action_processing)  # Phase 5: 新規追加
workflow.add_node("s5_commit", s5_commit)  # Phase F: S5 Commit ノード

# Set Entry Point
workflow.set_entry_point("safety")

# Add Edges
workflow.add_conditional_edges(
    "safety",
    lambda state: "safe" if state.get("safety_route", "safe") != "blocked" else "blocked",
    {
        "safe": "dissonance",
        "blocked": END,
    },
)

# Phase 2: dissonance → depth_selector
workflow.add_edge("dissonance", "depth_selector")

# Phase 2+: depth_selector → depth0 or depth1 or depth2
workflow.add_conditional_edges(
    "depth_selector",
    lambda state: "depth2" if state.get("need_depth2") else ("depth1" if state.get("need_depth1") else "depth0"),
    {
        "depth0": "depth0",
        "depth1": "depth1",
        "depth2": "depth2",
    },
)

workflow.add_edge("depth0", "merge")
workflow.add_edge("depth1", "merge")
workflow.add_edge("depth2", "merge")
workflow.add_edge("merge", "action_processing")  # Phase 5: Mergeの後にアクション処理
workflow.add_edge("action_processing", "s5_commit")  # Phase F: Action → S5 Commit
workflow.add_edge("s5_commit", END)

# Compile with Checkpointer
memory = MemorySaver()
app = workflow.compile(checkpointer=memory)
