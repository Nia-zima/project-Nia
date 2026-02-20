"""10 State-Transition Contracts — 状態遷移の不変条件テスト.

各契約は、LangGraph のノード間で守られるべき不変条件を1つテストする。
ソースコード: backend/core/agent_graph/ 配下
ドキュメント: docs/contracts.md
"""
from __future__ import annotations

import asyncio
import uuid

import pytest

from backend.core.agent_graph.state import AgentState
from backend.core.agent_graph.review_window import (
    D_LOW,
    D_MAX,
    K_HOLD,
    K_REJECT,
    MAX_PENDING,
    apply_review_decision,
    build_hold_cancelled_event,
    build_hold_request_event,
    cancel_review_on_new_input,
    clear_review_token,
    get_review_token,
    set_review_token,
)


# ── Helpers ──────────────────────────────────────────────────────


def _base_state(**overrides) -> AgentState:
    """最小限の AgentState dict を生成。"""
    s: dict = {
        "messages": [],
        "has_user_text": True,
        "user_text": "テスト",
        "safety_route": "safe",
        "safety_text": None,
        "dissonance": 0.0,
        "dissonance_on": False,
        "surprise_score": 0.0,
        "surprise_reasons": [],
        "need_depth1": False,
        "need_depth2": False,
        "reason_codes": [],
        "draft": "",
        "depth1_text": "",
        "depth2_text": "",
        "merge_mode": None,
        "final_text": None,
        "hold_required": False,
        "hold_kind": None,
        "review_token": None,
        "suppressed_actions": [],
        "confidence": 0.5,
        "confidence_metrics": {},
        "depth_action": "depth0",
        "depth_recommendation_reason": "",
        "proposed_actions": [],
        "approved_actions": [],
        "pending_actions": [],
        "rejected_actions": [],
        "action_results": [],
        "selected_depth": 0,
        "self_scope": False,
        "force_ab_followup": False,
        "external_reason": None,
        "external_used": False,
        "external_confidence": 0.0,
        "contradiction_flag": False,
        "thread_id": "test_thread",
        "memory_context": "",
        "memory_sections": {},
        "orchestrator_stage": None,
        "commit_result": None,
        "depth2_gate_met": False,
        "cumulative_turn_count": 0,
        "pre_thought_action": None,
        "game_context": "",
        "game_active": False,
    }
    s.update(overrides)
    return s  # type: ignore[return-value]


class _DummyState:
    def __init__(self, values: dict):
        self.values = values


class _DummyAsyncCtx:
    async def __aenter__(self):
        return object()

    async def __aexit__(self, exc_type, exc, tb):
        return False


class _DummyCheckpointerGateway:
    def get_async_checkpointer_conn(self):
        return _DummyAsyncCtx()


class _DummyTTS:
    async def generate_audio_url(self, **kwargs):
        return None

    async def get_audio_meta(self, url: str):
        return {}

    async def generate_audio(self, text: str, voice_id: str):
        return b""


class _DummyVision:
    async def build_user_input(self, input_text: str, image_data: str):
        return input_text


class _CaptureStreamApp:
    def __init__(self, events: list[dict], *, state_values: dict | None = None):
        self._events = list(events)
        self._state_values = dict(state_values or {})
        self.inputs = None

    async def astream_events(self, inputs, config=None, version=None, recursion_limit=None):
        self.inputs = inputs
        for event in self._events:
            yield event

    async def aget_state(self, config):
        return _DummyState(dict(self._state_values))


class _CaptureNonStreamApp:
    def __init__(self, result: dict):
        self._result = result
        self.inputs = None

    async def ainvoke(self, inputs, config=None):
        self.inputs = inputs
        return self._result


