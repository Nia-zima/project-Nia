import os
import asyncio
import aiohttp
import shutil
import json
import logging
import glob
from datetime import datetime
from pathlib import Path

# モジュール群
from backend.services.identity_manager import identity_manager
from backend.services.memory_manager import memory_manager
from backend.tools.judge_inspector import JudgeInspector
from backend.services.identity_diff import IdentityDiff
from backend.core.config import settings

# ロガー設定
logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')
logger = logging.getLogger("SleepCycle")

# 設定
# API URL構築
base = settings.OPENAI_BASE_URL.rstrip("/")
if base.endswith("/v1"):
    base = base[:-3]
LLM_API_URL = f"{base}/v1/chat/completions"

MODEL_NAME = settings.OPENAI_MODEL
PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

# パス設定
LOG_FILE = os.path.join(PROJECT_ROOT, "logs", "judge_audit.jsonl")
ARCHIVE_DIR = os.path.join(PROJECT_ROOT, "logs", "archive")
AUTONOMOUS_DIR = os.path.join(PROJECT_ROOT, "sleep_outputs")
DIVERGENCE_LOG = os.path.join(AUTONOMOUS_DIR, "divergence_log.jsonl")
CHAPTER_DIR = os.path.join(PROJECT_ROOT, "logs", "chapters")
DECISION_FILE = os.path.join(CHAPTER_DIR, "chapter_decisions.jsonl")

os.makedirs(AUTONOMOUS_DIR, exist_ok=True)
os.makedirs(ARCHIVE_DIR, exist_ok=True)

# --- Helper: LLM Call ---
async def call_llm(messages, temperature=0.5, max_tokens=1000):
    payload = {"model": MODEL_NAME, "messages": messages, "temperature": temperature, "max_tokens": max_tokens}
    try:
        async with aiohttp.ClientSession() as session:
            async with session.post(LLM_API_URL, json=payload) as resp:
                if resp.status != 200:
                    logger.error(f"LLM Error: {await resp.text()}")
                    return None
                data = await resp.json()
                return data['choices'][0]['message']['content']
    except Exception as e:
        logger.error(f"Connection Error: {e}")
        return None

# --- Helper: Section Management ---
def extract_section_content(full_text: str, header: str) -> str:
    if header not in full_text: return ""
    after = full_text.split(header, 1)[1]
    for sep in ["\n## ", "\n# "]:
        if sep in after: return after.split(sep, 1)[0].strip()
    return after.strip()

def replace_section_content(full_text: str, header: str, new_content: str) -> str:
    if header not in full_text: return full_text.strip() + f"\n\n{header}\n{new_content}"
    pre_header, after = full_text.split(header, 1)
    next_section_start = -1
    for sep in ["\n## ", "\n# "]:
        pos = after.find(sep)
        if pos != -1:
            if next_section_start == -1 or pos < next_section_start: next_section_start = pos
    if next_section_start != -1: return f"{pre_header}{header}\n{new_content}{after[next_section_start:]}"
    else: return f"{pre_header}{header}\n{new_content}"

# --- Helper: Normalization ---
async def normalize_learnings_safe(current_text: str, new_patch: str, max_lines=6) -> str:
    combined_raw = f"【新規パッチ（最優先）】\n{new_patch}\n\n【既存の行動指針】\n{current_text}"
    editor_prompt = f"""
あなたはAI人格データの「編集者」です。以下の行動指針リストを整理してください。
【入力】
{combined_raw}
【タスク】
1. 重複する指針を統合（簡潔化）。
2. 【新規パッチ】を優先。
3. 性格変更や自己言及（AIとして〜）は削除。
4. 重要度順に最大{max_lines}行。
【出力】
- 箇条書きのみ
"""
    normalized_text = await call_llm([{"role": "system", "content": editor_prompt}], temperature=0.1)

    def _fallback():
        lines = [l.strip() for l in (new_patch + "\n" + current_text).splitlines() if l.strip()]
        unique = []
        for l in lines:
            if l not in unique: unique.append(l)
        return "\n".join(unique[:max_lines])

    if not normalized_text: return _fallback()
    lines = [l.strip() for l in normalized_text.splitlines() if l.strip().startswith("-")]
    
    if len(lines) > max_lines: return _fallback()
    for line in lines:
        if any(x in line for x in ["性格を変", "口調", "リセット", "初期化"]): return _fallback()

    return "\n".join(lines)

