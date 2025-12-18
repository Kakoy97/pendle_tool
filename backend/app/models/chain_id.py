"""链 ID 模型"""

import json
from sqlalchemy import Column, Integer, String, Text

from app.core.db import Base


class ChainId(Base):
    """链 ID 表"""

    __tablename__ = "chain_ids"

    id = Column(Integer, primary_key=True, index=True)  # 链 ID（如 1, 42161, 56 等）
    name = Column(String(100), nullable=True, unique=True, index=True)  # 链路名称（如 eth, arbitrum, bnbchain）
    token_address = Column(String(255), nullable=True)  # 代币地址（USDT 地址）
    aggregators = Column(Text, nullable=True)  # 聚合器列表（JSON 格式，如 ["kyberswap", "odos"]）
    
    def get_aggregators_list(self) -> list[str]:
        """获取聚合器列表"""
        if not self.aggregators:
            return ["kyberswap"]  # 默认值
        try:
            return json.loads(self.aggregators)
        except (json.JSONDecodeError, TypeError):
            return ["kyberswap"]  # 如果解析失败，返回默认值
    
    def set_aggregators_list(self, aggregators: list[str]) -> None:
        """设置聚合器列表"""
        self.aggregators = json.dumps(aggregators) if aggregators else None

