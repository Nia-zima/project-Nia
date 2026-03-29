"""
Depth Contracts のテスト

Depth0Contract と Depth1Contract の動作を検証するテストスイート。
"""

import pytest
from backend.core.contracts import (
    Depth0Contract,
    Depth1Contract,
    ValidationResult,
    ContractValidator,
)


class TestDepth0Contract:
    """Depth0Contract のテスト"""

    def test_valid_depth0_output(self):
        """有効なDepth0出力のテスト"""
        valid_output = """
        この質問については、いくつかの観点から考える必要があるようです。

        まず、〜という側面を考えると、よくわからない部分があります。
        一方で、〜の可能性もあるかもしれません。

        疑問点:
        - 〜は確認できていない
        - 〜の情報が不足している

        もっと考える必要がありそうです。
        """
        result = Depth0Contract.validate(valid_output)
        assert result.is_valid
        assert result.score >= 0.7

    def test_invalid_depth0_with_conclusions(self):
        """結論を含む無効なDepth0出力のテスト"""
        invalid_output = """
        答えは明確です。〜すべきです。
        結論としては、〜が正しいです。
        間違いなく〜だと思います。
        """
        result = Depth0Contract.validate(invalid_output)
        assert not result.is_valid
        assert len(result.violations) > 0
        assert result.score < 0.5

    def test_depth0_without_uncertainty(self):
        """不確実性の表現がない出力のテスト"""
        output = """
        これは簡単な問題です。
        解決策は以下の通りです。
        実行すれば問題ありません。
        """
        result = Depth0Contract.validate(output)
        # 不確実性がないため、違反が検出されるべき
        violations_text = " ".join(result.violations)
        assert "不確実性" in violations_text or result.score < 0.8

    def test_depth0_empty_output(self):
        """空出力のテスト"""
        result = Depth0Contract.validate("")
        assert not result.is_valid
        assert "短すぎる" in result.violations[0]

    def test_depth0_with_questions(self):
        """質問を含む出力のテスト（推奨）"""
        output = """
        この点についてはよくわかりません。

        いくつか疑問があります:
        - 〜はどうなっているのでしょうか？
        - 〜は確認できますか？

        もっと情報が必要かもしれません。
        """
        result = Depth0Contract.validate(output)
        assert result.is_valid
        # 質問があるので警告は少ないはず
        assert len(result.warnings) <= 2


class TestDepth1Contract:
    """Depth1Contract のテスト"""

    def test_valid_depth1_output(self):
        """有効なDepth1出力のテスト"""
        valid_output = """
        質問: 〜についてどう考えるべきでしょうか？

        既知の情報:
        - Aは確認済み
        - Bは前提として与えられている

        未知の情報:
        - Cは不明
        - Dは確認が必要

        推論チェーン:
        ステップ1: もしAならば、〜となる
        ステップ2: その場合、〜を考慮する必要がある
        ステップ3: 仮にBであれば、〜の可能性がある

        選択肢1: 〜のアプローチ
        選択肢2: または、〜の方法

        次のステップ: 〜を確認する必要があります
        """
        result = Depth1Contract.validate(valid_output)
        assert result.is_valid
        assert result.score >= 0.7

    def test_invalid_depth1_without_questions(self):
        """質問がない無効なDepth1出力のテスト"""
        invalid_output = """
        これはシンプルな状況です。
        情報は十分に揃っています。
        特に疑問はありません。
        """
        result = Depth1Contract.validate(invalid_output)
        violations_text = " ".join(result.violations)
        assert "質問" in violations_text

    def test_depth1_without_organization(self):
        """情報整理がない出力のテスト"""
        output = """
        質問: 〜はどうでしょうか？

        いろいろ考えられます。
        推論すると〜となります。
        """
        result = Depth1Contract.validate(output)
        warnings_text = " ".join(result.warnings)
        assert "情報整理" in warnings_text or "既知" in warnings_text

    def test_depth1_without_reasoning(self):
        """推論チェーンがない出力のテスト"""
        output = """
        質問: 〜について

        既知の情報: A, B, C
        未知の情報: X, Y, Z

        結論は〜です。
        """
        result = Depth1Contract.validate(output)
        violations_text = " ".join(result.violations)
        assert "推論" in violations_text

    def test_depth1_with_single_option(self):
        """選択肢が一つしかない出力のテスト"""
        output = """
        質問: 〜について

        既知の情報: A
        未知の情報: B

        推論:
        ステップ1: もしAなら〜
        ステップ2: したがって〜

        唯一の方法は〜です。
        """
        result = Depth1Contract.validate(output)
        warnings_text = " ".join(result.warnings)
        assert "複数の解釈" in warnings_text or "選択肢" in warnings_text

    def test_depth1_short_output(self):
        """短すぎるDepth1出力のテスト"""
        output = "質問: 〜?"
        result = Depth1Contract.validate(output)
        # 短い出力は違反として検出される
        assert len(result.violations) > 0
        assert result.score < 0.8