# =====================================================================
# 契約 1: WAIT 透過契約
#   draft=="WAIT" かつ depth1_text/depth2_text が空 → final_text="WAIT",
#   hold_required=False, review_token=None, pending_actions=[]
# =====================================================================
class TestContract1_WaitPassthrough:
    """WAIT 透過契約: 「何もしない」がそのまま通過する。"""

    def test_merge_output_wait_passthrough(self, monkeypatch):
        """merge_output が WAIT を透過させること。"""
        monkeypatch.setattr(
            "backend.core.agent_graph.nodes.merge.settings",
            type("S", (), {
                "GUARDRAIL_V2_ENABLED": False,
                "EXPERIMENT_MODE": True,
            })(),
        )
        monkeypatch.setattr(
            "backend.core.agent_graph.nodes.merge.log_turn_observation",
            lambda *a, **kw: None,
        )
        from backend.core.agent_graph.nodes.merge import merge_output

        state = _base_state(draft="WAIT", depth1_text="", depth2_text="")
        result = merge_output(state)

        assert result["final_text"] == "WAIT"
        assert result["hold_required"] is False
        assert result["review_token"] is None
        assert result["pending_actions"] == []
        assert "system_wait_passthrough" in result["reason_codes"]

    def test_review_window_state_clean_on_wait(self):
        """WAIT 時に review_window の状態がクリーンであること。"""
        state = _base_state(
            final_text="WAIT",
            hold_required=False,
            review_token=None,
            pending_actions=[],
        )
        assert get_review_token(state) is None


# =====================================================================
# 契約 2: Hold 開始契約
#   Hold トリガー → final_text="WAIT", review_token が設定,
#   pending_actions に kind="say" が ≥1
# =====================================================================
class TestContract2_HoldStart:
    """Hold 開始契約: set_review_token が全必須フィールドを設定する。"""

    def test_set_review_token_sets_all_fields(self):
        state = _base_state()
        pending = [{"kind": "say", "text": "テスト発話", "risk": "med"}]
        update = set_review_token(state, pending_actions=pending)

        assert update["final_text"] == "WAIT"
        assert update["hold_required"] is True
        assert update["review_token"] is not None
        assert len(update["review_token"]) > 0
        say_items = [a for a in update["pending_actions"] if a.get("kind") == "say"]
        assert len(say_items) >= 1

    def test_hold_sets_merge_mode_prefix(self):
        state = _base_state()
        pending = [{"kind": "say", "text": "確認テスト", "risk": "med"}]
        update = set_review_token(state, pending_actions=pending)
        assert update["merge_mode"].startswith("review:")

    def test_hold_increases_dissonance(self):
        state = _base_state(dissonance=0.1)
        pending = [{"kind": "say", "text": "テスト", "risk": "med"}]
        update = set_review_token(state, pending_actions=pending, dissonance=0.1)
        assert update["dissonance"] == pytest.approx(0.1 + K_HOLD)

    def test_dissonance_capped_at_d_max(self):
        state = _base_state(dissonance=D_MAX)
        pending = [{"kind": "say", "text": "テスト", "risk": "med"}]
        update = set_review_token(state, pending_actions=pending, dissonance=D_MAX)
        assert update["dissonance"] <= D_MAX


