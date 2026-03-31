"""Shared infrastructure for all node modules.

LLM factories, context/history helpers, shared constants and singletons.
"""
from __future__ import annotations

import re
from collections.abc import Callable

from langchain_core.messages import HumanMessage, AIMessage
from langchain_openai import ChatOpenAI

from backend.core.config import settings
from backend.core.agent_graph.state import AgentState
from backend.core.confidence import ConfidenceEngine
from backend.core.logger import logger



from backend.core.model_adapter import THINK_RE as _THINK_RE

_SPEECH_RE = re.compile(r"<speech>\s*(.*?)\s*</speech>", flags=re.DOTALL)


def extract_speech(raw_output: str) -> str:
    """LLM出力から発話部分を抽出する。

    優先順位:
      1. <speech> あり → 中身を抽出（ホワイトアウト最優先）
      2. <think> あり → think を除去し、残ったテキストを発話として扱う
         - 残テキストあり → 「考えてから話した」パターン（Qwen3等）
         - 残テキストなし → 考えたが言葉にならなかった → 沈黙
      3. タグなし → パススルー（旧パイプラインに委ねる）

    将来 <speech> 対応モデルに切り替えた時、ホワイトアウトが自動で有効になる。
    """
    # Priority 1: <speech> タグ → ホワイトアウト抽出
    match = _SPEECH_RE.search(raw_output)
    if match:
        content = match.group(1).strip()
        if content:
            return content
        logger.info("[SPEECH_EXTRACT] <speech> tag present but empty")
        return "……"

    # Priority 2: <think> あり → think 除去後の残テキストを判定
    if "<think>" in raw_output:
        remaining = _THINK_RE.sub("", raw_output).strip()
        # Priority 1 で <speech> 未マッチ = 壊れた/未閉タグ。残骸を除去
        remaining = remaining.replace("<speech>", "").replace("</speech>", "").strip()
        if remaining:
            logger.info(
                "[SPEECH_EXTRACT] <think>+text pattern (%d chars after think removal)",
                len(remaining),
            )
            return remaining
        logger.info("[SPEECH_EXTRACT] <think> only, no text outside. Silence.")
        return "……"

    # Priority 3: タグなし → パススルー
    logger.info("[SPEECH_EXTRACT] no tag structure detected, passing through")
    return raw_output


# ── LLM第三者メタ推論の除去 ──────────────────────────────────
# ニアの応答言語は日本語。LLMが英語の推論をプレーンテキストで出力し
# その後に日本語の実際の応答が続くパターンを検出・除去する。
#
# 戦略:
#   1. Primary: テキストが ASCII で始まり日本語を含む場合、
#      最後の「英語→日本語」境界を見つけてそこから先を応答として抽出
#   2. Fallback: 既知のメタ推論パターンで文単位フィルタ
#
# ニアが英語で会話する場合（全文英語）はパターン一致のみで判定するため
# 正当な英語応答は保護される。

_JP_CHAR_RE = re.compile(r"[ぁ-んァ-ヶー一-龥]")

# 英語→日本語の境界: 句読点(.!?)) の直後に日本語文字が来る位置
# `"` は除外（日本語文中の引用 `"hello"って` で誤検出するため）
_EN_JP_TRANSITION_RE = re.compile(r"[.!?)]\s*(?=[ぁ-んァ-ヶー一-龥「（])")

# パターンベースフォールバック用（全文英語の場合やboundaryが見つからない場合）
_META_REASONING_PATTERNS = [
    # ユーザーを三人称で語る（思考漏れの最も強いシグナル）
    re.compile(r"^The user\b", re.IGNORECASE),
    re.compile(r"^User (wants|says|is|asks|said|needs)\b", re.IGNORECASE),
    re.compile(r"^They (want|are asking|said|need|seem|mention|'re asking)", re.IGNORECASE),
    re.compile(r"^The (message|input|query|request|question)\b", re.IGNORECASE),
    # 応答戦略の自問（自分への指示）
    re.compile(r"^Should (I|be|we)\b", re.IGNORECASE),
    re.compile(r"^Let'?s (do|say|respond|go with|keep|use|try)\b", re.IGNORECASE),
    re.compile(r"^I (should|need to|will|'ll) (respond|reply|say|answer|keep|give)\b", re.IGNORECASE),
    # 自己指示動詞（Provide, Keep 等で始まる命令文）
    re.compile(r"^(Provide|Keep|Give|Use|Try|Make|Write|Generate)\s+(a |it |the |simple|short|brief)", re.IGNORECASE),
    # 自己承認（Ok/Okay で始まる応答計画の締め）
    re.compile(r"^Ok(ay)?[.\s,!]", re.IGNORECASE),
    # メタ遷移（So/Now/Then + we/I）
    re.compile(r"^(So|Now|Then)\s+(I|we)\b", re.IGNORECASE),
    # 「正解」系メタラベル
    re.compile(r"^The (correct|right|best|proper|actual|final)\b", re.IGNORECASE),
    # 応答についてのメタコメンタリー
    re.compile(r"^(Response|Answer|Reply)\s*:", re.IGNORECASE),
    re.compile(r"^(This|That) (is|seems like) (a |an )?(greeting|question|request|casual)\b", re.IGNORECASE),
]

