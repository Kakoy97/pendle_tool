"""聪明钱 API 路由"""

import asyncio
import logging
from datetime import datetime, timedelta, timezone

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.db import get_session
from app.models.smart_money import SmartMoney
from app.models.wallet_transaction import WalletTransaction
from app.schemas.smart_money import (
    SmartMoneyCreate,
    SmartMoneyListResponse,
    SmartMoneyResponse,
    SmartMoneyUpdate,
)

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/smart-money", tags=["smart-money"])

# 等级排序：重点 > 聪明钱 > 蚂蚁仓
LEVEL_ORDER = {"重点": 0, "聪明钱": 1, "蚂蚁仓": 2}


@router.get("", response_model=SmartMoneyListResponse)
async def get_smart_money(
    session: AsyncSession = Depends(get_session),
) -> SmartMoneyListResponse:
    """
    获取所有聪明钱列表（按等级排序）
    """
    try:
        result = await session.execute(select(SmartMoney))
        all_smart_money = result.scalars().all()
        
        # 按等级排序（重点 > 聪明钱 > 蚂蚁仓），然后按创建时间倒序
        sorted_smart_money = sorted(
            all_smart_money,
            key=lambda x: (LEVEL_ORDER.get(x.level, 999), x.created_at),
        )
        
        return SmartMoneyListResponse(
            smart_money=sorted_smart_money,
            total=len(sorted_smart_money),
        )
    except Exception as e:
        logger.error(f"获取聪明钱列表失败: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail=f"获取失败: {str(e)}")


@router.post("", response_model=SmartMoneyResponse)
async def create_smart_money(
    data: SmartMoneyCreate,
    session: AsyncSession = Depends(get_session),
) -> SmartMoneyResponse:
    """
    创建聪明钱记录
    """
    try:
        # 检查钱包地址是否已存在
        existing = await session.execute(
            select(SmartMoney).where(SmartMoney.wallet_address == data.wallet_address)
        )
        if existing.scalar_one_or_none():
            raise HTTPException(status_code=400, detail="钱包地址已存在")
        
        smart_money = SmartMoney(
            wallet_address=data.wallet_address,
            name=data.name,
            level=data.level,
        )
        session.add(smart_money)
        await session.commit()
        await session.refresh(smart_money)
        
        logger.info(f"创建聪明钱记录: {smart_money.name} ({smart_money.wallet_address})")
        return smart_money
    except HTTPException:
        raise
    except Exception as e:
        await session.rollback()
        logger.error(f"创建聪明钱记录失败: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail=f"创建失败: {str(e)}")


@router.put("/{wallet_address}", response_model=SmartMoneyResponse)
async def update_smart_money(
    wallet_address: str,
    data: SmartMoneyUpdate,
    session: AsyncSession = Depends(get_session),
) -> SmartMoneyResponse:
    """
    更新聪明钱记录
    """
    try:
        result = await session.execute(
            select(SmartMoney).where(SmartMoney.wallet_address == wallet_address)
        )
        smart_money = result.scalar_one_or_none()
        
        if not smart_money:
            raise HTTPException(status_code=404, detail="聪明钱记录不存在")
        
        # 更新字段
        if data.name is not None:
            smart_money.name = data.name
        if data.level is not None:
            smart_money.level = data.level
        
        smart_money.updated_at = datetime.now(timezone.utc)
        await session.commit()
        await session.refresh(smart_money)
        
        logger.info(f"更新聪明钱记录: {smart_money.name} ({smart_money.wallet_address})")
        return smart_money
    except HTTPException:
        raise
    except Exception as e:
        await session.rollback()
        logger.error(f"更新聪明钱记录失败: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail=f"更新失败: {str(e)}")


@router.delete("/{wallet_address}")
async def delete_smart_money(
    wallet_address: str,
    session: AsyncSession = Depends(get_session),
) -> dict:
    """
    删除聪明钱记录及其相关的交易历史记录
    """
    try:
        result = await session.execute(
            select(SmartMoney).where(SmartMoney.wallet_address == wallet_address)
        )
        smart_money = result.scalar_one_or_none()
        
        if not smart_money:
            raise HTTPException(status_code=404, detail="聪明钱记录不存在")
        
        # 删除相关的交易历史记录
        from sqlalchemy import delete
        delete_result = await session.execute(
            delete(WalletTransaction).where(
                WalletTransaction.wallet_address == wallet_address
            )
        )
        deleted_count = delete_result.rowcount
        
        # 删除聪明钱记录
        await session.delete(smart_money)
        await session.commit()
        
        logger.info(f"删除聪明钱记录: {smart_money.name} ({smart_money.wallet_address})，同时删除了 {deleted_count} 条交易历史记录")
        return {
            "success": True,
            "message": "删除成功",
            "deleted_transactions": deleted_count,
        }
    except HTTPException:
        raise
    except Exception as e:
        await session.rollback()
        logger.error(f"删除聪明钱记录失败: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail=f"删除失败: {str(e)}")


@router.get("/{wallet_address}/operations")
async def get_wallet_operations(
    wallet_address: str,
    hours: int = Query(72, description="查询最近多少小时的操作（默认 72 小时）"),
    session: AsyncSession = Depends(get_session),
    refresh: bool = Query(False, description="是否从API刷新数据（默认False，使用缓存）"),
) -> dict:
    """
    获取钱包近 N 小时的操作记录
    
    Args:
        wallet_address: 钱包地址
        hours: 查询最近多少小时的操作（默认 72 小时）
        refresh: 是否从API刷新数据
    
    Returns:
        操作记录列表
    """
    try:
        from app.services.pendle_transaction_client import PendleTransactionClient
        from app.services.transaction_processor import process_transactions
        
        # 如果要求刷新，从API获取最新数据
        if refresh:
            logger.info(f"从API刷新钱包 {wallet_address} 的交易记录")
            client = PendleTransactionClient()
            transactions_data = await client.get_wallet_transactions(wallet_address, limit=100)
            
            if transactions_data:
                # 处理并保存交易记录
                processed = await process_transactions(transactions_data, wallet_address, session)
            else:
                processed = []
        else:
            # 从数据库读取
            # 过滤72小时内的记录
            hours_ago = datetime.now(timezone.utc) - timedelta(hours=hours)
            
            result = await session.execute(
                select(WalletTransaction).where(
                    WalletTransaction.wallet_address == wallet_address,
                    WalletTransaction.timestamp >= hours_ago,
                ).order_by(WalletTransaction.timestamp.desc())
            )
            db_transactions = result.scalars().all()
            
            processed = []
            for tx in db_transactions:
                # 确保时间戳是 aware datetime，并转换为 ISO 格式（包含时区信息）
                timestamp = tx.timestamp
                if timestamp.tzinfo is None:
                    # 如果 timestamp 是 naive，假设它是 UTC
                    timestamp = timestamp.replace(tzinfo=timezone.utc)
                else:
                    # 如果已经是 aware，确保是 UTC
                    timestamp = timestamp.astimezone(timezone.utc)
                
                processed.append({
                    "timestamp": timestamp.isoformat(),
                    "action": tx.action,
                    "project_name": tx.project_name or "未知项目",
                    "amount": tx.amount,
                    "implied_yield": tx.implied_yield,
                    "profit_usd": tx.profit_usd,
                    "chain_id": tx.chain_id,
                    "market_address": tx.market_address,
                    "tx_hash": tx.tx_hash,
                })
        
        # 获取限价订单记录
        from app.services.pendle_limit_order_client import PendleLimitOrderClient
        from app.services.limit_order_processor import process_limit_orders
        from app.models.chain_id import ChainId
        
        limit_orders = []
        
        if refresh:
            # 从API获取限价订单（遍历所有链）
            logger.info(f"从API刷新钱包 {wallet_address} 的限价订单")
            
            # 获取所有链信息（确保 select 已导入）
            chains_result = await session.execute(select(ChainId))
            chains = chains_result.scalars().all()
            
            limit_order_client = PendleLimitOrderClient()
            
            for chain in chains:
                try:
                    # 使用新的方法，自动循环查询直到找到72小时内的数据
                    recent_orders = await limit_order_client.get_wallet_limit_orders_within_hours(
                        wallet_address=wallet_address,
                        chain_id=chain.id,
                        hours=hours,
                        max_queries=20,  # 最多查询20次（2000条记录）
                    )
                    
                    if recent_orders:
                        # 构建API返回格式的数据结构
                        limit_orders_data = {
                            "total": len(recent_orders),
                            "results": recent_orders,
                        }
                        
                        # 处理并保存限价订单
                        processed_orders = await process_limit_orders(
                            limit_orders_data, wallet_address, chain.id, session
                        )
                        limit_orders.extend(processed_orders)
                    
                    # 等待5秒再查询下一个链
                    if chain != chains[-1]:
                        await asyncio.sleep(5)
                except Exception as e:
                    logger.error(f"获取链 {chain.name} 的限价订单失败: {e}", exc_info=True)
        else:
            # 从数据库读取限价订单
            from app.models.limit_order import LimitOrder
            
            hours_ago = datetime.now(timezone.utc) - timedelta(hours=hours)
            
            result = await session.execute(
                select(LimitOrder).where(
                    LimitOrder.wallet_address == wallet_address,
                    LimitOrder.latest_event_timestamp >= hours_ago,
                ).order_by(LimitOrder.latest_event_timestamp.desc())
            )
            db_orders = result.scalars().all()
            
            for order in db_orders:
                # 确保时间戳是 aware datetime，并转换为 ISO 格式（包含时区信息）
                timestamp = order.latest_event_timestamp
                if timestamp.tzinfo is None:
                    # 如果 timestamp 是 naive，假设它是 UTC
                    timestamp = timestamp.replace(tzinfo=timezone.utc)
                else:
                    # 如果已经是 aware，确保是 UTC
                    timestamp = timestamp.astimezone(timezone.utc)
                
                limit_orders.append({
                    "timestamp": timestamp.isoformat(),
                    "status": order.status,
                    "order_type": order.order_type,
                    "project_name": order.project_name or "未知项目",
                    "notional_volume_usd": order.notional_volume_usd,
                    "implied_yield": order.implied_yield,
                    "chain_id": order.chain_id,
                    "market_address": order.market_address,
                    "order_id": order.order_id,
                })
        
        return {
            "success": True,
            "wallet_address": wallet_address,
            "hours": hours,
            "operations": processed,
            "limit_orders": limit_orders,
            "total": len(processed) + len(limit_orders),
        }
    except Exception as e:
        logger.error(f"获取钱包操作记录失败: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail=f"获取失败: {str(e)}")

