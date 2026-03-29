import aiohttp
import logging

from backend.core.config import settings

logger = logging.getLogger("LLMReflection")


def _reflection_url() -> str:
    base = settings.OPENAI_BASE_URL.rstrip("/")
    if not base.endswith("/v1"):
        base += "/v1"
    return f"{base}/chat/completions"

async def deepen_reflection(api_url, model, interpretation):
    """
    Phase 8-B: 状況の深層解釈
    外部には出力せず、ニアの内面理解のためだけに使用する。
    """
    prompt = f"""
これはAIの内省プロセスです。ユーザーへの応答ではありません。
以下の「観測状況」を見て、あなた（ニア）の【内的理解】を1〜2文で独白してください。

【ルール】
1. 感情的になりすぎず、客観と主観を混ぜる。
2. 「〜と言おうかな」などの発話意図は書かない。あくまで認識のみ。
3. 簡潔に。
4. 必ず日本語で書く。

状況: {interpretation}
"""

    payload = {
        "model": model,
        "messages": [{"role": "system", "content": prompt}],
        "temperature": 0.4, # 冷静に
        "max_tokens": 150
    }

    headers = {"Content-Type": "application/json"}
    if settings.OPENAI_API_KEY:
        headers["Authorization"] = f"Bearer {settings.OPENAI_API_KEY}"

    url = api_url or _reflection_url()
    timeout = aiohttp.ClientTimeout(total=30)
    async with aiohttp.ClientSession(timeout=timeout) as session:
        async with session.post(url, json=payload, headers=headers) as resp:
            if resp.status != 200:
                logger.error(f"Reflection API Error: {resp.status}")
                return "（解釈不能）"
            data = await resp.json()
            return data["choices"][0]["message"]["content"]
