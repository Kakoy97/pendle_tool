"""限价订单模型"""

from datetime import datetime, timezone

from sqlalchemy import Column, DateTime, Float, Integer, String, Text

from app.core.db import Base


class LimitOrder(Base):
    """限价订单表"""

    __tablename__ = "limit_orders"

    id = Column(Integer, primary_key=True, index=True)
    
    # 订单ID（唯一标识）
    order_id = Column(String(255), unique=True, nullable=False, index=True)
    
    # 钱包地址
    wallet_address = Column(String(255), nullable=False, index=True)
    
    # 链ID
    chain_id = Column(Integer, nullable=False, index=True)
    
    # 市场地址（项目地址，从yt或pt推断）
    market_address = Column(String(255), nullable=True, index=True)
    
    # 订单状态：FILLABLE, CANCELLED, EXPIRED, FULLY_FILLED
    status = Column(String(50), nullable=False, index=True)
    
    # 订单类型：LONG_YIELD（买入）, SHORT_YIELD（卖出）
    order_type = Column(String(50), nullable=False)
    
    # 数量（notionalVolumeUSD）
    notional_volume_usd = Column(Float, nullable=True)
    
    # Implied Yield（计算值：e^{lnImpliedRate} - 1）
    implied_yield = Column(Float, nullable=True)
    
    # lnImpliedRate（原始值）
    ln_implied_rate = Column(String(255), nullable=True)
    
    # 项目名称（从PendleProject表关联获取）
    project_name = Column(String(255), nullable=True)
    
    # 最新事件时间戳（latestEventTimestamp）
    latest_event_timestamp = Column(DateTime, nullable=False, index=True)
    
    # 原始数据（JSON格式，用于调试）
    raw_data = Column(Text, nullable=True)
    
    # 时间戳
    created_at = Column(DateTime, default=lambda: datetime.now(timezone.utc), nullable=False)
    updated_at = Column(DateTime, default=lambda: datetime.now(timezone.utc), onupdate=lambda: datetime.now(timezone.utc), nullable=False)

