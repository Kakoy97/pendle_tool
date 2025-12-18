from __future__ import annotations

from collections.abc import Sequence
from datetime import datetime

from app.core.config import settings
from app.core.db import get_sessionmaker
from app.models.message import TelegramMessage
from app.services.repositories.message_repository import MessageRepository
from app.services.repositories.summary_repository import SummaryRepository
from app.services.summary_client import summary_client


class MessagePipeline:
    async def run_once(self) -> None:
        session_maker = get_sessionmaker()
        async with session_maker() as session:
            message_repo = MessageRepository(session)
            summary_repo = SummaryRepository(session)

            messages: Sequence[TelegramMessage] = await message_repo.list_unprocessed(
                chat_id=settings.telegram_target_chat_id,
                timeframe_minutes=settings.summary_timeframe_minutes,
            )

            if not messages:
                return

            summary_text, model_name = await summary_client.summarize(messages)

            await summary_repo.create_summary(
                time_window_start=self._extract_start(messages),
                time_window_end=self._extract_end(messages),
                chat_id=settings.telegram_target_chat_id,
                summary=summary_text,
                raw_message_ids=[message.message_id for message in messages],
                ai_model=model_name,
            )

            await message_repo.mark_processed([message.id for message in messages])

    @staticmethod
    def _extract_start(messages: Sequence[TelegramMessage]) -> datetime:
        return min(message.message_date for message in messages)

    @staticmethod
    def _extract_end(messages: Sequence[TelegramMessage]) -> datetime:
        return max(message.message_date for message in messages)


message_pipeline = MessagePipeline()