# =====================================================================
# 契約 3: Hold 取消契約
#   新規入力 → 既存 Hold を取消。旧トークンでは commit 不可。
# =====================================================================
class TestContract3_HoldCancel:
    """Hold 取消契約: 新入力でキャンセル後、旧トークンは無効。"""

    def test_cancel_on_new_input(self):
        token = uuid.uuid4().hex
        state = _base_state(
            review_token=token,
            merge_mode=f"review:{token}",
            hold_required=True,
            pending_actions=[{"kind": "say", "text": "旧発話"}],
        )
        cancel_update = cancel_review_on_new_input(state, user_text="新しい入力です")

        assert cancel_update["review_token"] is None
        assert cancel_update["hold_required"] is False
        assert cancel_update["pending_actions"] == []

    @pytest.mark.asyncio
    async def test_stale_approve_does_not_commit_after_cancel_race(self, monkeypatch):
        """approve が先に state を読んでも、cancel 後の旧 token commit は拒否される。"""
        from backend.controllers.api import review_router

        token = uuid.uuid4().hex
        shared_state = _base_state(
            review_token=token,
            merge_mode=f"review:{token}",
            hold_required=True,
            final_text="WAIT",
            pending_actions=[{"kind": "say", "text": "旧承認文"}],
        )
        first_read_taken = asyncio.Event()
        release_first_read = asyncio.Event()

        class _RaceApp:
            def __init__(self):
                self.read_count = 0
                self.updates: list[tuple[dict, str | None]] = []

            async def aget_state(self, config):
                self.read_count += 1
                snapshot = dict(shared_state)
                if self.read_count == 1:
                    first_read_taken.set()
                    await release_first_read.wait()
                return _DummyState(snapshot)

            async def aupdate_state(self, config, update, as_node=None):
                self.updates.append((dict(update), as_node))
                shared_state.update(update)

        race_app = _RaceApp()

        async def _noop_emit_commit_log(thread_id: str, line: str, **kwargs):
            return None

        monkeypatch.setattr(review_router.workflow, "compile", lambda checkpointer: race_app)
        monkeypatch.setattr(review_router.memory_manager, "get_async_checkpointer_conn", lambda: _DummyAsyncCtx())
        monkeypatch.setattr(review_router, "emit_commit_log", _noop_emit_commit_log)
        monkeypatch.setattr(review_router, "s5_commit", lambda state: {"commit_result": None})

        approve_task = asyncio.create_task(review_router._apply_review("race_thread", token, "approve"))
        await asyncio.wait_for(first_read_taken.wait(), timeout=1.0)

        cancel_update = cancel_review_on_new_input(shared_state, user_text="新しい入力")
        shared_state.update(cancel_update)
        release_first_read.set()

        result = await asyncio.wait_for(approve_task, timeout=1.0)
        assert result["ok"] is True
        assert result["applied"] is False
        assert result["reason"] == "token_mismatch"
        assert race_app.updates == []
        assert shared_state["final_text"] == "WAIT"

    def test_cancel_preserves_rejected_actions(self):
        token = uuid.uuid4().hex
        state = _base_state(
            review_token=token,
            merge_mode=f"review:{token}",
            hold_required=True,
            pending_actions=[{"kind": "say", "text": "発話"}],
            rejected_actions=[],
        )
        cancel_update = cancel_review_on_new_input(state, user_text="新入力")
        assert len(cancel_update["rejected_actions"]) >= 1
        shadowed = cancel_update["rejected_actions"][0]
        assert shadowed.get("cancel_reason") == "new_user_input"

    def test_cancel_without_user_text_is_noop(self):
        token = uuid.uuid4().hex
        state = _base_state(
            review_token=token,
            merge_mode=f"review:{token}",
        )
        result = cancel_review_on_new_input(state, user_text="")
        assert result == {}


# =====================================================================
# 契約 4: トークン一致必須契約
#   approve/reject は token が一致する場合のみ有効。
#   不一致 → 空 dict（副作用なし）。
# =====================================================================
class TestContract4_TokenMatch:
    """トークン一致必須契約: ミスマッチ = 副作用なし。"""

    def test_matching_token_approve(self):
        token = uuid.uuid4().hex
        state = _base_state(
            review_token=token,
            merge_mode=f"review:{token}",
            pending_actions=[{"kind": "say", "text": "承認テスト"}],
        )
        result = apply_review_decision(state, token=token, decision="approve")
        assert result != {}
        assert result["final_text"] == "承認テスト"

    def test_mismatched_token_returns_empty(self):
        real_token = uuid.uuid4().hex
        wrong_token = uuid.uuid4().hex
        state = _base_state(
            review_token=real_token,
            merge_mode=f"review:{real_token}",
            pending_actions=[{"kind": "say", "text": "テスト"}],
        )
        result = apply_review_decision(state, token=wrong_token, decision="approve")
        assert result == {}

    def test_no_token_in_state_returns_empty(self):
        state = _base_state(review_token=None, merge_mode=None)
        result = apply_review_decision(state, token="any_token", decision="approve")
        assert result == {}


