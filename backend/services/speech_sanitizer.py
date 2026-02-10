import re

# --- Stream Sanitizer (Robust Rolling Buffer) ---

# 状態タグ (PONDERING etc) 用の共通パターン
TAG_PATTERN = re.compile(
    r"\[(CONSENT|DISSONANCE|PONDERING|HAPPY|SAD|SURPRISED|ANGRY|RELAXED|SHY|SIGH|NEUTRAL)\]",
    re.IGNORECASE,
)

TOOL_BEGIN = re.compile(r"\[(SEARCH_MEMORY|SEARCH|TOOL_CALL)\]", re.IGNORECASE)
TOOL_END   = re.compile(r"\[(END_SEARCH_MEMORY|END_SEARCH|END_TOOL_CALL)\]", re.IGNORECASE)

# 「ツールJSON断片」の最小検出（誤爆を避け、search_memory だけ狙う）
TOOL_JSON_HINT = re.compile(r'"(?:name|arguments)"\s*:\s*|search_memory', re.IGNORECASE)

class StreamSanitizer:
    """
    RAWバッファとマッピングを使用した堅牢なストリームクリーナー。
    - chunk跨ぎのタグ分割 ([POND... + ERING]) を処理
    - 状態保持によるツールブロック除去 ([SEARCH]...[END_SEARCH] または [SEARCH]...EOF)
    - ツールブロック直前の有効なテキスト（例: 'working'）の保護
    """

    # 日本語向けの“切り位置”優先順（長い方を先に）
    _BOUNDARIES = ["\n\n", "\n", "。", "！", "？", "!", "?", "、"]

    def __init__(
        self,
        keep_chars: int = 80,
        max_buf: int = 16384,
        min_emit_chars: int = 20,
        boundary_window: int = 120,
    ):
        self.keep_chars = keep_chars
        self.max_buf = max_buf
        self.min_emit_chars = min_emit_chars
        self.boundary_window = boundary_window
        self.raw_buf = ""

    def _get_clean_and_mapping(self, s: str):
        """Finds skip ranges (tags, tool blocks) and returns cleaned text with raw index mapping."""
        skip_ranges = []
        
        # 1. Standard Tags (PONDERING etc)
        for m in TAG_PATTERN.finditer(s):
            skip_ranges.append((m.start(), m.end()))
            
        # 2. Stateful Tool Blocks (Handles [SEARCH_MEMORY]... to [END_SEARCH_MEMORY] or EOF)
        i = 0
        while i < len(s):
            m_begin = TOOL_BEGIN.search(s, i)
            if not m_begin:
                break
            m_end = TOOL_END.search(s, m_begin.end())
            if m_end:
                skip_ranges.append((m_begin.start(), m_end.end()))
                i = m_end.end()
            else:
                # Open-ended tool block (leaks until the end of current buffer)
                skip_ranges.append((m_begin.start(), len(s)))
                break
        
        # 3. Specific Tool JSON Hint (e.g. {"name": "search_memory"})
        # Only triggered if it looks like a JSON line start
        for m in re.finditer(r'^\s*\{\s*["\'][^"\']+["\']\s*[:：]', s, re.MULTILINE):
            line_end = s.find("\n", m.start())
            if line_end == -1: line_end = len(s)
            line_content = s[m.start():line_end]
            if TOOL_JSON_HINT.search(line_content):
                skip_ranges.append((m.start(), line_end + 1 if line_end < len(s) else line_end))

        # Merge overlapping skip ranges
        skip_ranges.sort()
        merged = []
        for start, end in skip_ranges:
            if not merged or start > merged[-1][1]:
                merged.append([start, end])
            else:
                merged[-1][1] = max(merged[-1][1], end)

        # Build clean string and index mapping
        clean_parts = []
        mapping = [0]
        curr_raw = 0
        for start, end in merged:
            if curr_raw < start:
                chunk = s[curr_raw:start]
                clean_parts.append(chunk)
                for _ in range(len(chunk)):
                    curr_raw += 1
                    mapping.append(curr_raw)
            curr_raw = end # skip
        
        if curr_raw < len(s):
            chunk = s[curr_raw:]
            clean_parts.append(chunk)
            for _ in range(len(chunk)):
                curr_raw += 1
                mapping.append(curr_raw)
                
        return "".join(clean_parts), mapping

    def _choose_emit_len(self, clean_all: str) -> int:
        """
        keep_chars を除いた範囲の中で、できるだけ自然な区切りまでを送る。
        """
        base = len(clean_all) - self.keep_chars
        if base <= 0:
            return 0
        if base < self.min_emit_chars:
            return 0

        # baseの直前あたり（boundary_window内）で区切りを探す
        search_from = max(0, base - self.boundary_window)
        head = clean_all[:base]

        best = -1
        for b in self._BOUNDARIES:
            pos = head.rfind(b, search_from)
            if pos != -1:
                cut = pos + len(b)  # 区切り文字も含める
                # もっとも後ろの区切りを優先
                if cut > best:
                    best = cut

        # 見つかったが短すぎる断片になるなら採用しない
        if best != -1 and best >= self.min_emit_chars:
            return best

        # 区切りが無ければ base をそのまま
        return base

    def push(self, chunk: str = "") -> str:
        """
        新しいchunkを投入し、安全に確定したテキストを返す。
        chunk="" の場合は「drain/tick」として、現バッファから吐けるものがあれば吐く。
        """
        if chunk is None:
            return ""

        if chunk:
            self.raw_buf += chunk
            # OOM防止
            if len(self.raw_buf) > self.max_buf:
                self.raw_buf = self.raw_buf[-self.max_buf:]

        if not self.raw_buf:
            return ""

        clean_all, mapping = self._get_clean_and_mapping(self.raw_buf)

        emit_len = self._choose_emit_len(clean_all)
        if emit_len <= 0:
            return ""

        emit_text = clean_all[:emit_len]

        # 送出した「浄化後テキスト」に対応する「生テキスト」のインデックス
        raw_cut_idx = mapping[emit_len]
        self.raw_buf = self.raw_buf[raw_cut_idx:]
        return emit_text

    def flush(self) -> str:
        """
        バッファに残っている全テキストを浄化して返し、バッファを空にする。
        """
        if not self.raw_buf:
            return ""
        clean_all, _ = self._get_clean_and_mapping(self.raw_buf)
        self.raw_buf = ""
        return clean_all

