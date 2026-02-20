from __future__ import annotations

import sys
from pathlib import Path
from types import SimpleNamespace

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.append(str(PROJECT_ROOT))

from backend.services.external_data import (
    ExternalDataBroker,
    ExternalDataRequest,
    ExternalDataResult,
    LanguageGate,
    ThinkingProcess,
)
from backend.core.config import settings
from backend.core.agent_graph.nodes import merge_output


class SequenceLLM:
    def __init__(self, responses: list[str]):
        self._responses = list(responses)
        self.calls: list[tuple[str, int]] = []

    def generate(self, prompt: str, max_tokens: int = 200) -> str:
        self.calls.append((prompt, max_tokens))
        if not self._responses:
            return ""
        return self._responses.pop(0)


class DummyBroker(ExternalDataBroker):
    def __init__(self, enabled: bool = True):
        super().__init__(enabled=enabled, max_log_size=20)
        self.queries: list[str] = []

    def _execute_search(self, request: ExternalDataRequest):
        self.queries.append(request.query)
        return ExternalDataResult(data=f"RAW:{request.query}", source="dummy", confidence=0.95, contradiction_flag=False)


class _Resp:
    def __init__(self, payload):
        self._payload = payload

    def json(self):
        return self._payload


class LowConfidenceBroker(ExternalDataBroker):
    def _execute_search(self, request: ExternalDataRequest):
        return ExternalDataResult(
            data=f"RAW:{request.query}",
            source="dummy",
            confidence=0.40,
            contradiction_flag=False,
            evidence=[{"source": "dummy", "title": "t", "snippet": "s", "url": ""}],
        )


class ContradictionBroker(ExternalDataBroker):
    def _execute_search(self, request: ExternalDataRequest):
        return ExternalDataResult(
            data=f"RAW:{request.query}",
            source="dummy",
            confidence=0.90,
            contradiction_flag=True,
            evidence=[
                {"source": "dummy", "title": "t1", "snippet": "1999年", "url": ""},
                {"source": "dummy", "title": "t2", "snippet": "2003年", "url": ""},
            ],
        )


def test_external_data_request_validate_success():
    req = ExternalDataRequest(
        reason="この主張の事実関係を確認するために日付を照合したいです",
        query="出来事 日付 公式",
        category="fact_check",
    )
    assert req.validate() is True


def test_external_data_request_validate_failure_short_reason():
    req = ExternalDataRequest(
        reason="事実確認",
        query="出来事 日付",
        category="fact_check",
    )
    assert req.validate() is False


def test_language_gate_parses_valid_json():
    llm = SequenceLLM(
        [
            """```json
            {"need": true, "reason": "この用語の定義と意味を確認しないと誤解が残るためです", "query": "Aという用語 定義", "category": "definition"}
            ```"""
        ]
    )
    gate = LanguageGate(llm)
    req = gate.generate_request("思考テキスト", {"depth": 3})
    assert req is not None
    assert req.category == "definition"
    assert req.validate() is True
    assert req.query.endswith("定義")


def test_language_gate_need_false_returns_none():
    llm = SequenceLLM(['{"need": false, "reason": "", "query": "", "category": ""}'])
    gate = LanguageGate(llm)
    assert gate.generate_request("思考テキスト", {"depth": 5}) is None


def test_broker_disabled_no_fetch():
    broker = DummyBroker(enabled=False)
    req = ExternalDataRequest(
        reason="この主張の事実を確認するために人名と日付を照合したいです",
        query="人物 生年 日付",
        category="fact_check",
    )
    out = broker.fetch(req)
    assert out is None
    assert broker.get_statistics()["total_fetches"] == 0


def test_broker_enabled_logs_fetch():
    broker = DummyBroker(enabled=True)
    req = ExternalDataRequest(
        reason="統計データの比較をしないと数値判断ができないため確認します",
        query="市場規模 統計 比較",
        category="data",
    )
    out = broker.fetch(req)
    assert out is not None
    assert out.data.startswith("RAW:")
    stats = broker.get_statistics()
    assert stats["total_fetches"] == 1
    assert stats["by_category"]["data"] == 1
    assert broker.queries == ["市場規模 統計 比較"]


