"""同步日志模型"""

from datetime import datetime

from sqlalchemy import Column, DateTime, Integer, String

from app.core.db import Base


class SyncLog(Base):
    """同步日志表，记录数据同步时间"""

    __tablename__ = "sync_logs"

    id = Column(Integer, primary_key=True, index=True)
    sync_type = Column(String(50), nullable=False, index=True)  # 同步类型（如 "pendle_projects"）
    sync_time = Column(DateTime, default=datetime.utcnow, nullable=False, index=True)  # 同步时间
    status = Column(String(20), default="success", nullable=False)  # 状态（success, failed）
    message = Column(String(500), nullable=True)  # 同步消息（如同步的项目数量）