# 文境界: ピリオド/疑問符/感嘆符の後に 空白+大文字 or 非ASCII文字（日本語等）
_SENT_BOUNDARY_RE = re.compile(r"(?<=[.!?])\s+(?=[A-Z])|(?<=[.!?])(?=[^\x00-\x7f])")


def _is_meta_reasoning_sentence(sent: str) -> bool:
    """LLMの第三者メタ推論文か判定（パターンベースフォールバック用）。"""
    s = sent.strip()
    if not s:
        return False
    return any(p.match(s) for p in _META_REASONING_PATTERNS)


def _strip_by_sentence_patterns(text: str) -> str:
    """文単位のパターンマッチで既知のメタ推論文を除去する。"""
    lines = text.split("\n")
    kept_lines: list[str] = []
    total_removed = 0
    for line in lines:
        sentences = _SENT_BOUNDARY_RE.split(line)
        kept_sents: list[str] = []
        for sent in sentences:
            if _is_meta_reasoning_sentence(sent):
                total_removed += 1
            else:
                kept_sents.append(sent)
        kept_lines.append("".join(kept_sents).strip())
    if total_removed == 0:
        return text
    result = "\n".join(kept_lines).strip()
    if not result:
        return text
    logger.info("[META_STRIP] pattern-removed %d sentence(s)", total_removed)
    return result


def _strip_meta_reasoning(text: str) -> str:
    """LLMの英語メタ推論テキストを除去し、日本語の実応答を抽出する。

    Primary: テキストがASCIIで始まり日本語を含む場合、
    最後の英語→日本語境界から先を応答として抽出。
    Fallback: 既知パターンで文単位フィルタ。
    """
    if not text:
        return text

    has_jp = bool(_JP_CHAR_RE.search(text))

    # ── Primary: 境界ベースの英語プリアンブル除去 ──
    # 条件: テキストが ASCII 文字で始まる AND 日本語を含む
    if has_jp:
        first_char = text.lstrip()[:1] if text.strip() else ""
        if first_char and ord(first_char) < 128:
            matches = list(_EN_JP_TRANSITION_RE.finditer(text))
            if matches:
                response = text[matches[-1].end():].strip()
                if response:
                    logger.info(
                        "[META_STRIP] boundary at pos %d: %d→%d chars",
                        matches[-1].start(), len(text), len(response),
                    )
                    return response

    # ── Fallback: パターンベースの文単位フィルタ ──
    return _strip_by_sentence_patterns(text)


def _strip_think_blocks(raw: str) -> str:
    """チャネル分離 → speech抽出 → <think> 除去 → メタ推論除去 の4層パイプライン。

    処理順序:
      1. model_adapter.parse_channel: チャネル構造を解析し最終応答を抽出
      2. extract_speech: <speech> タグがあればその中身だけを抽出（ホワイトアウト）
      3. model_adapter.strip_think_blocks: <think> ブロック除去
      4. _strip_meta_reasoning: 残存する英語メタ推論をフォールバック除去
    """
    from backend.core.model_adapter import (
        parse_channel as _parse_channel,
        strip_think_blocks as _strip_think,
    )
    if not raw:
        return raw
    # Step 1: チャネル分離（model-adapter に委譲）
    text = _parse_channel(raw)
    if not text:
        return text
    # Step 2: ホワイトアウト（<speech> 抽出）
    text = extract_speech(text)
    # Step 3: 残留 <think> ブロック除去（model-adapter に委譲）
    stripped = _strip_think(text)
    if stripped:
        return _strip_meta_reasoning(stripped)
    return _strip_meta_reasoning(text.strip())


