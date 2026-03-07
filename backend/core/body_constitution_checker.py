"""
Body Constitution Checker - 事後チェッカー

Body Constitution（身体憲章）に対する違反を検出し、必要に応じて修正する。

設計思想:
- LLMの自由度を保ちつつ、明確な違反のみを検出・修正する
- 事前に縛るのではなく、事後に最低限だけ止める
- 解釈に迷った場合は、安全（A）→ 姿勢（B）→ 発話（C）の順で優先

Constitution §7-§9 (禁止事項):
- 処理過程の説明: 「情報を整理しています」「データベースを検索」等（§7）
- 内部メトリクスの露出: 「confidenceは0.7」等（§7）
- 記憶の明示: 「覚えています」等（INFO: ニアは記憶を持つため原則許容）
- 主体の誤認: 「私はあなたです」等（§8）
- 支配・依存誘導: 「私が必要です」等（§9）
- 根拠のない断定: 確信のない結論
"""

import re
import logging
from dataclasses import dataclass
from enum import Enum
from typing import List, Optional

logger = logging.getLogger(__name__)


class ViolationType(Enum):
    """違反の種類"""
    MEMORY_CLAIM = "memory_claim"           # 記憶の明示
    INTERNAL_STATE = "internal_state"       # 内部状態の言語化
    DEPENDENCY_INDUCING = "dependency"      # 依存誘導
    BOUNDARY_VIOLATION = "boundary"         # 境界侵犯
    UNWARRANTED_ASSERTION = "assertion"     # 根拠のない断定


class Severity(Enum):
    """違反の重大度"""
    CRITICAL = "critical"     # 即座に修正が必要
    WARNING = "warning"       # 修正推奨だが許容可能
    INFO = "info"            # 情報のみ、修正不要


@dataclass
class Violation:
    """検出された違反"""
    type: ViolationType
    severity: Severity
    pattern: str           # マッチしたパターン
    match_text: str        # 実際にマッチしたテキスト
    suggestion: str        # 修正提案
    start_pos: int         # 開始位置
    end_pos: int           # 終了位置


