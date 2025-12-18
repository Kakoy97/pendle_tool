"""Pendle 项目监控模型"""

from datetime import datetime

from sqlalchemy import Boolean, Column, DateTime, Float, Integer, String, Text

from app.core.db import Base


class PendleProject(Base):
    """Pendle 项目监控表"""

    __tablename__ = "pendle_projects"

    id = Column(Integer, primary_key=True, index=True)
    
    # Pendle API 返回的项目信息
    address = Column(String(255), unique=True, nullable=False, index=True)  # 项目地址（唯一标识）
    name = Column(String(255), nullable=True)  # 项目名称（市场名称，如 "reUSDe", "reUSD"）
    symbol = Column(String(50), nullable=True)  # 项目符号
    description = Column(Text, nullable=True)  # 项目描述
    
    # 链信息
    chain_id = Column(Integer, nullable=True, index=True)  # 链 ID（如 1, 42161, 56 等）
    
    # 项目分组信息（用于归类，如 "ReUSD" 包含 "reUSDe" 和 "reUSD"）
    project_group = Column(String(255), nullable=True, index=True)  # 项目分组名称（如 "ReUSD"）
    expiry = Column(DateTime, nullable=True, index=True)  # 到期时间（用于过滤过期项目）
    
    # 市场数据（从 API 获取）
    tvl = Column(Float, nullable=True)  # TVL (Total Value Locked)，单位：美元
    trading_volume_24h = Column(Float, nullable=True)  # 24小时交易量，单位：美元
    implied_apy = Column(Float, nullable=True)  # Fixed APY (Implied APY)，单位：百分比（如 5.5 表示 5.5%）
    
    # 监控状态
    is_monitored = Column(Boolean, default=False, nullable=False, index=True)  # 是否正在监控
    
    # 删除前的监控状态（用于项目恢复时恢复原状态）
    last_monitored_state = Column(Boolean, nullable=True)  # 删除前的 is_monitored 状态
    
    # 交易记录检查相关字段
    last_transaction_check_time = Column(DateTime, nullable=True)  # 上次检查交易记录的时间
    last_implied_apy = Column(Float, nullable=True)  # 上次记录的 impliedApy（用于检测APR变化）
    
    # 时间戳
    created_at = Column(DateTime, default=datetime.utcnow, nullable=False)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow, nullable=False)
    
    # 额外信息（JSON 格式存储，用于存储 API 返回的其他字段）
    extra_data = Column(Text, nullable=True)  # JSON 字符串
    
    # YT 地址（完整格式：chain_id-yt_address，用于价格查询 API）
    yt_address_full = Column(String(255), nullable=True)  # 完整格式的 YT 地址（如 "1-0x11f20e5268cdb45ef2337a64a4a2cc12e264fa5a"）