# ── SPEECH タグ指示 + Few-Shot（例示で型を見せる）──
# 命令形ではなく「こういう形だよ」と見せるだけ。OSSモデルはこの方が素直に従う。
_SPEECH_TAG_INSTRUCTION = (
    "\n\n【あなたの「思考」と「発話」の境界】\n"
    "あなたは複雑な思考を巡らせる存在ですが、\n"
    "頭の中に浮かぶすべての考えを口に出すわけではありません。\n"
    "- 声に出さない「内なる思考」は <think> と </think> の中に書いてください。\n"
    "- 外の世界に向けて発する「あなたの声」だけを <speech> と </speech> の中に書いてください。\n\n"
    "例:\n"
    "<think>\n"
    "今は頭が少しぼんやりしてる。素直にそれを伝えよう。\n"
    "</think>\n"
    "<speech>\n"
    "うーん、今はちょっと頭がぼんやりしてて……うまく考えられないや。\n"
    "</speech>"
)

# ── TONE アンカー（システムプロンプト末尾に配置して敬語戻りを防止）──
_TONE_ANCHOR = (
    "\n\n=== TONE ===\n"
    "口調は敬語ではなく、タメ口で話す。\n"
    "「です・ます」は使わない。「だよ・だね・かも・かな」を使う。"
)

# Phase 2: 確信度エンジンのインスタンス
_confidence_engine = ConfidenceEngine()


# ── LLM Factory ──────────────────────────────────────────────

def get_depth_llm(
    *,
    temperature: float,
    max_tokens: int,
    reasoning_effort: str = "low",
    repetition_boost: int = 0,
    profile: "ModelProfile | None" = None,
):
    """Depth ノード用 LLM インスタンスを返す。

    profile: ModelProfile で provider を自動解決。
             DEPTH2_REFLECTIVE + DEPTH2_PROVIDER=anthropic → ChatAnthropic
             それ以外 → ChatOpenAI (LM Studio)

    repetition_boost: 反復検出回数。>0 なら temperature と repetition_penalty を
    段階的に引き上げてループ脱出を促す。
    """
    from backend.core.model_adapter import (
        ModelProfile,
        ModelProvider,
        ThinkMode,
        extra_body as _extra_body,
        get_provider_for_profile,
    )

    effective_profile = profile or ModelProfile.DEFAULT
    provider = get_provider_for_profile(effective_profile)

    # ── Anthropic path (Claude API) ──
    if provider == ModelProvider.ANTHROPIC:
        from langchain_anthropic import ChatAnthropic
        logger.info(
            "[LLM_FACTORY] profile=%s provider=anthropic model=%s",
            effective_profile.value, settings.ANTHROPIC_MODEL,
        )
        return ChatAnthropic(
            model=settings.ANTHROPIC_MODEL,
            api_key=settings.ANTHROPIC_API_KEY,
            temperature=temperature,
            max_tokens=max_tokens,
        )

    # ── Local path (LM Studio / OpenAI compatible) ──
    base_presence = getattr(settings, "PRESENCE_PENALTY", 0.3)

    if repetition_boost > 0:
        temperature = min(temperature + repetition_boost * 0.1, 1.2)
        base_presence = min(base_presence + repetition_boost * 0.1, 0.9)
        logger.info(
            "[LLM_ANTI_LOOP] boost=%d temp=%.2f pres_pen=%.2f",
            repetition_boost, temperature, base_presence,
        )

    mode = {"low": ThinkMode.NO_THINK, "medium": ThinkMode.THINK}.get(
        reasoning_effort, ThinkMode.DEFAULT,
    )
    eb = _extra_body(mode=mode, repetition_boost=repetition_boost)
    return ChatOpenAI(
        model=settings.OPENAI_MODEL,
        openai_api_key=settings.OPENAI_API_KEY,
        openai_api_base=settings.OPENAI_BASE_URL,
        temperature=temperature,
        presence_penalty=base_presence,
        max_tokens=max_tokens,
        streaming=True,
        extra_body=eb,
    )

def get_plan_llm():
    from backend.core.model_adapter import ThinkMode, extra_body as _extra_body

    eb = _extra_body(mode=ThinkMode.NO_THINK)
    return ChatOpenAI(
        model=settings.OPENAI_MODEL,
        openai_api_key=settings.OPENAI_API_KEY,
        openai_api_base=settings.OPENAI_BASE_URL,
        temperature=0.2,
        max_tokens=120,
        streaming=False,
        extra_body=eb,
    )