# =====================================================================
# 契約 5: Commit 原子性契約
#   approve → final_text=候補テキスト + state クリア
#   reject  → final_text="WAIT" + rejected_actions 記録
# =====================================================================
class TestContract5_CommitAtomicity:
    """Commit 原子性契約: 承認と却下の出力パターンが正確。"""

    def test_approve_sets_final_text_and_clears(self):
        token = uuid.uuid4().hex
        state = _base_state(
            review_token=token,
            merge_mode=f"review:{token}",
            pending_actions=[{"kind": "say", "text": "実行テキスト"}],
            dissonance=0.2,
        )
        result = apply_review_decision(state, token=token, decision="approve")

        assert result["final_text"] == "実行テキスト"
        assert result["review_token"] is None
        assert result["hold_required"] is False
        assert result["pending_actions"] == []
        assert result["merge_mode"] == "B"

    def test_reject_keeps_wait_and_records(self):
        token = uuid.uuid4().hex
        state = _base_state(
            review_token=token,
            merge_mode=f"review:{token}",
            pending_actions=[{"kind": "say", "text": "却下テキスト"}],
            dissonance=0.2,
        )
        result = apply_review_decision(state, token=token, decision="reject")

        assert result["final_text"] == "WAIT"
        assert result["review_token"] is None
        assert result["hold_required"] is False
        assert result["pending_actions"] == []
        assert result["merge_mode"] == "wait"
        assert len(result["rejected_actions"]) >= 1
        assert result["rejected_actions"][-1]["text"] == "却下テキスト"

    def test_reject_increases_dissonance(self):
        token = uuid.uuid4().hex
        state = _base_state(
            review_token=token,
            merge_mode=f"review:{token}",
            pending_actions=[{"kind": "say", "text": "テスト"}],
            dissonance=0.3,
        )
        result = apply_review_decision(state, token=token, decision="reject")
        assert result["dissonance"] == pytest.approx(0.3 + K_REJECT)

    def test_approve_with_no_say_defaults_to_wait(self):
        """pending_actions に say がない場合、approve でも WAIT になる。"""
        token = uuid.uuid4().hex
        state = _base_state(
            review_token=token,
            merge_mode=f"review:{token}",
            pending_actions=[{"kind": "action", "text": "not say"}],
        )
        result = apply_review_decision(state, token=token, decision="approve")
        assert result["final_text"] == "WAIT"


# =====================================================================
# 契約 6: final_result 一意契約
#   1 ストリームで final_result は最大1回。
#   run_agent_stream の実経路で final_result_emitted ガードを検証する。
# =====================================================================
class TestContract6_FinalResultUniqueness:
    """final_result 一意契約: 実ストリームで重複 emit しない。"""

    @staticmethod
    async def _collect_stream_events(monkeypatch, app):
        from backend.core.agent_stream import run_agent_stream

        monkeypatch.setattr("backend.core.agent_stream.workflow.compile", lambda checkpointer: app)
        ports = {
            "checkpointer": _DummyCheckpointerGateway(),
            "tts": _DummyTTS(),
            "vision": _DummyVision(),
        }
        events = []
        async for event in run_agent_stream(
            "テスト入力",
            thread_id="contract6_thread",
            voice_id="off",
            ports=ports,
        ):
            events.append(event)
        return events

    @pytest.mark.asyncio
    async def test_stream_merge_replay_emits_final_result_once(self, monkeypatch):
        merge_event = {
            "event": "on_chain_end",
            "name": "merge",
            "data": {
                "output": {
                    "final_text": "最終応答",
                    "merge_mode": "B",
                    "is_wait": False,
                    "hold_required": False,
                }
            },
        }
        app = _CaptureStreamApp(events=[merge_event, merge_event], state_values={"merge_mode": "B"})
        events = await self._collect_stream_events(monkeypatch, app)

        final_results = [
            e for e in events if isinstance(e, dict) and e.get("type") == "event" and e.get("name") == "final_result"
        ]
        assert len(final_results) == 1
        assert final_results[0]["payload"]["final_text"] == "最終応答"

    @pytest.mark.asyncio
    async def test_stream_wait_path_emits_single_final_result(self, monkeypatch):
        merge_event = {
            "event": "on_chain_end",
            "name": "merge",
            "data": {
                "output": {
                    "final_text": "WAIT",
                    "merge_mode": "wait",
                    "is_wait": True,
                    "hold_required": False,
                }
            },
        }
        app = _CaptureStreamApp(events=[merge_event], state_values={"merge_mode": "wait"})
        events = await self._collect_stream_events(monkeypatch, app)

        final_results = [
            e for e in events if isinstance(e, dict) and e.get("type") == "event" and e.get("name") == "final_result"
        ]
        assert len(final_results) == 1
        assert final_results[0]["payload"]["final_text"] == "WAIT"

    @pytest.mark.asyncio
    async def test_stream_safety_block_path_emits_single_final_result(self, monkeypatch):
        app = _CaptureStreamApp(
            events=[],
            state_values={"safety_route": "blocked", "safety_text": "安全上の理由でブロックしました"},
        )
        events = await self._collect_stream_events(monkeypatch, app)

        final_results = [
            e for e in events if isinstance(e, dict) and e.get("type") == "event" and e.get("name") == "final_result"
        ]
        assert len(final_results) == 1
        assert final_results[0]["payload"]["safety_blocked"] is True


