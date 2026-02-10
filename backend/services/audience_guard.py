from typing import Dict, Tuple

_HIGH_VIEWER_THRESHOLD = 50
_MASS_VIEWER_THRESHOLD = 200
_AGGRESSIVE_TONES = {"煽り", "攻撃的", "炎上", "aggressive"}

def build_audience_meta(
    viewer_count: int,
    interaction_type: str,
    tone: str = "neutral"
) -> Dict:
    """
    配信メタデータの構築ヘルパー
    interaction_type: "question", "smalltalk", "mass_reaction", "provocation", "emotional_dump"
    """
    return {
        "source": "livestream",
        "audience_mode": True,
        "viewer_count": viewer_count,
        "interaction_type": interaction_type,
        "tone": tone
    }

def compute_audience_bias(meta: Dict) -> float:
    """
    集団影響度（Bias Score）を 0.0(個人) - 1.0(群衆/炎上) で算出
    """
    if not meta or not meta.get("audience_mode"):
        return 0.0

    score = 0.0
    viewer_count = meta.get("viewer_count", 0)
    interaction = meta.get("interaction_type", "smalltalk")
    tone = meta.get("tone", "neutral")

    # 1. 規模バイアス
    if viewer_count >= _HIGH_VIEWER_THRESHOLD:
        score += 0.2
    if viewer_count >= _MASS_VIEWER_THRESHOLD:
        score += 0.2

    # 2. 種類バイアス
    if interaction == "mass_reaction": score += 0.3
    elif interaction == "provocation": score += 0.5
    elif interaction == "emotional_dump": score -= 0.1

    # 3. トーンバイアス
    if tone in _AGGRESSIVE_TONES:
        score += 0.3

    return max(0.0, min(1.0, score))

def apply_audience_attenuation(
    surprise: float,
    confidence: float,  # ← 修正: importance から confidence に統一
    bias_score: float
) -> Tuple[float, float]:
    """
    Biasスコアに基づいて減衰させる
    """
    # Surprise: バイアスが高い＝ただのノイズ
    adjusted_surprise = surprise * (1.0 - bias_score)
    
    # Confidence: バイアスが高くても「事実」としては少し残す (係数0.8)
    adjusted_confidence = confidence * (1.0 - (bias_score * 0.8))

    return round(adjusted_surprise, 3), round(adjusted_confidence, 3)