class TestContractValidator:
    """ContractValidator のテスト"""

    def test_validate_by_depth_0(self):
        """Depth0の検証テスト"""
        validator = ContractValidator()
        output = "これはわからない点が多いです。もっと考える必要がありそうです。"
        result = validator.validate_by_depth(0, output)
        assert isinstance(result, ValidationResult)
        assert result.is_valid

    def test_validate_by_depth_1(self):
        """Depth1の検証テスト"""
        validator = ContractValidator()
        output = """
        質問: 〜について

        既知の情報: A
        未知の情報: B

        推論:
        ステップ1: もしAなら〜
        ステップ2: その場合〜

        選択肢1: 〜
        選択肢2: または〜

        次のステップ: 〜を確認すべき
        """
        result = validator.validate_by_depth(1, output)
        assert isinstance(result, ValidationResult)
        assert result.is_valid

    def test_validate_invalid_depth(self):
        """未対応の深度のテスト"""
        validator = ContractValidator()
        result = validator.validate_by_depth(999, "test")
        assert not result.is_valid
        assert "未対応の深度" in result.violations[0]

    def test_generate_compliance_report(self):
        """コンプライアンスレポート生成のテスト"""
        validator = ContractValidator()
        # DBが存在しない場合でもエラーにならないことを確認
        report = validator.generate_compliance_report()
        assert isinstance(report, str)
        assert "Compliance Report" in report


class TestValidationResult:
    """ValidationResult のテスト"""

    def test_add_violation(self):
        """違反追加のテスト"""
        result = ValidationResult(is_valid=True)
        initial_score = result.score

        result.add_violation("Test violation", severity=0.3)

        assert len(result.violations) == 1
        assert result.score < initial_score
        assert result.score == initial_score - 0.3

    def test_add_warning(self):
        """警告追加のテスト"""
        result = ValidationResult(is_valid=True)
        initial_score = result.score

        result.add_warning("Test warning")

        assert len(result.warnings) == 1
        assert result.score == initial_score  # 警告はスコアに影響しない

    def test_validity_threshold(self):
        """有効性閾値のテスト"""
        result = ValidationResult(is_valid=True)

        # スコアが50%未満になると無効になる
        result.add_violation("Major violation", severity=0.6)

        assert not result.is_valid
        assert result.score < 0.5


# 統合テスト
class TestIntegration:
    """統合テスト"""

    def test_depth0_to_depth1_progression(self):
        """Depth0からDepth1への進行のテスト"""
        # Depth0: 不確実性を示す
        depth0_output = """
        この質問については複数の観点があるようです。

        疑問点:
        - 〜はどうなっているか？
        - 〜は確認できていない

        もっと情報が必要かもしれません。
        """
        depth0_result = Depth0Contract.validate(depth0_output)
        assert depth0_result.is_valid

        # Depth1: 質問を整理して深く分析
        depth1_output = """
        質問: 〜についての詳細はどうなっていますか？

        既知の情報:
        - Aは確認済み
        - Bは前提

        未知の情報:
        - Cは不明
        - Dは要確認

        推論チェーン:
        ステップ1: もしAならば〜
        ステップ2: その場合、〜となる

        選択肢1: 〜のアプローチ
        選択肢2: または〜の方法

        次のステップ: 〜を確認する必要がある
        """
        depth1_result = Depth1Contract.validate(depth1_output)
        assert depth1_result.is_valid

        # Depth1のスコアはDepth0と同等以上であるべき
        # （より詳細な分析が要求されるため）
        assert depth1_result.score >= 0.6


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