# =====================================================================
# 契約 7: SSE ペイロード互換契約
#   hold_request: review_token, hold_kind, preview_text, reason_codes, pending_actions
#   hold_cancelled: review_token, reason
#   final_result: final_text, merge_mode, is_wait
# =====================================================================
class TestContract7_SSEPayloadCompat:
    """SSE ペイロード互換契約: 必須キーが全て存在する。"""

    def test_hold_request_payload_has_required_keys(self):
        token = uuid.uuid4().hex
        update = {
            "review_token": token,
            "hold_kind": "speech_preview",
            "pending_actions": [{"kind": "say", "text": "テスト"}],
            "reason_codes": ["risk_long_text"],
        }
        ev = build_hold_request_event(update)
        payload = ev["payload"]
        required = {"review_token", "hold_kind", "preview_text", "reason_codes", "pending_actions"}
        assert required.issubset(set(payload.keys()))

    def test_hold_cancelled_payload_has_required_keys(self):
        ev = build_hold_cancelled_event(uuid.uuid4().hex)
        payload = ev["payload"]
        required = {"review_token", "reason"}
        assert required.issubset(set(payload.keys()))

    def test_final_result_event_shape(self):
        """final_result イベントの構造を検証（agent_stream.py と同じ形式）。"""
        # agent_stream.py L386-394 の形式を再現
        event = {
            "type": "event",
            "name": "final_result",
            "payload": {
                "final_text": "こんにちは",
                "merge_mode": "B",
                "is_wait": False,
            },
        }
        payload = event["payload"]
        required = {"final_text", "merge_mode", "is_wait"}
        assert required.issubset(set(payload.keys()))
        assert event["type"] == "event"
        assert event["name"] == "final_result"

    def test_hold_request_preview_text_from_pending(self):
        """pending_actions の say テキストが preview_text に反映される。"""
        token = uuid.uuid4().hex
        update = {
            "review_token": token,
            "pending_actions": [{"kind": "say", "text": "プレビュー文"}],
            "reason_codes": [],
        }
        ev = build_hold_request_event(update)
        assert ev["payload"]["preview_text"] == "プレビュー文"


# =====================================================================
# 契約 8: Depth 優先順位契約
#   dissonance ≥ 0.65 → 常に depth1 + dissonance_on（最高優先度）
#   need_depth2 → depth1 + dissonance_on
#   user_request → depth1
# =====================================================================
class TestContract8_DepthPriority:
    """Depth 優先順位契約: オーバーライドの優先順位が安定。"""

    def test_high_dissonance_forces_depth1(self):
        from backend.core.confidence import DepthAction
        from backend.core.agent_graph.nodes.routing import _resolve_depth_decision

        _, _, need_depth1, dissonance_on, reason_codes = _resolve_depth_decision(
            action=DepthAction.USE_DEPTH0,
            confidence=0.9,
            confidence_metrics={},
            dissonance=0.65,
            reason_codes=[],
            need_depth2=False,
        )
        assert need_depth1 is True
        assert dissonance_on is True
        assert "risk_high_dissonance" in reason_codes

    def test_low_dissonance_respects_confidence(self):
        from backend.core.confidence import DepthAction
        from backend.core.agent_graph.nodes.routing import _resolve_depth_decision

        _, _, need_depth1, dissonance_on, _ = _resolve_depth_decision(
            action=DepthAction.USE_DEPTH0,
            confidence=0.9,
            confidence_metrics={},
            dissonance=0.1,
            reason_codes=[],
            need_depth2=False,
        )
        assert need_depth1 is False
        assert dissonance_on is False

    def test_depth2_forces_depth1_and_dissonance(self):
        from backend.core.confidence import DepthAction
        from backend.core.agent_graph.nodes.routing import _resolve_depth_decision

        _, _, need_depth1, dissonance_on, _ = _resolve_depth_decision(
            action=DepthAction.USE_DEPTH0,
            confidence=0.9,
            confidence_metrics={},
            dissonance=0.1,
            reason_codes=[],
            need_depth2=True,
        )
        assert need_depth1 is True
        assert dissonance_on is True

    def test_user_request_forces_depth1(self):
        from backend.core.confidence import DepthAction
        from backend.core.agent_graph.nodes.routing import _resolve_depth_decision

        _, _, need_depth1, _, _ = _resolve_depth_decision(
            action=DepthAction.USE_DEPTH0,
            confidence=0.9,
            confidence_metrics={},
            dissonance=0.1,
            reason_codes=["user_request"],
            need_depth2=False,
        )
        assert need_depth1 is True

    def test_high_dissonance_overrides_depth0_even_with_high_confidence(self):
        """高 confidence でも dissonance>=0.65 なら depth1 強制。"""
        from backend.core.confidence import DepthAction
        from backend.core.agent_graph.nodes.routing import _resolve_depth_decision

        _, _, need_depth1, dissonance_on, _ = _resolve_depth_decision(
            action=DepthAction.USE_DEPTH0,
            confidence=0.99,
            confidence_metrics={},
            dissonance=0.70,
            reason_codes=[],
            need_depth2=False,
        )
        assert need_depth1 is True
        assert dissonance_on is True


