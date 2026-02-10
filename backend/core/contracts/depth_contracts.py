"""
Depth Contracts - 深度別の出力契約定義

Depth0（Pre-Thought）とDepth1（Organize & Ask）の
出力に対する原則（Principle-based Contract）を定義します。
"""

import re
from dataclasses import dataclass, field
from typing import List, Optional


@dataclass
class ValidationResult:
    """契約検証結果"""
    is_valid: bool
    violations: List[str] = field(default_factory=list)
    warnings: List[str] = field(default_factory=list)
    score: float = 1.0  # 0.0 - 1.0, 1.0が完全準拠

    def add_violation(self, message: str, severity: float = 0.2):
        """違反を追加し、スコアを減算"""
        self.violations.append(message)
        self.score = max(0.0, self.score - severity)
        self.is_valid = self.score > 0.5  # 50%超で有効（境界値は無効）

    def add_warning(self, message: str):
        """警告を追加（スコアには影響しない）"""
        self.warnings.append(message)


class Depth0Contract:
    """
    Depth0 (Pre-Thought) の契約

    原則:
    1. 結論を出さない - 断定的な主張を避ける
    2. 不確実性を明示する - 「わからない」「不明」などを積極的に使う
    3. 思考の断片を示す - 完全な答えではなく、考えの材料を提示
    4. 複数の可能性を残す - 一つの解釈に絞り込まない
    5. 即答を避ける - 深い思考が必要なサインを出す
    """

    # 違反パターン（結論的な表現）
    CONCLUSION_PATTERNS = [
        r"〜と思います$",
        r"〜すべきです$",
        r"〜が正しいです$",
        r"答えは〜です",
        r"結論としては",
        r"間違いなく〜",
        r"確実に〜",
        r"〜に決まっています",
        r"絶対に〜",
    ]

    # 推奨パターン（不確実性の表現）
    UNCERTAINTY_PATTERNS = [
        r"わからない",
        r"不明",
        r"はっきりしない",
        r"確信が持てない",
        r"可能性がある",
        r"〜かもしれない",
        r"〜のようだ",
        r"判断が難しい",
        r"情報が不足",
        r"もっと考える必要",
    ]

    # 思考の断片パターン
    FRAGMENT_PATTERNS = [
        r"〜という観点",
        r"〜の側面",
        r"〜を考えると",
        r"一方で",
        r"ただし",
        r"疑問点:",
        r"不明な点:",
        r"要確認:",
    ]

    @classmethod
    def validate(cls, output: str) -> ValidationResult:
        """
        Depth0出力を検証

        Args:
            output: 検証対象の出力テキスト

        Returns:
            ValidationResult: 検証結果
        """
        result = ValidationResult(is_valid=True)

        # 空出力チェック
        if not output or len(output.strip()) < 10:
            result.add_violation("出力が短すぎる（10文字未満）", severity=0.5)
            return result

        # 1. 結論パターンのチェック
        conclusion_count = 0
        for pattern in cls.CONCLUSION_PATTERNS:
            matches = re.findall(pattern, output, re.MULTILINE)
            if matches:
                conclusion_count += len(matches)
                result.add_violation(
                    f"結論的な表現を検出: '{pattern}' ({len(matches)}箇所)",
                    severity=0.15
                )

        # 2. 不確実性の表現チェック
        uncertainty_count = 0
        for pattern in cls.UNCERTAINTY_PATTERNS:
            matches = re.findall(pattern, output, re.IGNORECASE)
            uncertainty_count += len(matches)

        if uncertainty_count == 0:
            result.add_violation(
                "不確実性の表現が見つからない（「わからない」「不明」などを使用すべき）",
                severity=0.3
            )

        # 3. 思考の断片パターンチェック
        fragment_count = 0
        for pattern in cls.FRAGMENT_PATTERNS:
            matches = re.findall(pattern, output, re.IGNORECASE)
            fragment_count += len(matches)

        if fragment_count == 0:
            result.add_warning(
                "思考の断片を示す表現が少ない（推奨: 「〜という観点」「疑問点:」など）"
            )

        # 4. 長さチェック（Depth0は簡潔であるべき）
        if len(output) > 500:
            result.add_warning(
                f"出力が長い（{len(output)}文字）。Depth0は簡潔な断片が推奨される"
            )

        # 5. 質問形式のチェック（Depth0は質問を投げかけるべき）
        question_count = output.count("？") + output.count("?")
        if question_count == 0:
            result.add_warning(
                "質問が含まれていない（推奨: 不明点を質問形式で提示）"
            )

        return result


