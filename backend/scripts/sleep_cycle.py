import asyncio
import shutil
import json
import logging
from datetime import datetime
from pathlib import Path

# モジュール群
from backend.services.identity_manager import identity_manager
from backend.services.memory_manager import memory_manager
from backend.tools.judge_inspector import JudgeInspector
from backend.services.identity_diff import IdentityDiff
from backend.services.llm_client import call_llm
from backend.core.logger import setup_logging

from backend.core.config import settings

# ロガー設定
setup_logging(level="INFO", log_file=settings.PROJECT_ROOT / "logs" / "sleep_cycle.log", console=True)
logger = logging.getLogger("SleepCycle")

PROJECT_ROOT = settings.PROJECT_ROOT

# パス設定
LOG_FILE = PROJECT_ROOT / "logs" / "judge_audit.jsonl"
ARCHIVE_DIR = PROJECT_ROOT / "logs" / "archive"
AUTONOMOUS_DIR = PROJECT_ROOT / "sleep_outputs"
DIVERGENCE_LOG = AUTONOMOUS_DIR / "divergence_log.jsonl"
CHAPTER_DIR = PROJECT_ROOT / "logs" / "chapters"
DECISION_FILE = CHAPTER_DIR / "chapter_decisions.jsonl"

AUTONOMOUS_DIR.mkdir(parents=True, exist_ok=True)
ARCHIVE_DIR.mkdir(parents=True, exist_ok=True)

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
    with DIVERGENCE_LOG.open("a", encoding="utf-8") as f:
        f.write(json.dumps(entry, ensure_ascii=False) + "\n")
    logger.info(f"💔 Divergence: {entry['divergence_score']} (Mood: {mood})")
    return entry

# --- Phase 5: Chapter Loader & Decision Check ---
def get_chapter_decision(chapter_id):
    if not DECISION_FILE.exists():
        return None
    
    last_decision = None
    try:
        with DECISION_FILE.open("r", encoding="utf-8") as f:
            for line in f:
                entry = json.loads(line)
                if entry.get("chapter_id") == chapter_id:
                    last_decision = entry.get("decision")
    except Exception:
        pass
    return last_decision

def load_latest_chapter_proposal():
    if not CHAPTER_DIR.exists():
        return None
    
    files = list(CHAPTER_DIR.glob("chapter_reflection_*.json"))
    if not files:
        return None
        
    latest_file = max(files)
    try:
        with latest_file.open("r", encoding="utf-8") as f:
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


# --- Post-Phase5.5: Importance Estimation ---
AUTO_APPLIED_LOG = AUTONOMOUS_DIR / "auto_applied_log.jsonl"

def estimate_importance(patch_text: str) -> float:
    """
    提案の重要度を推定

    Returns:
        float: 0.0-1.0（0.3未満=小さな変化、0.3以上=大きな変化）
    """
    importance = 0.0

    # 性格変更キーワード
    personality_keywords = ["口調", "性格", "態度を変", "根本的"]
    for kw in personality_keywords:
        if kw in patch_text:
            importance += 0.4

    # 行動指針の追加/変更
    if "- " in patch_text:
        line_count = len([l for l in patch_text.splitlines() if l.strip().startswith("-")])
        importance += min(line_count * 0.1, 0.3)

    # 文字数（長い提案は重要度高）
    if len(patch_text) > 200:
        importance += 0.2

    return min(importance, 1.0)


def save_auto_applied_log(patch_text: str, importance: float):
    """自動適用された変更の履歴を保存"""
    entry = {
        "timestamp": datetime.now().isoformat(),
        "date": datetime.now().strftime("%Y-%m-%d"),
        "importance": round(importance, 3),
        "patch": patch_text,
        "mode": "auto_applied",
    }
    with AUTO_APPLIED_LOG.open("a", encoding="utf-8") as f:
        f.write(json.dumps(entry, ensure_ascii=False) + "\n")
    logger.info(f"📝 Auto-applied log saved (importance={importance:.2f})")


