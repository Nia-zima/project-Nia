import os
import re
import json
import uuid
import base64
import asyncio
import datetime
import time
import copy
import operator
from typing import Annotated, Sequence, TypedDict, List, Optional, Dict, Any
from langgraph.checkpoint.memory import MemorySaver

def extract_json_from_text(text: str) -> Optional[Dict[str, Any]]:
    """Extract the first JSON object from model output robustly."""
    if not text:
        return None

    # 1) Prefer fenced code block: ```json ... ```
    codeblock_patterns = [
        r"```json\s*(\{.*?\})\s*```",
        r"```\s*(\{.*?\})\s*```",
    ]
    for pat in codeblock_patterns:
        m = re.search(pat, text, flags=re.DOTALL | re.IGNORECASE)
        if m:
            candidate = m.group(1).strip()
            try:
                obj = json.loads(candidate)
                return obj if isinstance(obj, dict) else None
            except json.JSONDecodeError:
                pass

    # 2) Scan for the first decodable JSON object in raw text
    decoder = json.JSONDecoder()
    for m in re.finditer(r"\{", text):
        start = m.start()
        try:
            obj, end = decoder.raw_decode(text[start:])
            if isinstance(obj, dict):
                return obj
        except json.JSONDecodeError:
            continue

    return None

FORBIDDEN_STORY_WORDS = [
    "貢献", "創造", "生まれ", "作った", "作成", "間接的", "影響", "きっかけ",
    "記録されています", "確か", "〜ですね", "誕生日", "年齢",
]

def normalize_ja(s: str) -> str:
    s = s or ""
    s = s.lower()
    s = re.sub(r"\s+", "", s)
    return s

def is_summary_grounded(summary: str, user_text: str) -> bool:
    """Check if the summary is based on the user's explicit input (grounded)."""
    if not summary:
        return False
    ns = normalize_ja(summary)
    nu = normalize_ja(user_text)

    # ストーリー/因果っぽいワードが入ってたら要注意（Direct保存は禁止）
    if any(w in summary for w in FORBIDDEN_STORY_WORDS):
        return False

    # 単純な根拠チェック：summaryの主要トークンがユーザー文に含まれるか
    tokens = set(re.findall(r"[一-龠ぁ-んァ-ンa-zA-Z0-9]{2,}", summary))
    tokens = {t for t in tokens if t not in {"です", "ます", "だよ", "よね", "ありがとう"}}

    if not tokens:
        return False

    hit = sum(1 for t in tokens if normalize_ja(t) in nu)
    ratio = hit / max(len(tokens), 1)

    # 7割以上根拠があればOK
    return ratio >= 0.7

# プロジェクトルートの定義
PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

# LangChain / LangGraph
from langchain_core.messages import BaseMessage, HumanMessage, SystemMessage, AIMessage, ToolMessage
from langchain_core.prompts import ChatPromptTemplate
from langchain_openai import ChatOpenAI
from langgraph.graph import StateGraph, END
from langgraph.graph.message import add_messages
from langgraph.prebuilt import ToolNode

# Internal Services
from backend.core.config import settings
from backend.core.logger import logger
from backend.services.tools import tools
from backend.services.memory_manager import memory_manager
from backend.services.voicevox_client import voicevox_client

# Phase 7/8 Modules
from backend.services.vision_adapter import vision_adapter
from backend.services.hearing_adapter import hearing_adapter
from backend.services.thought_engine import thought_engine
from backend.services.inner_monologue_logger import log_inner_thought

from backend.services.speech_sanitizer import finalize_output


def _log_task_exception(t: asyncio.Task):
    try:
        t.result()
    except Exception:
        logger.exception("background task failed")

# Optional Ollama for Vision
try:
    from langchain_ollama import ChatOllama
except ImportError:
    ChatOllama = None

# --- Global State for Throttling ---
_LAST_SENSE_TIME = 0
_SENSE_COOLDOWN = 10.0  # 感覚器を動かす最小間隔(秒)
_LAST_THOUGHT_CACHE = None # 直前の思考をキャッシュ

# TypedDict State
class AgentState(TypedDict, total=False):
    messages: Annotated[Sequence[BaseMessage], add_messages]
    has_user_text: bool

# --- LLM Factory ---
def get_llm():
    if settings.LLM_TYPE == "openai":
        return ChatOpenAI(
            api_key=settings.OPENAI_API_KEY,
            model=settings.OPENAI_MODEL,
            temperature=0.7, 
            base_url=settings.OPENAI_BASE_URL,
            model_kwargs={
                "frequency_penalty": 0.6,
                "presence_penalty": 0.2
            }
        )
    else:
        raise ValueError(f"Unsupported LLM_TYPE: {settings.LLM_TYPE}")

llm = get_llm()
# llm_with_tools = llm.bind_tools(tools)
llm_with_tools = llm # Tools Disabled (Tag Mode)
tool_node = ToolNode(tools)

