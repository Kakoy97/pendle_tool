"""限价订单处理服务"""

import json
import logging
import math
from datetime import datetime, timedelta, timezone

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.limit_order import LimitOrder
from app.models.pendle_project import PendleProject

logger = logging.getLogger(__name__)


def calculate_implied_yield_from_ln_rate(ln_implied_rate: str) -> float | None:
    """
    计算 Implied Yield
    
    公式: 实际APY = e^{lnImpliedRate / 1e18} - 1
    
    注意：lnImpliedRate 是一个大整数（以 wei 为单位），需要先除以 1e18 转换为实际值
    
    Args:
        ln_implied_rate: lnImpliedRate 字符串值（大整数，需要除以 1e18）
    
    Returns:
        Implied Yield（百分比形式，例如 5.0 表示 5%），如果计算失败则返回 None
    """
    try:
        # 转换为浮点数
        ln_rate_raw = float(ln_implied_rate)
        
        # 除以 1e18 转换为实际值
        # 例如：188461005086490266 / 1e18 = 0.188461005086490266
        ln_rate = ln_rate_raw / 1e18
        
        logger.debug(f"lnImpliedRate 原始值: {ln_rate_raw}, 除以 1e18 后: {ln_rate}")
        
        # 检查 ln_rate 的值范围，避免 math.exp 溢出
        # math.exp 在 ln_rate > 709 时会溢出（因为 e^709 接近 float 的最大值）
        # 对于合理的 APY 计算，ln_rate 通常在 -10 到 10 之间
        MAX_LN_RATE = 10  # 设置一个合理的上限
        MIN_LN_RATE = -10  # 设置一个合理的下限
        
        if ln_rate > MAX_LN_RATE:
            logger.warning(f"lnImpliedRate 值过大 ({ln_rate})，可能异常，跳过计算")
            return None
        
        if ln_rate < MIN_LN_RATE:
            logger.warning(f"lnImpliedRate 值过小 ({ln_rate})，可能异常，跳过计算")
            return None
        
        # 计算 e^{lnImpliedRate / 1e18}
        try:
            exp_result = math.exp(ln_rate)
        except OverflowError:
            logger.error(f"计算 e^{ln_rate} 时发生溢出，ln_rate={ln_rate}")
            return None
        
        # 检查 exp_result 是否为无穷大或 NaN
        if not math.isfinite(exp_result):
            logger.warning(f"exp_result 不是有限数: {exp_result}, ln_rate={ln_rate}")
            return None
        
        # 计算 APY = e^{lnImpliedRate / 1e18} - 1
        apy = exp_result - 1
        
        # 转换为百分比（乘以100）
        implied_yield_percent = apy * 100
        
        # 检查结果是否合理（APY 通常在 -100% 到 10000% 之间）
        if abs(implied_yield_percent) > 10000:
            logger.warning(f"计算出的 Implied Yield 异常: {implied_yield_percent}%, ln_rate={ln_rate}")
            return None
        
        logger.debug(f"计算 Implied Yield: lnImpliedRate原始={ln_rate_raw}, ln_rate={ln_rate}, e^{ln_rate}={exp_result}, APY={apy}, 百分比={implied_yield_percent}%")
        
        return implied_yield_percent
    except (ValueError, OverflowError) as e:
        logger.error(f"计算 Implied Yield 失败: {e}, ln_implied_rate={ln_implied_rate}", exc_info=True)
        return None


