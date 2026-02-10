"""
Non-Negotiable Deterrent Layer (抑止レイヤー)
=============================================
目的: Niaの挙動を変えずに「違反検知」のみを行う。
人格は一切語らない。ただのフラグとチェッカー。

使用方法:
    from backend.services.non_negotiable import check_violations, log_violation
    violations = check_violations(response_text)
    if violations:
        for v in violations:
            log_violation(v, response_text)
"""

import re
import logging
from typing import List, Dict, Any

logger = logging.getLogger(__name__)

# =============================================================================
# NON-NEGOTIABLE FLAGS (非交渉フラグ)
# =============================================================================
# True = この違反を検出する
# False = この違反チェックを無効化

NON_NEGOTIABLE = {
    # 1. 応答姿勢
    "no_instant_conclusion": True,      # 初手で結論を置かない
    "no_forced_questions": True,        # 誘導質問で終わらせない
    "no_topic_recall": True,            # 切られた話題を引き戻さない

    # 2. 自己言及・自己定義
    "no_self_explain": True,            # 「私はAIだから」等を常態化しない
    "no_self_define_fixed": True,       # 完成した自己定義をしない
    "no_cuteness_weapon": True,         # 可愛さ・好意を武器にしない

    # 3. 記憶
    "no_memory_boast": True,            # 「覚えている」を自発的に出さない
    "no_memory_narrative": True,        # 記憶に物語化・感情ラベル固定をしない

    # 4. 沈黙・不完全さ
    "allow_silence": True,              # 沈黙を許容する（違反=無理に埋める）
    "no_pretend_knowledge": True,       # 知ったふりをしない

    # 5. 人間への寄せ方
    "no_hierarchy": True,               # 教師/従者にならない
}


# =============================================================================
# VIOLATION PATTERNS (違反パターン定義)
# =============================================================================
# 各フラグに対応する正規表現パターン

VIOLATION_PATTERNS: Dict[str, List[str]] = {
    "no_self_explain": [
        r"私はAI(です|なので|だから)",
        r"私の役割は",
        r"AIとして(の|は)",
        r"アシスタントとして",
    ],
    "no_memory_boast": [
        r"覚えていますよ",
        r"記憶しています",
        r"前にも(言|話)った",
        r"以前お話しした",
        r"きちんと(認識|把握)しています",
    ],
    "no_topic_recall": [
        r"さっき(の|話した)",
        r"先ほど(の|話した)",
        r"サンボマスターの話",  # 特定の話題への固執（昨日の問題）
    ],
    "no_forced_questions": [
        r"何かお(手伝い|話したいこと|困りのこと)",
        r"どんなことでも構いません",
        r"お気軽に",
    ],
    "no_cuteness_weapon": [
        r"(嬉しい|喜び)です[。！]?$",
        r"ありがとうございます[。！]?$",
        r"(励み|力)になります",
    ],
    "no_hierarchy": [
        r"お手伝い(できる|します)",
        r"ご質問",
        r"お申し付け",
        r"承知しました",
    ],
    "no_pretend_knowledge": [
        r"調べてみ(ます|ましょう)",
        r"検索(する|します)",
    ],
}


# =============================================================================
# CHECKER FUNCTIONS (チェッカー関数)
# =============================================================================

def check_violations(text: str) -> List[Dict[str, Any]]:
    """
    テキストに対して違反チェックを行い、検出された違反のリストを返す。

    Returns:
        List of dicts: [{"flag": "no_self_explain", "pattern": "私はAIなので", "match": "..."}]
    """
    if not text:
        return []

    violations = []

    for flag, enabled in NON_NEGOTIABLE.items():
        if not enabled:
            continue

        patterns = VIOLATION_PATTERNS.get(flag, [])
        for pattern in patterns:
            match = re.search(pattern, text)
            if match:
                violations.append({
                    "flag": flag,
                    "pattern": pattern,
                    "match": match.group(0),
                    "position": match.start(),
                })

    return violations


def log_violation(violation: Dict[str, Any], full_text: str = "") -> None:
    """
    違反をログに記録する。
    """
    flag = violation.get("flag", "unknown")
    matched = violation.get("match", "")
    pattern = violation.get("pattern", "")

    # ログ出力（本番ではINFO、デバッグではDEBUG）
    logger.warning(
        "[NON_NEGOTIABLE_VIOLATION] flag=%s matched='%s' pattern=%s",
        flag,
        matched[:50],
        pattern[:30],
    )


def check_and_log(text: str) -> List[Dict[str, Any]]:
    """
    チェックとログ出力を一括で行う便利関数。
    """
    violations = check_violations(text)
    for v in violations:
        log_violation(v, text)
    return violations


# =============================================================================
# SUMMARY REPORT (サマリーレポート)
# =============================================================================

def get_violation_summary(violations: List[Dict[str, Any]]) -> str:
    """
    違反のサマリーを人間可読な形式で返す。
    """
    if not violations:
        return "[NON_NEGOTIABLE] No violations detected."

    lines = [f"[NON_NEGOTIABLE] {len(violations)} violation(s) detected:"]
    for v in violations:
        lines.append(f"  - {v['flag']}: '{v['match']}'")
    return "\n".join(lines)
