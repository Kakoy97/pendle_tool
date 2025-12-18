"""Telegram 通知模块 - 使用 Bot API

只支持 Bot API 方式发送通知
"""

import asyncio
import logging
from typing import Optional

import httpx

from app.core.config import settings

logger = logging.getLogger(__name__)


class TelegramNotifier:
    """Telegram 通知发送器（Bot API）"""
    
    def __init__(self) -> None:
        self._bot_token: str = settings.telegram_bot_token
        self._chat_id: int = settings.telegram_bot_chat_id
        self._lock = asyncio.Lock()
        self._initialized = False
    
    async def initialize(self) -> None:
        """初始化通知器"""
        async with self._lock:
            if self._initialized:
                return
            
            logger.info(f"使用 Bot API 发送通知，Chat ID: {self._chat_id}")
            self._initialized = True
    
    async def send_message(
        self,
        message: str,
        parse_mode: Optional[str] = None,
        disable_notification: bool = False,
    ) -> bool:
        """
        发送文本消息
        
        Args:
            message: 消息内容
            parse_mode: 解析模式（'HTML' 或 'Markdown'）
            disable_notification: 是否静默发送（不通知用户）
        
        Returns:
            是否发送成功
        """
        if not self._initialized:
            await self.initialize()
        
        url = f"https://api.telegram.org/bot{self._bot_token}/sendMessage"
        
        payload = {
            "chat_id": self._chat_id,
            "text": message,
            "disable_notification": disable_notification,
        }
        
        # 添加解析模式
        if parse_mode:
            payload["parse_mode"] = parse_mode
        
        try:
            async with httpx.AsyncClient(timeout=30.0) as client:
                response = await client.post(url, json=payload)
                response.raise_for_status()
                result = response.json()
                
                if result.get("ok"):
                    logger.debug(f"成功发送 Telegram 消息到 {self._chat_id}")
                    return True
                else:
                    logger.error(f"发送 Telegram 消息失败: {result.get('description', '未知错误')}")
                    return False
        except Exception as e:
            logger.error(f"Bot API 请求失败: {e}")
            return False
    
    async def send_formatted_message(
        self,
        title: str,
        content: str,
        parse_mode: Optional[str] = "HTML",
        disable_notification: bool = False,
    ) -> bool:
        """
        发送格式化消息（带标题）
        
        Args:
            title: 消息标题
            content: 消息内容
            parse_mode: 解析模式（'HTML' 或 'Markdown'）
            disable_notification: 是否静默发送
        
        Returns:
            是否发送成功
        """
        if parse_mode == "HTML":
            message = f"<b>{title}</b>\n\n{content}"
        elif parse_mode == "Markdown":
            message = f"*{title}*\n\n{content}"
        else:
            message = f"{title}\n\n{content}"
        
        return await self.send_message(message, parse_mode, disable_notification)
    
    async def close(self) -> None:
        """关闭连接"""
        self._initialized = False


# 全局单例
_telegram_notifier: Optional[TelegramNotifier] = None


async def get_telegram_notifier() -> TelegramNotifier:
    """获取 Telegram 通知器单例"""
    global _telegram_notifier
    if _telegram_notifier is None:
        _telegram_notifier = TelegramNotifier()
        await _telegram_notifier.initialize()
    return _telegram_notifier


async def send_notification(
    message: str,
    parse_mode: Optional[str] = None,
    disable_notification: bool = False,
) -> bool:
    """
    发送通知的便捷函数
    
    Args:
        message: 消息内容
        parse_mode: 解析模式（'HTML' 或 'Markdown'）
        disable_notification: 是否静默发送
    
    Returns:
        是否发送成功
    """
    notifier = await get_telegram_notifier()
    return await notifier.send_message(message, parse_mode, disable_notification)


async def send_formatted_notification(
    title: str,
    content: str,
    parse_mode: Optional[str] = "HTML",
    disable_notification: bool = False,
) -> bool:
    """
    发送格式化通知的便捷函数
    
    Args:
        title: 消息标题
        content: 消息内容
        parse_mode: 解析模式（'HTML' 或 'Markdown'）
        disable_notification: 是否静默发送
    
    Returns:
        是否发送成功
    """
    notifier = await get_telegram_notifier()
    return await notifier.send_formatted_message(title, content, parse_mode, disable_notification)