def test_thinking_process_depth_gate_blocks_external_under_min_depth():
    llm = SequenceLLM(["浅い思考"])
    broker = DummyBroker(enabled=True)
    proc = ThinkingProcess(llm, min_depth_for_external=3, broker=broker)
    out = proc.process("入力", depth=2)
    assert out.thought == "浅い思考"
    assert out.external_used is False
    assert out.external_reason is None
    assert broker.get_statistics()["total_fetches"] == 0


def test_thinking_process_uses_gate_and_broker_when_depth_sufficient():
    llm = SequenceLLM(
        [
            "初期思考",
            '{"need": true, "reason": "この主張の事実確認として日付と人名の整合を確認する必要があるため", "query": "事件 日付 人名 公式", "category": "fact_check"}',
            "統合後思考",
        ]
    )
    broker = DummyBroker(enabled=True)
    proc = ThinkingProcess(
        llm,
        min_depth_for_external=3,
        broker=broker,
        surprise_calculator=lambda _thought, _ctx: 0.95,
    )
    out = proc.process("入力", depth=6)
    assert out.thought == "統合後思考"
    assert out.external_used is True
    assert out.request is not None
    assert out.external_reason is not None
    assert broker.get_statistics()["total_fetches"] == 1


def test_thinking_process_depth_3_to_5_requires_high_surprise():
    llm = SequenceLLM(
        [
            "初期思考",
            '{"need": true, "reason": "この主張の事実確認として日付と人名の整合を確認する必要があるため", "query": "事件 日付 人名 公式", "category": "fact_check"}',
        ]
    )
    broker = DummyBroker(enabled=True)
    proc = ThinkingProcess(
        llm,
        min_depth_for_external=3,
        broker=broker,
        surprise_calculator=lambda _thought, _ctx: 0.70,
    )
    out = proc.process("入力", depth=4)
    assert out.external_used is False
    assert out.external_priority > 0.0
    assert broker.get_statistics()["total_fetches"] == 0


def test_thinking_process_depth_3_to_5_blocks_definition_even_high_surprise():
    llm = SequenceLLM(
        [
            "初期思考",
            '{"need": true, "reason": "この用語の定義が曖昧で基準を確認したいので外部確認が必要です", "query": "Aという用語 意味", "category": "definition"}',
        ]
    )
    broker = DummyBroker(enabled=True)
    proc = ThinkingProcess(
        llm,
        min_depth_for_external=3,
        broker=broker,
        surprise_calculator=lambda _thought, _ctx: 0.99,
    )
    out = proc.process("入力", depth=5)
    assert out.external_used is False
    assert broker.get_statistics()["total_fetches"] == 0


def test_feedback_loop_raises_threshold_after_many_failures():
    llm = SequenceLLM(
        [
            "初期思考",
            '{"need": true, "reason": "この主張の事実確認として日付と人名の整合を確認する必要があるため", "query": "事件 日付 人名 公式", "category": "fact_check"}',
        ]
    )
    broker = DummyBroker(enabled=True)
    for _ in range(5):
        broker.record_feedback(category="fact_check", useful=False, source="dummy", error="no_results")
    proc = ThinkingProcess(
        llm,
        min_depth_for_external=3,
        broker=broker,
        surprise_calculator=lambda _thought, _ctx: 0.85,
    )
    out = proc.process("入力", depth=4)
    assert out.external_used is False
    assert broker.get_statistics()["total_fetches"] == 0


def test_feedback_loop_lowers_threshold_after_successes():
    llm = SequenceLLM(
        [
            "初期思考",
            '{"need": true, "reason": "この主張の事実確認として日付と人名の整合を確認する必要があるため", "query": "事件 日付 人名 公式", "category": "fact_check"}',
            "統合後思考",
        ]
    )
    broker = DummyBroker(enabled=True)
    for _ in range(5):
        broker.record_feedback(category="fact_check", useful=True, source="dummy", error=None)
    proc = ThinkingProcess(
        llm,
        min_depth_for_external=3,
        broker=broker,
        surprise_calculator=lambda _thought, _ctx: 0.76,
    )
    out = proc.process("入力", depth=4)
    assert out.external_used is True
    assert out.thought == "統合後思考"