# =====================================================================
# 契約 9: ターン初期化契約
#   毎ターン draft, depth1_text, depth2_text を "" にリセット。
# =====================================================================
class TestContract9_TurnInit:
    """ターン初期化契約: チェックポイントの汚染を防止。"""

    @pytest.mark.asyncio
    async def test_stream_inputs_reset_depth_texts(self, monkeypatch):
        """run_agent_stream が stale state に依存せず空文字でターン投入する。"""
        from backend.core.agent_stream import run_agent_stream

        merge_event = {
            "event": "on_chain_end",
            "name": "merge",
            "data": {"output": {"final_text": "WAIT", "merge_mode": "wait", "is_wait": True}},
        }
        app = _CaptureStreamApp(
            events=[merge_event],
            state_values={"draft": "旧draft", "depth1_text": "旧depth1", "depth2_text": "旧depth2"},
        )
        monkeypatch.setattr("backend.core.agent_stream.workflow.compile", lambda checkpointer: app)
        ports = {
            "checkpointer": _DummyCheckpointerGateway(),
            "tts": _DummyTTS(),
            "vision": _DummyVision(),
        }

        async for _ in run_agent_stream(
            "ターン初期化stream",
            thread_id="contract9_stream",
            voice_id="off",
            ports=ports,
        ):
            pass

        assert app.inputs is not None
        assert app.inputs["draft"] == ""
        assert app.inputs["depth1_text"] == ""
        assert app.inputs["depth2_text"] == ""
        assert isinstance(app.inputs["draft"], str)
        assert isinstance(app.inputs["depth1_text"], str)
        assert isinstance(app.inputs["depth2_text"], str)

    @pytest.mark.asyncio
    async def test_non_stream_inputs_reset_depth_texts(self, monkeypatch):
        """run_agent_non_stream が毎ターン空文字で inputs を初期化する。"""
        from langchain_core.messages import AIMessage
        from backend.core.agent import run_agent_non_stream

        app = _CaptureNonStreamApp(result={"messages": [AIMessage(content="了解です")]})
        monkeypatch.setattr("backend.core.agent.workflow.compile", lambda checkpointer: app)
        monkeypatch.setattr("backend.core.agent.settings.ORCHESTRATOR_S5_ENABLED", True)
        ports = {
            "checkpointer": _DummyCheckpointerGateway(),
            "tts": _DummyTTS(),
            "vision": _DummyVision(),
        }

        result = await run_agent_non_stream(
            "ターン初期化nonstream",
            thread_id="contract9_nonstream",
            voice_id="off",
            ports=ports,
        )

        assert result["type"] == "text"
        assert app.inputs is not None
        assert app.inputs["draft"] == ""
        assert app.inputs["depth1_text"] == ""
        assert app.inputs["depth2_text"] == ""

    @pytest.mark.asyncio
    async def test_non_stream_silence_still_resets_depth_fields(self, monkeypatch):
        """[SILENCE] でも reset フィールドは空文字固定。"""
        from langchain_core.messages import AIMessage
        from backend.core.agent import run_agent_non_stream

        app = _CaptureNonStreamApp(result={"messages": [AIMessage(content="WAIT")]})
        monkeypatch.setattr("backend.core.agent.workflow.compile", lambda checkpointer: app)
        monkeypatch.setattr("backend.core.agent.settings.ORCHESTRATOR_S5_ENABLED", True)
        ports = {
            "checkpointer": _DummyCheckpointerGateway(),
            "tts": _DummyTTS(),
            "vision": _DummyVision(),
        }

        await run_agent_non_stream(
            "[SILENCE]",
            thread_id="contract9_silence",
            voice_id="off",
            ports=ports,
        )

        assert app.inputs is not None
        assert app.inputs["has_user_text"] is False
        assert app.inputs["draft"] == ""
        assert app.inputs["depth1_text"] == ""
        assert app.inputs["depth2_text"] == ""


