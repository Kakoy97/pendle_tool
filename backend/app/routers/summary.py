from typing import List

from fastapi import APIRouter, Depends
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.db import get_session
from app.schemas.summary import SummaryItem, SummaryListResponse
from app.services.repositories.summary_repository import SummaryRepository

router = APIRouter(prefix="/summaries", tags=["summaries"])


@router.get("/", response_model=SummaryListResponse)
async def list_summaries(
    limit: int = 20,
    session: AsyncSession = Depends(get_session),
) -> SummaryListResponse:
    repo = SummaryRepository(session)
    records = await repo.list_recent(limit=limit)

    items: List[SummaryItem] = []
    for record in records:
        raw_ids = [int(mid) for mid in record.raw_message_ids.split(",") if mid]
        items.append(
            SummaryItem(
                id=record.id,
                time_window_start=record.time_window_start,
                time_window_end=record.time_window_end,
                generated_at=record.generated_at,
                source_chat_id=record.source_chat_id,
                summary=record.summary,
                raw_message_ids=raw_ids,
                ai_model=record.ai_model,
                status=record.status,
            )
        )

    return SummaryListResponse(items=items)
