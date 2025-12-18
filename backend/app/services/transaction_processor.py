"""交易记录处理服务"""

import json
import logging
from datetime import datetime, timedelta, timezone

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.pendle_project import PendleProject
from app.models.wallet_transaction import WalletTransaction

logger = logging.getLogger(__name__)


def calculate_implied_yield(
    yt_price: float,
    pt_price: float,
    minutes_to_expiry: int,
    market_address: str | None = None,
    transaction_date: datetime | None = None,
) -> float | None:
    """
    计算 Implied Yield
    
    公式: [(1 + (YT价格/PT价格))^(365*24*60/剩余分钟数) - 1] × 100%
    剩余分钟数 = 到期日期（小时:分钟） - 历史记录日期（小时:分钟）
    
    举例：
    - 开始时间：2025年10月11日 09:28
    - 结束时间：2025年12月18日 08:00
    - 相差时间：97832分钟
    - 公式：[(1 + (YT价格 ÷ PT价格))^(365*24*60/97832) - 1] × 100%
    
    Args:
        yt_price: YT价格（从priceInAsset.yt读取）
        pt_price: PT价格（从priceInAsset.pt读取）
        minutes_to_expiry: 剩余分钟数（到期日期和历史记录日期相差的分钟数）
        market_address: 市场地址（用于日志）
        transaction_date: 交易日期（用于日志）
    
    Returns:
        Implied Yield（百分比），如果计算失败则返回 None
    """
    try:
        if pt_price <= 0 or minutes_to_expiry <= 0:
            logger.warning(f"无效的参数: pt_price={pt_price}, minutes_to_expiry={minutes_to_expiry}")
            return None
        
        # 计算 YT/PT 比率
        ratio = yt_price / pt_price
        
        # 计算年化收益率
        # [(1 + ratio)^(365*24*60/minutes_to_expiry) - 1] × 100%
        # 365*24*60 = 525600 分钟（一年的总分钟数）
        minutes_per_year = 365 * 24 * 60
        exponent = minutes_per_year / minutes_to_expiry
        base = 1 + ratio
        power_result = base ** exponent
        annualized = (power_result - 1) * 100
        
        # 详细日志输出
        logger.info("=" * 80)
        logger.info("Implied Yield 计算详情")
        logger.info("=" * 80)
        logger.info(f"市场地址: {market_address or 'N/A'}")
        logger.info(f"交易日期: {transaction_date.isoformat() if transaction_date else 'N/A'}")
        logger.info(f"YT价格: {yt_price}")
        logger.info(f"PT价格: {pt_price}")
        logger.info(f"剩余分钟数: {minutes_to_expiry}")
        logger.info(f"YT/PT 比率: {ratio}")
        logger.info(f"计算公式: [(1 + {ratio})^({minutes_per_year}/{minutes_to_expiry}) - 1] × 100%")
        logger.info(f"计算步骤:")
        logger.info(f"  1. 基础值 (1 + ratio) = 1 + {ratio} = {base}")
        logger.info(f"  2. 指数 (365*24*60/minutes_to_expiry) = {minutes_per_year}/{minutes_to_expiry} = {exponent}")
        logger.info(f"  3. 幂运算 {base}^{exponent} = {power_result}")
        logger.info(f"  4. 减去1: {power_result} - 1 = {power_result - 1}")
        logger.info(f"  5. 乘以100%: {power_result - 1} × 100 = {annualized}%")
        logger.info(f"最终结果: {annualized:.4f}%")
        logger.info("=" * 80)
        
        return annualized
    except Exception as e:
        logger.error(f"计算 Implied Yield 失败: {e}", exc_info=True)
        return None


def calculate_minutes_to_expiry(
    expiry_date: datetime,
    transaction_date: datetime,
) -> int:
    """
    计算剩余分钟数（精确计算，包括小时、分钟、秒）
    
    剩余分钟数 = 到期日期（小时:分钟） - 历史记录日期（小时:分钟）
    
    例如：
    - 交易日期：2025-10-11 09:28
    - 到期日期：2025-12-18 08:00
    - 时间差：97832 分钟
    
    Args:
        expiry_date: 到期日期
        transaction_date: 交易日期
    
    Returns:
        剩余分钟数（如果计算失败则返回 0）
    """
    try:
        # 确保两个 datetime 都是 aware（带时区）或都是 naive（不带时区）
        # 统一转换为 UTC aware datetime
        if expiry_date.tzinfo is None:
            # 如果 expiry_date 是 naive，假设它是 UTC
            expiry_date = expiry_date.replace(tzinfo=timezone.utc)
        else:
            # 如果已经是 aware，转换为 UTC
            expiry_date = expiry_date.astimezone(timezone.utc)
        
        if transaction_date.tzinfo is None:
            # 如果 transaction_date 是 naive，假设它是 UTC
            transaction_date = transaction_date.replace(tzinfo=timezone.utc)
        else:
            # 如果已经是 aware，转换为 UTC
            transaction_date = transaction_date.astimezone(timezone.utc)
        
        if expiry_date <= transaction_date:
            return 0
        
        # 计算精确的时间差（包括小时、分钟、秒）
        delta = expiry_date - transaction_date
        
        # 将时间差转换为总分钟数
        total_minutes = int(delta.total_seconds() / 60)  # 60 秒 = 1 分钟
        
        return max(0, total_minutes)
    except Exception as e:
        logger.error(f"计算剩余分钟数失败: {e}", exc_info=True)
        return 0


