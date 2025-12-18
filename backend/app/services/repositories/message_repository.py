from collections.abc import Sequence
from datetime import datetime, timedelta

from sqlalchemy import select, update
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.message import TelegramMessage


class MessageRepository:
    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def add_message(
        self,
        *,
        chat_id: int,
        message_id: int,
        sender_id: int | None,
        sender_username: str | None,
        content: str,
        message_date: datetime,
    ) -> None:
        message = TelegramMessage(
            chat_id=chat_id,
            message_id=message_id,
            sender_id=sender_id,
            sender_username=sender_username,
            content=content,
            message_date=message_date,
            inserted_at=datetime.utcnow(),
        )
        self._session.add(message)
        try:
            await self._session.commit()
        except IntegrityError:
            await self._session.rollback()

    async def list_unprocessed(
        self,
        *,
        chat_id: int,
        timeframe_minutes: int,
    ) -> Sequence[TelegramMessage]:
        window_start = datetime.utcnow() - timedelta(minutes=timeframe_minutes)
        result = await self._session.execute(
            select(TelegramMessage)
            .where(TelegramMessage.chat_id == chat_id)
            .where(TelegramMessage.message_date >= window_start)
            .where(TelegramMessage.processed.is_(False))
            .order_by(TelegramMessage.message_date.asc())
        )
        return result.scalars().all()

    async def mark_processed(self, message_ids: Sequence[int]) -> None:
        if not message_ids:
            return
        await self._session.execute(
            update(TelegramMessage)
            .where(TelegramMessage.id.in_(message_ids))
            .values(processed=True)
        )
        await self._session.commit()
