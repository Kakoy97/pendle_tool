"""价格测试客户端"""

import asyncio
import logging
from urllib.parse import urlencode

import httpx

logger = logging.getLogger(__name__)


class PriceTestClient:
    """价格测试客户端，用于测试代币转换"""

    def __init__(self) -> None:
        self._base_url = "https://api-v2.pendle.finance"
        self._client = httpx.AsyncClient(
            base_url=self._base_url,
            timeout=30.0,
            follow_redirects=True,
        )

    async def test_convert(
        self,
        chain_id: int,
        tokens_in: str,
        tokens_out: str,
        amounts_in: int = 100000000,  # 100 USDT (6 decimals)
        receiver: str = "0xd8dA6BF26964aF9D7eEd9e03E53415D37aA96045",
        slippage: float = 0.01,
        enable_aggregator: bool = True,
        aggregators: str | list[str] = "kyberswap",
        additional_data: str = "impliedApy,effectiveApy",
    ) -> dict:
        """
        测试代币转换 API
        
        Args:
            chain_id: 链 ID
            tokens_in: 输入代币地址
            tokens_out: 输出代币地址（YT 地址）
            amounts_in: 输入数量（以代币的最小单位计算）
            receiver: 接收地址
            slippage: 滑点
            enable_aggregator: 是否启用聚合器
            aggregators: 聚合器名称
            additional_data: 额外数据字段
        
        Returns:
            API 响应数据
        """
        endpoint = f"/core/v2/sdk/{chain_id}/convert"
        
        # 构建查询参数
        params = {
            "receiver": receiver.lower(),
            "slippage": str(slippage),
            "tokensIn": tokens_in.lower(),
            "tokensOut": tokens_out.lower(),
            "amountsIn": str(amounts_in),
        }
        
        # 可选参数
        if enable_aggregator:
            params["enableAggregator"] = "true"
            if aggregators:
                # 如果 aggregators 是列表，转换为逗号分隔的字符串
                if isinstance(aggregators, list):
                    params["aggregators"] = ",".join(aggregators)
                else:
                    params["aggregators"] = aggregators
        
        if additional_data:
            params["additionalData"] = additional_data
        
        # 构建 URL
        query_string = urlencode(params)
        url = f"{self._base_url}{endpoint}?{query_string}"
        
        max_retries = 3
        retry_delay = 5  # 初始延迟 5 秒（增加延迟时间）
        
        for attempt in range(max_retries):
            try:
                # 除了第一次请求，其他请求前都添加延迟
                if attempt > 0:
                    wait_time = retry_delay * (2 ** (attempt - 1))  # 指数退避：5s, 10s, 20s
                    logger.info(f"重试前等待 {wait_time} 秒...")
                    await asyncio.sleep(wait_time)
                
                logger.info(f"测试价格转换: chain_id={chain_id}, tokens_in={tokens_in}, tokens_out={tokens_out}, aggregator={aggregators}, 尝试 {attempt + 1}/{max_retries}")
                response = await self._client.get(
                    url,
                    headers={
                        "Accept": "application/json",
                        "User-Agent": "PendleTool/1.0",
                    }
                )
                response.raise_for_status()
                
                data = response.json()
                logger.debug(f"价格转换响应: {len(data.get('routes', []))} 条路由")
                
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
                        logger.error(f"价格转换 API 请求失败（429）: 已重试 {max_retries} 次，放弃")
                        raise
                else:
                    logger.error(f"价格转换 API 请求失败: {e.response.status_code} - {e.response.text}")
                    raise
            except Exception as e:
                logger.error(f"价格转换失败: {e}", exc_info=True)
                raise

    async def close(self) -> None:
        """关闭客户端"""
        await self._client.aclose()


# 全局实例
price_test_client = PriceTestClient()