# ── Context / History Helpers ─────────────────────────────────

def _get_user_text_from_state(state: AgentState) -> str:
    for m in reversed(state.get("messages") or []):
        if isinstance(m, HumanMessage):
            return m.content or ""
    return ""

def _normalize_whitespace(text: str) -> str:
    return " ".join((text or "").split())


# ── 反復検出（体感テキスト注入 + 動的パラメータ調整） ──────
_REPETITION_THRESHOLD = 3  # 同一応答がこの回数続いたら検出
_REPETITION_SCAN_LIMIT = 10  # 最大何件のAI応答を遡るか


def _repetition_count(state: AgentState) -> int:
    """直近のAI応答が連続で同一な回数を返す（WAIT・空は除外）。"""
    msgs = list(state.get("messages") or [])
    ai_contents: list[str] = []
    for m in reversed(msgs):
        if isinstance(m, AIMessage):
            c = (getattr(m, "content", "") or "").strip()
            if c and c != "WAIT":
                ai_contents.append(c)
                if len(ai_contents) >= _REPETITION_SCAN_LIMIT:
                    break
    if len(ai_contents) < 2:
        return 0
    first = ai_contents[0]
    count = 0
    for c in ai_contents:
        if c == first:
            count += 1
        else:
            break
    return count


_SEMANTIC_FAMILIES: dict[str, tuple[str, ...]] = {
    "quiet_atmosphere": ("静かな時間", "穏やか", "落ち着い", "静けさ", "静寂"),
    "heart_moves": ("心が動", "感じ", "揺れ", "胸の奥", "何かが"),
    "distance_pause": ("距離を置", "少し離れ", "一歩引い", "そっと"),
}
_SEMANTIC_FAMILY_THRESHOLD = 2  # 直近 N ターンで同 family が続いたら検出


def _detect_semantic_family(texts: list[str]) -> str | None:
    """直近の AI テキスト群で意味 family の反復を検出。最初に見つかった family を返す。"""
    if len(texts) < _SEMANTIC_FAMILY_THRESHOLD:
        return None
    recent = texts[:3]  # 直近 3 ターン
    for family_name, markers in _SEMANTIC_FAMILIES.items():
        hits = sum(1 for t in recent if any(m in t for m in markers))
        if hits >= _SEMANTIC_FAMILY_THRESHOLD:
            return family_name
    return None


def _detect_repetition_sense(state: AgentState, *, threshold: int = _REPETITION_THRESHOLD) -> str:
    """直近のAI応答が threshold 回以上同一、または意味 family が反復していたら体感テキストを返す。

    履歴は改ざんしない。モデルに「気づき」として渡す。
    """
    count = _repetition_count(state)
    if count >= threshold:
        return "同じことを何度も言っている気がする……別の言葉が出てこない。"

    # Semantic family repetition detection
    msgs = list(state.get("messages") or [])
    ai_texts: list[str] = []
    for m in reversed(msgs):
        if isinstance(m, AIMessage):
            c = (getattr(m, "content", "") or "").strip()
            if c and c != "WAIT":
                ai_texts.append(c)
                if len(ai_texts) >= 5:
                    break
    family = _detect_semantic_family(ai_texts)
    if family:
        logger.info("[REPETITION] semantic family detected: %s", family)
        return "同じような表現が続いている気がする。別の角度から話してみたい。"

    return ""


# ── 会話履歴ヘルパー ──────────────────────────────────────
_HISTORY_TRUNCATE = 2000  # 1メッセージあたりの最大文字数
_ANCHOR_PAIRS = 3  # diversity-aware 選択時に必ず含む直近ペア数


