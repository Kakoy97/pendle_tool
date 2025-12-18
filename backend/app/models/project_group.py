"""项目分组模型"""

from sqlalchemy import Column, DateTime, Integer, String

from app.core.db import Base


class ProjectGroup(Base):
    """项目分组表（用于存储用户手动创建的分组）"""

    __tablename__ = "project_groups"

    id = Column(Integer, primary_key=True, index=True)
    name = Column(String(255), unique=True, nullable=False, index=True)  # 分组名称（唯一）
    created_at = Column(DateTime, default=lambda: __import__("datetime").datetime.utcnow(), nullable=False)

