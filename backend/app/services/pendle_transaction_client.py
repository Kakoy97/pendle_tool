"""Pendle 交易记录 API 客户端"""

import logging
import os
from typing import Optional
from urllib.parse import urlencode

import httpx

logger = logging.getLogger(__name__)


class PendleTransactionClient:
    """Pendle 交易记录 API 客户端"""

    def __init__(self) -> None:
        self._base_url = "https://api-v2.pendle.finance"
        self._timeout = 60.0

    async def get_wallet_transactions(
        self,
        wallet_address: str,
        limit: int = 100,
    ) -> Optional[dict]:
        """
        获取钱包的交易记录
        
        Args:
            wallet_address: 钱包地址
            limit: 返回记录数量限制（默认100）
        
        Returns:
            交易记录数据（字典格式），如果失败则返回 None
        """
        endpoint = "/core/v1/pnl/transactions"
        
        # 构建查询参数
        params = {
            "limit": limit,
            "user": wallet_address,
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
                    logger.info(f"成功获取钱包 {wallet_address} 的交易记录，共 {result.get('total', 0)} 条")
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

