"""DeepSeek API 客户端，用于生成摘要"""

import json
import logging
from typing import Sequence, Tuple

import httpx

from app.core.config import settings
from app.models.message import TelegramMessage

logger = logging.getLogger(__name__)


class SummaryClient:
    def __init__(self) -> None:
        self._base_url = "https://api.deepseek.com/chat/completions"
        self._model = "deepseek-chat"

    def _build_prompt(self, messages: Sequence[TelegramMessage]) -> str:
        formatted = []
        for message in messages:
            sender = message.sender_username or (str(message.sender_id) if message.sender_id else "unknown")
            timestamp = message.message_date.strftime("%Y-%m-%d %H:%M:%S")
            formatted.append(f"[{timestamp}] {sender}: {message.content}")
        return "\n".join(formatted)

    async def summarize(self, messages: Sequence[TelegramMessage]) -> Tuple[str, str]:
        payload = {
            "model": self._model,
            "messages": [
                {
                    "role": "system",
                    "content": (
                        "你是一名加密貨幣分析師，專門總結 Pendle 社群的對話焦點。"
                        "請整理出主要話題、提到的 YT 策略以及任何價格/風險訊號。"
                    ),
                },
                {
                    "role": "user",
                    "content": (
                        "以下是 Telegram 群組在最近一段時間的對話，請用繁體中文整理摘要，"
                        "列出：1) 今日重點 2) 相關 YT 連結或策略 3) 可能的價格/風險提示 4) 關鍵參與者。\n\n"
                        + self._build_prompt(messages)
                    ),
                },
            ],
            "temperature": 0.3,
        }

        headers = {
            "Authorization": f"Bearer {settings.deepseek_api_key}",
            "Content-Type": "application/json",
        }

        async with httpx.AsyncClient(timeout=30.0) as client:
            response = await client.post(self._base_url, headers=headers, json=payload)
            response.raise_for_status()
            data = response.json()

        try:
            summary_text = data["choices"][0]["message"]["content"].strip()
            model_name = data.get("model", self._model)
        except (KeyError, IndexError) as exc:  # pragma: no cover - defensive
            logger.exception("DeepSeek 回傳格式不符合預期: %s", json.dumps(data, ensure_ascii=False))
            raise RuntimeError("DeepSeek 回傳格式不正確") from exc

        return summary_text, model_name


summary_client = SummaryClient()
