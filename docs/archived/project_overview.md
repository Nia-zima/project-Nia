# Project Nia: Functionality & Structure Overview

AIバディ「ニア (Nia)」の主要機能とプロジェクト構造の概要です。

## 1. Project Structure

Backend (FastAPI) と Frontend (Next.js) の分離構成ですが、同一リポジトリで管理され、シームレスに連携しています。

```
AI_Buddy/
├── backend/               # Python (FastAPI)
│   ├── server.py          # Entry Point (API & Static File Mount)
│   ├── core/              # Core Logic
│   │   ├── agent.py       # Agent Workflow & Thinking Process
│   │   ├── config.py      # Configuration & Path Management
│   │   └── tech_manual.md # System Prompts & Instructions
│   ├── services/          # Business Logic
│   │   ├── memory_manager.py  # Long-term/Short-term Memory
│   │   ├── memory_judge.py    # Memory Importance Analysis
│   │   └── speech_sanitizer.py # Output Filtering & Metacognition Tags
│   └── controllers/       # API Routes
│       └── api/stream_router.py # SSE Streaming Chat
│
├── frontend/              # TypeScript (Next.js)
│   ├── app/page.tsx       # Main UI Layout
│   ├── components/
│   │   ├── AvatarView.tsx # 3D Avatar Control (VRM)
│   │   └── ChatInterface.tsx # Chat UI
│   └── lib/api.ts         # API Client
```

## 2. Key Components & Logic

### A. Metacognition (内部状態のメタ認知)
ニアは自身の発言に対して「納得(Consent)」や「違和感(Dissonance)」といった内部タグを付与し、それを記憶や身体表現に反映させます。

**Backend Logic (`speech_sanitizer.py` & `agent.py`)**:
AIの生の思考出力からタグ(`[CONSENT]`など)を抽出し、ユーザーに見えるテキストからは削除しつつ、メタデータとしてフロントエンドと記憶システムに渡します。
```python
# backend/core/agent.py (Simplified)
cleaned, tags = _extract_emotion_tags(sanitized_text)
if "consent" in tags:
    # 記憶の重要度を上げる
    importance_val += 0.5
if "dissonance" in tags:
    # すぐに判断せず、記憶を「保留」にする
    decision = "pending"
```

### B. Memory Formation (記憶形成)
全ての会話を記録するのではなく、AI自身が「重要度(Importance)」と「驚き(Surprise)」を判定し、長期記憶に残す価値があるものだけを選別します。

**Memory Judge (`memory_judge.py`)**:
```python
# 会話の内容を分析し、JSONで評価を返す
MemoryJudgment(
    summary="ユーザーはプログラミングが趣味である",
    importance=0.8,  # 高い重要度 -> 保存
    surprise=0.1,
    should_save=True
)
```

### C. 3D Embodiment (身体性)
感情や内部状態タグに基づいて、3Dアバターがリアルタイムに反応します。

**Frontend Animation (`AvatarView.tsx`)**:
```typescript
// プロシージャルアニメーション（計算による動的制御）
if (emotion === 'consent') {
    // 納得：前傾姿勢で興味を示す
    spinePoseRef.current = { x: 0.15, ... }; 
} else if (emotion === 'dissonance') {
    // 違和感：視線を逸らし、首をかしげる
    headPoseRef.current = { y: 0.3, z: 0.15, ... };
    // 数秒後にゆっくり視線を戻すループ処理...
}
```

### D. Streaming & Safety (ストリーミングと安全性)
回答はストリーミング(SSE)で即座に表示されますが、内部思考やシステム命令が漏洩しないよう、強力なフィルタリングがリアルタイムに行われます。

**Stream Router (`stream_router.py`)**:
- `detect_internal_leak()`: 内部ログやプロンプトの漏洩を検知。
- `finalize_output()`: ユーザーに見せるべきでないタグやト書きを削除。

---

## 3. Workflow Summary

1.  **Input**: ユーザーがチャット入力（テキスト/画像）。
2.  **Think**: BackendのAgentが思考し、回答と「内部状態タグ」を生成。
3.  **Sanitize**: システムがタグを分離し、テキストを浄化。
4.  **Feedback**:
    - **Memory**: 重要なやり取りはその場で長期記憶に保存。
    - **Frontend**: テキストを表示しつつ、タグに応じてアバターが「頷く」「視線を逸らす」などの演技を行う。

このサイクルにより、ニアは単なる応答機械ではなく、「感じ、考え、記憶する」パートナーとして振る舞います。