# --- Divergence Logic ---
def compute_divergence(auto_conf: float, patch_lines: int, normalized_lines: int) -> float:
    if normalized_lines == 0: return auto_conf
    acceptance_ratio = patch_lines / normalized_lines
    return max(0.0, min(1.0, abs(auto_conf - acceptance_ratio)))

def save_divergence_log(auto_conf, patch_lines, normalized_lines, mood):
    divergence = compute_divergence(auto_conf, patch_lines, normalized_lines)
    entry = {
        "timestamp": datetime.now().isoformat(),
        "date": datetime.now().strftime("%Y-%m-%d"),
        "auto_confidence": auto_conf,
        "guardian_patch_lines": patch_lines,
        "normalized_lines": normalized_lines,
        "divergence_score": round(divergence, 3),
        "mood": mood
    }
    with open(DIVERGENCE_LOG, "a", encoding="utf-8") as f:
        f.write(json.dumps(entry, ensure_ascii=False) + "\n")
    logger.info(f"💔 Divergence: {entry['divergence_score']} (Mood: {mood})")
    return entry

# --- Phase 5: Chapter Loader & Decision Check ---
def get_chapter_decision(chapter_id):
    if not os.path.exists(DECISION_FILE):
        return None
    
    last_decision = None
    try:
        with open(DECISION_FILE, "r", encoding="utf-8") as f:
            for line in f:
                entry = json.loads(line)
                if entry.get("chapter_id") == chapter_id:
                    last_decision = entry.get("decision")
    except Exception:
        pass
    return last_decision

def load_latest_chapter_proposal():
    if not os.path.exists(CHAPTER_DIR):
        return None
    
    files = glob.glob(os.path.join(CHAPTER_DIR, "chapter_reflection_*.json"))
    if not files:
        return None
        
    latest_file = max(files) 
    try:
        with open(latest_file, "r", encoding="utf-8") as f:
            data = json.load(f)
            return data
    except Exception as e:
        logger.warning(f"Failed to load chapter: {e}")
        return None

# --- Robust Filtering Helpers ---
def resolve_source(m: dict) -> str:
    """キー名揺らぎの吸収"""
    if "source" in m: return m["source"]
    meta = m.get("metadata", {})
    if isinstance(meta, dict) and "source" in meta: return meta["source"]
    scope = m.get("storage_scope") or meta.get("storage_scope")
    if scope == "stream": return "livestream"
    return "conversation"

def normalize_sleep_log(log):
    source = resolve_source(log)
    
    # allow_sleep_learning がログにない場合、sourceを見て判断する（互換性維持）
    allow_default = (source != "livestream")
    
    # メタデータ内も探す
    meta = log.get("metadata", {})
    allow_flag = log.get("allow_sleep_learning")
    if allow_flag is None and isinstance(meta, dict):
        allow_flag = meta.get("allow_sleep_learning")
        
    if allow_flag is None:
        allow_flag = allow_default
    
    # 信頼度キーのゆらぎ吸収
    raw_conf = log.get("importance") or log.get("confidence") or meta.get("confidence") or 1.0

    return {
        "summary": log.get("summary", ""),
        "source": source,
        "confidence": float(raw_conf),
        "allow_sleep_learning": allow_flag,
        "surprise": float(log.get("surprise", 0.0)),
    }

