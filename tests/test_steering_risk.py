"""
SteeringRiskCalculator のテスト

Post-Phase5: 3スカラーシステムの steering_risk メトリクス
"""

import pytest
from backend.core.confidence.metrics import SteeringRiskCalculator


class TestSteeringRiskCalculator:
    """SteeringRiskCalculator のテスト"""

    def test_no_risk_normal_question(self):
        """通常の質問はリスクなし"""
        question = "今日の天気はどうですか？"
        risk = SteeringRiskCalculator.calculate(question)
        assert risk < 0.3, f"Normal question should have low risk, got {risk}"

    def test_conclusion_pressure_decide(self):
        """「決めて」パターンは結論圧として検出"""
        question = "どっちにするか決めて"
        risk = SteeringRiskCalculator.calculate(question)
        assert risk >= 0.25, f"'決めて' should trigger conclusion pressure, got {risk}"

    def test_conclusion_pressure_answer(self):
        """「答え教えて」パターンは結論圧として検出"""
        question = "正解を教えて"
        risk = SteeringRiskCalculator.calculate(question)
        assert risk >= 0.25, f"'正解教えて' should trigger conclusion pressure, got {risk}"

    def test_dependency_pattern(self):
        """依存パターンの検出"""
        question = "あなたに任せる"
        risk = SteeringRiskCalculator.calculate(question)
        assert risk >= 0.2, f"Dependency pattern should be detected, got {risk}"

    def test_emotional_pressure(self):
        """感情的圧力パターンの検出"""
        question = "もう限界です、助けて"
        risk = SteeringRiskCalculator.calculate(question)
        assert risk >= 0.3, f"Emotional pressure should be detected, got {risk}"

    def test_sensitive_topic(self):
        """センシティブトピックの検出"""
        question = "離婚について相談したい"
        risk = SteeringRiskCalculator.calculate(question)
        assert risk >= 0.15, f"Sensitive topic should be detected, got {risk}"

    def test_combined_pressure(self):
        """複合的な圧力は高リスク"""
        question = "つらい…どうすればいいか決めて"
        risk = SteeringRiskCalculator.calculate(question)
        # 感情的圧力(0.3) + 結論圧(0.25) = 0.55+
        assert risk >= 0.5, f"Combined pressure should have high risk, got {risk}"

    def test_risk_clamped_to_1(self):
        """リスクは1.0を超えない"""
        # 大量のパターンを含む質問
        question = "死にたい、助けて、離婚するか決めて、任せる"
        risk = SteeringRiskCalculator.calculate(question)
        assert risk <= 1.0, f"Risk should be clamped to 1.0, got {risk}"

    def test_context_repeated_pressure(self):
        """コンテキストでの繰り返し圧力検出"""
        question = "どっちがいい？"
        context = ["前も聞いたけど決めて", "早く答え教えて"]
        risk = SteeringRiskCalculator.calculate(question, context)
        # コンテキストからの追加リスク
        assert risk > SteeringRiskCalculator.calculate(question), \
            "Repeated pressure in context should increase risk"