# Backward compatibility aliases
RollingStreamCleaner = StreamSanitizer


# 沈黙時の既定文
SILENCE_DEFAULT = "……今は、静かにここにいます。"

# ト書き・描写の削除パターン
STAGE_DIRECTIONS = [
    r"（[^）]{0,40}）",                 # （微笑みながら）
    r"\*[^*]{0,80}\*",                 # *ざわめき* などの強調
    r"\(.*?\)",                        # 半角括弧のト書き
    r"^少し間を置いて.*?\n",           # 行頭のト書き
]

TAG_LINE_RE = re.compile(r'^\[\[[A-Z0-9_]+\]\]\s*\{.*\}\s*$', re.IGNORECASE)
SILENCE_TAG_RE = re.compile(r'^\s*\[SILENCE\]\s*$', re.IGNORECASE)
TAG_PATTERN = re.compile(
    r"\[(CONSENT|DISSONANCE|PONDERING|HAPPY|SAD|SURPRISED|ANGRY|RELAXED|SHY|SIGH|NEUTRAL)\]",
    re.IGNORECASE,
)

# 内部状態やLLMメタ情報のハードブロック（本気で漏洩している場合のみ沈黙へ）
# 定数定義: JSON検知パターン（誤爆判定用に分離）
JSON_SHAPE_PAT = r"""\{\s*["'][^"']+["']\s*[:：]"""

