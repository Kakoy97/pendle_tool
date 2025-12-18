"""项目历史记录模型"""

from datetime import datetime

from sqlalchemy import Column, Date, DateTime, Integer, String

from app.core.db import Base


class ProjectHistory(Base):
    """项目历史记录表，用于记录每日同步新增/删除的项目"""

    __tablename__ = "project_history"

    id = Column(Integer, primary_key=True, index=True)
    
    # 记录日期（只记录日期，不包含时间）
    record_date = Column(Date, nullable=False, index=True)
    
    # 操作类型：'added' 或 'deleted'
    action = Column(String(20), nullable=False, index=True)
    
    # 项目地址
    project_address = Column(String(255), nullable=False, index=True)
    
    # 项目名称
    project_name = Column(String(255), nullable=True)
    
    # 时间戳
    created_at = Column(DateTime, default=datetime.utcnow, nullable=False)