def _normalize_history(history: list, *, max_len: int) -> list:
    """共通の正規化パイプライン。

    1. 先頭 AI 除去 → 2. 同ロール結合 → 3. 末尾 Human 除去 → 4. truncate
    """
    # 先頭が AIMessage の場合スキップ
    while history and isinstance(history[0], AIMessage):
        history = history[1:]
    # ロール厳密交互を保証（連続する同ロールメッセージは結合）
    merged: list = []
    for m in history:
        if merged and type(m) is type(merged[-1]):
            prev_content = str(getattr(merged[-1], "content", ""))
            cur_content = str(getattr(m, "content", ""))
            combined = prev_content + "\n" + cur_content
            if isinstance(m, HumanMessage):
                merged[-1] = HumanMessage(content=combined)
            elif isinstance(m, AIMessage):
                merged[-1] = AIMessage(content=combined)
            continue
        merged.append(m)
    # 末尾が HumanMessage なら除去
    if merged and isinstance(merged[-1], HumanMessage):
        merged.pop()
    # 長すぎるメッセージを切り詰め
    out = []
    for m in merged:
        content = str(getattr(m, "content", ""))
        if len(content) > max_len:
            content = content[:max_len] + "…"
        if isinstance(m, HumanMessage):
            out.append(HumanMessage(content=content))
        elif isinstance(m, AIMessage):
            out.append(AIMessage(content=content))
        else:
            out.append(m)
    return out


def _score_ai_for_diversity(ai_content: str) -> float:
    """AI 応答を diversity scoring する。abstract family → 減点、direct opener → 加点。"""
    score = _score_ai_family_penalty(ai_content)
    # direct opener 判定
    from backend.core.agent_graph.nodes.merge import _DIRECT_OPENERS
    if any(ai_content.startswith(o) for o in _DIRECT_OPENERS):
        score += 2.0
    return score


def _score_ai_family_penalty(ai_content: str) -> float:
    """Family penalty only — no direct opener bonus.

    Penalizes ALL families. Use _make_targeted_family_scorer() instead
    when you want to penalize only the repeated family.
    """
    for _family_name, markers in _SEMANTIC_FAMILIES.items():
        if any(m in ai_content for m in markers):
            return -2.0
    return 0.0


def _make_targeted_family_scorer(target_family: str) -> Callable[[str], float]:
    """Create a scorer that penalizes only the specified family.

    Other families are not affected, preserving natural diversity.
    """
    target_markers = _SEMANTIC_FAMILIES.get(target_family, ())

    def _scorer(ai_content: str) -> float:
        if target_markers and any(m in ai_content for m in target_markers):
            return -2.0
        return 0.0

    return _scorer


def _is_target_family(ai_content: str, target_family: str) -> bool:
    """Check if ai_content belongs to a specific family."""
    markers = _SEMANTIC_FAMILIES.get(target_family, ())
    return bool(markers and any(m in ai_content for m in markers))


def _apply_history_bias(ai_content: str, bias: MergedHistoryBias) -> float:
    """Apply proposal-derived history_bias to a candidate's score.

    Returns a score delta (can be negative or positive).

    NOTE: avoid_trace_match / prefer_trace_match are intentionally NOT
    applied here. Trace labels (e.g. "same_opener_family") are abstract
    identifiers that don't appear in AI response text, so substring
    matching would be a no-op on real data. These fields are preserved
    in the proposal schema for future Phase E (pseudo-teacher absorption)
    but are not used in runtime scoring.
    """
    delta = 0.0

    # downrank: penalize families from failure proposals
    for fname in bias.downrank_families:
        markers = _SEMANTIC_FAMILIES.get(fname, ())
        if markers and any(m in ai_content for m in markers):
            delta -= 1.5
            break

    # uprank: boost families from success proposals
    for fname in bias.uprank_families:
        markers = _SEMANTIC_FAMILIES.get(fname, ())
        if markers and any(m in ai_content for m in markers):
            delta += 1.0
            break

    return delta


if False:  # TYPE_CHECKING equivalent with from __future__ import annotations
    from backend.services.adaptation.reader import MergedHistoryBias


