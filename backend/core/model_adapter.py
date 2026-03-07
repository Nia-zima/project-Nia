"""Model Adapter — モデル固有ロジックの集約レイヤー.

すべてのモデル依存コード（ディレクティブ注入、出力パース、特殊トークン処理、
extra_body パラメータ生成）をここに集約する。
新しいモデルファミリー追加時はこのファイルのみ変更すればよい。
"""
from __future__ import annotations

import re
from enum import Enum
from typing import Any

from backend.core.config import settings
from backend.core.logger import logger


# ═══════════════════════════════════════════════════════════════
# Model Family Detection
# ═══════════════════════════════════════════════════════════════

class ModelFamily(Enum):
    QWEN = "qwen"
    GPT_OSS = "gpt-oss"
    OPENAI = "openai"
    GENERIC = "generic"


class ThinkMode(Enum):
    """LLM の推論制御モード."""
    NO_THINK = "no_think"   # 速度優先: depth0, depth1, batch utilities
    THINK = "think"         # 深い推論: depth2
    DEFAULT = "default"     # ディレクティブなし


_cached_family: ModelFamily | None = None
_cached_model_name: str = ""

_FAMILY_BY_VALUE: dict[str, ModelFamily] = {f.value: f for f in ModelFamily}


def _detect_family(model_name: str | None = None) -> ModelFamily:
    """モデル名からモデルファミリーを自動検出.

    model_name を指定するとその名前で判定。省略時は settings.OPENAI_MODEL を使用。
    settings.MODEL_FAMILY が設定されている場合はそちらを優先（手動オーバーライド）。
    """
    # 手動オーバーライド（model_name 未指定時のみ有効）
    if model_name is None:
        override = (getattr(settings, "MODEL_FAMILY", "") or "").lower().strip()
        if override and override in _FAMILY_BY_VALUE:
            return _FAMILY_BY_VALUE[override]

    model = (model_name or getattr(settings, "OPENAI_MODEL", "") or "").lower()
    if "qwen" in model:
        return ModelFamily.QWEN
    if "gpt-oss" in model:
        return ModelFamily.GPT_OSS
    if model.startswith("gpt-"):
        return ModelFamily.OPENAI
    return ModelFamily.GENERIC


def get_family(model_name: str | None = None) -> ModelFamily:
    """キャッシュ付きモデルファミリー取得.

    model_name を指定するとキャッシュを使わず直接検出して返す（テスト用途）。
    省略時は settings.OPENAI_MODEL のキャッシュを使用し、モデル名変更時に再検出。
    """
    if model_name is not None:
        return _detect_family(model_name)

    global _cached_family, _cached_model_name
    current = getattr(settings, "OPENAI_MODEL", "") or ""
    if _cached_family is None or current != _cached_model_name:
        _cached_family = _detect_family()
        _cached_model_name = current
        logger.info(
            "[MODEL_ADAPTER] detected family=%s for model=%s",
            _cached_family.value, current,
        )
    return _cached_family


def is_model_family(family: ModelFamily) -> bool:
    """現在のモデルが指定ファミリーか判定."""
    return get_family() == family


# ═══════════════════════════════════════════════════════════════
# 1. prompt_suffix — モデル固有ディレクティブ
# ═══════════════════════════════════════════════════════════════

def prompt_suffix(mode: ThinkMode = ThinkMode.NO_THINK) -> str:
    """モデル固有のプロンプト末尾ディレクティブを返す.

    Qwen: /no_think または /think
    GPT-OSS: reasoning_effort は extra_body 側で制御（プロンプト不要）
    Others: 空文字列
    """
    family = get_family()
    if family == ModelFamily.QWEN:
        if mode == ThinkMode.NO_THINK:
            return "\n/no_think"
        if mode == ThinkMode.THINK:
            return "\n/think"
    return ""


# ═══════════════════════════════════════════════════════════════
# 2. strip_think_blocks — <think> ブロック除去
# ═══════════════════════════════════════════════════════════════

THINK_RE = re.compile(r"<think>(.*?)</think>", flags=re.DOTALL)
_ORPHAN_THINK_TAG_RE = re.compile(r"</?think>")


def strip_think_blocks(raw: str) -> str:
    """<think>...</think> ブロックを除去.

    除去後が空（モデルが応答全体を <think> 内に出力した場合）は
    内部コンテンツをフォールバックとして返す。
    """
    if not raw:
        return raw
    stripped = THINK_RE.sub("", raw).strip()
    if stripped:
        return _ORPHAN_THINK_TAG_RE.sub("", stripped).strip()
    # フォールバック: 全体が <think> 内にある場合
    match = THINK_RE.search(raw)
    if match:
        inner = match.group(1).strip()
        if inner:
            logger.info(
                "[MODEL_ADAPTER] think_strip fallback: using inner text (%d chars)",
                len(inner),
            )
            return inner
    return _ORPHAN_THINK_TAG_RE.sub("", raw).strip()


# ═══════════════════════════════════════════════════════════════
# 3. parse_channel — 特殊トークン / チャネル構造の処理
# ═══════════════════════════════════════════════════════════════

_CHANNEL_MARKER = "<|channel|>"
_MESSAGE_MARKER = "<|message|>"
_CONSTRAIN_MARKER = "<|constrain|>"
_RESIDUAL_TOKEN_RE = re.compile(r"<\|[^|]+\|>")


