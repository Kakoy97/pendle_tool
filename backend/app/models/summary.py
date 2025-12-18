from datetime import datetime

from sqlalchemy import Column, DateTime, ForeignKey, Integer, Text

from app.core.db import Base


class ConversationSummary(Base):
    __tablename__ = "conversation_summaries"

    id = Column(Integer, primary_key=True, index=True)
    time_window_start = Column(DateTime, nullable=False)
    time_window_end = Column(DateTime, nullable=False)
    generated_at = Column(DateTime, default=datetime.utcnow, nullable=False)
    source_chat_id = Column(Integer, nullable=False, index=True)
    summary = Column(Text, nullable=False)
    raw_message_ids = Column(Text, nullable=False)
    ai_model = Column(Text, nullable=True)
    status = Column(Text, default="completed", nullable=False)
