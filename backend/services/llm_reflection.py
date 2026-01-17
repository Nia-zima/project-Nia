import aiohttp
import logging

logger = logging.getLogger("LLMReflection")

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

状況: {interpretation}
"""

    payload = {
        "model": model,
        "messages": [{"role": "system", "content": prompt}],
        "temperature": 0.4, # 冷静に
        "max_tokens": 150
    }

    async with aiohttp.ClientSession() as session:
        async with session.post(api_url, json=payload) as resp:
            if resp.status != 200:
                logger.error(f"Reflection API Error: {resp.status}")
                return "（解釈不能）"
            data = await resp.json()
            return data["choices"][0]["message"]["content"]