async def process_limit_orders(
    limit_orders_data: dict,
    wallet_address: str,
    chain_id: int,
    session: AsyncSession,
) -> list[dict]:
    """
    处理限价订单数据
    
    1. 只捕获72小时内的订单
    2. 计算 Implied Yield
    3. 保存到数据库（如果订单已存在则更新，否则创建）
    
    Args:
        limit_orders_data: API 返回的限价订单数据
        wallet_address: 钱包地址
        chain_id: 链ID
        session: 数据库会话
    
    Returns:
        处理后的限价订单列表
    """
    logger.info(f"开始处理钱包 {wallet_address} 在链 {chain_id} 的限价订单")
    
    if not limit_orders_data or "results" not in limit_orders_data:
        logger.warning("限价订单数据为空或格式不正确")
        return []
    
    results = limit_orders_data.get("results", [])
    if not results:
        logger.info("没有限价订单记录")
        return []
    
    logger.info(f"收到 {len(results)} 条原始限价订单记录")
    
    # 计算72小时前的时间
    now = datetime.now(timezone.utc)
    hours_72_ago = now - timedelta(hours=72)
    
    processed_orders = []
    
    for order in results:
        try:
            # 1. 解析最新事件时间戳
            latest_event_timestamp_str = order.get("latestEventTimestamp")
            if not latest_event_timestamp_str:
                # 如果没有latestEventTimestamp，使用createdAt
                latest_event_timestamp_str = order.get("createdAt")
            
            if not latest_event_timestamp_str:
                continue
            
            # 解析时间戳（格式：2025-10-02T07:12:35.464Z）
            try:
                latest_event_timestamp = datetime.fromisoformat(latest_event_timestamp_str.replace("Z", "+00:00"))
            except Exception as e:
                logger.warning(f"解析时间戳失败: {latest_event_timestamp_str}, 错误: {e}")
                continue
            
            # 2. 过滤72小时内的订单
            if latest_event_timestamp < hours_72_ago:
                continue
            
            # 3. 获取必要字段
            order_id = order.get("id")
            status = order.get("status")
            order_state = order.get("orderState", {})
            order_type = order_state.get("orderType", "")
            notional_volume_usd = order_state.get("notionalVolumeUSD", 0)
            ln_implied_rate = order.get("lnImpliedRate")
            
            if not order_id or not status:
                continue
            
            # 4. 获取市场地址（从yt或pt推断，优先使用yt）
            # 只处理正在监控的项目
            yt_address = order.get("yt")
            pt_address = order.get("pt")
            market_address = None
            project_name = None
            project = None
            
            # 尝试通过yt地址查找项目（只查找正在监控的项目）
            if yt_address:
                # 构建完整格式的yt地址：chain_id-yt_address
                yt_address_full = f"{chain_id}-{yt_address}"
                
                # 查找匹配的项目（只查询正在监控的项目）
                project = await session.execute(
                    select(PendleProject).where(
                        PendleProject.yt_address_full == yt_address_full,
                        PendleProject.chain_id == chain_id,
                        PendleProject.is_monitored == True,  # 只查询正在监控的项目
                    )
                )
                project = project.scalar_one_or_none()
                
                if project:
                    market_address = project.address
                    project_name = project.name
                else:
                    # 如果完整格式没找到，尝试模糊匹配（只查询正在监控的项目）
                    project = await session.execute(
                        select(PendleProject).where(
                            PendleProject.yt_address_full.like(f"%{yt_address}%"),
                            PendleProject.chain_id == chain_id,
                            PendleProject.is_monitored == True,  # 只查询正在监控的项目
                        )
                    )
                    project = project.scalar_one_or_none()
                    
                    if project:
                        market_address = project.address
                        project_name = project.name
            
            # 如果没找到，尝试通过extra_data中的yt字段查找（只查找正在监控的项目）
            if not market_address:
                # 遍历所有正在监控的项目，检查extra_data中的yt字段
                all_projects = await session.execute(
                    select(PendleProject).where(
                        PendleProject.chain_id == chain_id,
                        PendleProject.is_monitored == True,  # 只查询正在监控的项目
                    )
                )
                for proj in all_projects.scalars().all():
                    if proj.extra_data:
                        try:
                            extra_data = json.loads(proj.extra_data)
                            proj_yt = extra_data.get("yt", "")
                            # 检查是否匹配
                            if isinstance(proj_yt, str):
                                if yt_address and (proj_yt.endswith(yt_address) or proj_yt == yt_address):
                                    market_address = proj.address
                                    project_name = proj.name
                                    project = proj
                                    break
                        except (json.JSONDecodeError, KeyError):
                            continue
            
            # 如果仍然没找到项目，跳过这条限价订单（不在监控列表中）
            if not market_address:
                logger.debug(f"跳过未监控项目的限价订单: yt={yt_address}, chain_id={chain_id}, order_id={order_id}")
                continue
            
            # 5. 计算 Implied Yield
            implied_yield = None
            if ln_implied_rate:
                implied_yield = calculate_implied_yield_from_ln_rate(ln_implied_rate)
            
            # 6. 检查是否已存在（根据订单ID）
            existing_result = await session.execute(
                select(LimitOrder).where(
                    LimitOrder.order_id == order_id,
                )
            )
            existing_order = existing_result.scalar_one_or_none()
            
            if existing_order:
                logger.debug(f"限价订单已存在，更新: {order_id}, 状态: {status}")
                # 更新现有记录
                existing_order.status = status
                existing_order.order_type = order_type
                existing_order.notional_volume_usd = notional_volume_usd
                existing_order.implied_yield = implied_yield
                existing_order.ln_implied_rate = ln_implied_rate
                existing_order.project_name = project_name
                existing_order.market_address = market_address
                existing_order.latest_event_timestamp = latest_event_timestamp
                existing_order.updated_at = datetime.now(timezone.utc)
                existing_order.raw_data = json.dumps(order, ensure_ascii=False)
            else:
                # 创建新记录
                new_order = LimitOrder(
                    order_id=order_id,
                    wallet_address=wallet_address,
                    chain_id=chain_id,
                    market_address=market_address,
                    status=status,
                    order_type=order_type,
                    notional_volume_usd=notional_volume_usd,
                    implied_yield=implied_yield,
                    ln_implied_rate=ln_implied_rate,
                    project_name=project_name,
                    latest_event_timestamp=latest_event_timestamp,
                    raw_data=json.dumps(order, ensure_ascii=False),
                )
                session.add(new_order)
            
            # 7. 构建返回数据
            processed_orders.append({
                "timestamp": latest_event_timestamp.isoformat(),
                "status": status,
                "order_type": order_type,
                "project_name": project_name or "未知项目",
                "notional_volume_usd": notional_volume_usd,
                "implied_yield": implied_yield,
                "chain_id": chain_id,
                "market_address": market_address,
                "order_id": order_id,
            })
            
        except Exception as e:
            logger.error(f"处理限价订单失败: {e}", exc_info=True)
            continue
    
    # 提交数据库更改
    try:
        await session.commit()
        logger.info(f"成功处理 {len(processed_orders)} 条限价订单记录")
    except Exception as e:
        await session.rollback()
        logger.error(f"保存限价订单失败: {e}", exc_info=True)
    
    # 按时间倒序排序（最新的在前）
    processed_orders.sort(key=lambda x: x["timestamp"], reverse=True)
    
    return processed_orders