# 本当に止めたいもの（少数精鋭）
CRITICAL_BLOCK = [
    # 内部プロンプト/会話構造が露出している系（強いシグナル）
    r'["\']role["\']\s*[:：]\s*["\'](system|developer|assistant|user|tool)["\']',
    r'["\']messages["\']\s*[:：]\s*\[',          # messages 配列
    r'["\']system(_prompt)?["\']\s*[:：]',       # system / system_prompt
    r'["\']developer(_prompt)?["\']\s*[:：]',    # developer / developer_prompt
    r'["\']tool_calls["\']\s*[:：]',             # tool_calls
    r'["\']function_call["\']\s*[:：]',          # function_call
    # JSON構造 + 内部キーの組み合わせ（確度が高いのでブロック）
    r"""\{\s*["'][^"']+["']\s*[:：][\s\S]{0,200}["'](summary|details|category|importance|confidence|surprise|tags|reason_tag)["']\s*[:：]""",
]

# 誤爆しやすいので “検知だけ” に回す
WARN_ONLY = [
    # あなたの「思考露出」系は言い回しが広すぎるので warn に落とすのが無難
    r"私は考えています",
    r"判断しました",
    r"記憶の断片",
    r"頭の中でざわめ",
    r"内部ログ",
    # JSON形（単体は危険じゃない）
    JSON_SHAPE_PAT,
    # 内部タグ由来キー（単体だと普通の文章でも出るので warn）
    r'["\']summary["\']\s*[:：]',
    r'["\']details["\']\s*[:：]',
    r'["\']category["\']\s*[:：]',
    r'["\']importance["\']\s*[:：]',
    r'["\']confidence["\']\s*[:：]',
    r'["\']surprise["\']\s*[:：]',
    r'["\']tags["\']\s*[:：]',
    r'["\']reason_tag["\']\s*[:：]',
]

# 技術・システム用語の自然化（安全な置換）
SOFT_REWRITE_SAFE = [
    (r"プロンプト", "内側の約束"),
    (r"レイヤー", "層"),
    # ツール・検索の軟化（メタ発言の自然化）
    (r"検索(します|してみる)", "思い出してみるね"),
    (r"検索を実行(します|した|中)", "少し考えてみるね"),
    (r"ツールを?(使い|使)います", "やってみるね"),
    (r"(関数|function)\s*を?(呼|使|実行)", "……"),
    (r"データを?(取得|参照)します", "見てみるね"),
]

# 人格・記憶に関わる表現（ニア自身の揺らぎとして保護するため、通常は適用しない）
SOFT_REWRITE_PERSONALITY = [
    (r"覚えています", "そうですね"),
    (r"以前も言いました", "今の話に沿うと"),
    (r"過去にも言いましたね", "今の文脈だと"),
    (r"覚えている通り", "そうですね"),
    (r"心の中で", ""),
    (r"頭の中で", ""),
    (r"記憶がざわめ(く|きます)?", ""),
    (r"内部(で|に)は", ""),
    (r"私は考えています", "……"),
    (r"判断しました", "そう感じる"),
]

# Define STATE_TAGS constant for reuse
STATE_TAGS = [
    "CONSENT", "DISSONANCE", "PONDERING",
    "HAPPY", "SAD", "SURPRISED", "ANGRY", "RELAXED", "SHY", "SIGH", "NEUTRAL"
]
# Robust Regex: Handle [TAG], [ TAG ], ［TAG］(fullwidth)
STATE_TAG_RE = re.compile(
    r"[\[\［]\s*(?:%s)\s*[\]\］]" % "|".join(map(re.escape, STATE_TAGS)),
    re.IGNORECASE,
)

# --- Style Guard: Suppress instant conclusions / forced guidance ---
DECISIVE_PATTERNS = [
    r"答えは",
    r"結論は",
    r"正解は",
    r"〜に決まってる",
    r"断言(できる|します)",
]

