"""
Somatic Translator — convert internal metrics to felt-sense text.

Design doc: docs/somatic_self_awareness_design.md
Principle: Hide the mechanism, deliver the experience.

Phase S.1a: rule-based translation, 0 LLM calls, <5 ms.
"""
from __future__ import annotations

from dataclasses import dataclass

from backend.services.memory.somatic_calibration import SomaticCalibration


@dataclass
class InternalMetrics:
    """Raw metrics collected from retrieval + DB stats each turn."""

    # Memory (from retrieval results)
    retrieval_count: int = 0
    top_similarity: float = 0.0
    memory_total: int = 0
    recent_memory_count: int = 0

    # Search intent (from retrieval.detect_intent)
    intent_detected: str = "default"
    topic_keywords_matched: int = 0

    # Time (from telemetry_kv)
    last_sleep_hours_ago: float = 999.0

    # Confidence (from scored memories)
    avg_confidence: float = 0.0
    high_confidence_ratio: float = 0.0

    # v0.2 — dissonance fields (populated by S.1b; defaults for S.1a)
    recent_somatic_contradiction: bool = False
    somatic_accuracy_recent: float = 1.0
    somatic_sample_count: int = 0
    recent_tip_of_tongue: bool = False


@dataclass
class SomaticSense:
    """A single felt-sense expression with intensity."""

    text: str
    intensity: float  # 0.0–1.0


def translate(
    metrics: InternalMetrics,
    calibration: SomaticCalibration | None = None,
) -> list[SomaticSense]:
    """Convert internal metrics to a list of somatic senses.

    All rule-based — no LLM calls.
    """
    if calibration is None:
        calibration = SomaticCalibration()

    senses: list[SomaticSense] = []
    senses.extend(_memory_senses(metrics, calibration))
    senses.extend(_richness_senses(metrics))
    senses.extend(_confidence_senses(metrics))
    senses.extend(_sleep_senses(metrics))
    senses.extend(_temporal_senses(metrics))
    senses.extend(_dissonance_senses(metrics))
    return senses


# ── Sense generators (design doc §3.3) ────────────────────────


def _memory_senses(
    metrics: InternalMetrics, cal: SomaticCalibration,
) -> list[SomaticSense]:
    """Memory retrieval ease — threshold-driven."""
    if metrics.top_similarity >= cal.high_confidence_threshold:
        return [SomaticSense(
            text="この話題については、はっきり覚えていることがある気がする",
            intensity=0.9,
        )]
    if metrics.top_similarity >= cal.medium_confidence_threshold:
        return [SomaticSense(
            text="この話題について、なんとなく覚えがある感覚がある",
            intensity=0.6,
        )]
    if metrics.top_similarity < cal.low_confidence_threshold and metrics.retrieval_count > 0:
        return [SomaticSense(
            text="この話題については、あまり記憶にない感じがする",
            intensity=0.5,
        )]
    return []


def _richness_senses(metrics: InternalMetrics) -> list[SomaticSense]:
    """Memory richness — recent activity and total volume."""
    if metrics.recent_memory_count >= 5:
        return [SomaticSense(
            text="最近いろんなことがあった気がする。頭の中が賑やかな感じ",
            intensity=0.6,
        )]
    if metrics.memory_total < 10:
        return [SomaticSense(
            text="まだあまり多くのことを経験していない感覚がある",
            intensity=0.4,
        )]
    return []


def _confidence_senses(metrics: InternalMetrics) -> list[SomaticSense]:
    """Confidence in retrieved memories."""
    if metrics.avg_confidence >= 0.8:
        return [SomaticSense(
            text="今引き出した記憶には、わりと自信がある",
            intensity=0.7,
        )]
    if metrics.avg_confidence < 0.4 and metrics.retrieval_count > 0:
        return [SomaticSense(
            text="覚えてはいるけど、それが正しいかはちょっと自信がない",
            intensity=0.5,
        )]
    return []


def _sleep_senses(metrics: InternalMetrics) -> list[SomaticSense]:
    """Sleep Cycle recency — mental clarity."""
    if metrics.last_sleep_hours_ago <= 2:
        return [SomaticSense(
            text="少し前に頭が整理された感覚がある。考えがまとまりやすい",
            intensity=0.6,
        )]
    if metrics.last_sleep_hours_ago >= 24:
        return [SomaticSense(
            text="しばらく頭の整理ができていない感じがする。少しぼんやりしている",
            intensity=0.5,
        )]
    return []


def _temporal_senses(metrics: InternalMetrics) -> list[SomaticSense]:
    """Reaction to temporal references in query."""
    if metrics.intent_detected == "temporal" and metrics.topic_keywords_matched > 0:
        return [SomaticSense(
            text="最近のことを思い出そうとしている感覚がある",
            intensity=0.4,
        )]
    return []


def _dissonance_senses(metrics: InternalMetrics) -> list[SomaticSense]:
    """Self-doubt from somatic dissonance (v0.2, populated by S.1b)."""
    senses: list[SomaticSense] = []

    if metrics.recent_somatic_contradiction:
        senses.append(SomaticSense(
            text="さっき自分の記憶を信じたのに間違ってた。少し自分の感覚に自信が持てない",
            intensity=0.7,
        ))

    if metrics.somatic_accuracy_recent < 0.5 and metrics.somatic_sample_count >= 5:
        senses.append(SomaticSense(
            text="最近、覚えてると思ったことが違ってたことが何度かある。記憶が少し曖昧になってるかもしれない",
            intensity=0.6,
        ))

    if metrics.recent_tip_of_tongue:
        senses.append(SomaticSense(
            text="さっき思い出せそうだったのに言葉にならなかった感覚が残ってる",
            intensity=0.5,
        ))

    return senses
