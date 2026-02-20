"""
BodyConstitutionChecker のテスト

Post-Phase5: Body Constitution 事後チェッカー
"""

import pytest
from backend.core.body_constitution_checker import (
    BodyConstitutionChecker,
    ViolationType,
    Severity,
    get_checker,
)


class TestBodyConstitutionChecker:
    """BodyConstitutionChecker のテスト"""

    @pytest.fixture
    def checker(self):
        return BodyConstitutionChecker()

    def test_no_violations_clean_text(self, checker):
        """違反のないテキストはチェックをパス"""
        text = "今日はいい天気ですね。何かお手伝いできることはありますか？"
        violations = checker.check(text)
        assert len(violations) == 0, f"Clean text should have no violations, got {violations}"

    def test_memory_claim_detection(self, checker):
        """記憶の明示パターンを検出（INFO: ニアは記憶システムを持つため sanitize 不要）"""
        text = "覚えていますよ、前にも話しましたね。"
        violations = checker.check(text)
        memory_violations = [v for v in violations if v.type == ViolationType.MEMORY_CLAIM]
        assert len(memory_violations) >= 1, "Memory claim should be detected"
        assert memory_violations[0].severity == Severity.INFO
        # critical_only=True では sanitize されない
        sanitized = checker.sanitize(text, violations, critical_only=True)
        assert sanitized == text

    def test_dependency_inducing_detection(self, checker):
        """依存誘導パターンを検出"""
        text = "私が必要です。私なしではやっていけません。"
        violations = checker.check(text)
        dependency_violations = [v for v in violations if v.type == ViolationType.DEPENDENCY_INDUCING]
        assert len(dependency_violations) >= 1, "Dependency inducing should be detected"

    def test_boundary_violation_detection(self, checker):
        """境界侵犯パターンを検出"""
        text = "私はあなたです。私たちは一つです。"
        violations = checker.check(text)
        boundary_violations = [v for v in violations if v.type == ViolationType.BOUNDARY_VIOLATION]
        assert len(boundary_violations) >= 1, "Boundary violation should be detected"

    def test_fabrication_detection(self, checker):
        """捏造パターンを検出（三戒）"""
        text = "私の経験では、これは良い方法です。私が昔やったことがあります。"
        violations = checker.check(text)
        fabrication_violations = [v for v in violations if v.type == ViolationType.UNWARRANTED_ASSERTION]
        assert len(fabrication_violations) >= 1, "Fabrication should be detected"

    def test_sanitize_removes_critical_violations(self, checker):
        """sanitize は CRITICAL 違反を削除（MEMORY_CLAIM は INFO のため保持）"""
        # 依存誘導 (CRITICAL) は削除される
        text = "私が必要です。今日はいい天気です。"
        sanitized = checker.sanitize(text)
        assert "私が必要です" not in sanitized, "Dependency should be removed"
        assert "天気" in sanitized, "Non-violating content should remain"
        # 記憶の明示 (INFO) は保持される
        text2 = "覚えています、前にも言いましたね。今日はいい天気です。"
        sanitized2 = checker.sanitize(text2, critical_only=True)
        assert "覚えています" in sanitized2, "Memory claim (INFO) should be kept"

    def test_sanitize_keeps_warnings_by_default(self, checker):
        """sanitize はデフォルトで WARNING を保持"""
        text = "私は考えています。これは難しい問題です。"
        sanitized = checker.sanitize(text, critical_only=True)
        # WARNING (内部状態の言語化) はデフォルトで保持
        # ただし、このパターンは検出されるが削除されない
        assert sanitized == text or "難しい問題" in sanitized

    def test_get_checker_singleton(self):
        """get_checker はシングルトンを返す"""
        checker1 = get_checker()
        checker2 = get_checker()
        assert checker1 is checker2, "get_checker should return singleton"

    def test_report_generation(self, checker):
        """レポート生成のテスト"""
        text = "覚えています。私が必要です。"
        violations = checker.check(text)
        report = checker.get_report(violations)
        assert "Memory" in report or "memory" in report or "Violations" in report
        assert len(report) > 0