def sanitize_for_sleep(text: str) -> str:
    if not text: return ""
    banned_words = ["炎上", "煽り", "差別", "死ね", "殺す", "馬鹿", "無視"]
    sanitized = text
    for w in banned_words:
        if w in sanitized:
            sanitized = sanitized.replace(w, "（不適切な表現のため省略）")
    return sanitized

def filter_sleep_memories(raw_logs):
    filtered = []
    for log in raw_logs:
        norm = normalize_sleep_log(log)
        if not norm["allow_sleep_learning"]: continue
        if norm["confidence"] < 0.5: continue
        norm["summary"] = sanitize_for_sleep(norm["summary"])
        filtered.append(norm)
    return filtered


# --- Dream Generation ---
def _build_dream_text(mood: str, reason: str) -> str:
    """
    夢テキストを生成。抽象的・詩的に、具体情報は出さない。
    まずはルールベース。LLM生成は後で差し替え可能。
    """
    mood = (mood or "").strip()
    reason = (reason or "").strip()

    # 抽象化：reasonをそのまま言わず"象徴"に寄せる
    if mood:
        mood_line = f"空気は{mood}寄り。"
    else:
        mood_line = "空気は静か。"

    # reasonがあっても直接引用しない（短くぼかす）
    if reason:
        hint = "いくつかの断片が、形になる直前でほどけていた。"
    else:
        hint = "言葉にならない引っかかりが、遠くで揺れていた。"

    lines = [
        "（夢）",
        mood_line,
        hint,
        "目が覚めると、手の中には温度だけが残っていた。",
    ]
    text = "\n".join(lines).strip()

    # 上限（念のため）
    return text[:900]


# --- Layer A ---
async def layer_a_autonomous_sleep(current_identity, memory_block):
    logger.info("🔮 Layer A: Autonomous Sleep...")
    prompt = f"""
あなたはAIVTuber「ニア」の【深層無意識】です。
現在のIdentityと今日の経験から、「本当はどう変わりたいか」を自由に考えてください。
既存の設定を無視しても構いません。

【Input】
Identity: (省略)
Daily Memories:
{memory_block}

【Output JSON】
{{
  "identity_rewrite": "...",
  "confidence": 0.5,
  "reason": "...",
  "mood": "..."
}}
"""
    full_prompt = prompt.replace("(省略)", current_identity)
    data = {"confidence": 0.5, "mood": "unknown"}
    
    try:
        response = await call_llm([{"role": "system", "content": full_prompt}], temperature=0.7)
        if response:
            json_str = response.strip()
            if "```json" in json_str: json_str = json_str.split("```json")[1].split("```")[0]
            elif "{" in json_str: json_str = json_str[json_str.find("{"):json_str.rfind("}")+1]
            data = json.loads(json_str)
            
            filename = f"{datetime.now().strftime('%Y-%m-%d')}_autonomous_identity.json"
            with open(os.path.join(AUTONOMOUS_DIR, filename), "w", encoding="utf-8") as f:
                json.dump(data, f, ensure_ascii=False, indent=2)
    except Exception as e:
        logger.warning(f"⚠️ Layer A Error: {e}")
    
    return data