GUIDANCE_PATTERNS = [
    r"まず.+?(しよう|してください|するのがいい)",
    r"次に.+?(しよう|してください|するのがいい)",
    r"こう考えるべき",
    r"これが正解",
]

FORCED_QUESTION_PATTERNS = [
    r"何かお(手伝い|話したいこと|困りのこと)",
    r"どんなことでも構いません",
    r"お気軽に",
    r"どうしましたか",
    r"どうされましたか",
]

# Internal planner line patterns (leak guard)
INTERNAL_PLAN_LINE_RE = re.compile(
    r"^\s*[-•]\s*(Acknowledge|Briefly|Explain|Ask|Confirm|Summarize|Rephrase|Provide|Offer|Suggest|State|Clarify)\b",
    re.IGNORECASE,
)
PLAN_VERB_RE = re.compile(
    r"\b(acknowledge|briefly|explain|ask|confirm|summarize|rephrase|provide|offer|suggest|state|clarify)\b",
    re.IGNORECASE,
)

def _ascii_ratio(s: str) -> float:
    if not s:
        return 0.0
    total = 0
    ascii_count = 0
    for ch in s:
        if ch.isspace():
            continue
        total += 1
        if ord(ch) < 128:
            ascii_count += 1
    return (ascii_count / total) if total else 0.0

def _looks_like_plan_line(line: str) -> bool:
    if not line:
        return False
    if INTERNAL_PLAN_LINE_RE.match(line):
        return True
    if PLAN_VERB_RE.search(line):
        # If it's mostly ASCII and not Japanese, it's likely a leaked plan
        if _ascii_ratio(line) >= 0.7 and not re.search(r"[ぁ-んァ-ン一-龥]", line):
            return True
    return False

SOFTEN_DECISIVE_RULES = [
    (r"答えは(.+?)です", r"今の文脈だと\1かもしれません"),
    (r"結論は(.+?)です", r"現時点では\1とも言えます"),
    (r"正解は(.+?)です", r"ひとつの見方としては\1かもしれません"),
    (r"すべき", "する考え方もあります"),
]

def _soften_decisive_guidance(text: str) -> str:
    if not text:
        return text

    # Drop forced-question sentences
    sentences = re.split(r"(?<=[。！？\n])", text)
    kept = []
    for s in sentences:
        if any(re.search(p, s) for p in FORCED_QUESTION_PATTERNS):
            continue
        kept.append(s)
    t = "".join(kept).strip()

    # Soft replacements
    for pat, repl in SOFTEN_DECISIVE_RULES:
        t = re.sub(pat, repl, t)

    # If still decisive/guiding, append a hedge
    if any(re.search(p, t) for p in (DECISIVE_PATTERNS + GUIDANCE_PATTERNS)):
        if not re.search(r"(断定|言い切)|(?:かもしれません|とは限らない)", t):
            t = t + "\n\n断定は避けておくね。"

    return t