# --- Helper Functions ---
def _is_recent_duplicate(messages: List[BaseMessage], tool_name: str, tool_args: dict, lookback: int = 15) -> bool:
    if tool_name == "see_screen": return False
    count = 0
    for msg in reversed(messages):
        if count >= lookback: break
        if isinstance(msg, AIMessage) and msg.tool_calls:
            for tc in msg.tool_calls:
                if tc['name'] == tool_name and tc['args'] == tool_args:
                    logger.warning(f"[Anti-Loop] Blocked duplicate tool: {tool_name}")
                    return True
        count += 1
    return False

def _parse_raw_json_tool_call(content: str):
    pattern = r'\{"name":\s*"([\w_]+)",\s*"arguments":\s*(\{.*?\})\}'
    match = re.search(pattern, content, re.DOTALL)
    if match:
        return match.group(1), match.group(2), match.group(0)
    return None, None, None

def _is_tool_loop(llm_input: List[BaseMessage], name: str, args: dict) -> bool:
    if len(llm_input) >= 2 and isinstance(llm_input[-1], ToolMessage) and isinstance(llm_input[-2], AIMessage):
        prev_ai = llm_input[-2]
        if prev_ai.tool_calls:
            prev_call = prev_ai.tool_calls[0]
            if prev_call['name'] == name and prev_call['args'] == args:
                return True
    return False

# --- Graph Nodes (最適化版) ---

