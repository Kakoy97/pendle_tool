"""钱包交易记录模型"""

from datetime import datetime, timezone

from sqlalchemy import Column, DateTime, Float, Integer, String, Text

from app.core.db import Base


class WalletTransaction(Base):
    """钱包交易记录表"""

    __tablename__ = "wallet_transactions"

    id = Column(Integer, primary_key=True, index=True)
    
    # 钱包地址
    wallet_address = Column(String(255), nullable=False, index=True)
    
    # 市场地址（项目地址）
    market_address = Column(String(255), nullable=False, index=True)
    
    # 链ID
    chain_id = Column(Integer, nullable=False, index=True)
    
    # 交易哈希
    tx_hash = Column(String(255), nullable=False, index=True)
    
    # 操作类型：buyYt, sellYt, buyYtLimitOrder, sellYtLimitOrder, redeemYtYield
    action = Column(String(50), nullable=False, index=True)
    
    # 交易时间（UTC）
    timestamp = Column(DateTime, nullable=False, index=True)
    
    # 交易金额（读取txValueAsset）
    amount = Column(Float, nullable=False)
    
    # Implied Yield（计算值）
    implied_yield = Column(Float, nullable=True)
    
    # 利润（USD，卖出时读取profit.usd，买入时为0）
    profit_usd = Column(Float, nullable=False, default=0.0)
    
    # 项目名称（从PendleProject表关联获取）
    project_name = Column(String(255), nullable=True)
    
    # 原始数据（JSON格式，用于调试）
    raw_data = Column(Text, nullable=True)
    
    # 时间戳
    created_at = Column(DateTime, default=lambda: datetime.now(timezone.utc), nullable=False)
    updated_at = Column(DateTime, default=lambda: datetime.now(timezone.utc), onupdate=lambda: datetime.now(timezone.utc), nullable=False)

