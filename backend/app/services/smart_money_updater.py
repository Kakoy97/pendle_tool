"""聪明钱历史记录自动更新服务"""

import asyncio
import logging
from datetime import datetime, timezone

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.db import get_session
from app.models.smart_money import SmartMoney
from app.models.wallet_transaction import WalletTransaction
from app.models.limit_order import LimitOrder
from app.services.pendle_transaction_client import PendleTransactionClient
from app.services.pendle_limit_order_client import PendleLimitOrderClient
from app.services.transaction_processor import process_transactions
from app.services.limit_order_processor import process_limit_orders
from app.services.telegram_notifier import send_notification
from app.models.chain_id import ChainId

logger = logging.getLogger(__name__)


class SmartMoneyUpdater:
    """聪明钱历史记录自动更新服务"""
    
    def __init__(self):
        self._running = False
        self._task = None
        self._update_duration = 8 * 60  # 8分钟（秒）
    
    async def start(self):
        """启动自动更新服务"""
        if self._running:
            logger.warning("聪明钱更新服务已在运行")
            return
        
        self._running = True
        self._task = asyncio.create_task(self._update_loop())
        logger.info("聪明钱自动更新服务已启动")
    
    async def stop(self):
        """停止自动更新服务"""
        self._running = False
        if self._task:
            self._task.cancel()
            try:
                await self._task
            except asyncio.CancelledError:
                pass
        logger.info("聪明钱自动更新服务已停止")
    
    async def _update_loop(self):
        """更新循环"""
        from app.core.db import get_sessionmaker
        
        while self._running:
            try:
                # 创建数据库会话
                session_maker = get_sessionmaker()
                async with session_maker() as session:
                    try:
                        result = await session.execute(select(SmartMoney))
                        wallets = result.scalars().all()
                        
                        if not wallets:
                            logger.info("没有聪明钱钱包需要更新，等待下一轮")
                            await asyncio.sleep(60)  # 等待1分钟后重试
                            continue
                        
                        # 遍历每个钱包进行更新
                        total_wallets = len(wallets)
                        print(f"\n{'='*60}")
                        print(f"📊 开始聪明钱更新循环，共 {total_wallets} 个钱包")
                        print(f"{'='*60}\n")
                        logger.info(f"开始聪明钱更新循环，共 {total_wallets} 个钱包")
                        
                        for index, wallet in enumerate(wallets, 1):
                            if not self._running:
                                break
                            
                            wallet_name = wallet.name or wallet.wallet_address[:8]
                            print(f"\n[{index}/{total_wallets}] 🔄 正在更新钱包: {wallet_name} ({wallet.wallet_address})")
                            logger.info(f"[{index}/{total_wallets}] 开始更新钱包: {wallet_name} ({wallet.wallet_address})")
                            
                            try:
                                await self._update_wallet(wallet, session)
                                print(f"[{index}/{total_wallets}] ✅ 钱包 {wallet_name} 更新完成")
                            except Exception as e:
                                print(f"[{index}/{total_wallets}] ❌ 钱包 {wallet_name} 更新失败: {e}")
                                logger.error(f"更新钱包 {wallet.wallet_address} 失败: {e}", exc_info=True)
                            
                            # 等待8分钟后更新下一个钱包
                            if self._running and index < total_wallets:
                                print(f"[{index}/{total_wallets}] ⏳ 等待 8 分钟后更新下一个钱包...\n")
                                await asyncio.sleep(self._update_duration)
                        
                        print(f"\n{'='*60}")
                        print(f"✅ 本轮聪明钱更新循环完成，共处理 {total_wallets} 个钱包")
                        print(f"{'='*60}\n")
                        logger.info(f"本轮聪明钱更新循环完成，共处理 {total_wallets} 个钱包")
                        
                    except Exception as e:
                        await session.rollback()
                        raise
                
            except Exception as e:
                logger.error(f"更新循环出错: {e}", exc_info=True)
                await asyncio.sleep(60)  # 出错后等待1分钟再重试
    
    async def _update_wallet(self, wallet: SmartMoney, session: AsyncSession):
        """更新单个钱包的历史记录"""
        wallet_address = wallet.wallet_address
        wallet_name = wallet.name or wallet_address[:8]
        
        start_time = datetime.now(timezone.utc)
        
        try:
            # 1. 获取交易记录
            print(f"  📥 正在获取钱包 {wallet_name} 的交易记录...")
            transaction_client = PendleTransactionClient()
            transactions_data = await transaction_client.get_wallet_transactions(wallet_address, limit=100)
            
            new_transactions = []
            if transactions_data:
                print(f"  ✅ 获取到 {len(transactions_data.get('results', []))} 条交易记录，正在处理...")
                processed = await process_transactions(transactions_data, wallet_address, session)
                new_transactions = processed
                print(f"  ✅ 处理完成，共 {len(new_transactions)} 条有效交易记录")
            else:
                print(f"  ℹ️  未获取到交易记录")
            
            # 2. 获取限价订单记录（遍历所有链）
            limit_order_client = PendleLimitOrderClient()
            chains_result = await session.execute(select(ChainId))
            chains = chains_result.scalars().all()
            
            print(f"  📥 正在获取钱包 {wallet_name} 的限价订单记录（共 {len(chains)} 条链）...")
            new_limit_orders = []
            for chain_index, chain in enumerate(chains, 1):
                try:
                    print(f"    [{chain_index}/{len(chains)}] 查询链 {chain.name} (ID: {chain.id})...")
                    recent_orders = await limit_order_client.get_wallet_limit_orders_within_hours(
                        wallet_address=wallet_address,
                        chain_id=chain.id,
                        hours=72,
                        max_queries=20,
                    )
                    
                    if recent_orders:
                        print(f"    ✅ 链 {chain.name} 获取到 {len(recent_orders)} 条限价订单，正在处理...")
                        limit_orders_data = {
                            "total": len(recent_orders),
                            "results": recent_orders,
                        }
                        processed_orders = await process_limit_orders(
                            limit_orders_data, wallet_address, chain.id, session
                        )
                        new_limit_orders.extend(processed_orders)
                        print(f"    ✅ 链 {chain.name} 处理完成，共 {len(processed_orders)} 条有效限价订单")
                    else:
                        print(f"    ℹ️  链 {chain.name} 未获取到限价订单")
                    
                    # 等待5秒再查询下一个链
                    if chain != chains[-1]:
                        await asyncio.sleep(5)
                except Exception as e:
                    print(f"    ❌ 链 {chain.name} 查询失败: {e}")
                    logger.error(f"获取链 {chain.name} 的限价订单失败: {e}", exc_info=True)
            
            print(f"  ✅ 限价订单查询完成，共 {len(new_limit_orders)} 条有效记录")
            
            # 3. 合并所有新记录并按时间排序
            all_new_records = []
            
            # 添加交易记录
            for tx in new_transactions:
                all_new_records.append({
                    "type": "transaction",
                    "timestamp": datetime.fromisoformat(tx["timestamp"].replace("Z", "+00:00")),
                    "data": tx,
                })
            
            # 添加限价订单
            for order in new_limit_orders:
                all_new_records.append({
                    "type": "limit_order",
                    "timestamp": datetime.fromisoformat(order["timestamp"].replace("Z", "+00:00")),
                    "data": order,
                })
            
            # 按时间排序（由远到近）
            all_new_records.sort(key=lambda x: x["timestamp"])
            
            # 4. 获取上次更新的时间戳
            last_timestamp = wallet.last_update_timestamp
            
            # 确保 last_timestamp 是 aware UTC datetime（用于比较）
            if last_timestamp:
                if last_timestamp.tzinfo is None:
                    # 如果 last_timestamp 是 naive，假设它是 UTC
                    last_timestamp = last_timestamp.replace(tzinfo=timezone.utc)
                else:
                    # 如果已经是 aware，转换为 UTC
                    last_timestamp = last_timestamp.astimezone(timezone.utc)
            
            # 5. 过滤出新的记录（比上次更新时间更近的记录）
            new_records = []
            if last_timestamp:
                for record in all_new_records:
                    # 确保 record["timestamp"] 也是 aware UTC datetime
                    record_timestamp = record["timestamp"]
                    if record_timestamp.tzinfo is None:
                        record_timestamp = record_timestamp.replace(tzinfo=timezone.utc)
                    else:
                        record_timestamp = record_timestamp.astimezone(timezone.utc)
                    
                    if record_timestamp > last_timestamp:
                        new_records.append(record)
            else:
                # 如果没有上次更新时间，只取最新的5条记录（避免首次更新时发送太多通知）
                new_records = all_new_records[-5:]
            
            # 6. 如果有新记录，发送通知
            if new_records:
                print(f"  📨 发现 {len(new_records)} 条新记录，准备发送通知...")
                logger.info(f"钱包 {wallet_name} 有 {len(new_records)} 条新记录，准备发送通知")
                
                # 按时间由远到近发送通知
                for record_index, record in enumerate(new_records, 1):
                    print(f"    [{record_index}/{len(new_records)}] 发送通知...")
                    await self._send_notification(wallet_name, wallet_address, record, session)
                    # 每条通知之间等待1秒，避免发送过快
                    await asyncio.sleep(1)
                
                # 更新最后更新时间戳（使用最新记录的时间戳）
                wallet.last_update_timestamp = new_records[-1]["timestamp"]
                await session.commit()
                print(f"  ✅ 已发送 {len(new_records)} 条通知，并更新最后更新时间戳")
                logger.info(f"已更新钱包 {wallet_name} 的最后更新时间戳: {wallet.last_update_timestamp}")
            else:
                print(f"  ℹ️  没有新记录，无需发送通知")
                logger.debug(f"钱包 {wallet_name} 没有新记录")
            
            # 7. 更新最后更新时间戳（即使没有新记录，也更新为当前时间）
            if not wallet.last_update_timestamp:
                wallet.last_update_timestamp = datetime.now(timezone.utc)
                await session.commit()
            
            end_time = datetime.now(timezone.utc)
            duration = (end_time - start_time).total_seconds()
            print(f"  ⏱️  更新完成，总耗时: {duration:.2f} 秒")
            logger.info(f"钱包 {wallet_name} 更新完成，耗时 {duration:.2f} 秒")
            
        except Exception as e:
            logger.error(f"更新钱包 {wallet_name} 失败: {e}", exc_info=True)
            await session.rollback()
    
    async def _send_notification(self, wallet_name: str, wallet_address: str, record: dict, session: AsyncSession):
        """发送通知"""
        try:
            record_type = record["type"]
            timestamp = record["timestamp"]
            data = record["data"]
            
            # 转换为北京时间（UTC+8）
            from datetime import timedelta
            beijing_offset = timedelta(hours=8)
            beijing_time = timestamp + beijing_offset
            time_str = beijing_time.strftime("%Y-%m-%d %H:%M:%S")
            
            # 构建钱包地址链接
            wallet_url = f"https://app.pendle.finance/trade/dashboard/user/{wallet_address}"
            
            # 获取链信息（用于构建项目链接）
            chain_id = data.get("chain_id")
            chain_name = None
            if chain_id:
                chain_result = await session.execute(
                    select(ChainId).where(ChainId.id == chain_id)
                )
                chain = chain_result.scalar_one_or_none()
                if chain:
                    chain_name = chain.name
            
            if record_type == "transaction":
                # 交易记录通知
                action = data.get("action", "")
                project_name = data.get("project_name", "未知项目")
                market_address = data.get("market_address")
                amount = data.get("amount", 0)
                implied_yield = data.get("implied_yield")
                profit_usd = data.get("profit_usd", 0)
                
                # 操作类型标签
                action_labels = {
                    "buyYt": "市价买入",
                    "sellYt": "市价卖出",
                    "buyYtLimitOrder": "限价买入",
                    "sellYtLimitOrder": "限价卖出",
                    "redeemYtYield": "领取奖励",
                }
                action_label = action_labels.get(action, action)
                
                # 构建项目链接
                project_link = project_name
                if market_address:
                    chain_param = f"&chain={chain_name}" if chain_name else ""
                    project_url = f"https://app.pendle.finance/trade/markets/{market_address}/swap?view=yt{chain_param}"
                    project_link = f'<a href="{project_url}">{project_name}</a>'
                
                # 构建消息
                message = (
                    f"<b>💰 聪明钱更新</b>\n\n"
                    f"钱包: <a href=\"{wallet_url}\">{wallet_name}</a>\n"
                    f"地址: <code>{wallet_address[:10]}...{wallet_address[-8:]}</code>\n"
                    f"时间: {time_str} (北京时间)\n\n"
                    f"操作: {action_label}\n"
                    f"项目: {project_link}\n"
                )
                
                if action in ["buyYt", "sellYt", "buyYtLimitOrder", "sellYtLimitOrder"]:
                    message += f"金额: ${amount:.2f}\n"
                    if implied_yield:
                        message += f"Implied Yield: {implied_yield:.2f}%\n"
                
                if action in ["sellYt", "sellYtLimitOrder", "redeemYtYield"]:
                    message += f"利润: ${profit_usd:.2f}\n"
                
            elif record_type == "limit_order":
                # 限价订单通知
                status = data.get("status", "")
                order_type = data.get("order_type", "")
                project_name = data.get("project_name", "未知项目")
                market_address = data.get("market_address")
                volume = data.get("notional_volume_usd", 0)
                implied_yield = data.get("implied_yield")
                
                # 状态标签
                status_labels = {
                    "FILLABLE": "开启挂单",
                    "CANCELLED": "取消挂单",
                    "EXPIRED": "挂单过期",
                    "FULLY_FILLED": "挂单填充完成",
                    "EMPTY_MAKER_BALANCE": "余额不足",
                }
                status_label = status_labels.get(status, status)
                
                # 买入/卖出标签
                buy_sell_label = "买入" if order_type == "LONG_YIELD" else "卖出"
                
                # 构建项目链接
                project_link = project_name
                if market_address:
                    chain_param = f"&chain={chain_name}" if chain_name else ""
                    project_url = f"https://app.pendle.finance/trade/markets/{market_address}/swap?view=yt{chain_param}"
                    project_link = f'<a href="{project_url}">{project_name}</a>'
                
                # 构建消息
                message = (
                    f"<b>📋 限价订单更新</b>\n\n"
                    f"钱包: <a href=\"{wallet_url}\">{wallet_name}</a>\n"
                    f"地址: <code>{wallet_address[:10]}...{wallet_address[-8:]}</code>\n"
                    f"时间: {time_str} (北京时间)\n\n"
                    f"状态: {status_label}\n"
                    f"类型: {buy_sell_label}\n"
                    f"项目: {project_link}\n"
                    f"数量: ${volume:.2f} YT\n"
                )
                
                if implied_yield:
                    message += f"Implied Yield: {implied_yield:.2f}%\n"
            
            else:
                return
            
            # 发送通知
            success = await send_notification(message, parse_mode="HTML")
            if success:
                logger.debug(f"成功发送通知: {wallet_name} - {record_type}")
            else:
                logger.warning(f"发送通知失败: {wallet_name} - {record_type}")
                
        except Exception as e:
            logger.error(f"发送通知时出错: {e}", exc_info=True)


# 全局实例
smart_money_updater = SmartMoneyUpdater()

