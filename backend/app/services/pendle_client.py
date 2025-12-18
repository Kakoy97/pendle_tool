"""Pendle API 客户端"""

import json
import logging
from typing import Any

import httpx

logger = logging.getLogger(__name__)


class PendleClient:
    """Pendle API 客户端，用于获取项目列表等信息"""

    BASE_URL = "https://api-v2.pendle.finance"

    def __init__(self) -> None:
        self._client = httpx.AsyncClient(
            base_url=self.BASE_URL,
            timeout=30.0,
            headers={
                "Accept": "application/json",
                "User-Agent": "PendleTool/1.0",
            },
        )

    async def get_all_markets(self, filter_expired: bool = True) -> list[dict[str, Any]]:
        """
        获取所有市场（项目）列表
        
        Args:
            filter_expired: 是否过滤已过期的市场（默认 True）
        
        Returns:
            项目列表，每个项目包含 address, name, symbol 等信息
        """
        try:
            # 根据 Pendle API 文档：https://api-v2.pendle.finance/core/docs#tag/markets
            # 正确的端点是 /core/v1/markets/all
            endpoint = "/core/v1/markets/all"
            
            logger.info(f"请求端点: {endpoint}")
            response = await self._client.get(endpoint)
            response.raise_for_status()
            
            data = response.json()
            logger.info(f"响应状态: {response.status_code}, 响应长度: {len(response.text)}")
            
            # 根据实际 API 响应：{"markets": [...]}
            if isinstance(data, dict) and "markets" in data:
                markets = data["markets"]
                logger.info(f"✓ 成功获取到 {len(markets)} 个市场")
                
                # 过滤已过期的市场
                if filter_expired:
                    from datetime import datetime, timezone
                    now = datetime.now(timezone.utc)
                    original_count = len(markets)
                    markets = [
                        m for m in markets
                        if m.get("expiry") and datetime.fromisoformat(m["expiry"].replace("Z", "+00:00")) > now
                    ]
                    logger.info(f"过滤过期市场: {original_count} -> {len(markets)} (已过滤 {original_count - len(markets)} 个)")
                
                # 记录第一个市场的结构以便调试
                if markets and isinstance(markets[0], dict):
                    logger.debug(f"市场数据结构示例: {list(markets[0].keys())[:10]}")
                
                return markets
            elif isinstance(data, list):
                # 如果直接返回数组（备用情况）
                markets = data
                if filter_expired:
                    from datetime import datetime, timezone
                    now = datetime.now(timezone.utc)
                    original_count = len(markets)
                    markets = [
                        m for m in markets
                        if m.get("expiry") and datetime.fromisoformat(m["expiry"].replace("Z", "+00:00")) > now
                    ]
                    logger.info(f"过滤过期市场: {original_count} -> {len(markets)} (已过滤 {original_count - len(markets)} 个)")
                
                logger.info(f"✓ 成功获取到 {len(markets)} 个市场（直接数组格式）")
                return markets
            else:
                logger.warning(f"意外的响应格式: {type(data)}, 键: {list(data.keys()) if isinstance(data, dict) else 'N/A'}")
                return []
            
        except httpx.HTTPStatusError as e:
            logger.error(f"Pendle API 请求失败: {e.response.status_code} - {e.response.text}")
            raise
        except Exception as e:
            logger.error(f"获取 Pendle 市场列表时出错: {e}", exc_info=True)
            raise

    async def get_all_projects(self) -> list[dict[str, Any]]:
        """
        获取所有项目（上层分组）列表
        
        尝试多个可能的端点来获取项目分组信息
        
        Returns:
            项目列表，每个项目包含分组信息
        """
        # 尝试多个可能的端点
        endpoints = [
            "/core/v1/projects",
            "/core/v1/projects/all",
            "/core/v1/tokens",
            "/core/v1/tokens/all",
            "/core/v1/sy",
            "/core/v1/sy/all",
        ]
        
        for endpoint in endpoints:
            try:
                logger.info(f"尝试项目端点: {endpoint}")
                response = await self._client.get(endpoint)
                
                if response.status_code == 200:
                    data = response.json()
                    
                    # 尝试提取项目列表
                    if isinstance(data, dict):
                        projects = data.get("items", data.get("data", data.get("results", data.get("projects", data.get("tokens", [])))))
                    elif isinstance(data, list):
                        projects = data
                    else:
                        continue
                    
                    if projects:
                        logger.info(f"✓ 从 {endpoint} 成功获取到 {len(projects)} 个项目")
                        return projects
                        
            except Exception as e:
                logger.debug(f"端点 {endpoint} 失败: {e}")
                continue
        
        logger.warning("未能找到项目分组 API，将使用市场名称进行分组")
        return []

    async def get_market_details(self, address: str) -> dict[str, Any] | None:
        """
        获取特定市场的详细信息
        
        Args:
            address: 市场地址
            
        Returns:
            市场详细信息，如果不存在则返回 None
        """
        try:
            response = await self._client.get(f"/core/v1/markets/{address}")
            response.raise_for_status()
            return response.json()
        except httpx.HTTPStatusError as e:
            if e.response.status_code == 404:
                return None
            logger.error(f"获取市场详情失败: {e.response.status_code}")
            raise
        except Exception as e:
            logger.error(f"获取市场详情时出错: {e}", exc_info=True)
            raise

    async def close(self) -> None:
        """关闭 HTTP 客户端"""
        await self._client.aclose()


# 全局客户端实例
pendle_client = PendleClient()