def test_broker_statistics_contains_feedback():
    broker = DummyBroker(enabled=True)
    broker.record_feedback(category="data", useful=False, source="dummy", error="no_results")
    stats = broker.get_statistics()
    assert "feedback" in stats
    assert "data" in stats["feedback"]
    assert stats["feedback"]["data"]["total"] >= 1


def test_thinking_process_does_not_integrate_low_confidence_result():
    llm = SequenceLLM(
        [
            "初期思考",
            '{"need": true, "reason": "この主張の事実確認として日付と人名の整合を確認する必要があるため", "query": "事件 日付 人名 公式", "category": "fact_check"}',
        ]
    )
    broker = LowConfidenceBroker(enabled=True)
    proc = ThinkingProcess(
        llm,
        min_depth_for_external=3,
        broker=broker,
        surprise_calculator=lambda _thought, _ctx: 0.95,
    )
    out = proc.process("入力", depth=6)
    assert out.external_used is False
    assert out.external_confidence < 0.65


def test_thinking_process_does_not_integrate_when_contradiction_flagged():
    llm = SequenceLLM(
        [
            "初期思考",
            '{"need": true, "reason": "この主張の事実確認として日付と人名の整合を確認する必要があるため", "query": "事件 日付 人名 公式", "category": "fact_check"}',
        ]
    )
    broker = ContradictionBroker(enabled=True)
    proc = ThinkingProcess(
        llm,
        min_depth_for_external=3,
        broker=broker,
        surprise_calculator=lambda _thought, _ctx: 0.95,
    )
    out = proc.process("入力", depth=6)
    assert out.external_used is False
    assert out.contradiction_flag is True


def test_prioritize_requests_orders_by_feedback_adapted_priority():
    broker = DummyBroker(enabled=True)
    for _ in range(5):
        broker.record_feedback(category="fact_check", useful=False, source="dummy", error="no_results")
        broker.record_feedback(category="data", useful=True, source="dummy", error=None)

    requests = [
        ExternalDataRequest(
            reason="この主張の事実確認として日付と人名の整合を確認する必要があるため",
            query="A いつ",
            category="fact_check",
        ),
        ExternalDataRequest(
            reason="数値の比較データを確認しないと判断ができないため外部参照が必要です",
            query="A 統計 比較",
            category="data",
        ),
    ]
    ranked = broker.prioritize_requests(requests, surprise=0.9)
    assert ranked[0][0].category == "data"
    assert ranked[0][1] > ranked[1][1]


def test_thinking_process_executes_candidates_in_priority_order():
    llm = SequenceLLM(
        [
            "初期思考",
            '{"need": false, "reason": "", "query": "", "category": ""}',
            "統合後思考",
        ]
    )
    broker = DummyBroker(enabled=True)
    for _ in range(5):
        broker.record_feedback(category="fact_check", useful=False, source="dummy", error="no_results")
        broker.record_feedback(category="data", useful=True, source="dummy", error=None)

    proc = ThinkingProcess(
        llm,
        min_depth_for_external=3,
        broker=broker,
        surprise_calculator=lambda _thought, _ctx: 0.92,
    )
    out = proc.process_existing_thought(
        thought="元思考",
        user_input="入力",
        depth=6,
        context={
            "candidate_requests": [
                {
                    "reason": "この主張の事実確認として日付と人名の整合を確認する必要があるため",
                    "query": "A いつ",
                    "category": "fact_check",
                },
                {
                    "reason": "数値の比較データを確認しないと判断ができないため外部参照が必要です",
                    "query": "A 統計 比較",
                    "category": "data",
                },
            ]
        },
    )
    assert out.external_used is True
    assert out.request is not None
    assert out.request.category == "data"
    assert broker.queries[0] == "A 統計 比較"


