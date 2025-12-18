"""Pendle 限价订单 API 客户端"""

import asyncio
import logging
import os
from typing import Optional
from urllib.parse import urlencode

import httpx

logger = logging.getLogger(__name__)


class PendleLimitOrderClient:
    """Pendle 限价订单 API 客户端"""

    def __init__(self) -> None:
        self._base_url = "https://api-v2.pendle.finance"
        self._timeout = 60.0

    async def get_wallet_limit_orders(
        self,
        wallet_address: str,
        chain_id: int,
        limit: int = 100,
        skip: int = 0,
    ) -> Optional[dict]:
        """
        获取钱包在指定链上的限价订单记录
        
        Args:
            wallet_address: 钱包地址
            chain_id: 链ID
            limit: 返回记录数量限制（默认100）
            skip: 跳过的记录数量（默认0）
        
        Returns:
            限价订单数据（字典格式），如果失败则返回 None
        """
        endpoint = "/core/v1/limit-orders/makers/limit-orders"
        
        # 构建查询参数
        params = {
            "limit": limit,
            "chainId": chain_id,
            "maker": wallet_address,
        }
        
        if skip > 0:
            params["skip"] = skip
        
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
                    logger.error(f"获取限价订单失败，状态码: {response.status_code}, 响应: {response.text}")
                    return None
                
                # 解析JSON响应
                try:
                    result = response.json()
                    logger.debug(f"成功获取钱包 {wallet_address} 在链 {chain_id} 的限价订单，共 {result.get('total', 0)} 条（skip={skip}）")
                    return result
                except Exception as e:
                    logger.error(f"JSON 解析失败: {e}, 原始响应: {response.text}")
                    return None
                    
        except httpx.TimeoutException:
            logger.error(f"请求超时（超过 {self._timeout} 秒）")
            raise  # 重新抛出异常，让调用者处理重试
        except (httpx.ConnectError, httpx.ReadError, ConnectionError) as e:
            # 处理连接错误（包括 "Server closed the connection"）
            logger.warning(f"连接错误: {e}，将重试")
            raise  # 重新抛出异常，让调用者处理重试
        except httpx.RequestError as e:
            logger.error(f"请求出错: {e}")
            raise  # 重新抛出异常，让调用者处理重试
        except Exception as e:
            logger.error(f"未知错误: {e}", exc_info=True)
            raise  # 重新抛出异常，让调用者处理重试

    async def get_wallet_limit_orders_within_hours(
        self,
        wallet_address: str,
        chain_id: int,
        hours: int = 72,
        max_queries: int = 20,
    ) -> list[dict]:
        """
        获取钱包在指定链上的限价订单记录（72小时内）
        
        由于API返回的数据是按时间从远到近排序的，需要循环查询并使用skip参数
        直到找到72小时内的数据。
        
        Args:
            wallet_address: 钱包地址
            chain_id: 链ID
            hours: 查询最近多少小时的订单（默认72小时）
            max_queries: 最大查询次数，避免无限循环（默认20次，即最多查询2000条）
        
        Returns:
            72小时内的限价订单列表
        """
        from datetime import datetime, timedelta, timezone
        
        all_orders = []
        skip = 0
        query_count = 0
        found_recent_orders = False
        
        # 计算时间阈值
        now = datetime.now(timezone.utc)
        time_threshold = now - timedelta(hours=hours)
        
        logger.info(f"开始查询钱包 {wallet_address} 在链 {chain_id} 的限价订单（{hours}小时内）")
        
        while query_count < max_queries:
            query_count += 1
            
            # 查询数据（带重试机制）
            result = None
            retry_count = 0
            max_retries = 3
            
            while retry_count < max_retries:
                try:
                    result = await self.get_wallet_limit_orders(
                        wallet_address=wallet_address,
                        chain_id=chain_id,
                        limit=100,
                        skip=skip,
                    )
                    break  # 成功获取数据，退出重试循环
                except Exception as e:
                    retry_count += 1
                    if retry_count >= max_retries:
                        logger.error(f"查询限价订单失败（已重试 {max_retries} 次）: {e}", exc_info=True)
                        result = None
                    else:
                        # 等待后重试
                        wait_time = retry_count * 2  # 递增等待时间：2秒、4秒
                        logger.warning(f"查询限价订单失败，{wait_time}秒后重试 ({retry_count}/{max_retries}): {e}")
                        await asyncio.sleep(wait_time)
            
            if not result or "results" not in result:
                logger.debug(f"查询结果为空，停止查询（skip={skip}）")
                break
            
            # 在每次查询之间添加短暂延迟，避免请求过快导致连接关闭
            if query_count > 1:
                await asyncio.sleep(1)  # 每次查询后等待1秒
            
            results = result.get("results", [])
            if not results:
                logger.debug(f"没有更多数据，停止查询（skip={skip}）")
                break
            
            logger.debug(f"查询到 {len(results)} 条记录（skip={skip}）")
            
            # 检查是否有72小时内的数据
            recent_orders_in_batch = []
            all_old_orders = True
            
            for order in results:
                # 解析时间戳
                latest_event_timestamp_str = order.get("latestEventTimestamp") or order.get("createdAt")
                if not latest_event_timestamp_str:
                    continue
                
                try:
                    latest_event_timestamp = datetime.fromisoformat(
                        latest_event_timestamp_str.replace("Z", "+00:00")
                    )
                except Exception:
                    continue
                
                # 检查是否在时间范围内
                if latest_event_timestamp >= time_threshold:
                    recent_orders_in_batch.append(order)
                    all_old_orders = False
                    found_recent_orders = True
            
            # 如果找到了72小时内的数据，添加到结果中
            if recent_orders_in_batch:
                all_orders.extend(recent_orders_in_batch)
                logger.debug(f"本批次找到 {len(recent_orders_in_batch)} 条72小时内的订单")
            
            # 如果这一批全部都是旧数据
            if all_old_orders:
                if found_recent_orders:
                    # 如果之前已经找到过新数据，说明已经跨过了时间边界，可以停止
                    logger.debug(f"本批次全部是旧数据，且之前已找到新数据，停止查询")
                    break
                else:
                    # 如果还没找到新数据，继续查询更早的数据
                    skip += 100
                    logger.debug(f"本批次全部是旧数据，继续查询（skip={skip}）")
                    continue
            
            # 如果这一批有新数据，继续查询下一批
            skip += 100
            
            # 如果返回的数据少于100条，说明已经到末尾了
            if len(results) < 100:
                logger.debug(f"返回数据少于100条，已到末尾，停止查询")
                break
        
        logger.info(f"查询完成，共查询 {query_count} 次，找到 {len(all_orders)} 条72小时内的订单")
        
        return all_orders