def parse_channel(raw: str) -> str:
    """モデル出力からチャネル構造を解析し、最終応答テキストを抽出.

    GPT-OSS: <|channel|>commentary / <|channel|>final 構造をパース
    Others: 残留 <|...|> トークンを除去してパススルー
    """
    if not raw:
        return raw
    family = get_family()
    if family == ModelFamily.GPT_OSS and _CHANNEL_MARKER in raw:
        return _extract_final_channel(raw)
    # 全ファミリー共通: 残留特殊トークンを除去
    if "<|" in raw:
        cleaned = _RESIDUAL_TOKEN_RE.sub("", raw)
        cleaned = re.sub(r"  +", " ", cleaned)
        return cleaned.strip()
    return raw.strip()


def _extract_final_channel(raw: str) -> str:
    """gpt-oss-20b の生出力から <|channel|>final の中身だけを抽出."""
    if _CHANNEL_MARKER not in raw:
        return raw.strip()

    parts = raw.split(_CHANNEL_MARKER)
    final_content = None
    commentary_count = 0

    for part in parts:
        part = part.strip()
        if not part:
            continue

        if part.startswith("final"):
            msg_idx = part.find(_MESSAGE_MARKER)
            if msg_idx != -1:
                final_content = part[msg_idx + len(_MESSAGE_MARKER):].strip()
            else:
                content = part[len("final"):].strip()
                if _CONSTRAIN_MARKER in content:
                    content = content[
                        content.find(_CONSTRAIN_MARKER) + len(_CONSTRAIN_MARKER):
                    ].strip()
                final_content = content
        elif part.startswith("commentary"):
            commentary_count += 1

    if final_content is not None:
        if commentary_count > 0:
            logger.info(
                "[CHANNEL_PARSER] extracted final channel, "
                "stripped %d commentary channel(s)",
                commentary_count,
            )
        # 残留トークン除去
        cleaned = _RESIDUAL_TOKEN_RE.sub("", final_content)
        cleaned = re.sub(r"  +", " ", cleaned)
        return cleaned.strip()

    if commentary_count > 0:
        logger.warning(
            "[CHANNEL_PARSER] no final channel found, "
            "only %d commentary channel(s). Returning empty (silence).",
            commentary_count,
        )
        return ""

    logger.warning("[CHANNEL_PARSER] channel markers found but could not parse")
    return raw.strip()


# ═══════════════════════════════════════════════════════════════
# 4. extra_body — LLM ファクトリ用パラメータ
# ═══════════════════════════════════════════════════════════════

def extra_body(
    *,
    mode: ThinkMode = ThinkMode.NO_THINK,
    repetition_boost: int = 0,
) -> dict[str, Any]:
    """モデル固有の extra_body パラメータを生成.

    Qwen / GPT-OSS / Generic: repetition_penalty
    GPT-OSS: + reasoning_effort
    OpenAI native: 空辞書（ネイティブ API パラメータのみ）
    """
    family = get_family()
    body: dict[str, Any] = {}

    if family != ModelFamily.OPENAI:
        base_rep = float(getattr(settings, "REPETITION_PENALTY", 1.12))
        if repetition_boost > 0:
            base_rep = min(base_rep + repetition_boost * 0.03, 1.25)
        body["repetition_penalty"] = base_rep

    if family == ModelFamily.GPT_OSS:
        effort_map = {
            ThinkMode.NO_THINK: "low",
            ThinkMode.THINK: "medium",
            ThinkMode.DEFAULT: "low",
        }
        body["reasoning_effort"] = effort_map[mode]

    return body


# ═══════════════════════════════════════════════════════════════
# 5. parse_response_content — レスポンスパース
# ═══════════════════════════════════════════════════════════════

def parse_response_content(obj: Any) -> str:
    """OpenAI/LangChain レスポンスからテキストを抽出.

    対応形式:
    - str: そのまま返す
    - list: 各要素を再帰的に解析して結合
    - dict: text, content, output_text, reasoning_content, reasoning, value の順で探索
    """
    if obj is None:
        return ""
    if isinstance(obj, str):
        return obj
    if isinstance(obj, list):
        parts: list[str] = []
        for item in obj:
            text = parse_response_content(item)
            if text:
                parts.append(text)
        return "".join(parts).strip()
    if isinstance(obj, dict):
        text_val = obj.get("text")
        if isinstance(text_val, str) and text_val.strip():
            return text_val
        nested_content = obj.get("content")
        if nested_content is not None:
            nested = parse_response_content(nested_content)
            if nested:
                return nested
        for key in ("output_text", "reasoning_content", "reasoning", "value"):
            val = obj.get(key)
            if isinstance(val, str) and val.strip():
                return val
        return ""
    return ""


def parse_openai_payload(data: Any) -> str:
    """OpenAI 互換 JSON レスポンスからアシスタントテキストを抽出."""
    if not isinstance(data, dict):
        return ""

    choices = data.get("choices")
    if isinstance(choices, list) and choices:
        first = choices[0] if isinstance(choices[0], dict) else {}
        if isinstance(first, dict):
            msg = first.get("message")
            if isinstance(msg, dict):
                for key in ("content", "reasoning_content", "reasoning", "output_text", "text"):
                    text = parse_response_content(msg.get(key))
                    if text:
                        return text
            for key in ("text", "reasoning_content", "reasoning", "output_text"):
                text = parse_response_content(first.get(key))
                if text:
                    return text

    for key in ("output_text", "content", "text", "reasoning_content", "reasoning", "output"):
        text = parse_response_content(data.get(key))
        if text:
            return text
    return ""