def test_merge_output_applies_external_pipeline_result(monkeypatch):
    def _fake_pipeline(
        *,
        say_candidate: str,
        user_text: str,
        selected_depth: int,
        surprise_signal: float,
        candidate_requests: list[dict] | None = None,
        force_fetch: bool = False,
    ):
        assert say_candidate == "元の応答"
        assert selected_depth == 2
        assert isinstance(surprise_signal, float)
        assert surprise_signal == 0.77
        assert isinstance(candidate_requests, list)
        return "外部統合後の応答", "事実確認のため日付照合が必要", {
            "gate_a_pass": True,
            "candidate_count": len(candidate_requests or []),
            "selected_request": {"category": "fact_check", "query": "X いつ"},
            "external_used": True,
            "external_priority": 0.9,
            "external_confidence": 0.7,
            "contradiction_flag": False,
        }

    monkeypatch.setattr("backend.core.agent_graph.nodes.merge._apply_external_data_pipeline", _fake_pipeline)

    state = {
        "safety_route": "safe",
        "draft": "元の応答",
        "depth1_text": "",
        "dissonance_on": False,
        "need_depth1": False,
        "need_depth2": False,
        "user_text": "こんにちは",
        "reason_codes": [],
        "dissonance": 0.0,
        "surprise_score": 0.77,
        "selected_depth": 2,
    }
    out = merge_output(state)
    assert out.get("final_text") == "外部統合後の応答"
    assert out.get("external_reason") == "事実確認のため日付照合が必要"


def test_merge_output_builds_external_candidate_requests(monkeypatch):
    captured: dict = {}

    def _fake_pipeline(
        *,
        say_candidate: str,
        user_text: str,
        selected_depth: int,
        surprise_signal: float,
        candidate_requests: list[dict] | None = None,
        force_fetch: bool = False,
    ):
        captured["candidate_requests"] = list(candidate_requests or [])
        return say_candidate, None, {
            "gate_a_pass": False,
            "candidate_count": len(candidate_requests or []),
            "selected_request": None,
            "external_used": False,
            "external_priority": 0.0,
            "external_confidence": None,
            "contradiction_flag": None,
        }

    monkeypatch.setattr("backend.core.agent_graph.nodes.merge._apply_external_data_pipeline", _fake_pipeline)

    state = {
        "safety_route": "safe",
        "draft": "比較データを見て判断しよう",
        "depth1_text": "",
        "dissonance_on": False,
        "need_depth1": False,
        "need_depth2": False,
        "user_text": "この件の統計を比較して",
        "reason_codes": [],
        "dissonance": 0.2,
        "selected_depth": 1,
    }
    out = merge_output(state)
    assert out.get("final_text") == "比較データを見て判断しよう"
    cands = captured.get("candidate_requests") or []
    assert cands
    assert any(c.get("category") == "data" for c in cands)


def test_merge_output_emits_observation_record(monkeypatch):
    calls: list[dict] = []

    def _fake_log(payload: dict):
        calls.append(dict(payload))

    monkeypatch.setattr("backend.core.agent_graph.nodes.merge.log_turn_observation", _fake_log)

    state = {
        "thread_id": "t-observe",
        "turn_id": "turn-1",
        "safety_route": "safe",
        "draft": "最終応答",
        "depth1_text": "",
        "dissonance_on": False,
        "need_depth1": False,
        "need_depth2": False,
        "user_text": "こんにちは",
        "reason_codes": [],
        "dissonance": 0.11,
        "selected_depth": 1,
    }
    out = merge_output(state)
    assert out.get("final_text") == "最終応答"
    assert calls
    rec = calls[-1]
    assert rec.get("thread_id") == "t-observe"
    assert rec.get("turn_id") == "turn-1"
    assert rec.get("final_text") == "最終応答"
    assert rec.get("merge_mode") == "B"


def test_broker_google_search_success(monkeypatch):
    monkeypatch.setattr(settings, "GOOGLE_API_KEY", "dummy-key")
    monkeypatch.setattr(settings, "GOOGLE_CSE_ID", "dummy-cx")
    monkeypatch.setattr(settings, "EXTERNAL_SEARCH_PROVIDER", "google")

    def _fake_get(url, params=None, timeout=0):
        assert "googleapis.com/customsearch/v1" in url
        assert params["q"] == "X いつ"
        return _Resp(
            {
                "items": [
                    {"title": "X", "snippet": "Xの年は不明", "link": "https://example.com/x"},
                    {"title": "X2", "snippet": "補足", "link": "https://example.com/x2"},
                ]
            }
        )

    monkeypatch.setattr("backend.services.external_data.requests.get", _fake_get)
    broker = ExternalDataBroker(enabled=True)
    req = ExternalDataRequest(
        reason="この事実の年号を確認したいので外部参照が必要です",
        query="X いつ",
        category="fact_check",
    )
    out = broker.fetch(req)
    assert out is not None
    assert out.source == "google_custom_search"
    assert "https://example.com/x" in out.data


