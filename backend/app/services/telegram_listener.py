import asyncio
import logging
from pathlib import Path

from telethon import TelegramClient, events

from app.core.config import settings
from app.core.db import get_sessionmaker
from app.services.proxy_helper import build_telegram_client_proxy
from app.services.repositories.message_repository import MessageRepository

logger = logging.getLogger(__name__)


class TelegramListener:
    def __init__(self) -> None:
        self._client: TelegramClient | None = None
        self._lock = asyncio.Lock()

    async def start(self) -> None:
        async with self._lock:
            if self._client and self._client.is_connected():
                return

            # 确保数据库已初始化（如果还没有）
            from app.core.db import init_models
            await init_models()

            data_dir = Path(settings.telegram_data_dir)
            data_dir.mkdir(parents=True, exist_ok=True)

            session_path = data_dir / settings.telegram_session_name
            
            # 构建代理配置
            connection, proxy = build_telegram_client_proxy(
                proxy_type=settings.telegram_proxy_type,
                proxy_host=settings.telegram_proxy_host,
                proxy_port=settings.telegram_proxy_port,
                proxy_secret=settings.telegram_proxy_secret,
            )
            
            # 创建客户端
            # 注意：Telethon 的 MTProto 协议本身有自动心跳机制（ping/pong，约每 60 秒）
            # 但 MTProxy 服务器可能设置了更短的超时时间，导致连接被断开
            client_kwargs = {
                "session": str(session_path),
                "api_id": settings.telegram_api_id,
                "api_hash": settings.telegram_api_hash,
                # 连接配置：优化连接稳定性
                "connection_retries": 5,  # 连接重试次数
                "retry_delay": 1,  # 重试延迟（秒）
                "timeout": 30,  # 连接超时（秒）
                # 注意：Telethon 默认启用自动重连，无需手动配置
                # MTProto 协议本身有心跳机制（ping/pong），约每 60 秒发送一次
            }
            
            # 对于 MTProxy，需要同时传递 connection 和 proxy
            if connection is not None:
                client_kwargs["connection"] = connection
                if proxy is not None:
                    client_kwargs["proxy"] = proxy
                logger.info(f"使用 MTProxy 代理：{settings.telegram_proxy_host}:{settings.telegram_proxy_port}")
                logger.info(f"连接配置：连接重试={client_kwargs['connection_retries']}次，超时={client_kwargs['timeout']}秒")
                logger.info(f"提示：Telethon 有自动心跳机制（约每 60 秒），如果仍频繁断开，可能是 MTProxy 服务器设置了更短的超时")
            elif proxy is not None:
                client_kwargs["proxy"] = proxy
                # proxy[0] 是 socks.SOCKS5 或 socks.HTTP
                try:
                    import socks
                    proxy_type_name = "SOCKS5" if proxy[0] == socks.SOCKS5 else "HTTP"
                except:
                    proxy_type_name = "代理"
                logger.info(f"使用 {proxy_type_name} 代理：{proxy[1]}:{proxy[2]}")
            else:
                logger.info("未配置代理，尝试直接连接（如果失败，请配置代理）")
            
            client = TelegramClient(**client_kwargs)

            await client.connect()

            if not await client.is_user_authorized():
                logger.error("Telegram 客户端尚未授权，请先执行登入流程")
                raise RuntimeError("Telegram 客户端需要人工授权，请依 README 指示先登入")

            # 注册事件处理器
            # 注意：Telegram 的超级群组 Chat ID 格式是 -100xxxxxxxxxx
            # 如果用户配置的是 -xxxxxxxxxx，需要转换为 -100xxxxxxxxxx
            target_chat_id = settings.telegram_target_chat_id
            
            # 检查并转换 Chat ID 格式（如果是超级群组）
            if target_chat_id < 0 and not str(target_chat_id).startswith('-100'):
                # 尝试转换为超级群组格式
                # 例如：-1973272550 -> -1001973272550
                potential_supergroup_id = int(f"-100{str(abs(target_chat_id))}")
                logger.info(f"检测到 Chat ID 格式可能不正确，尝试使用超级群组格式: {potential_supergroup_id}")
                # 先尝试验证这个 ID
                try:
                    test_entity = await client.get_entity(potential_supergroup_id)
                    if hasattr(test_entity, 'title'):
                        logger.info(f"验证成功，使用超级群组 Chat ID: {potential_supergroup_id} ({test_entity.title})")
                        target_chat_id = potential_supergroup_id
                except:
                    logger.warning(f"无法验证 {potential_supergroup_id}，使用原始 Chat ID: {target_chat_id}")
            
            # 如果指定了话题 ID，只监听该话题；否则监听整个群组的所有消息
            if settings.telegram_target_topic_id:
                client.add_event_handler(
                    self._handle_new_message,
                    events.NewMessage(
                        chats=[target_chat_id],
                        func=lambda e: getattr(e.message, 'reply_to', None) and 
                                      hasattr(e.message.reply_to, 'reply_to_top_id') and
                                      e.message.reply_to.reply_to_top_id == settings.telegram_target_topic_id
                    ),
                )
                logger.info(f"已注册消息监听器，目标群组 Chat ID: {target_chat_id}, 话题 ID: {settings.telegram_target_topic_id}")
            else:
                # 监听指定群组的所有消息（包括所有话题）
                client.add_event_handler(
                    self._handle_new_message,
                    events.NewMessage(chats=[target_chat_id]),
                )
                logger.info(f"已注册消息监听器，目标群组 Chat ID: {target_chat_id}（监听所有话题）")

            await client.start(phone=settings.telegram_phone_number)
            self._client = client
            
            # 验证连接状态
            me = await client.get_me()
            logger.info(f"Telegram listener 已启动，当前用户: {me.first_name} (@{me.username or '无用户名'})")
            
            # 验证目标群组/频道是否存在
            try:
                # 使用 get_entity 可以处理频道、超级群组和普通群组
                target_chat = await client.get_entity(settings.telegram_target_chat_id)
                chat_type = "频道" if getattr(target_chat, 'broadcast', False) else "超级群组" if getattr(target_chat, 'megagroup', False) else "群组"
                chat_title = getattr(target_chat, 'title', '未知')
                logger.info(f"目标 {chat_type} 验证成功: {chat_title}")
                logger.info(f"Chat ID: {settings.telegram_target_chat_id}, 类型: {chat_type}")
            except Exception as e:
                logger.warning(f"无法验证目标群组/频道 {settings.telegram_target_chat_id}: {e}")
                logger.warning("监听器仍会尝试监听，但如果 Chat ID 不正确可能无法接收消息")

    async def stop(self) -> None:
        async with self._lock:
            if self._client and self._client.is_connected():
                await self._client.disconnect()
                logger.info("Telegram listener 已停止")
            self._client = None

    async def _handle_new_message(self, event: events.NewMessage.Event) -> None:
        message = event.message
        
        # 记录所有收到的消息事件（用于调试）
        topic_id = getattr(message, 'reply_to', None)
        if topic_id and hasattr(topic_id, 'reply_to_top_id'):
            topic_id = topic_id.reply_to_top_id
        else:
            topic_id = None
        
        # 打印调试信息（INFO 级别，确保能看到）
        target_chat_id = settings.telegram_target_chat_id
        msg_chat_id = message.chat_id
        
        logger.info(f"收到消息事件: chat_id={msg_chat_id}, 配置的 Chat ID={target_chat_id}, message_id={message.id}, topic_id={topic_id}, has_text={bool(message.message)}")
        
        # 检查 Chat ID 是否匹配（支持格式转换）
        chat_id_matched = False
        if msg_chat_id == target_chat_id:
            chat_id_matched = True
        elif target_chat_id < 0 and not str(target_chat_id).startswith('-100'):
            # 如果配置的 Chat ID 不是 -100 开头，但消息是，也匹配
            potential_id = int(f"-100{str(abs(target_chat_id))}")
            if msg_chat_id == potential_id:
                logger.info(f"Chat ID 格式匹配（转换后）: {msg_chat_id} == {potential_id}")
                chat_id_matched = True
        
        if not chat_id_matched:
            logger.warning(f"Chat ID 不匹配，跳过: 消息来自 {msg_chat_id}，配置的是 {target_chat_id}")
            return
        
        if not message.message:
            logger.info(f"消息 {message.id} 没有文本内容，跳过")
            return

        sender = await event.get_sender()
        sender_username = getattr(sender, "username", None) if sender else None
        sender_name = getattr(sender, "first_name", None) or getattr(sender, "last_name", None) or "未知用户"

        # 打印接收到的消息（用于验证）
        print("\n" + "=" * 60)
        print("📨 收到新消息")
        print("=" * 60)
        print(f"发送者: {sender_username or sender_name} (ID: {message.sender_id})")
        print(f"时间: {message.date}")
        print(f"消息 ID: {message.id}")
        if topic_id:
            print(f"主题 ID: {topic_id}")
        print(f"内容:")
        print(f"  {message.message}")
        print("=" * 60 + "\n")

        session_maker = get_sessionmaker()
        async with session_maker() as session:
            repo = MessageRepository(session)
            await repo.add_message(
                chat_id=message.chat_id,
                message_id=message.id,
                sender_id=message.sender_id,
                sender_username=sender_username,
                content=message.message,
                message_date=message.date,
            )
            logger.info(f"消息已保存到数据库: {message.id}")


telegram_listener = TelegramListener()
