"""聪明钱 Schema"""

from datetime import datetime
from typing import Literal

from pydantic import BaseModel, Field


class SmartMoneyBase(BaseModel):
    """聪明钱基础模型"""
    
    wallet_address: str = Field(..., description="钱包地址")
    name: str | None = Field(None, description="名称")
    level: Literal["重点", "聪明钱", "蚂蚁仓"] = Field(..., description="等级")


class SmartMoneyCreate(SmartMoneyBase):
    """创建聪明钱"""
    pass


class SmartMoneyUpdate(BaseModel):
    """更新聪明钱"""
    
    name: str | None = Field(None, description="名称")
    level: Literal["重点", "聪明钱", "蚂蚁仓"] | None = Field(None, description="等级")


class SmartMoneyResponse(SmartMoneyBase):
    """聪明钱响应模型"""
    
    id: int
    created_at: datetime
    updated_at: datetime
    
    class Config:
        from_attributes = True


class SmartMoneyListResponse(BaseModel):
    """聪明钱列表响应"""
    
    smart_money: list[SmartMoneyResponse]
    total: int