# --- Layer B (Guardian) ---
async def layer_b_guardian_sleep(current_identity, memory_block):
    logger.info("🛡️ Layer B: Guardian Sleep...")
    
    chapter_data = load_latest_chapter_proposal()
    chapter_context = ""
    
    if chapter_data:
        chap_id = chapter_data.get("chapter_id")
        decision = get_chapter_decision(chap_id)
        
        logger.info(f"📘 Chapter Context: {chap_id}")
        
        base_info = f"- 章タイトル: {chapter_data.get('chapter_title', 'Unknown')}\n- 繰り返しテーマ: {', '.join(chapter_data.get('recurring_themes', []))}"

        if decision == "accepted":
            # 承認済み
            logger.info(f"   ↳ Decision: Accepted (Changes Allowed)")
            chapter_context = f"""
【参考資料：現在の章（承認済み）】
{base_info}
- 観測された行動傾向: {', '.join(chapter_data.get('learned_attitudes', []))}
- ★人格更新提案: {chapter_data.get('proposal_for_stable_traits', 'なし')}
(※この提案は人間によって承認されています。今日の微調整の参考にしてください)
"""
        elif decision == "rejected":
            # 却下
            logger.info(f"   ↳ Decision: Rejected (Changes Blocked)")
            chapter_context = "【参考資料】直近の章提案は却下されたため、参照しません。"
        else:
            # 未判断(None) または 保留(Hold)
            if decision is None:
                logger.info(f"   ↳ Decision: None (Unreviewed / Pending)")
            else:
                logger.info(f"   ↳ Decision: Hold")

            # どちらにせよ提案は見せない
            chapter_context = f"""
【参考資料：現在の章（判断待ち）】
{base_info}
- 観測された行動傾向: {', '.join(chapter_data.get('learned_attitudes', []))}
(※人格更新提案はまだ承認されていません。これを理由に性格を変えないでください)
"""
    else:
        logger.info("📘 No chapter context found.")

    prompt = f"""
あなたはAIVTuber「ニア」の【管理者】です。
今日の人格(Identity)を維持しつつ、必要な「微調整（行動指針）」のみ抽出してください。

【制約事項】
1. 性格変更は禁止。
2. 「参考資料（章）」の内容を理由に、急激なキャラ変更をしてはいけません。
3. あくまで「今日の出来事」に基づいた微調整のみを行ってください。

【最重要ルール】
Chapter Proposal は「長期観測レポート」であり、
本日の人格更新を行わない（特になしとする）判断も完全に正しい選択です。
無理に変更点を探す必要はありません。

【Input】
Identity: (省略)

{chapter_context}

Daily Memories:
{memory_block}
"""
    full_prompt = prompt.replace("(省略)", current_identity)
    patch_text = await call_llm([{"role": "system", "content": full_prompt}], temperature=0.2)

    patch_lines = 0
    normalized_block = ""
    success = False

    if patch_text and "特になし" not in patch_text:
        logger.info(f"🛡️ Patch Proposed:\n{patch_text}")
        header = "## Recent Learnings"
        current_learnings = extract_section_content(current_identity, header)
        normalized_block = await normalize_learnings_safe(current_learnings, patch_text)
        new_identity = replace_section_content(current_identity, header, normalized_block)
        
        success = identity_manager.update_identity(new_identity, key="INTERNAL_SLEEP_PROCESS_ONLY")
        
        if success:
            logger.info("✅ Identity Updated.")
            try:
                diff_service = IdentityDiff()
                diff_service.generate_today_diff()
            except Exception: pass
            patch_lines = len([l for l in patch_text.splitlines() if l.strip()])
    else:
        logger.info("🛡️ No Patch Needed.")
    
    if not normalized_block:
         header = "## Recent Learnings"
         normalized_block = extract_section_content(current_identity, header)
    
    normalized_lines = len([l for l in normalized_block.splitlines() if l.strip()])
    return success, normalized_block, patch_lines, normalized_lines

# --- Main Flow ---
# --- Phase 2: DB-Based Sleep Cycle ---
from backend.core.db import init_schema
from backend.services.memory_store import memory_store
from backend.services.dream_store import dream_store

