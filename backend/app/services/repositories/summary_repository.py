from collections.abc import Sequence
from datetime import datetime

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.summary import ConversationSummary


class SummaryRepository:
    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def create_summary(
        self,
        *,
        time_window_start: datetime,
        time_window_end: datetime,
        chat_id: int,
        summary: str,
        raw_message_ids: Sequence[int],
        ai_model: str | None,
        status: str = "completed",
    ) -> ConversationSummary:
        record = ConversationSummary(
            time_window_start=time_window_start,
            time_window_end=time_window_end,
            generated_at=datetime.utcnow(),
            source_chat_id=chat_id,
            summary=summary,
            raw_message_ids=",".join(str(mid) for mid in raw_message_ids),
            ai_model=ai_model,
            status=status,
        )
        self._session.add(record)
        await self._session.commit()
        await self._session.refresh(record)
        return record

    async def list_recent(self, *, limit: int = 20) -> Sequence[ConversationSummary]:
        result = await self._session.execute(
            select(ConversationSummary)
            .order_by(ConversationSummary.generated_at.desc())
            .limit(limit)
        )
        return result.scalars().all()
