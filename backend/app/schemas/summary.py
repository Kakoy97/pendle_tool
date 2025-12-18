from datetime import datetime
from typing import List

from pydantic import BaseModel


class SummaryItem(BaseModel):
    id: int
    time_window_start: datetime
    time_window_end: datetime
    generated_at: datetime
    source_chat_id: int
    summary: str
    raw_message_ids: List[int]
    ai_model: str | None = None
    status: str


class SummaryListResponse(BaseModel):
    items: List[SummaryItem]