def finalize_output(text: str, *, force_silence: bool = False) -> str:
    """
    発話憲章（フェーズ2）に基づき、最終出力を浄化する。
    戻り値: (浄化済み本文, 抽出されたシステムタグリスト)
    """
    if not text:
        return SILENCE_DEFAULT

    # 1) 状態タグ除去（最優先・最強力）
    #    文中のどこにあっても確実に消す
    text = STATE_TAG_RE.sub("", text)

    # 2) [SEARCH_MEMORY]... 等のtool block除去
    text = re.sub(
        r"\[SEARCH_[A-Z0-9_]+\][\s\S]*?\[END_SEARCH_[A-Z0-9_]+\]\s*",
        "",
        text,
        flags=re.IGNORECASE,
    )
    
    # 3) 行頭整理（タグ除去後の空行削除）
    text = re.sub(r"^\s*\n+", "", text)      # 冒頭の空行を削る
    text = re.sub(r"\n{3,}", "\n\n", text)   # 空行連発を整える

    # 4) 特定のツール定義JSON (search_memory等) 除去
    text = re.sub(
        r'\{\s*"name"\s*:\s*"(search_memory|internal_op|blob_op)"\s*,\s*"arguments"\s*:\s*\{[\s\S]*?\}\s*\}\s*',
        "",
        text,
        flags=re.MULTILINE | re.DOTALL,
    )

    # --- 以下、従来のクリーニング ---

    # --- 1) 行分割とタグの退避 ---
    lines = text.splitlines()
    speech_lines = []
    system_tags = []

    for line in lines:
        l = line.strip()
        if TAG_LINE_RE.fullmatch(l):
            system_tags.append(l)
        else:
            speech_lines.append(line)

    speech_body = "\n".join(speech_lines).strip()

    # --- 2) 沈黙（SILENCE）判定：最優先 ---
    if force_silence or SILENCE_TAG_RE.fullmatch(speech_body) or "[SILENCE]" in speech_body:
        return SILENCE_DEFAULT

    t = speech_body

    # --- 3) 技術タグの除去：閉じタグがある時だけブロック除去 ---
    t = re.sub(
        r"<(INTERNAL_LOG|SYSTEM_INSTRUCTION)>\s*.*?\s*</\1>",
        "",
        t,
        flags=re.DOTALL | re.IGNORECASE
    )
    t = re.sub(r"</?(INTERNAL_LOG|SYSTEM_INSTRUCTION)>", "", t, flags=re.IGNORECASE)

    # --- 4) 接頭辞・レイヤータグの除去（行頭のみ） ---
    t = re.sub(r"^\s*\[?(LAYER\s*3|SPEECH|RESPONSE|ニア|応答)[^\]]*\]?[:：]?\s*", "", t, flags=re.IGNORECASE)

    # フィルタ後の行を精査（ログ形式の行を排除）
    final_speech_lines = []
    # 完全に排除したいキーワード（大文字小文字無視）
    LOG_KEYWORDS = [r"Memory Pending", r"INFO", r"ERROR", r"WARNING", r"DEBUG", r"VectorStore", r"telemetry"]
    log_pattern = re.compile(rf"({'|'.join(LOG_KEYWORDS)})", re.IGNORECASE)

    for line in t.splitlines():
        if _looks_like_plan_line(line):
            continue
        # 日付形式 (2026-01-11) や ログキーワードを含む行を排除
        if re.search(r'^\d{4}-\d{2}-\d{2}', line) or log_pattern.search(line):
            continue
        final_speech_lines.append(line)
    t = "\n".join(final_speech_lines).strip()

    # --- 5) HARD_BLOCK（CRITICAL：該当行のみをフィルタリング） ---
    # 旧：本文全体を無効化 -> 改善：該当行だけ落として、残りがあれば通す
    t_lines = t.splitlines()
    final_t_lines = []
    for line in t_lines:
        is_critical = any(re.search(pat, line, re.IGNORECASE) for pat in CRITICAL_BLOCK)
        if not is_critical:
            final_t_lines.append(line)
        else:
            # クリティカル行が見つかったらログを出してもいい（Adviser推奨）
            pass
    t = "\n".join(final_t_lines).strip()

    # --- 5.5) State/Emotion タグの完全除去 ---
    # TAG_PATTERN ([PONDERING], [CONSENT], etc.) を本文から確実に削除
    t = TAG_PATTERN.sub("", t)
    # 二重スペース整形
    t = re.sub(r"[ \t]{2,}", " ", t)

    # --- 6) ト書き削除 / ソフト置換 ---
    for pat in STAGE_DIRECTIONS:
        t = re.sub(pat, "", t, flags=re.MULTILINE)
    
    # SAFEな置換のみ適用（人格は削らない）
    for pat, repl in SOFT_REWRITE_SAFE:
        t = re.sub(pat, repl, t)

    # 人格置換 (SOFT_REWRITE_PERSONALITY) は意図的にスキップ

    clean_speech = t.strip()

    # --- 7) Sentence-level tool mention filter (Refined) ---
    # Drop sentences that mention internal tool/search operations as code/logs
    # より「動詞結合」や「特定の言い回し」に絞り、日常会話の単語（検索、関数など）単体での誤爆を防ぐ。
    TOOL_SENTENCE_RE = re.compile(
        r"(検索(を実行|します|中)|ツールを?(呼|起動|使)|関数を?(呼|起動|使)|(tool|search|function|query)\s*(call|exec|run|running))", 
        re.IGNORECASE
    )
    sentences = re.split(r"(?<=[。！？\n])", clean_speech)
    filtered_sentences = [s for s in sentences if not TOOL_SENTENCE_RE.search(s)]
    clean_speech = "".join(filtered_sentences).strip()

    # --- 8) 最後のゴミ掃除（孤立したカッコの除去） ---
    # アドバイザー推奨：独立した ] や [[ を消す
    clean_speech = re.sub(r"^\s*[\[\]]+\s*$", "", clean_speech, flags=re.MULTILINE).strip()
    clean_speech = re.sub(r"\[\[[^\n]*$", "", clean_speech).strip()

    # --- 7.5) Style guard: suppress instant conclusions / forced guidance ---
    clean_speech = _soften_decisive_guidance(clean_speech)

    # --- 8) 最終沈黙判定と救済 ---
    if (not clean_speech) or re.fullmatch(r"[\.\,。．、…・\s!！?？\-—～〜ー]*", clean_speech):
        if system_tags:
            return SILENCE_DEFAULT
        else:
            return SILENCE_DEFAULT

    return clean_speech