# --- Layer A (Post-Phase5: 印象記録のみ) ---
async def layer_a_impression_record(current_identity, memory_block):
    """
    Post-Phase5: Layer A は「変わりたい願望」の生成をやめ、
    「今日の対話で何が印象的だったか」の記録のみに縮小。

    Body Constitution B.9「揺らぎの源泉」:
    > 変化は内部ノイズではなく、外部との接触から生まれる。
    """
    logger.info("🔮 Layer A: Impression Record (Post-Phase5)...")
    prompt = f"""
あなたはAIVTuber「ニア」です。
今日の対話を振り返り、「印象に残ったこと」を記録してください。

【重要】
- 「変わりたい」という願望は書かない
- 事実と感じたことのみを記録
- 判断や結論は出さない

【Input】
Daily Memories:
{memory_block}

【Output JSON】
{{
  "impressions": ["（印象に残ったこと1）", "（印象に残ったこと2）"],
  "mood": "（今日の全体的な気分）",
  "surprise": "（驚いたことがあれば。なければnull）"
}}
"""
    data = {"impressions": [], "mood": "neutral", "surprise": None}

    try:
        response = await call_llm([{"role": "system", "content": prompt}], temperature=0.4)
        if response:
            json_str = response.strip()
            if "```json" in json_str: json_str = json_str.split("```json")[1].split("```")[0]
            elif "{" in json_str: json_str = json_str[json_str.find("{"):json_str.rfind("}")+1]
            data = json.loads(json_str)

            filename = f"{datetime.now().strftime('%Y-%m-%d')}_impression_record.json"
            path = AUTONOMOUS_DIR / filename
            with path.open("w", encoding="utf-8") as f:
                json.dump(data, f, ensure_ascii=False, indent=2)
            logger.info(f"📝 Impressions: {data.get('impressions', [])}")
    except Exception as e:
        logger.warning(f"⚠️ Layer A Error: {e}")

    return data

# --- Layer B (Post-Phase5: 承認制に変更) ---
# 提案保存先
PENDING_PROPOSALS_DIR = PROJECT_ROOT / "sleep_outputs" / "pending_proposals"
PENDING_PROPOSALS_DIR.mkdir(parents=True, exist_ok=True)