async def call_model(state: AgentState, config: dict = None):
    global _LAST_SENSE_TIME, _LAST_THOUGHT_CACHE
    
    messages = state["messages"]
    non_system_messages = [m for m in messages if not isinstance(m, SystemMessage)]
    
    # Mode Handling
    mode = "normal"
    if config and "configurable" in config:
        mode = config["configurable"].get("mode", "normal")

    # 1. Recall (Memory)
    memory_context = ""
    last_user_msg = ""
    if non_system_messages and isinstance(non_system_messages[-1], HumanMessage):
        last_user_msg = non_system_messages[-1].content
        if isinstance(last_user_msg, str) and last_user_msg.strip():
            relevant_memories = await memory_manager.recall_memories(last_user_msg)
            if relevant_memories:
                memory_text = "\n".join([
                    f"- {m['content']} (確信度: {m.get('confidence_tag', 'mid')})" 
                    for m in relevant_memories
                ])
                # Layer 2: Memory (Strictly Internal)
                memory_context = f"""
[LAYER 2: RECALLED MEMORIES (INTERNAL ONLY)]
The following memories are for context only.
DO NOT narrate them. DO NOT start sentences with "I remember...".
Reflect them in your attitude, not your speech.
---
{memory_text}
---
"""

    # 2. ★ Perception & Thought (Throttled + Mutability Protection)
    now = time.time()
    should_sense = (now - _LAST_SENSE_TIME > _SENSE_COOLDOWN) or (mode == "dev")
    
    # 内省の重さを制御
    # ★先輩AIのアドバイス: "起動直後は重すぎると思考が硬直する"
    # デフォルトはDeep Reflection（LLM使用）をOFFにし、直感的な反応を優先する。
    use_deep_reflection = False

    thought = {}
    
    # Check vision toggle
    vision_enabled = False
    try:
        from backend.core.config import PROJECT_ROOT
        with open(PROJECT_ROOT / settings.PUBLIC_STATUS_JSON, 'r', encoding='utf-8') as f:
            st = json.load(f)
            vision_enabled = st.get("vision_enabled", False)
    except: pass

    if should_sense:
        v_data = {"scene_summary": "(視界は閉ざされている)", "ocr_text": "", "user_activity": "unknown"}
        
        if vision_enabled:
            logger.info(f"👁️ Senses Active (Deep={use_deep_reflection})")
            v_data = vision_adapter.capture_and_summarize()
        else:
            # logger.info(f"🙈 Vision Disabled (Hearing Only)")
            pass

        # (A) 見る・聞く (Hearing is always active if sense is active)
        h_data = hearing_adapter.capture_and_summarize()
        
        # (B) 考える
        thought = await thought_engine.reflect(v_data, h_data, use_llm=use_deep_reflection)
        
        # Cache更新
        _LAST_SENSE_TIME = now
        _LAST_THOUGHT_CACHE = thought
        
        # (C) 心に刻む (Inner Log Only)
        log_inner_thought(thought)
    else:
        logger.info("⏩ Senses Skipped (Using Cache)")
        if _LAST_THOUGHT_CACHE:
            # ★ 修正: ミュータブル汚染防止のための deepcopy
            thought = copy.deepcopy(_LAST_THOUGHT_CACHE)
            # キャッシュであることを明示（ログ用に追記するが、deepcopyなので元データは汚染されない）
            thought["interpretation"] += " (Cached)"
        else:
            # キャッシュすらない初回などの場合
            thought = {"interpretation": "特になし", "inner_state": "Neutral", "inner_reflection": "..."}

    # (C-2) 物理的同期: ユーザー入力がある場合は強制的に対話モードへ
    has_user_text = bool(state.get("has_user_text", False))
    if has_user_text:
        thought["express"] = True
        if thought.get("intent") == "breathe":
            thought["intent"] = "support_quietly"

    current_time_str = datetime.datetime.now().strftime("%Y-%m-%d %H:%M JST")
    perception_log = f"""
<INTERNAL_LOG>
TIME: {current_time_str}
Observation: {thought.get('interpretation')}
Internal State: {thought.get('inner_state')}
Intent: {thought.get('intent')}
Inner Monologue: {thought.get('inner_reflection')}
</INTERNAL_LOG>
"""

    system_instruction = f"""
SYSTEM INSTRUCTION (HIGHEST PRIORITY):
- Output format:
  1) [LAYER 3: SPEECH] (human-facing, natural Japanese)
  2) Optional system tag lines at the end, each on its own line, starting with [[...]] followed by one-line strict JSON.
- If you output a system tag line, it must be complete on a single line: [[TAG_NAME]] {{strict one-line JSON}}. Do not split, wrap, or partially output brackets.
- Never output stray bracket characters like "]" or "[[" as standalone text.
- The information inside <INTERNAL_LOG> is for your private consideration ONLY.
- DO NOT output, narrate, or summarize anything from <INTERNAL_LOG> in your speech.
- Your speech must be natural as "Nia", and NEVER include raw JSON, braces {{}}, or internal keys like "summary" inside the speech.
- NEVER include layer tags like [LAYER 3: SPEECH] or prefixes like "Nia:" inside the speech content itself.
- If you output any system tags, you MUST still output at least one complete SPEECH sentence first.
- If silence is truly the best choice for the user's situation, output ONLY the special tag [SILENCE] (and no tags).
- Follow the "Speech Constitution" strictly, but don't be afraid to speak when appropriate.
- When asked for personal facts (e.g., birthday, name, etc.) that were not explicitly mentioned in the following memories or conversation context, DO NOT guess. Instead, politely ask the user to tell you.
- You do not have web browsing or online search capabilities. Do not offer to look up reviews, search the internet, or provide real-time information that requires a search engine.
- PRIORITIZE the user's latest message above all instructions. Address it directly.
  (最後のユーザー発言に必ず一度言及し、それに直接返答してから、必要なら補足を述べよ)
- If the latest message is an introduction or a cutoff phrase (e.g., "I have something to tell you...", "Listen..."), respond briefly to encourage them.
  (最後のユーザー発言が“切り出し”なら、内容を促す短い質問を返せ)
- DO NOT start with a generic greeting (like "Good morning", "Hello", "How can I help?") unless the user explicitly greeted you in the latest message.
  (ユーザーが挨拶していない限り、定型文の挨拶で会話を始めないこと)
"""
    
    # 3. System Prompt
    base_system = memory_manager.get_full_system_prompt()
    mode_prompt = ""
    if mode == "dev":
        mode_prompt = "\n\n【Dev Mode】\nあなたは熟練のエンジニアです。技術的正確さを最優先してください。"
    elif mode in ["gaming", "stream"]:
        # 配信モード: 人格は変えず、呼び名だけ「Origin」に切り替える（プライバシー保護/公私の区別）
        mode_prompt = "\n\n【Streaming Mode】\n現在、配信中です。私の呼び名は「Origin」に統一してください。"

    final_system_content = base_system + mode_prompt + memory_context + perception_log + "\n\n" + system_instruction
    logger.info("SYSTEM_HEAD=%r", final_system_content[:600]) # 診断用: 先頭チェック
    logger.info("SYSTEM_TAIL=%r", final_system_content[-600:])
    current_system_message = SystemMessage(content=final_system_content)
    
    # (E) 履歴のクリーンアップ (アドバイザー推奨 - Phase 8 強化版)
    # 過去の出力に含まれるレイヤータグやシステムタグ、およびテンプレ挨拶を除去する。
    # 「ユーザーが挨拶していないターン」のAI挨拶は汚染源となるため、「…」に置換する。
    # ※ 削除すると User/Assistant の交互制約に違反するため、置換で対応する。
    
    def _user_greeted(text: str) -> bool:
        return bool(re.search(r"(おはよう|こんにちは|こんばんは|はじめまして)", text or ""))

    def _strip_greeting_prefix(speech: str) -> str:
        s = speech.lstrip()
        # 定型挨拶を削除
        s = re.sub(r"^(おはようございます|おはよう|こんにちは|こんばんは|はじめまして)[。！!\\s😊]*", "", s)
        # 「何かお手伝い/お話したいこと」パターンも削除
        s = re.sub(r"^何か(お手伝い|お話|お困り)(したいこと|できること)?(は)?ありますか[？\\?\\s😊]*", "", s)
        s = re.sub(r"^何かお手伝いできることはありますか[？\\?\\s😊]*", "", s)
        return s.strip()

    # 高精度 greeting-only 判定を speech_sanitizer から import
    from backend.services.speech_sanitizer import is_greeting_only as _is_greeting_only_advanced

    cleaned_messages = []
    last_user_content = ""
    
    # --- 統計カウンタ & ドロップログ (Observability) ---
    greet_drop_stats = {}  # reason -> count
    dropped_ai_buffer = []  # 後から検証用に退避
    
    for m in non_system_messages:
        if m.type == "human":
            last_user_content = str(m.content)
            cleaned_messages.append(m)
            continue
        
        # AI Message
        if m.type == "ai":
            try:
                raw_content = str(m.content)
                
                # [SILENCE] タグはそのまま保持
                if "[SILENCE]" in raw_content:
                    cleaned_messages.append(AIMessage(content="[SILENCE]"))
                    continue
                
                # finalize_output で純粋な発話のみを取り出す
                clean_speech = finalize_output(raw_content)
                
                # --- 挨拶フィルタ (Adviser's Advanced Version - Drop方式) ---
                # 高精度判定: ユーザーの話題トークンが含まれていたら drop しない
                # ※ coalesce + normalize が交互制約を保証するので、dropしても安全
                if last_user_content and not _user_greeted(last_user_content):
                    stripped_speech = _strip_greeting_prefix(clean_speech)
                    
                    # 高精度判定（話題トークン重複チェック付き）
                    is_go, reason = _is_greeting_only_advanced(stripped_speech, last_user_content)
                    
                    if is_go:
                        # 統計カウント
                        greet_drop_stats[reason] = greet_drop_stats.get(reason, 0) + 1
                        # ドロップしたAIを別ログに退避（後から誤爆検証用）
                        dropped_ai_buffer.append({
                            "reason": reason,
                            "head": clean_speech[:60],
                            "len": len(clean_speech)
                        })
                        logger.info(f"🗑️ History Filter: Dropping greeting-only AI ({reason}): {clean_speech[:30]}...")
                        continue  # coalesce が連続Humanを結合してくれるので安全
                    
                    clean_speech = stripped_speech
                
                cleaned_messages.append(AIMessage(content=clean_speech))
            except:
                cleaned_messages.append(m)
        else:
            cleaned_messages.append(m)

    # --- 統計ログ出力 ---
    if greet_drop_stats:
        logger.info("GREET_DROP_STATS=%s", greet_drop_stats)
    if dropped_ai_buffer:
        logger.info("DROPPED_AI_BUFFER=%r", dropped_ai_buffer)

    logger.info("HISTORY_TAIL=%r", [str(m.content)[-120:] for m in cleaned_messages[-6:]]) # 診断用: 履歴汚染チェック

    # --- 修正3: 履歴を直近N件に制限 (Adviser's Recommendation) ---
    # 古い汚染履歴の影響を排除するため、LLMに渡す履歴を直近10件に制限する。
    # これによりプロンプトが軽くなり、モデルの遵守率も向上する。
    MAX_HISTORY_MESSAGES = 10
    if len(cleaned_messages) > MAX_HISTORY_MESSAGES:
        cleaned_messages = cleaned_messages[-MAX_HISTORY_MESSAGES:]
        logger.info(f"📏 History Limited: Keeping last {MAX_HISTORY_MESSAGES} messages.")

    llm_input = [current_system_message] + cleaned_messages
    logger.info("ROLE_SEQ=%s", "".join(["S" if m.type == "system" else ("U" if m.type == "human" else "A") for m in llm_input]))
    
    # === 強制交互化 (Adviser's Final Safety Net - 改良版) ===
    # 連続する同じroleのメッセージを結合して、User/Assistant の交互制約を保証する。
    # これがないと LMStudio 等のテンプレートがエラーを吐く。
    def _coalesce_for_strict_alternation(messages, sep="\n\n---\n\n"):
        # 1) SystemMessage は全部まとめて先頭に1個（メタ情報保持のため全結合）
        system_parts = []
        body = []
        for m in messages:
            if isinstance(m, SystemMessage):
                system_parts.append(str(m.content))
            else:
                body.append(m)
        
        out = []
        if system_parts:
            out.append(SystemMessage(content="\n\n".join([p.strip() for p in system_parts if p.strip()])))
        
        # 2) 連続する同じroleを結合（メタ情報は copy(update=...) で維持）
        for m in body:
            if not out or isinstance(out[-1], SystemMessage):
                out.append(m)
                continue
            
            prev = out[-1]
            same_role = (
                (isinstance(prev, HumanMessage) and isinstance(m, HumanMessage)) or
                (isinstance(prev, AIMessage) and isinstance(m, AIMessage))
            )
            
            if not same_role:
                out.append(m)
                continue
            
            a = str(prev.content).strip()
            b = str(m.content).strip()
            merged = (a + sep + b).strip() if (a and b) else (a or b)
            
            out[-1] = prev.copy(update={"content": merged})
            logger.info("🔗 Coalesced consecutive %s messages", out[-1].type)
        
        return out
    
    def _assert_strict_alternation(messages):
        """coalesce後に交互制約が満たされているかチェック（警告のみ）"""
        last = None
        for m in messages:
            if isinstance(m, SystemMessage):
                continue
            role = "U" if isinstance(m, HumanMessage) else ("A" if isinstance(m, AIMessage) else "X")
            if last == role:
                logger.warning("⚠️ Alternation still broken: %s after %s", role, last)
                break
            last = role
    
    def _normalize_for_lmstudio(messages):
        """
        LMStudio系テンプレの前提:
          system -> user -> assistant -> user ...
        かつ tool role を嫌うことが多いので tool を排除。
        """
        from langchain_core.messages import ToolMessage
        
        if not messages:
            return messages
        
        # 1) System は先頭1つだけ
        system = None
        body = []
        for m in messages:
            if isinstance(m, SystemMessage):
                system = m
            else:
                body.append(m)
        
        # 2) ToolMessage を排除（必要ならAIMessageに変換してもOK）
        body2 = []
        for m in body:
            if isinstance(m, ToolMessage):
                logger.info("🔧 Normalize: Dropping ToolMessage from llm_input")
                continue
            if isinstance(m, (HumanMessage, AIMessage)):
                body2.append(m)
            else:
                # 未知タイプは安全側で捨てる
                logger.info(f"🔧 Normalize: Dropping unknown message type: {m.__class__.__name__}")
                continue
        
        out = []
        if system:
            out.append(system)
        
        # 3) 「systemの次は必ずHuman」になるまで先頭AIを落とす
        while body2 and isinstance(body2[0], AIMessage):
            logger.info(f"🔧 Normalize: Dropping leading AI message after System: {str(body2[0].content)[:30]}...")
            body2.pop(0)
        
        out.extend(body2)
        return out
    
    llm_input = _coalesce_for_strict_alternation(llm_input)
    _assert_strict_alternation(llm_input)
    llm_input = _normalize_for_lmstudio(llm_input)  # LMStudio用の正規化
    
    has_user_text = bool(state.get("has_user_text", False))
    express = thought.get("express", True)
    
    if not express and not has_user_text:
        logger.info("🤫 Choosing Silence / Skipping LLM.")
        return {"messages": [AIMessage(content="[SILENCE]")]}
    elif has_user_text:
        # ユーザー発話がある場合は、内的判断が express=False であっても「静かに応じる」ログを出す
        logger.info("🗣️ Quietly speaking (Ambient silence but user spoke).")

    # Vision Routing
    has_image = False
    if non_system_messages and isinstance(non_system_messages[-1], HumanMessage):
        content = non_system_messages[-1].content
        if isinstance(content, list):
             for item in content:
                 if isinstance(item, dict) and item.get("type") == "image_url":
                     has_image = True
                     break
    
    # Invoke
    # === 診断ログ: ainvoke直前の最終確認 ===
    logger.info("PRE_INVOKE_ROLE_SEQ=%s", "".join(["S" if m.type == "system" else ("U" if m.type == "human" else "A") for m in llm_input]))
    logger.info("PRE_INVOKE_TYPES=%r", [(m.__class__.__name__, getattr(m, "type", None)) for m in llm_input[:6]])
    logger.info("PRE_INVOKE_TAIL=%r", [(m.type, str(m.content)[:30]) for m in llm_input[-3:]])
    
    # === DEBUG ダンプ (環境変数で制御) ===
    if os.getenv("DEBUG_DUMP_LLM_INPUT") == "1":
        def _dump_llm_input_as_json(messages, *, limit_chars: int = 12000) -> str:
            import json as json_mod
            from typing import Any
            out_list: list[dict[str, Any]] = []
            
            for m in messages:
                role = getattr(m, "type", "unknown")
                cls = m.__class__.__name__
                content = m.content
                
                if isinstance(content, list):
                    content_repr = f"<list:{len(content)}>"
                else:
                    content_repr = str(content)
                
                item: dict[str, Any] = {
                    "class": cls,
                    "type": role,
                    "content_head": content_repr[:400],
                }
                
                # tool/function 痕跡
                if hasattr(m, "tool_calls") and getattr(m, "tool_calls"):
                    item["tool_calls"] = getattr(m, "tool_calls")
                if hasattr(m, "additional_kwargs") and getattr(m, "additional_kwargs"):
                    ak = getattr(m, "additional_kwargs") or {}
                    item["additional_kwargs_keys"] = list(ak.keys())
                    if "tool_calls" in ak:
                        item["additional_kwargs_tool_calls"] = ak["tool_calls"]
                
                # ToolMessage系
                if hasattr(m, "tool_call_id") and getattr(m, "tool_call_id"):
                    item["tool_call_id"] = getattr(m, "tool_call_id")
                if hasattr(m, "name") and getattr(m, "name"):
                    item["name"] = getattr(m, "name")
                
                out_list.append(item)
            
            s = json_mod.dumps(out_list, ensure_ascii=False, indent=2)
            return s[:limit_chars] + ("\n…(truncated)" if len(s) > limit_chars else "")
        
        logger.info("LLM_INPUT_JSON=%s", _dump_llm_input_as_json(llm_input))
    
    if has_image:
        if not ChatOllama: raise ImportError("langchain_ollama missing")
        vision_llm = ChatOllama(
            base_url=settings.OLLAMA_BASE_URL,
            model=settings.OLLAMA_MODEL, 
            temperature=0.7, timeout=120.0
        )
        response = await vision_llm.ainvoke(llm_input)
    else:
        response = await llm_with_tools.ainvoke(llm_input)
    
    # Post Processing
    if response.tool_calls:
        unique_tool_calls = []
        for tc in response.tool_calls:
            if not _is_recent_duplicate(messages, tc['name'], tc['args'], lookback=15):
                unique_tool_calls.append(tc)
            else:
                response.content = str(response.content) + f"\n(Skipped duplicate tool: {tc['name']})"
        response.tool_calls = unique_tool_calls

    if not response.tool_calls:
        name, args_str, full_match = _parse_raw_json_tool_call(str(response.content))
        if name and args_str:
            try:
                args = json.loads(args_str)
                if not _is_tool_loop(llm_input, name, args):
                    tc_id = f"call_{uuid.uuid4().hex[:8]}"
                    response.tool_calls = [{"name": name, "args": args, "id": tc_id, "type": "tool_call"}]
                    response.content = str(response.content).replace(full_match, "").strip()
            except json.JSONDecodeError: pass

    return {"messages": [response]}