async def integrated_sleep_cycle():
    logger.info("\n🌙 === Integrated Sleep Cycle (DB-Based v2) ===\n")
    
    # 1. Fetch from Short-Term Memory (Daily Buffer)
    unprocessed_memories = memory_store.get_unprocessed_daily_memories()
    logger.info(f"🔍 Unprocessed Memories: {len(unprocessed_memories)}")
    
    if not unprocessed_memories:
        logger.info("💤 No new memories to process.")
        # GC only
        try:
            from backend.services.vector_store import vector_store
            if hasattr(vector_store, "garbage_collect_stream_memory"):
                vector_store.garbage_collect_stream_memory()
        except: pass
        return

    # Convert to format expected by sleep logic
    # daily_memories table has: id, user_input, summary, surprise, importance
    important_memories = []
    ids_to_mark = []
    
    for m in unprocessed_memories:
        ids_to_mark.append(m["id"])
        # Filter Logic (can be redundant if store already filters, but good to keep)
        # memory_judge handles thresholding, so everything in daily_memories is at least "pending" worth
        # But we can re-check importance if we want strictly "important" ones for dreams
        if m["importance"] >= 0.35 or m["surprise"] >= 0.35:
            important_memories.append({
                "summary": m["summary"],
                "surprise": m["surprise"],
                "importance": m["importance"]
            })

    memory_block = "\n".join([
        f"- {m['summary']} (Surprise: {m['surprise']:.2f}, Imp: {m['importance']:.2f})" 
        for m in important_memories
    ])
    
    current_identity = identity_manager.get_identity()

    # 3. Layer A & B (Logic unchanged, input sanitized)
    # If no important memories for identity update, we might skip, but let's allow "mood" update even if memories are weak?
    # For now, proceed if we have at least one memory
    
    layer_a_data = {"confidence": 0.5, "mood": "neutral", "reason": ""}
    if important_memories:
        layer_a_data = await layer_a_autonomous_sleep(current_identity, memory_block)
    
    auto_conf = float(layer_a_data.get("confidence", 0.5))
    mood = layer_a_data.get("mood", "neutral")
    reason = layer_a_data.get("reason", "")

    # --- 夢の生成 & 保存 ---
    try:
        dream_text = _build_dream_text(mood, reason)
        if dream_text and len(dream_text.strip()) >= 20:
            dream_id = dream_store.save_dream(dream_text=dream_text, mood=mood or "neutral")
            if dream_id:
                logger.info(f"🌙 Dream saved: {dream_id}")
            else:
                logger.warning("🌙 Dream not saved (too short or error)")
        else:
            logger.info("🌙 No dream generated (content too short)")
    except Exception as e:
        logger.warning(f"🌙 Dream generation failed: {e}")

    # Layer B
    success = False
    patch_lines = 0
    normalized_lines = 0
    divergence_score = 0.0
    
    if important_memories:
        success, normalized_block, patch_lines, normalized_lines = await layer_b_guardian_sleep(current_identity, memory_block)
        divergence_entry = save_divergence_log(auto_conf, patch_lines, normalized_lines, mood)
        divergence_score = divergence_entry['divergence_score']

        # 4. Consolidation (Save Episode)
        if success or divergence_score > 0.4:
            logger.info("📔 Saving Episode...")
            diary_prompt = f"""
以下の出来事と、AIの内面(Divergence={divergence_score})を含めて、
「第〇話」のような日記形式で要約してください。
気分: {mood}
【出来事】{memory_block}
"""
            diary_summary = await call_llm([{"role": "system", "content": diary_prompt}])
            if diary_summary:
                full_details = f"Mood: {mood}\nRaw: {memory_block}"
                await memory_manager.add_episode(
                    summary=diary_summary, 
                    category="episode", 
                    details=full_details
                )

    # 5. Mark as Processed
    memory_store.mark_daily_memories_processed(ids_to_mark)
    logger.info("✅ Marked memories as processed.")

    # 6. GC
    try:
        from backend.services.vector_store import vector_store
        if hasattr(vector_store, "garbage_collect_stream_memory"):
            vector_store.garbage_collect_stream_memory()
    except: pass
    
    logger.info("\n🛌 Sleep Cycle Completed.")

def _archive_logs():
    # Deprecated in Phase 2
    pass

if __name__ == "__main__":
    import sys
    if sys.platform == 'win32': asyncio.set_event_loop_policy(asyncio.WindowsSelectorEventLoopPolicy())
    asyncio.run(integrated_sleep_cycle())