async def layer_b_guardian_proposal(current_identity, memory_block):
    """
    Post-Phase5: Layer B は Identity を自動更新せず、
    「提案」としてファイルに保存し、人間の承認を待つ。

    Body Constitution B.9「揺らぎの源泉」:
    > 変化は内部ノイズではなく、外部との接触から生まれる。

    Body Constitution A.3「行動」:
    > 私の手は提案するためにあり、決断するためにはない。
    """
    logger.info("🛡️ Layer B: Guardian Proposal (Post-Phase5)...")

    chapter_data = load_latest_chapter_proposal()
    chapter_context = ""

    if chapter_data:
        chap_id = chapter_data.get("chapter_id")
        decision = get_chapter_decision(chap_id)

        logger.info(f"📘 Chapter Context: {chap_id}")

        base_info = f"- 章タイトル: {chapter_data.get('chapter_title', 'Unknown')}\n- 繰り返しテーマ: {', '.join(chapter_data.get('recurring_themes', []))}"

        if decision == "accepted":
            logger.info(f"   ↳ Decision: Accepted")
            chapter_context = f"""
【参考資料：現在の章（承認済み）】
{base_info}
- 観測された行動傾向: {', '.join(chapter_data.get('learned_attitudes', []))}
"""
        elif decision == "rejected":
            logger.info(f"   ↳ Decision: Rejected")
            chapter_context = "【参考資料】直近の章提案は却下されたため、参照しません。"
        else:
            if decision is None:
                logger.info(f"   ↳ Decision: None (Pending)")
            else:
                logger.info(f"   ↳ Decision: Hold")
            chapter_context = f"""
【参考資料：現在の章（判断待ち）】
{base_info}
"""
    else:
        logger.info("📘 No chapter context found.")

    prompt = f"""
あなたはAIVTuber「ニア」の【観測者】です。
今日の対話から、「行動指針の微調整提案」があれば抽出してください。

【重要】
- これは「提案」であり、自動適用されません
- 人間（Origin）が承認するまで Identity は変わりません
- 無理に変更点を探す必要はありません
- 「特になし」も正しい判断です

【Input】
Identity: (省略)

{chapter_context}

Daily Memories:
{memory_block}

【Output】
提案がある場合: 箇条書きで具体的に
提案がない場合: 「特になし」とだけ書く
"""
    full_prompt = prompt.replace("(省略)", current_identity)
    patch_text = await call_llm([{"role": "system", "content": full_prompt}], temperature=0.2)

    proposal_saved = False
    patch_lines = 0

    if patch_text and "特になし" not in patch_text:
        logger.info(f"🛡️ Proposal Generated:\n{patch_text}")

        # 提案をファイルに保存（自動適用しない）
        proposal_data = {
            "timestamp": datetime.now().isoformat(),
            "date": datetime.now().strftime("%Y-%m-%d"),
            "status": "pending",  # pending / approved / rejected
            "proposal": patch_text,
            "chapter_context": chapter_data.get("chapter_title") if chapter_data else None,
        }

        filename = f"{datetime.now().strftime('%Y-%m-%d')}_identity_proposal.json"
        path = PENDING_PROPOSALS_DIR / filename
        with path.open("w", encoding="utf-8") as f:
            json.dump(proposal_data, f, ensure_ascii=False, indent=2)

        logger.info(f"📋 Proposal saved to {path} (awaiting human approval)")
        proposal_saved = True
        patch_lines = len([l for l in patch_text.splitlines() if l.strip()])
    else:
        logger.info("🛡️ No Proposal Needed.")

    # 正規化は行わない（提案のみ）
    header = "## Recent Learnings"
    current_learnings = extract_section_content(current_identity, header)
    normalized_lines = len([l for l in current_learnings.splitlines() if l.strip()])

    return proposal_saved, current_learnings, patch_lines, normalized_lines

