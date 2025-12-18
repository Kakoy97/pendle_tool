"""资产价格查询客户端"""

import asyncio
import logging
from urllib.parse import urlencode

import httpx

logger = logging.getLogger(__name__)


class AssetsPriceClient:
    """资产价格查询客户端，用于查询 YT/PT 等资产的价格"""

    def __init__(self) -> None:
        self._base_url = "https://api-v2.pendle.finance"
        self._client = httpx.AsyncClient(
            base_url=self._base_url,
            timeout=30.0,
            follow_redirects=True,
        )

    async def get_assets_prices(
        self,
        ids: str | list[str],
        chain_id: int | None = None,
        asset_type: str = "YT",
    ) -> dict:
        """
        查询资产价格
        
        Args:
            ids: 资产地址列表（可以是字符串，逗号分隔，或列表）
            chain_id: 链 ID（可选）
            asset_type: 资产类型（默认：YT）
        
        Returns:
            API 响应数据
        """
        endpoint = "/core/v1/prices/assets"
        
        # 构建查询参数
        params = {}
        
        # 处理 ids 参数
        if isinstance(ids, list):
            ids_str = ",".join(ids)
        else:
            ids_str = ids
        
        if ids_str:
            params["ids"] = ids_str
        
        if chain_id is not None:
            params["chainId"] = str(chain_id)
        
        if asset_type:
            params["type"] = asset_type
        
        # 构建 URL
        if params:
            query_string = urlencode(params)
            url = f"{self._base_url}{endpoint}?{query_string}"
        else:
            url = f"{self._base_url}{endpoint}"
        
        max_retries = 3
        retry_delay = 5  # 初始延迟 5 秒
        
        for attempt in range(max_retries):
            try:
                # 除了第一次请求，其他请求前都添加延迟
                if attempt > 0:
                    wait_time = retry_delay * (2 ** (attempt - 1))  # 指数退避：5s, 10s, 20s
                    logger.info(f"重试前等待 {wait_time} 秒...")
                    await asyncio.sleep(wait_time)
                
                logger.info(f"查询资产价格: ids={ids_str}, chain_id={chain_id}, type={asset_type}, 尝试 {attempt + 1}/{max_retries}")
                response = await self._client.get(
                    url,
                    headers={
                        "Accept": "application/json",
                        "User-Agent": "PendleTool/1.0",
                    }
                )
                response.raise_for_status()
                
                data = response.json()
                logger.debug(f"资产价格响应: {len(data) if isinstance(data, dict) else 'N/A'} 条记录")
                
                return data
            except httpx.HTTPStatusError as e:
                if e.response.status_code == 429:
                    # 429 错误：请求过多，需要等待
                    if attempt < max_retries - 1:
                        wait_time = retry_delay * (2 ** attempt)  # 指数退避：5s, 10s, 20s
                        logger.warning(f"收到 429 错误，等待 {wait_time} 秒后重试...")
                        await asyncio.sleep(wait_time)
                        continue
                    else:
                        logger.error(f"资产价格 API 请求失败（429）: 已重试 {max_retries} 次，放弃")
                        raise
                else:
                    logger.error(f"资产价格 API 请求失败: {e.response.status_code} - {e.response.text}")
                    raise
            except Exception as e:
                logger.error(f"资产价格查询失败: {e}", exc_info=True)
                raise

    async def close(self) -> None:
        """关闭客户端"""
        await self._client.aclose()


# 全局实例
assets_price_client = AssetsPriceClient()