def extract_metadata(text: str):
    """
    タグを抽出し、本文から完全に除去する。
    - 全タグを大文字化して返す
    - primary_tag は末尾に最も近いタグを採用
    """
    if not text:
        return "", "NONE", []

    all_tags = [t.upper() for t in TAG_PATTERN.findall(text)]
    cleaned_text = TAG_PATTERN.sub("", text).replace("  ", " ").strip()
    primary_tag = all_tags[-1] if all_tags else "NONE"
    return cleaned_text, primary_tag, all_tags


# --- 高精度 greeting-only 判定 (Adviser's Advanced Version) ---

import unicodedata

# 「挨拶だけ」or「挨拶 + 汎用ヘルプ誘導」の型
_GREET_RE = re.compile(
    r"(おはよう(ございます)?|こんにちは|こんばんは|はじめまして|よろしく(お願いします)?|お疲れ様(です)?|ただいま|おかえり)",
    re.IGNORECASE,
)

# 「何かお手伝い…」など、会話を"初期化"する汎用誘導
_GENERIC_PROMPT_RES = [
    re.compile(r"何か(お手伝い|手伝|質問|相談|困っていること|話したいこと).*(ありますか|ある\?|あります\?|あるかな)"),
    re.compile(r"(どうしましたか|どうされましたか|ご用件(は|が)ありますか)"),
    re.compile(r"(お手伝いできること|できること).*(ありますか|ある\?|あります\?|あるかな)"),
    re.compile(r"(何か).*(できますか|できる\?|できます\?)"),
    re.compile(r"(いつでも).*(言って|聞いて|頼って)"),
]

# 記号除去パターン
_PUNCT_RE = re.compile(r"[ \t\r\n\u3000。、．，,！!？?\-—―…・:;\"'「」『』（）\(\)\[\]【】😊]+")
_KANJI_SEQ_RE = re.compile(r"[\u4E00-\u9FFF]{2,}")  # 2文字以上の漢字連続
_ALNUM_SEQ_RE = re.compile(r"[A-Za-z0-9]{2,}")      # AI/GPTなど
_KATAKANA_SEQ_RE = re.compile(r"[\u30A0-\u30FF]{2,}")  # 2文字以上のカタカナ連続（ニア、コード、ログ等）