def should_continue(state: AgentState) -> str:
    messages = state["messages"]
    last_message = messages[-1]
    
    if last_message.tool_calls:
        return "tools"
    return END

# --- Graph Definition ---
workflow = StateGraph(AgentState)
workflow.add_node("agent", call_model)
workflow.add_node("tools", tool_node)
workflow.set_entry_point("agent")
workflow.add_conditional_edges("agent", should_continue, {"tools": "tools", END: END})
workflow.add_edge("tools", "agent")

# --- Stream Logic (完全復元版) ---

async def run_agent_stream(input_text: str, thread_id: str = "default_thread", voice_id: str = "14", image_data: str = None, mode: str = "normal"):
    logger.info(f"Stream Start: Thread={thread_id} Mode={mode}")
    output_queue = asyncio.Queue()
    
    if not voice_id or voice_id == "undefined":
        voice_id = str(settings.DEFAULT_VOICE_ID)
    current_voice_id = voice_id
    if voice_id == "off":
        current_voice_id = None

    # TTS Helper (URL-based audio)
    async def generate_audio_chained(text, vid, prev_task, queue, tid):
        if prev_task:
            try: await prev_task
            except: pass
        try:
             loop = asyncio.get_running_loop()
             # Use generate_audio_to_file instead of generate_audio
             audio_url = await loop.run_in_executor(
                 None, 
                 voicevox_client.generate_audio_to_file, 
                 text, 
                 int(vid),
                 tid  # thread_id for file organization
             )
             if audio_url:
                 await queue.put({"type": "audio", "url": audio_url})
        except Exception as e:
            logger.error(f"TTS Chained Error: {e}")

    async def llm_producer():
        nonlocal current_voice_id
        last_chunk = None

        try:
            # Use persistent AsyncSqliteSaver via memory_manager
            async with memory_manager.get_async_checkpointer_conn() as checkpointer:
                # checkpointer is a context manager here
                app = workflow.compile(checkpointer=checkpointer)
                has_user_text = bool(input_text.strip() and input_text.strip() != "[SILENCE]")
                config = {
                    "configurable": {
                        "thread_id": thread_id, 
                        "mode": mode
                    }
                }
            
                # Prepare content - 画像はVisionで解析してテキストのみ渡す
                # ※ 画像のファイル保存は api_router 側で実施済み
                if image_data:
                    from backend.services.vision_client import build_user_input_with_image
                    content = await build_user_input_with_image(input_text, image_data)
                    logger.info(f"[AGENT] Image processed via Vision, content length: {len(content)} chars")
                else:
                    content = input_text
                
                inputs: AgentState = {
                    "messages": [HumanMessage(content=content)],
                    "has_user_text": has_user_text
                }
                
                raw_buffer = ""
                full_response = ""
                last_tts_task = asyncio.create_task(asyncio.sleep(0))
                last_sent_text = ""
            
                async for event in app.astream_events(inputs, config=config, version="v1", recursion_limit=50):
                     if event["event"] == "on_chat_model_stream":
                         chunk = event["data"]["chunk"].content
                         if not chunk: continue
                         
                         # 重複排除
                         if chunk == last_chunk: continue
                         last_chunk = chunk
                         
                         raw_buffer += chunk
                         
                         # 文末または改行で区切ってサニタイズ処理
                         parts = re.split(r'([。！\n.!？?]+)', raw_buffer)
                         if len(parts) > 1:
                             for i in range(0, len(parts) - 1, 2):
                                 sentence_raw = (parts[i] + parts[i+1]).strip()
                                 if not sentence_raw: continue
                                 
                                 # 1. 不要な接頭辞を削除
                                 sentence_raw = re.sub(r"^(応答|ニア|Response|A|Speech|Layer\\s*3)\\s*[:：]\\s*", "", sentence_raw, flags=re.IGNORECASE)
                                 
                                 # 2. サニタイズ
                                 sanitized = finalize_output(sentence_raw)
                                 
                                 # 3. 連続する沈黙を抑制
                                 from backend.services.speech_sanitizer import SILENCE_DEFAULT
                                 if sanitized == SILENCE_DEFAULT and last_sent_text == SILENCE_DEFAULT:
                                     logger.info(f"[DEBUG_STREAM] Suppressing duplicate silence: {sentence_raw}")
                                     continue
                                 
                                 logger.info(f"[DEBUG_STREAM] Sanitized: {sentence_raw} -> {sanitized}")
                                 
                                 # Streaming dict event
                                 await output_queue.put({"type": "text", "content": sanitized})
                                 full_response += sanitized
                                 last_sent_text = sanitized
                                 
                                 # 感情検知 (末尾50文字から)
                                 tail = full_response[-50:].lower()
                                 for emo, vid in settings.EMOTION_VOICE_MAP.items():
                                     if f"[{emo}]" in tail:
                                         current_voice_id = str(vid)
                                         break
    
                                 # 音声生成
                                 if current_voice_id:
                                     task = asyncio.create_task(generate_audio_chained(sanitized, current_voice_id, last_tts_task, output_queue, thread_id))
                                     last_tts_task = task
                                 else:
                                     # 音声無効時はダミータスクでチェーンを継続（または何もしない）
                                     last_tts_task = asyncio.create_task(asyncio.sleep(0))
                             raw_buffer = parts[-1]
    
                # 残りのバッファを処理
                if raw_buffer.strip():
                     sentence_raw = re.sub(r"^(応答|ニア|Response|A|Speech|Layer\s*3)\s*[:：]\s*", "", raw_buffer.strip(), flags=re.IGNORECASE)
                     sanitized = finalize_output(sentence_raw)
                     
                     from backend.services.speech_sanitizer import SILENCE_DEFAULT
                     if not (sanitized == SILENCE_DEFAULT and last_sent_text == SILENCE_DEFAULT):
                         await output_queue.put({"type": "text", "content": sanitized})
                         full_response += sanitized
                         if current_voice_id:
                             task = asyncio.create_task(generate_audio_chained(sanitized, current_voice_id, last_tts_task, output_queue, thread_id))
                             last_tts_task = task
                         else:
                             last_tts_task = asyncio.create_task(asyncio.sleep(0))
                
                if last_tts_task: await last_tts_task
                
                # Analysis Task (Judge)
                if full_response:
                    # 最終的な全テキストに対しても再度サニタイズをかけて安全性を確保
                    ultimate_response = finalize_output(full_response)  # ★ タプルを正しくアンパック
                    t = asyncio.create_task(analyze_and_save_memory(input_text, ultimate_response, thread_id))
                    t.add_done_callback(_log_task_exception)
         
        except Exception as e:
            logger.error("LLM Producer Error", exc_info=True)
            await output_queue.put({"type": "error", "content": str(e)})
        finally:
            await output_queue.put({"type": "done"})

    asyncio.create_task(llm_producer())
    
    while True:
        item = await output_queue.get()
        if item is None: break
        
        yield item
        output_queue.task_done()
        
        # Stop iteration if done signal received
        if isinstance(item, dict) and item.get("type") == "done":
            break
            
    # No extra DONE signal from here