def test_broker_auto_fallback_to_wikipedia(monkeypatch):
    monkeypatch.setattr(settings, "GOOGLE_API_KEY", "")
    monkeypatch.setattr(settings, "GOOGLE_CSE_ID", "")
    monkeypatch.setattr(settings, "EXTERNAL_SEARCH_PROVIDER", "auto")

    def _fake_get(url, params=None, timeout=0):
        if "wikipedia.org/w/api.php" in url:
            return _Resp(
                {"query": {"search": [{"title": "X", "snippet": "Xは<strong>説明</strong>です"}]}}
            )
        return _Resp({})

    monkeypatch.setattr("backend.services.external_data.requests.get", _fake_get)
    broker = ExternalDataBroker(enabled=True)
    req = ExternalDataRequest(
        reason="この用語の定義が曖昧で基準を確認したいので外部参照が必要です",
        query="X 定義",
        category="definition",
    )
    out = broker.fetch(req)
    assert out is not None
    assert "wikipedia" in out.source
    assert "<strong>" not in out.data


# --- force_fetch (user explicit search) tests ---

def test_detect_user_search_request():
    from backend.core.agent_graph.nodes import _detect_user_search_request
    assert _detect_user_search_request("プロジェクトAについてググって") is True
    assert _detect_user_search_request("ネットで調べてみて") is True
    assert _detect_user_search_request("検索してみて") is True
    assert _detect_user_search_request("ウェブ検索して") is True
    assert _detect_user_search_request("web検索して") is True
    # ゲーム文脈の「調べて」は反応しない
    assert _detect_user_search_request("周りを調べて") is False
    assert _detect_user_search_request("こんにちは") is False
    assert _detect_user_search_request("データを見せて") is False


def test_force_fetch_bypasses_depth_and_surprise():
    """force_fetch=True のとき depth/surprise ゲートをバイパスする。"""
    from backend.core.agent_graph.nodes import _apply_external_data_pipeline

    candidate = [{"category": "fact_check", "reason": "ユーザーが明示的に事実が不明な情報を確認したいと要求しました", "query": "テスト"}]
    _, _, meta = _apply_external_data_pipeline(
        say_candidate="テスト応答",
        user_text="テストをググって",
        selected_depth=0,  # depth0 = 通常はスキップ
        surprise_signal=0.0,  # surprise 0 = 通常はスキップ
        candidate_requests=candidate,
        force_fetch=True,
    )
    # force_fetch 時はゲートを通過してパイプラインが実行される
    assert meta.get("gate_a_pass") is True


def test_build_candidate_with_user_search_trigger():
    from backend.core.agent_graph.nodes import _build_external_candidate_requests
    candidates = _build_external_candidate_requests(
        user_text="東京タワーについてググって",
        say_candidate="",
    )
    assert len(candidates) >= 1
    assert candidates[0]["category"] == "fact_check"
    assert "ユーザーが明示的" in candidates[0]["reason"]
    # トリガーキーワードが除去されてクエリに含まれない
    assert "ググって" not in candidates[0]["query"]
    # 「について」も除去されてクリーンなクエリ
    assert "東京タワー" in candidates[0]["query"]


def test_extract_search_query_cleans_conversational_text():
    from backend.core.agent_graph.nodes import _extract_search_query
    # 会話文 + 検索要求 → 検索対象だけ抽出
    assert "プロジェクトA" in _extract_search_query("あれー？おかしいな。プロジェクトAについてググって")
    assert "あれー" not in _extract_search_query("あれー？おかしいな。プロジェクトAについてググって")
    # シンプルなケース
    assert "東京タワー" in _extract_search_query("東京タワーについてググって")
    # フィラー + 依頼表現の除去
    q = _extract_search_query("じゃあ、もう一度ジャッキーチェンとプロジェクトAについてググってみてくれる？")
    assert "ジャッキーチェン" in q
    assert "プロジェクトA" in q
    assert "じゃあ" not in q
    assert "もう一度" not in q
    assert "してみてくれる" not in q
    # トリガーだけの場合
    q = _extract_search_query("ググって")
    assert q == "" or len(q) < 3  # 空 or 非常に短い
