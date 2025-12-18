"""聪明钱模型"""

from datetime import datetime, timezone

from sqlalchemy import Column, DateTime, Integer, String

from app.core.db import Base


class SmartMoney(Base):
    """聪明钱表，用于记录重点钱包、聪明钱、蚂蚁仓等信息"""

    __tablename__ = "smart_money"

    id = Column(Integer, primary_key=True, index=True)
    
    # 钱包地址（唯一标识）
    wallet_address = Column(String(255), unique=True, nullable=False, index=True)
    
    # 名称
    name = Column(String(255), nullable=True)
    
    # 等级：重点、聪明钱、蚂蚁仓
    # 重要程度：重点 > 聪明钱 > 蚂蚁仓
    level = Column(String(50), nullable=False, index=True)  # "重点", "聪明钱", "蚂蚁仓"
    
    # 上次更新的最新时间戳（用于判断是否有新记录）
    last_update_timestamp = Column(DateTime, nullable=True, index=True)
    
    # 时间戳
    created_at = Column(DateTime, default=lambda: datetime.now(timezone.utc), nullable=False)
    updated_at = Column(DateTime, default=lambda: datetime.now(timezone.utc), onupdate=lambda: datetime.now(timezone.utc), nullable=False)