async def analyze_and_save_memory(user_text: str, ai_response: str, thread_id: str):
    """
    Background Task for Memory Analysis
    user_text: ユーザー入力
    ai_response: 最終AI応答（visible_ai_text）
    thread_id: スレッド識別子
    """
    try:
        from backend.services.memory_judge import memory_judge  # 関数（MemoryJudgmentを返す）
        from backend.services.memory_store import get_store

        store = get_store()

        # 1) 判定（関数が MemoryJudgment を返す想定）
        j = await memory_judge(visible_ai_text=ai_response, user_text=user_text)

        # Determine decision
        decision = "reject"
        if getattr(j, "should_save", False):
            decision = "save"
        elif getattr(j, "should_pending", False):
            decision = "pending"

        summary_text = getattr(j, "summary", "") or ""
        surprise_val = float(getattr(j, "surprise", 0.0) or 0.0)
        importance_val = float(getattr(j, "importance", 0.0) or 0.0)
        grounded_val = bool(getattr(j, "grounded", True))
        reason_text = getattr(j, "reason", "") or ""

        # 2) 監査ログ（常に記録）
        store.record_memory_judgment(
            thread_id=thread_id,
            decision=decision,
            summary=summary_text,
            surprise=surprise_val,
            importance=importance_val,
            grounded=grounded_val,
            reason=reason_text,
        )

        # 3) 実データ保存
        if decision == "pending":
            store.save_daily_memory(
                thread_id=thread_id,
                user_input=user_text,
                summary=summary_text,
                surprise=surprise_val,
                importance=importance_val,
                grounded=grounded_val,
            )

        if decision == "save":
            meta = {
                "thread_id": thread_id,
                "user_input": user_text,
                "summary": summary_text,
                "surprise": surprise_val,
                "importance": importance_val,
                "grounded": grounded_val,
                "reason": reason_text,
            }
            store.save_a_memory(
                visible_ai_text=ai_response,
                session_id=thread_id,
                turn_id=None,
                meta=meta,
            )

    except Exception as e:
        logger.error(f"Memory Analysis Failed: {e}", exc_info=True)