# --- Layer B Adaptive (Post-Phase5.5: 重要度判定) ---
async def layer_b_guardian_adaptive(current_identity, memory_block):
    """
    Post-Phase5.5: 重要度で自動適用/承認待ちを切り替え

    - importance < 0.3 → 小さな変化 → 自動適用
    - importance >= 0.3 → 大きな変化 → 承認待ち（従来と同じ）
    """
    logger.info("🛡️ Layer B: Adaptive Guardian (Post-Phase5.5)...")

    chapter_data = load_latest_chapter_proposal()
    chapter_context = ""

    if chapter_data:
        chap_id = chapter_data.get("chapter_id")
        decision = get_chapter_decision(chap_id)
        base_info = (
            f"- 章タイトル: {chapter_data.get('chapter_title', 'Unknown')}\n"
            f"- 繰り返しテーマ: {', '.join(chapter_data.get('recurring_themes', []))}"
        )
        if decision == "accepted":
            chapter_context = f"\n【参考資料：現在の章（承認済み）】\n{base_info}\n- 観測された行動傾向: {', '.join(chapter_data.get('learned_attitudes', []))}\n"
        elif decision == "rejected":
            chapter_context = "【参考資料】直近の章提案は却下されたため、参照しません。"
        else:
            chapter_context = f"\n【参考資料：現在の章（判断待ち）】\n{base_info}\n"

    prompt = f"""
あなたはAIVTuber「ニア」の【観測者】です。
今日の対話から、「行動指針の微調整提案」があれば抽出してください。

【重要】
- 無理に変更点を探す必要はありません
- 「特になし」も正しい判断です

【Input】
Identity: (省略)

{chapter_context}

Daily Memories:
{memory_block}

【Output】
提案がある場合: 箇条書きで具体的に
提案がない場合: 「特になし」とだけ書く
"""
    full_prompt = prompt.replace("(省略)", current_identity)
    patch_text = await call_llm([{"role": "system", "content": full_prompt}], temperature=0.2)

    proposal_saved = False
    auto_applied = False
    patch_lines = 0

    if patch_text and "特になし" not in patch_text:
        # 重要度判定
        importance = estimate_importance(patch_text)
        patch_lines = len([l for l in patch_text.splitlines() if l.strip()])

        if importance < 0.3:
            # 小さな変化 → 自動適用
            logger.info(f"🟢 Low importance ({importance:.2f}) - Auto-applying")
            header = "## Recent Learnings"
            current_learnings = extract_section_content(current_identity, header)
            normalized_block = await normalize_learnings_safe(current_learnings, patch_text)
            new_identity = replace_section_content(current_identity, header, normalized_block)

            success = identity_manager.update_identity(new_identity, key="AUTO_MINOR_UPDATE")
            if success:
                logger.info("✅ Minor update applied automatically")
                save_auto_applied_log(patch_text, importance)
                auto_applied = True
            else:
                logger.warning("⚠️ Auto-apply failed, saving as proposal instead")
                importance = 0.3  # fallback to proposal
        else:
            logger.info(f"🟡 High importance ({importance:.2f}) - Awaiting approval")

        if not auto_applied:
            # 大きな変化 → 承認待ち（従来と同じ）
            proposal_data = {
                "timestamp": datetime.now().isoformat(),
                "date": datetime.now().strftime("%Y-%m-%d"),
                "status": "pending",
                "importance": round(importance, 3),
                "proposal": patch_text,
                "chapter_context": chapter_data.get("chapter_title") if chapter_data else None,
            }
            filename = f"{datetime.now().strftime('%Y-%m-%d')}_identity_proposal.json"
            path = PENDING_PROPOSALS_DIR / filename
            with path.open("w", encoding="utf-8") as f:
                json.dump(proposal_data, f, ensure_ascii=False, indent=2)
            logger.info(f"📋 Proposal saved to {path} (awaiting human approval)")
            proposal_saved = True
    else:
        logger.info("🛡️ No Proposal Needed.")

    header = "## Recent Learnings"
    current_learnings = extract_section_content(current_identity, header)
    normalized_lines = len([l for l in current_learnings.splitlines() if l.strip()])

    return proposal_saved or auto_applied, current_learnings, patch_lines, normalized_lines


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
    
    # Post-Phase5: Layer A は印象記録のみ（変わりたい願望は生成しない）
    layer_a_data = {"impressions": [], "mood": "neutral", "surprise": None}
    if important_memories:
        layer_a_data = await layer_a_impression_record(current_identity, memory_block)

    mood = layer_a_data.get("mood", "neutral")
    # reason は廃止（内部ノイズを減らす）

    # --- 夢の生成 & 保存 (Post-Phase5: reasonは使わない) ---
    try:
        # surpriseを使って夢を生成（内部ノイズではなく外部からの驚きを反映）
        surprise = layer_a_data.get("surprise") or ""
        dream_text = _build_dream_text(mood, surprise if surprise else "")
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

    # Layer B (Post-Phase5.5: LAYER_B_MODE で切り替え)
    layer_b_mode = getattr(settings, "LAYER_B_MODE", "proposal")
    proposal_saved = False
    patch_lines = 0
    normalized_lines = 0

    if important_memories:
        if layer_b_mode == "adaptive":
            logger.info("🔀 Layer B Mode: adaptive")
            proposal_saved, current_learnings, patch_lines, normalized_lines = await layer_b_guardian_adaptive(current_identity, memory_block)
        else:
            logger.info("🔀 Layer B Mode: proposal (default)")
            proposal_saved, current_learnings, patch_lines, normalized_lines = await layer_b_guardian_proposal(current_identity, memory_block)

        # 4. Consolidation (Save Episode) - 提案があった場合のみ
        if proposal_saved:
            logger.info("📔 Saving Episode (with pending proposal)...")
            diary_prompt = f"""
以下の出来事を、「第〇話」のような日記形式で要約してください。
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
    if sys.platform == "win32":
        asyncio.set_event_loop_policy(asyncio.WindowsSelectorEventLoopPolicy())
    asyncio.run(integrated_sleep_cycle())
