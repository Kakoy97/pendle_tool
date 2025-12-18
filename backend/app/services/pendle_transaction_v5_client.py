"""Pendle V5 交易记录 API 客户端"""

import logging
import os
from typing import Optional
from urllib.parse import quote, urlencode

import httpx

logger = logging.getLogger(__name__)


class PendleTransactionV5Client:
    """Pendle V5 交易记录 API 客户端"""

    def __init__(self) -> None:
        self._base_url = "https://api-v2.pendle.finance"
        self._timeout = 60.0

    async def get_project_transactions(
        self,
        chain_id: int,
        address: str,
        type: str = "TRADES",
        limit: int = 1,
        min_value: float = 50000,
        action: str = "SHORT_YIELD",
    ) -> Optional[dict]:
        """
        获取项目的交易记录（V5 API）
        
        Args:
            chain_id: 链ID
            address: 项目地址
            type: 交易类型（默认 TRADES）
            limit: 返回记录数量限制（默认 1）
            min_value: 最小价值（默认 50000）
            action: 操作类型（默认 SHORT_YIELD）
        
        Returns:
            交易记录数据（字典格式），如果失败则返回 None
        """
        endpoint = f"/core/v5/{chain_id}/transactions/{quote(address, safe='')}"
        
        # 构建查询参数
        params = {
            "type": type,
            "limit": str(limit),
            "minValue": str(min_value),
            "action": action,
        }
        
        url = f"{self._base_url}{endpoint}?{urlencode(params)}"
        
        # 尝试从环境变量获取代理配置
        proxies = None
        http_proxy = os.environ.get("HTTP_PROXY") or os.environ.get("http_proxy")
        https_proxy = os.environ.get("HTTPS_PROXY") or os.environ.get("https_proxy")
        
        if http_proxy or https_proxy:
            proxies = {
                "http://": http_proxy,
                "https://": https_proxy or http_proxy,
            }
            logger.debug(f"使用代理: {proxies}")
        
        try:
            async with httpx.AsyncClient(
                timeout=self._timeout,
                follow_redirects=True,
                proxies=proxies,
            ) as client:
                response = await client.get(url)
                
                # 检查响应状态
                if response.status_code != 200:
                    logger.error(f"获取交易记录失败，状态码: {response.status_code}, 响应: {response.text}")
                    return None
                
                # 解析JSON响应
                try:
                    result = response.json()
                    logger.debug(f"成功获取项目 {address} 在链 {chain_id} 的交易记录，共 {result.get('total', 0)} 条")
                    return result
                except Exception as e:
                    logger.error(f"JSON 解析失败: {e}, 原始响应: {response.text}")
                    return None
                    
        except httpx.TimeoutException:
            logger.error(f"请求超时（超过 {self._timeout} 秒）")
            return None
        except httpx.ConnectError as e:
            logger.error(f"连接失败: {e}")
            return None
        except httpx.RequestError as e:
            logger.error(f"请求出错: {e}")
            return None
        except Exception as e:
            logger.error(f"未知错误: {e}", exc_info=True)
            return None


# 全局实例
pendle_transaction_v5_client = PendleTransactionV5Client()

