import json
import re
from typing import Any, Dict, List, Tuple

_TAG_LINE_RE = re.compile(r'^\[\[([A-Z0-9_]+)\]\]\s*(\{.*\})\s*$')

def parse_tool_tags(text: str) -> Tuple[str, List[Dict[str, Any]]]:
    """
    入力テキストから「命令行」を取り除き、(clean_text, actions) を返す。
    命令行形式:
      [[MEMORY_WRITE]] {"content":"..","tags":[".."],"confidence":0.7,"surprise":0.2}
    """
    if not text:
        return "", []

    lines = text.splitlines()
    actions: List[Dict[str, Any]] = []
    kept: List[str] = []

    for line in lines:
        m = _TAG_LINE_RE.match(line.strip())
        if not m:
            kept.append(line)
            continue

        name = m.group(1)
        payload_str = m.group(2)

        try:
            payload = json.loads(payload_str)
            if isinstance(payload, dict):
                actions.append({"type": name, "payload": payload})
        except Exception:
            # 壊れた命令行は本文として残さず捨てる（A層を汚さない）
            # 代わりにB層で検出エラーを記録するのが望ましい（実行側で）
            actions.append({"type": "TAG_PARSE_ERROR", "payload": {"raw": line}})

    clean_text = "\n".join(kept).strip()
    return clean_text, actions