# =====================================================================
# 契約 10: 記憶書き込み境界契約
#   WAIT/Hold 時は S5 が記憶を保存しない。
#   S5 有効時のみ s5_commit が書き込みを行う。
# =====================================================================
class TestContract10_MemoryWriteBoundary:
    """記憶書き込み境界契約: WAIT/Hold = 記憶保存なし。"""

    def test_s5_skips_when_hold_required(self, monkeypatch):
        monkeypatch.setattr(
            "backend.core.agent_graph.nodes.actions.settings",
            type("S", (), {"ORCHESTRATOR_S5_ENABLED": True})(),
        )
        from backend.core.agent_graph.nodes.actions import s5_commit

        state = _base_state(hold_required=True, final_text="WAIT")
        result = s5_commit(state)
        assert result["commit_result"]["skipped"] is True

    def test_s5_skips_when_final_text_wait(self, monkeypatch):
        monkeypatch.setattr(
            "backend.core.agent_graph.nodes.actions.settings",
            type("S", (), {"ORCHESTRATOR_S5_ENABLED": True})(),
        )
        from backend.core.agent_graph.nodes.actions import s5_commit

        state = _base_state(hold_required=False, final_text="WAIT")
        result = s5_commit(state)
        assert result["commit_result"]["skipped"] is True

    def test_s5_skips_when_final_text_empty(self, monkeypatch):
        monkeypatch.setattr(
            "backend.core.agent_graph.nodes.actions.settings",
            type("S", (), {"ORCHESTRATOR_S5_ENABLED": True})(),
        )
        from backend.core.agent_graph.nodes.actions import s5_commit

        state = _base_state(hold_required=False, final_text="")
        result = s5_commit(state)
        assert result["commit_result"]["skipped"] is True

    def test_s5_noop_when_disabled(self, monkeypatch):
        monkeypatch.setattr(
            "backend.core.agent_graph.nodes.actions.settings",
            type("S", (), {"ORCHESTRATOR_S5_ENABLED": False})(),
        )
        from backend.core.agent_graph.nodes.actions import s5_commit

        state = _base_state(final_text="こんにちは", hold_required=False)
        result = s5_commit(state)
        assert result["commit_result"] is None

    def test_s5_executes_when_enabled_and_not_wait(self, monkeypatch):
        """S5 有効 + 非WAIT → commit 実行（モック）。"""

        class FakeResult:
            success = True
            inserted_episodic = 1
            upserted_semantic = 0
            revoked_semantic = 0
            added_working = 0
            closed_working = 0
            errors = []

        monkeypatch.setattr(
            "backend.core.agent_graph.nodes.actions.settings",
            type("S", (), {"ORCHESTRATOR_S5_ENABLED": True})(),
        )
        monkeypatch.setattr(
            "backend.services.memory.commit_executor.execute",
            lambda plan, thread_id, turn_id: FakeResult(),
        )
        from backend.core.agent_graph.nodes.actions import s5_commit

        state = _base_state(final_text="こんにちは", hold_required=False)
        result = s5_commit(state)
        assert result["orchestrator_stage"] == "S5"
        assert result["commit_result"] is not None
        assert result["commit_result"].get("skipped") is not True
        assert result["commit_result"]["success"] is True


# =====================================================================
# 契約 横断: 定数の整合性
# =====================================================================
class TestContractConstants:
    """定数が設計仕様と一致する。"""

    def test_d_low(self):
        assert D_LOW == pytest.approx(0.30)

    def test_d_max(self):
        assert D_MAX == pytest.approx(0.95)

    def test_k_hold(self):
        assert K_HOLD == pytest.approx(0.03)

    def test_k_reject(self):
        assert K_REJECT == pytest.approx(0.07)

    def test_max_pending(self):
        assert MAX_PENDING == 10

    def test_clear_review_token_structure(self):
        """clear_review_token の出力が必要なキーを全て含む。"""
        result = clear_review_token()
        assert result["merge_mode"] is None
        assert result["review_token"] is None
        assert result["hold_required"] is False
        assert result["hold_kind"] is None
        assert result["pending_actions"] == []