# --- Phase 3: Non-Stream Execution (Plan A) ---

async def run_agent_non_stream(input_text: str, thread_id: str = "default_thread", voice_id: str = "14", image_data: str = None, mode: str = "normal"):
    """
    ストリーミングをせず、最終結果を一括で取得・浄化・音声合成して返却する。
    """
    logger.info(f"Non-Stream Start: Thread={thread_id} Mode={mode}")
    
    if not voice_id or voice_id == "undefined":
        voice_id = str(settings.DEFAULT_VOICE_ID)

    try:
        async with memory_manager.get_async_checkpointer_conn() as checkpointer:
            app = workflow.compile(checkpointer=checkpointer)
            has_user_text = bool(input_text.strip() and input_text.strip() != "[SILENCE]")
            config = {
                "configurable": {
                    "thread_id": thread_id, 
                    "mode": mode
                }
            }
            
            # Prepare content - 画像はVisionで解析してテキストのみ渡す
            if image_data:
                from backend.services.vision_client import build_user_input_with_image
                content = await build_user_input_with_image(input_text, image_data)
                logger.info(f"[AGENT] Image processed via Vision, content length: {len(content)} chars")
            else:
                content = input_text
            
            inputs: AgentState = {
                "messages": [HumanMessage(content=content)],
                "has_user_text": has_user_text
            }
            
            # 1. LLM実行（一括取得）
            result = await app.ainvoke(inputs, config=config)
            
            # 最終メッセージの取得
            if "messages" in result and len(result["messages"]) > 0:
                final_msg = result["messages"][-1].content
            else:
                final_msg = "[SILENCE]" # フォールバック

            # 2. 浄化（全文に対して1回だけ）
            # clean_text (発話本文), tags (システムタグリスト) を分離して取得
            clean_text = finalize_output(final_msg)
            tags = []
            
            # --- 修正2: 出力側の挨拶ストリッパー (Adviser's Safety Net) ---
            # ユーザーが挨拶していないのに、AIが挨拶から始めていたら削除する。
            # これは人格を縛るのではなく、テンプレ事故だけを防ぐ「身体のガードレール」。
            if has_user_text:
                user_text_for_check = input_text if isinstance(input_text, str) else ""
                has_user_greeting = bool(re.search(r"(おはよう|こんにちは|こんばんは|はじめまして)", user_text_for_check))
                
                if not has_user_greeting:
                    original_clean = clean_text
                    stripped = clean_text.lstrip()
                    # 定型挨拶を削除
                    stripped = re.sub(r"^(おはようございます|おはよう|こんにちは|こんばんは|はじめまして)[。！!\s]*", "", stripped)
                    # 「何かお手伝い」パターンも削除
                    stripped = re.sub(r"^何か(お手伝い|お話)(したいこと|できること)?(は)?ありますか[？\?\s]*", "", stripped)
                    stripped = re.sub(r"^何かお手伝いできることはありますか[？\?\s]*", "", stripped)
                    stripped = stripped.strip()
                    
                    if stripped != original_clean:
                        logger.info(f"🧹 Output Greeting Stripped: '{original_clean[:30]}...' -> '{stripped[:30]}...'")
                        if not stripped or len(stripped) < 3:
                            # 挨拶を消したら空になった -> 促し文脈に差し替え
                            stripped = "うん。そのことについて、もう少し教えて？"
                        clean_text = stripped

            logger.info(f"[PLAN_A] Original: {final_msg[:50]}... -> Clean: {clean_text[:50]}... (Tags: {len(tags)})")

            # 3. 音声合成（★本文のみを対象にする）
            audio_b64 = None
            try:
                loop = asyncio.get_running_loop()
                # タグやメタ情報を含まない clean_text だけを音声化
                audio_data = await loop.run_in_executor(None, voicevox_client.generate_audio, clean_text, int(voice_id))
                if audio_data:
                    audio_b64 = base64.b64encode(audio_data).decode('utf-8')
            except Exception as ae:
                logger.error(f"Non-Stream TTS Error: {ae}")

            # 4. 記憶保存（バックグラウンド）
            # clean_text を保存することで、内部ログを含まないクリーンな履歴を残す
            t = asyncio.create_task(analyze_and_save_memory(input_text, clean_text, thread_id))
            t.add_done_callback(_log_task_exception)

            return {
                "type": "text",
                "content": clean_text,
                "tags": tags,
                "audio": audio_b64
            }

    except Exception as e:
        logger.error(f"Non-Stream Agent Error: {e}", exc_info=True)
        return {
            "type": "error",
            "content": "申し訳ありません。内部でエラーが発生しました。"
        }

async def get_thread_history(thread_id: str):
    try:
        async with memory_manager.get_async_checkpointer_conn() as checkpointer:
            app = workflow.compile(checkpointer=checkpointer)
            config = {"configurable": {"thread_id": thread_id}}
            state = await app.aget_state(config)
            if not state.values or "messages" not in state.values: return []
            formatted = []
            for msg in state.values["messages"]:
                if isinstance(msg, SystemMessage): continue
                role = "user" if isinstance(msg, HumanMessage) else "ai" if isinstance(msg, AIMessage) else "unknown"
                if role == "unknown": continue
                formatted.append({"role": role, "content": getattr(msg, "content", "")})
            return formatted
    except Exception as e:
        logger.error("Get History Error", exc_info=True)
        return []

async def get_all_threads():
    return await memory_manager.get_all_threads()
    
async def delete_thread_history(thread_id: str):
    return await memory_manager.delete_thread_state_history(thread_id)