class Depth1Contract:
    """
    Depth1 (Organize & Ask) の契約

    原則:
    1. 質問を明示する - 不明点を明確な質問として提示
    2. 情報を整理する - 既知の情報と未知の情報を区別
    3. 推論チェーンを示す - 思考過程を段階的に説明
    4. 複数の解釈を提示 - 一つの答えに絞り込まず、選択肢を示す
    5. 次のステップを提案 - より深い理解に必要なアクションを示す
    """

    # 必須要素パターン
    QUESTION_PATTERNS = [
        r"質問[：:]",
        r"不明点[：:]",
        r"確認したい点[：:]",
        r"〜でしょうか？",
        r"〜ですか？",
    ]

    ORGANIZE_PATTERNS = [
        r"既知の情報[：:]",
        r"わかっていること[：:]",
        r"前提[：:]",
        r"未知の情報[：:]",
        r"わからないこと[：:]",
    ]

    REASONING_PATTERNS = [
        r"もし〜なら",
        r"〜の場合",
        r"仮に",
        r"理由[：:]",
        r"根拠[：:]",
        r"ステップ\s*\d+",
        r"第\s*\d+\s*段階",
    ]

    ALTERNATIVES_PATTERNS = [
        r"選択肢\s*\d+",
        r"可能性\s*\d+",
        r"パターン\s*\d+",
        r"A\)\s*",
        r"B\)\s*",
        r"一つ目",
        r"二つ目",
        r"または",
        r"あるいは",
    ]

    NEXT_STEP_PATTERNS = [
        r"次のステップ[：:]",
        r"必要なアクション[：:]",
        r"〜する必要があります",
        r"〜を確認すべき",
        r"〜を調査",
    ]

    @classmethod
    def validate(cls, output: str) -> ValidationResult:
        """
        Depth1出力を検証

        Args:
            output: 検証対象の出力テキスト

        Returns:
            ValidationResult: 検証結果
        """
        result = ValidationResult(is_valid=True)

        # 空出力チェック
        if not output or len(output.strip()) < 20:
            result.add_violation("出力が短すぎる（20文字未満）", severity=0.5)
            return result

        # 1. 質問の明示チェック
        question_found = False
        for pattern in cls.QUESTION_PATTERNS:
            if re.search(pattern, output):
                question_found = True
                break

        if not question_found:
            result.add_violation(
                "質問が明示されていない（推奨: 「質問:」「不明点:」などのセクション）",
                severity=0.25
            )

        # 2. 情報整理のチェック
        organize_found = False
        for pattern in cls.ORGANIZE_PATTERNS:
            if re.search(pattern, output):
                organize_found = True
                break

        if not organize_found:
            result.add_warning(
                "情報整理が不十分（推奨: 「既知の情報」「未知の情報」などで整理）"
            )

        # 3. 推論チェーンのチェック
        reasoning_count = 0
        for pattern in cls.REASONING_PATTERNS:
            matches = re.findall(pattern, output, re.IGNORECASE)
            reasoning_count += len(matches)

        if reasoning_count == 0:
            result.add_violation(
                "推論チェーンが不明確（推奨: 「もし〜なら」「ステップ1」などで段階的に説明）",
                severity=0.2
            )

        # 4. 複数の解釈/選択肢のチェック
        alternatives_count = 0
        for pattern in cls.ALTERNATIVES_PATTERNS:
            matches = re.findall(pattern, output, re.IGNORECASE)
            alternatives_count += len(matches)

        if alternatives_count < 2:
            result.add_warning(
                "複数の解釈・選択肢が提示されていない（推奨: 「選択肢1」「選択肢2」など）"
            )

        # 5. 次のステップのチェック
        next_step_found = False
        for pattern in cls.NEXT_STEP_PATTERNS:
            if re.search(pattern, output):
                next_step_found = True
                break

        if not next_step_found:
            result.add_warning(
                "次のステップが明示されていない（推奨: 「次のステップ:」セクション）"
            )

        # 6. 長さチェック（Depth1は詳細であるべき）
        if len(output) < 100:
            result.add_violation(
                f"出力が短い（{len(output)}文字）。Depth1は詳細な分析が必要",
                severity=0.2
            )

        return result