async def process_transactions(
    transactions_data: dict,
    wallet_address: str,
    session: AsyncSession,
) -> list[dict]:
    """
    处理交易记录数据
    
    1. 只捕获 "buyYt" 和 "sellYt" 操作
    2. 过滤72小时内的交易（已注释，用于测试）
    3. 计算 Implied Yield
    4. 保存到数据库
    
    Args:
        transactions_data: API 返回的交易记录数据
        wallet_address: 钱包地址
        session: 数据库会话
    
    Returns:
        处理后的交易记录列表
    """
    logger.info(f"开始处理钱包 {wallet_address} 的交易记录")
    
    if not transactions_data or "results" not in transactions_data:
        logger.warning("交易记录数据为空或格式不正确")
        return []
    
    results = transactions_data.get("results", [])
    if not results:
        logger.info("没有交易记录")
        return []
    
    logger.info(f"收到 {len(results)} 条原始交易记录")
    
    # 计算72小时前的时间
    # now = datetime.now(timezone.utc)
    # hours_72_ago = now - timedelta(hours=72)
    
    processed_transactions = []
    
    processed_count = 0
    for tx in results:
        try:
            # 1. 处理 buyYt, sellYt, buyYtLimitOrder, sellYtLimitOrder, redeemYtYield
            action = tx.get("action")
            if action not in ["buyYt", "sellYt", "buyYtLimitOrder", "sellYtLimitOrder", "redeemYtYield"]:
                continue
            
            processed_count += 1
            logger.info(f"处理第 {processed_count} 条交易记录: action={action}, tx_hash={tx.get('txHash', 'N/A')}")
            
            # 2. 解析交易时间
            timestamp_str = tx.get("timestamp")
            if not timestamp_str:
                continue
            
            # 解析时间戳（格式：2025-11-24T10:30:35.000Z）
            try:
                tx_timestamp = datetime.fromisoformat(timestamp_str.replace("Z", "+00:00"))
            except Exception as e:
                logger.warning(f"解析时间戳失败: {timestamp_str}, 错误: {e}")
                continue
            
            # 3. 过滤72小时内的交易（已注释，用于测试）
            # if tx_timestamp < hours_72_ago:
            #     continue
            
            # 4. 获取必要字段
            market_address = tx.get("market")
            chain_id = tx.get("chainId")
            tx_hash = tx.get("txHash")
            tx_value_asset = tx.get("txValueAsset", 0)
            price_in_asset = tx.get("priceInAsset", {})
            profit = tx.get("profit", {})
            
            if not market_address or not chain_id or not tx_hash:
                continue
            
            # 5. 获取项目信息（用于获取到期日和项目名称）
            # 只处理正在监控的项目
            project = await session.execute(
                select(PendleProject).where(
                    PendleProject.address == market_address,
                    PendleProject.chain_id == chain_id,
                    PendleProject.is_monitored == True,  # 只查询正在监控的项目
                )
            )
            project = project.scalar_one_or_none()
            
            # 如果项目不在监控列表中，跳过这条交易记录
            if not project:
                logger.debug(f"跳过未监控项目的交易记录: market={market_address}, chain_id={chain_id}")
                continue
            
            if not project.expiry:
                logger.warning(f"项目缺少到期日信息: market={market_address}, chain_id={chain_id}, project_name={project.name}")
                # 即使没有到期日，也继续处理，但无法计算 Implied Yield
                implied_yield = None
                project_name = project.name
            else:
                project_name = project.name
                # 确保 expiry 是 aware datetime
                expiry_date = project.expiry
                if expiry_date.tzinfo is None:
                    # 如果 expiry 是 naive，假设它是 UTC
                    expiry_date = expiry_date.replace(tzinfo=timezone.utc)
                else:
                    # 如果已经是 aware，转换为 UTC
                    expiry_date = expiry_date.astimezone(timezone.utc)
                
                # 计算 Implied Yield（限价买入、限价卖出需要计算，领取奖励不需要）
                if action in ["buyYtLimitOrder", "sellYtLimitOrder"]:
                    # 计算剩余分钟数
                    minutes_to_expiry = calculate_minutes_to_expiry(expiry_date, tx_timestamp)
                    
                    # 计算 Implied Yield
                    yt_price = price_in_asset.get("yt", 0)
                    pt_price = price_in_asset.get("pt", 0)
                    
                    if yt_price > 0 and pt_price > 0 and minutes_to_expiry > 0:
                        implied_yield = calculate_implied_yield(
                            yt_price=yt_price,
                            pt_price=pt_price,
                            minutes_to_expiry=minutes_to_expiry,
                            market_address=market_address,
                            transaction_date=tx_timestamp,
                        )
                    else:
                        logger.warning(f"无法计算 Implied Yield: yt_price={yt_price}, pt_price={pt_price}, minutes_to_expiry={minutes_to_expiry}")
                        implied_yield = None
                elif action in ["buyYt", "sellYt"]:
                    # 普通买入卖出也需要计算 Implied Yield
                    minutes_to_expiry = calculate_minutes_to_expiry(expiry_date, tx_timestamp)
                    yt_price = price_in_asset.get("yt", 0)
                    pt_price = price_in_asset.get("pt", 0)
                    
                    if yt_price > 0 and pt_price > 0 and minutes_to_expiry > 0:
                        implied_yield = calculate_implied_yield(
                            yt_price=yt_price,
                            pt_price=pt_price,
                            minutes_to_expiry=minutes_to_expiry,
                            market_address=market_address,
                            transaction_date=tx_timestamp,
                        )
                    else:
                        implied_yield = None
                else:
                    # 领取奖励不需要计算 Implied Yield
                    implied_yield = None
            
            # 6. 获取利润
            # 卖出和限价卖出：读取profit.usd
            # 领取奖励：读取profit.usd
            # 买入和限价买入：固定为0
            if action in ["sellYt", "sellYtLimitOrder", "redeemYtYield"]:
                profit_usd = profit.get("usd", 0)
            else:
                profit_usd = 0
            
            # 7. 检查是否已存在（避免重复保存）
            existing_result = await session.execute(
                select(WalletTransaction).where(
                    WalletTransaction.wallet_address == wallet_address,
                    WalletTransaction.tx_hash == tx_hash,
                    WalletTransaction.action == action,
                )
            )
            existing_tx = existing_result.scalar_one_or_none()
            
            if existing_tx:
                logger.info(f"交易记录已存在，更新: {tx_hash}")
                # 更新现有记录（即使已存在也重新计算，确保日志输出）
                existing_tx.amount = tx_value_asset
                existing_tx.implied_yield = implied_yield
                existing_tx.profit_usd = profit_usd
                existing_tx.project_name = project_name
                existing_tx.updated_at = datetime.now(timezone.utc)
            else:
                # 创建新记录
                new_tx = WalletTransaction(
                    wallet_address=wallet_address,
                    market_address=market_address,
                    chain_id=chain_id,
                    tx_hash=tx_hash,
                    action=action,
                    timestamp=tx_timestamp,
                    amount=tx_value_asset,
                    implied_yield=implied_yield,
                    profit_usd=profit_usd,
                    project_name=project_name,
                    raw_data=json.dumps(tx, ensure_ascii=False),
                )
                session.add(new_tx)
            
            # 8. 构建返回数据
            processed_transactions.append({
                "timestamp": tx_timestamp.isoformat(),
                "action": action,
                "project_name": project_name or "未知项目",
                "amount": tx_value_asset,
                "implied_yield": implied_yield,
                "profit_usd": profit_usd,
                "chain_id": chain_id,
                "market_address": market_address,
                "tx_hash": tx_hash,
            })
            
        except Exception as e:
            logger.error(f"处理交易记录失败: {e}", exc_info=True)
            continue
    
    # 提交数据库更改
    try:
        await session.commit()
        logger.info(f"成功处理 {len(processed_transactions)} 条交易记录")
    except Exception as e:
        await session.rollback()
        logger.error(f"保存交易记录失败: {e}", exc_info=True)
    
    # 按时间倒序排序（最新的在前）
    processed_transactions.sort(key=lambda x: x["timestamp"], reverse=True)
    
    return processed_transactions