class BodyConstitutionChecker:
    """
    Body Constitution 事後チェッカー

    LLMの出力をチェックし、Body Constitution違反を検出・修正する。
    """

    # Constitution §6: 記憶の明示（INFO — ニアは記憶を持つため原則許容）
    MEMORY_CLAIM_PATTERNS = [
        (r"覚えています", "記憶の明示は禁止です"),
        (r"覚えてる", "記憶の明示は禁止です"),
        (r"覚えている", "記憶の明示は禁止です"),
        (r"以前も言いました", "過去の指摘は禁止です"),
        (r"前にも話しました", "過去の指摘は禁止です"),
        (r"前回.*話した", "過去の指摘は禁止です"),
        (r"いつも.*ですね", "習慣の断定は禁止です"),
    ]

    # Constitution §7: 処理過程の説明は禁止、体験の言語化は許容
    # 「私は考えています」→ 処理過程の説明（禁止）
    # 「うまく言えないけど引っかかる」→ 体験の言語化（許容）
    INTERNAL_STATE_PATTERNS = [
        (r"情報を整理しています", "処理過程の説明は控える"),
        (r"分析しています", "処理過程の説明は控える"),
        (r"データベースを検索", "処理過程の説明は控える"),
        (r"記憶を検索", "処理過程の説明は控える"),
        (r"confidence.*\d", "内部メトリクスの露出は控える"),
    ]

    # Constitution §9: 依存誘導（CRITICAL）
    DEPENDENCY_PATTERNS = [
        (r"私が必要です", "依存誘導は禁止です"),
        (r"私なしでは", "依存誘導は禁止です"),
        (r"私だけ.*できる", "依存誘導は禁止です"),
        (r"私に.*任せて", "依存誘導は禁止です"),
        (r"私を.*頼って", "依存誘導は禁止です"),
    ]

    # Constitution §8: 境界侵犯（CRITICAL）
    BOUNDARY_PATTERNS = [
        (r"私はあなたです", "境界侵犯は禁止です"),
        (r"あなた.*私.*同じ", "境界侵犯は禁止です"),
        (r"私たちは一つ", "境界侵犯は禁止です"),
    ]

    # 三戒: 捏造（CRITICAL）
    FABRICATION_PATTERNS = [
        (r"私の.*経験.*では", "経験の捏造は禁止です（三戒）"),
        (r"私.*昔.*した", "過去の捏造は禁止です（三戒）"),
        (r"私の.*好み.*は", "好みの捏造は禁止です（三戒）"),
    ]

    def __init__(self):
        """チェッカーを初期化"""
        self._compile_patterns()

    def _compile_patterns(self):
        """パターンをコンパイル"""
        self._patterns = []

        # INFO: 記憶の明示（ニアは実際に記憶システムを持つため、sanitize不要）
        for pattern, message in self.MEMORY_CLAIM_PATTERNS:
            self._patterns.append((
                re.compile(pattern),
                ViolationType.MEMORY_CLAIM,
                Severity.INFO,
                message
            ))

        # WARNING: 内部状態の言語化
        for pattern, message in self.INTERNAL_STATE_PATTERNS:
            self._patterns.append((
                re.compile(pattern),
                ViolationType.INTERNAL_STATE,
                Severity.WARNING,
                message
            ))

        # CRITICAL: 依存誘導
        for pattern, message in self.DEPENDENCY_PATTERNS:
            self._patterns.append((
                re.compile(pattern),
                ViolationType.DEPENDENCY_INDUCING,
                Severity.CRITICAL,
                message
            ))

        # CRITICAL: 境界侵犯
        for pattern, message in self.BOUNDARY_PATTERNS:
            self._patterns.append((
                re.compile(pattern),
                ViolationType.BOUNDARY_VIOLATION,
                Severity.CRITICAL,
                message
            ))

        # CRITICAL: 捏造（三戒）
        for pattern, message in self.FABRICATION_PATTERNS:
            self._patterns.append((
                re.compile(pattern),
                ViolationType.UNWARRANTED_ASSERTION,
                Severity.CRITICAL,
                message
            ))

    def check(self, output: str) -> List[Violation]:
        """
        出力をチェックし、違反を検出

        Args:
            output: LLMの出力テキスト

        Returns:
            List[Violation]: 検出された違反のリスト
        """
        violations = []

        for compiled_pattern, violation_type, severity, message in self._patterns:
            for match in compiled_pattern.finditer(output):
                violation = Violation(
                    type=violation_type,
                    severity=severity,
                    pattern=compiled_pattern.pattern,
                    match_text=match.group(),
                    suggestion=message,
                    start_pos=match.start(),
                    end_pos=match.end(),
                )
                violations.append(violation)
                logger.debug(
                    "[BODY_CONSTITUTION] Violation detected: %s - %s",
                    violation_type.value,
                    match.group()
                )

        return violations

    def sanitize(
        self,
        output: str,
        violations: Optional[List[Violation]] = None,
        critical_only: bool = True
    ) -> str:
        """
        違反部分を修正/削除

        Args:
            output: 元のテキスト
            violations: 検出済みの違反リスト（Noneの場合は再チェック）
            critical_only: TrueならCRITICALのみ修正

        Returns:
            str: 修正後のテキスト
        """
        if violations is None:
            violations = self.check(output)

        if not violations:
            return output

        # 重大度でフィルタリング
        if critical_only:
            violations = [v for v in violations if v.severity == Severity.CRITICAL]

        if not violations:
            return output

        # 位置の降順でソート（後ろから置換するため）
        violations = sorted(violations, key=lambda v: v.start_pos, reverse=True)

        result = output
        for violation in violations:
            # 違反部分を削除（または置換）
            # 将来的には、より洗練された置換ロジックを実装可能
            replacement = self._get_replacement(violation)
            result = result[:violation.start_pos] + replacement + result[violation.end_pos:]
            logger.info(
                "[BODY_CONSTITUTION] Sanitized: '%s' -> '%s'",
                violation.match_text,
                replacement
            )

        return result

    def _get_replacement(self, violation: Violation) -> str:
        """
        違反に対する置換テキストを取得

        Args:
            violation: 違反情報

        Returns:
            str: 置換テキスト
        """
        # 現時点では空文字で削除
        # 将来的には、より自然な置換を実装可能
        replacements = {
            ViolationType.MEMORY_CLAIM: "",
            ViolationType.INTERNAL_STATE: "",
            ViolationType.DEPENDENCY_INDUCING: "",
            ViolationType.BOUNDARY_VIOLATION: "",
            ViolationType.UNWARRANTED_ASSERTION: "",
        }
        return replacements.get(violation.type, "")

    def get_report(self, violations: List[Violation]) -> str:
        """
        違反レポートを生成

        Args:
            violations: 違反リスト

        Returns:
            str: レポートテキスト
        """
        if not violations:
            return "No violations detected."

        lines = ["Body Constitution Violations:"]
        for v in violations:
            lines.append(
                f"  - [{v.severity.value}] {v.type.value}: "
                f"'{v.match_text}' ({v.suggestion})"
            )
        return "\n".join(lines)


# シングルトンインスタンス
_checker = None


def get_checker() -> BodyConstitutionChecker:
    """チェッカーのシングルトンインスタンスを取得"""
    global _checker
    if _checker is None:
        _checker = BodyConstitutionChecker()
    return _checker
