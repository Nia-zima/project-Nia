import re
from typing import Optional

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

# 内部状態やLLMメタ情報のハードブロック（本気で漏洩している場合のみ沈黙へ）
HARD_BLOCK = [
    # 思考・内部状態の露出（確定系）
    r"私は考えています",
    r"判断しました",
    r"記憶の断片",
    r"頭の中でざわめ",
    r"内部ログ",
    # --- JSON/辞書形式の漏洩ブロック（確度を上げる） ---
    # { "key": ... } / { 'key': ... } の形だけをハードブロック
    r"""\{\s*["'][^"']+["']\s*[:：]""",
    # “内部タグ由来”のキーが本文に出たらほぼ漏洩確定
    r'["\']summary["\']\s*[:：]',
    r'["\']details["\']\s*[:：]',
    r'["\']category["\']\s*[:：]',
    r'["\']importance["\']\s*[:：]',
    r'["\']confidence["\']\s*[:：]',
    r'["\']surprise["\']\s*[:：]',
    r'["\']tags["\']\s*[:：]',
    r'["\']reason_tag["\']\s*[:：]',
]

# 記憶の明示的な言及を柔らかい表現に置換（伴走レイヤーへの誘導）
SOFT_REWRITE = [
    # 基本の言い換え
    (r"覚えています", "そうですね"),
    (r"以前も言いました", "今の話に沿うと"),
    (r"過去にも言いましたね", "今の文脈だと"),
    (r"覚えている通り", "そうですね"),
    # 開発語彙の自然化
    (r"プロンプト", "内側の約束"),
    (r"レイヤー", "層"),
    # 内部っぽい独り言の消去・軟化
    (r"心の中で", ""),
    (r"頭の中で", ""),
    (r"記憶がざわめ(く|きます)?", ""),
    (r"内部(で|に)は", ""),
    # 思考の言語化の言い換え
    (r"私は考えています", "……"),
    (r"判断しました", "そう感じる"),
]

def finalize_output(text: str, *, force_silence: bool = False) -> str:
    """
    発話憲章（フェーズ2）に基づき、最終出力を浄化する。
    戻り値: (浄化済み本文, 抽出されたシステムタグリスト)
    """
    if not text:
        return SILENCE_DEFAULT

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
        # 日付形式 (2026-01-11) や ログキーワードを含む行を排除
        if re.search(r'^\d{4}-\d{2}-\d{2}', line) or log_pattern.search(line):
            continue
        final_speech_lines.append(line)
    t = "\n".join(final_speech_lines).strip()

    # --- 5) HARD_BLOCK（行単位でチェックして誤爆防止） ---
    t_lines = t.splitlines()
    for pat in HARD_BLOCK:
        if any(re.search(pat, line) for line in t_lines):
            t = "" # 本文全体を無効化
            break

    # --- 6) ト書き削除 / ソフト置換 ---
    for pat in STAGE_DIRECTIONS:
        t = re.sub(pat, "", t, flags=re.MULTILINE)
    for pat, repl in SOFT_REWRITE:
        t = re.sub(pat, repl, t)

    clean_speech = t.strip()

    # --- 7) 最後のゴミ掃除（孤立したカッコの除去） ---
    # アドバイザー推奨：独立した ] や [[ を消す
    clean_speech = re.sub(r"^\s*[\[\]]+\s*$", "", clean_speech, flags=re.MULTILINE).strip()
    clean_speech = re.sub(r"\[\[[^\n]*$", "", clean_speech).strip()

    # --- 8) 最終沈黙判定と救済 ---
    if (not clean_speech) or re.fullmatch(r"[\.\,。．、…・\s!！?？\-—～〜ー]*", clean_speech):
        if system_tags:
            return SILENCE_DEFAULT
        else:
            return SILENCE_DEFAULT

    return clean_speech


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
