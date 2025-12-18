"""Pendle 项目 Schema"""

from datetime import datetime

from pydantic import BaseModel, Field


class PendleProjectBase(BaseModel):
    """项目基础信息"""

    address: str = Field(..., description="项目地址（唯一标识）")
    name: str | None = Field(None, description="项目名称")
    symbol: str | None = Field(None, description="项目符号")
    description: str | None = Field(None, description="项目描述")


class PendleProjectResponse(PendleProjectBase):
    """项目响应模型"""

    id: int
    project_group: str | None = Field(None, description="项目分组名称")
    expiry: datetime | None = Field(None, description="到期时间")
    chain_id: int | None = Field(None, description="链 ID")
    tvl: float | None = Field(None, description="TVL (Total Value Locked)，单位：美元")
    trading_volume_24h: float | None = Field(None, description="24小时交易量，单位：美元")
    implied_apy: float | None = Field(None, description="Fixed APY (Implied APY)，单位：百分比")
    is_monitored: bool = Field(..., description="是否正在监控")
    created_at: datetime
    updated_at: datetime

    class Config:
        from_attributes = True


class PendleProjectListResponse(BaseModel):
    """项目列表响应"""

    monitored: list[PendleProjectResponse] = Field(default_factory=list, description="正在监控的项目")
    unmonitored: list[PendleProjectResponse] = Field(default_factory=list, description="未监控的项目")


class ToggleMonitorRequest(BaseModel):
    """切换监控状态请求"""

    address: str = Field(..., description="项目地址")
    is_monitored: bool = Field(..., description="是否监控")