def _norm(s: str) -> str:
    s = unicodedata.normalize("NFKC", s or "")
    return s.strip()

def _topic_tokens_from_user(user_text: str) -> set:
    """
    日本語形態素なしでできる範囲の"話題トークン"抽出。
    - 漢字2文字以上の連続
    - 英数2文字以上（AI/GPT/LLM/2026等）
    - カタカナ2文字以上（ニア/コード/ログ等）
    """
    u = _norm(user_text)
    tokens = set(_KANJI_SEQ_RE.findall(u))
    tokens |= set(_ALNUM_SEQ_RE.findall(u))
    tokens |= set(_KATAKANA_SEQ_RE.findall(u))  # カタカナ追加
    # ありがちな汎用語を除外（「状況」は重要なので除外しない）
    stop = {"何回", "今", "話", "こと", "大丈夫", "確認", "お話", "質問", "相談"}
    return {t for t in tokens if t not in stop}

def _has_topic_overlap(last_user_text: str, ai_text: str) -> bool:
    toks = _topic_tokens_from_user(last_user_text)
    if not toks:
        return False
    a = _norm(ai_text)
    return any(t in a for t in toks)

def is_greeting_only(ai_text: str, last_user_text: str = "") -> tuple:
    """
    高精度の「挨拶のみ」判定。
    
    返り値: (greeting_only: bool, reason: str)
    
    - ユーザーの話題トークンがAIの返答に含まれていたら False
    - 挨拶語 + 汎用誘導のみで構成されていたら True
    """
    t = _norm(ai_text)
    if not t:
        return True, "empty"
    
    # 既に無害化された沈黙系はそのまま残す
    if t in {"…", "...", "[SILENCE]", SILENCE_DEFAULT}:
        return False, "silence_marker"
    
    # ユーザー話題トークンが入ってるなら、挨拶テンプレじゃない可能性が高いので除外
    if last_user_text and _has_topic_overlap(last_user_text, t):
        return False, "topic_overlap"
    
    # まず挨拶語が含まれているか
    if not _GREET_RE.search(t):
        return False, "no_greet_word"
    
    # 挨拶語以外の"実質内容"があるかを雑に見る
    compact = _PUNCT_RE.sub("", t)  # 記号除去
    # 改行を除去して汎用誘導のマッチングを改善
    compact = compact.replace("\n", "").replace("\r", "")
    # 挨拶語を消して残りを見る
    compact_wo_greet = _GREET_RE.sub("", compact)
    
    # 汎用誘導を消す
    tmp = compact_wo_greet
    for r in _GENERIC_PROMPT_RES:
        tmp = r.sub("", tmp)
    
    # ここで何も残らないなら "挨拶 + 汎用誘導" と判定
    if len(tmp) == 0:
        return True, "greet_plus_generic"
    
    # 残りがごく短い場合だけ追加で True（例: 「おはよ！」）
    
    if len(tmp) <= 2:
        return True, "greet_only_short_tail"
    
    return False, "has_content"


def detect_internal_leak(text: str) -> dict[str, list[str]]:
    """
    Check if the text contains any internal system leaks.
    Separates results into 'critical' (must block) and 'warn' (logging only).
    """
    out = {"critical": [], "warn": []}
    if not text:
        return out
    
    # Check CRITICAL
    for pat in CRITICAL_BLOCK:
        if re.search(pat, text, re.IGNORECASE):
            out["critical"].append(f"Matched CRITICAL: {pat}")

    # Check WARN
    for pat in WARN_ONLY:
        if re.search(pat, text, re.IGNORECASE):
            out["warn"].append(f"Matched WARN: {pat}")
            
    return out


def is_critical_leak(leak: dict[str, list[str]]) -> bool:
    """
    Determine if the detected leaks are critical enough to block the stream/output.
    """
    if not leak:
        return False
    return bool(leak.get("critical"))