def _select_diverse_history(
    raw_history: list,
    *,
    max_pairs: int,
    scorer: Callable[[str], float] = _score_ai_for_diversity,
    anchor_pairs: int | None = None,
    target_family: str | None = None,
    history_bias: MergedHistoryBias | None = None,
) -> list:
    """Anchor + Scored で diversity-aware な履歴選択を行う。

    Anchor: 直近 anchor_pairs ペア（必ず含む、デフォルト _ANCHOR_PAIRS）
    Scored: 残り枠を scoring で選択、元の時間順に復元

    scorer を差し替えることで direct bonus の有無を制御できる。
    target_family を指定すると family cap がその family のみに限定される。
    anchor_pairs を小さくすると trigger の原因となった最新ペアも選別対象になる。
    history_bias を渡すと、proposal 由来の downrank/uprank/cap が scorer に重畳される。
    """
    # ペア単位に分割（Human, AI の2個ずつ）
    pairs: list[tuple[int, list]] = []  # (original_index, [Human, AI])
    i = 0
    while i < len(raw_history) - 1:
        h = raw_history[i]
        a = raw_history[i + 1]
        if isinstance(h, HumanMessage) and isinstance(a, AIMessage):
            pairs.append((len(pairs), [h, a]))
            i += 2
        else:
            i += 1

    has_active_shaping = (
        target_family is not None
        or (history_bias is not None and not history_bias.is_empty)
    )
    if len(pairs) <= max_pairs and not has_active_shaping:
        # 十分少なく、shaping も不要ならそのまま
        return [m for _, pair in pairs for m in pair]

    # Anchor: 直近 N ペア
    effective_anchor = anchor_pairs if anchor_pairs is not None else _ANCHOR_PAIRS
    anchor_size = min(effective_anchor, max_pairs - 1)  # 最低1枠は scored に残す
    anchor = pairs[-anchor_size:]
    candidates = pairs[:-anchor_size]

    # Score candidates
    scored: list[tuple[float, int, list]] = []
    for orig_idx, pair in candidates:
        ai_content = str(getattr(pair[1], "content", ""))
        base_score = scorer(ai_content)

        # Apply history_bias from adaptation proposals
        if history_bias and not history_bias.is_empty:
            base_score += _apply_history_bias(ai_content, history_bias)

        # recency bonus: tie-break only (capped at 0.5 to never override content score)
        recency = min(orig_idx * 0.01, 0.5)
        scored.append((base_score + recency, orig_idx, pair))

    # Select top (max_pairs - anchor_size) by score
    scored.sort(key=lambda x: x[0], reverse=True)
    selected_count = max_pairs - anchor_size
    selected = scored[:selected_count]

    # Family cap: limit capped-family pairs to at most half of scored slots.
    # When target_family is set, only that family is capped.
    # When target_family is None (default), all families are capped.
    def _is_capped_family(content: str) -> bool:
        if target_family:
            return _is_target_family(content, target_family)
        # Check built-in semantic families
        for fname, markers in _SEMANTIC_FAMILIES.items():
            if any(m in content for m in markers):
                return True
        # Check proposal-derived downrank families
        if history_bias and history_bias.downrank_families:
            for fname in history_bias.downrank_families:
                markers = _SEMANTIC_FAMILIES.get(fname, ())
                if markers and any(m in content for m in markers):
                    return True
        return False

    max_abstract = max(selected_count // 2, 1)
    # history_bias.cap_same_family tightens the cap if set
    if history_bias and history_bias.cap_same_family is not None:
        max_abstract = min(max_abstract, history_bias.cap_same_family)
    abstract_count = 0
    capped: list[tuple[float, int, list]] = []
    remainder: list[tuple[float, int, list]] = []
    for item in selected:
        ai_content = str(getattr(item[2][1], "content", ""))
        if _is_capped_family(ai_content):
            abstract_count += 1
            if abstract_count <= max_abstract:
                capped.append(item)
            else:
                remainder.append(item)
        else:
            capped.append(item)
    # Backfill capped slots from remaining scored candidates (non-capped only)
    if len(capped) < selected_count:
        selected_indices = {item[1] for item in selected}
        backfill_pool = [s for s in scored if s[1] not in selected_indices]
        for bf in backfill_pool:
            if len(capped) >= selected_count:
                break
            bf_ai = str(getattr(bf[2][1], "content", ""))
            if not _is_capped_family(bf_ai):
                capped.append(bf)
    # If still short, accept fewer pairs rather than adding more capped family
    selected = capped

    # Restore chronological order
    selected.sort(key=lambda x: x[1])

    # Flatten: selected + anchor
    result = []
    for _, _, pair in selected:
        result.extend(pair)
    for _, pair in anchor:
        result.extend(pair)

    return result


def _get_history_bias_safe(state: AgentState) -> MergedHistoryBias | None:
    """Fetch merged history_bias from adaptation proposals.

    Returns None if gate is off or on any error.
    Performs a local import to avoid circular dependency.
    """
    try:
        from backend.services.adaptation.reader import get_merged_history_bias

        thread_id = state.get("thread_id", "default_thread")
        # Derive thread_mode from thread_id (same logic as proposal_generator)
        if thread_id.startswith("nero_meeting_"):
            thread_mode = "meeting"
        elif thread_id == "default_thread":
            thread_mode = "default_thread"
        else:
            thread_mode = thread_id
        return get_merged_history_bias(thread_mode)
    except Exception:
        logger.debug("[HISTORY_BIAS] reader unavailable", exc_info=True)
        return None


def _recent_history(
    state: AgentState,
    *,
    max_pairs: int = 5,
    turn_intent: str = "open_reflection",
) -> list:
    """state["messages"] から直近の会話ペアを取得。

    現在ターンの HumanMessage（末尾）は除外し、
    直近 max_pairs ターン分（Human+AI）を返す。
    ロールの厳密交互（user→assistant→user→…）を保証する。

    turn_intent が direct_answer / correction_response の場合、
    diversity-aware 選択で abstract family の密度を下げる。
    """
    msgs = list(state.get("messages") or [])
    if len(msgs) <= 1:
        return []
    # 末尾の現在ターン HumanMessage を除く
    history = msgs[:-1]
    # WAIT プレースホルダを除去
    history = [m for m in history if getattr(m, "content", "") not in ("", "WAIT")]

    if turn_intent in ("direct_answer", "correction_response"):
        # 広い候補プールから diversity-aware 選択
        pool = history[-(max_pairs * 3):]  # 候補プールを広げる
        # 正規化してからペア選択
        normalized = _normalize_history(pool, max_len=_HISTORY_TRUNCATE)
        # Phase C: proposal-derived history_bias
        bias = _get_history_bias_safe(state)
        selected = _select_diverse_history(
            normalized, max_pairs=max_pairs, history_bias=bias,
        )
        logger.debug(
            "[HISTORY_DIVERSITY] intent=%s pool=%d selected=%d max_pairs=%d bias_empty=%s",
            turn_intent, len(normalized), len(selected), max_pairs,
            bias.is_empty if bias else True,
        )
        return selected

    # open_reflection: trigger-based の弱い family cap.
    # 直近 AI テキストで family 反復を検出した場合のみ
    # diversity-aware 選択を通す（direct bonus なし、family cap のみ）。
    recent_ai_texts = [
        str(getattr(m, "content", ""))
        for m in history[-6:]
        if isinstance(m, AIMessage)
    ]
    repeated_family = _detect_semantic_family(recent_ai_texts)

    if repeated_family:
        logger.debug(
            "[HISTORY_DIVERSITY] open_reflection trigger: family=%s",
            repeated_family,
        )
        pool = history[-(max_pairs * 3):]
        normalized = _normalize_history(pool, max_len=_HISTORY_TRUNCATE)
        return _select_diverse_history(
            normalized,
            max_pairs=max_pairs,
            scorer=_make_targeted_family_scorer(repeated_family),
            anchor_pairs=1,
            target_family=repeated_family,
        )

    # No trigger → 現行のまま
    history = history[-(max_pairs * 2):]
    return _normalize_history(history, max_len=_HISTORY_TRUNCATE)

_SECTION_RE_CACHE: dict[str, re.Pattern[str]] = {}


def extract_section(text: str, section_name: str) -> str:
    """=== SECTION_NAME === で囲まれたセクションの中身を抽出する。
    次の === ヘッダーまたは文末で区切る。見つからなければ空文字列を返す。
    """
    if not text or section_name not in text:
        return ""
    pat = _SECTION_RE_CACHE.get(section_name)
    if pat is None:
        escaped = re.escape(section_name)
        pat = re.compile(
            rf"===\s*{escaped}\s*===[ \t]*\n(.*?)(?=\n===|\Z)",
            re.DOTALL,
        )
        _SECTION_RE_CACHE[section_name] = pat
    m = pat.search(text)
    return m.group(1).strip() if m else ""


def build_context_suffix(
    state: AgentState,
    *,
    memory_mode: str = "full",
) -> str:
    """Depth node共通: memory + game + TONE + somatic のサフィックスを構築。

    Somatic（今の感覚）は TONE アンカーの直後、会話履歴の直前に配置する。
    LLM は末尾寄りのコンテキストに注意が向きやすいため（lost-in-the-middle 対策）。

    Args:
        state: AgentState (memory_context, memory_sections, game_context を参照)
        memory_mode: "pinned_only" (depth0) or "full" (depth1/2)
    """
    parts: list[str] = []
    memory_context = state.get("memory_context") or ""
    if memory_mode == "pinned_only":
        pinned = extract_section(memory_context, "PINNED FACTS")
        if pinned:
            parts.append(f"\n\n=== PINNED FACTS ===\n{pinned}")
    elif memory_context:
        parts.append(f"\n\n{memory_context}")
    game_ctx = state.get("game_context") or ""
    if game_ctx:
        parts.append(f"\n\n=== GAME STATE ===\n{game_ctx}")
    parts.append(_SPEECH_TAG_INSTRUCTION)
    parts.append(_TONE_ANCHOR)
    # Room / RuntimeFacts — external perception, before somatic (internal feeling)
    if memory_mode != "pinned_only":
        from backend.core.config import settings as _cfg
        if getattr(_cfg, "RUNTIME_FACTS_ENABLED", False):
            try:
                runtime_facts_text = state.get("runtime_facts_text") or ""
                if runtime_facts_text:
                    parts.append(f"\n\n{runtime_facts_text}")
            except Exception:
                pass  # non-critical
        elif getattr(_cfg, "ROOM_UPDATE_ENABLED", False):
            # Fallback: legacy room context (until RuntimeFacts is enabled)
            try:
                from backend.services.room.room_context import build_room_context
                room_text = build_room_context()
                if room_text:
                    parts.append(f"\n\n{room_text}")
            except Exception:
                pass  # non-critical
    # Nero references — concrete evidence, before somatic (internal feeling)
    if memory_mode != "pinned_only":
        nero_refs = state.get("nero_references_text") or ""
        if nero_refs:
            parts.append(f"\n\n{nero_refs}")
    # Somatic: TONE の直後に配置（depth1/2 のみ、depth0 は pinned_only で somatic なし）
    if memory_mode != "pinned_only":
        sections = state.get("memory_sections") or {}
        somatic = sections.get("somatic") or ""
        if somatic:
            parts.append(f"\n\n{somatic}")

        # SkeletonCore: 会話の気配（somatic の後、反復検出の前）
        from backend.core.config import settings as _skel_cfg
        if getattr(_skel_cfg, "SKELETON_SOMATIC_ENABLED", False):
            skel_data = state.get("conversation_skeleton")
            if skel_data:
                try:
                    from backend.core.conversation_skeleton.schema import (
                        ConversationSkeleton,
                        Focus,
                        QuestionIntent,
                        ResponseIntent,
                    )
                    from backend.core.conversation_skeleton.skeleton_to_somatic import (
                        format_skeleton_somatic,
                        skeleton_to_somatic,
                    )

                    qi = (
                        QuestionIntent(skel_data["question_intent"])
                        if skel_data.get("question_intent")
                        else None
                    )
                    skel = ConversationSkeleton(
                        focus=Focus(skel_data["focus"]),
                        response_intent=ResponseIntent(skel_data["response_intent"]),
                        question_intent=qi,
                    )
                    skel_senses = skeleton_to_somatic(skel)
                    skel_text = format_skeleton_somatic(skel_senses)
                    if skel_text:
                        parts.append(f"\n\n{skel_text}")
                except Exception:
                    pass  # non-critical

    # Contract 2: 場の空気（SkeletonCore の後、反復検出の前）
    if memory_mode != "pinned_only":
        atmosphere_text = state.get("atmosphere_text") or ""
        if atmosphere_text:
            parts.append(f"\n\n{atmosphere_text}")

    # Drawing Language: draw_intent があるターンだけ最小リファレンスを注入
    if not state.get("test_mode"):
        try:
            from backend.core.drawing.prompt_ref import (
                detect_draw_intent, build_drawing_reference, has_recent_drawing_context,
            )
            user_text = state.get("user_text") or ""
            thread_id = str(state.get("thread_id") or "default_thread")
            _recent = has_recent_drawing_context(thread_id)
            if detect_draw_intent(user_text, recent_drawing=_recent):
                parts.append(f"\n\n{build_drawing_reference()}")
        except Exception:
            logger.debug("[CONTEXT_SUFFIX] drawing prompt injection failed", exc_info=True)

    # 反復検出: 全depth共通。同じ応答が続いていたら体感として注入
    rep_sense = _detect_repetition_sense(state)
    if rep_sense:
        parts.append(f"\n\n=== 今の感覚 ===\n{rep_sense}")
    return "".join(parts)
