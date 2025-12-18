"""获取 Telegram 群聊的 Chat ID。

使用方式：
1. 确保已完成 Telegram 授权（运行过 bootstrap_telegram.py）
2. 在 backend 目录下执行：python -m scripts.get_chat_id
3. 脚本会列出你加入的所有群组和频道，显示它们的 ID 和名称
"""

import asyncio
import socket
import os
from pathlib import Path
from typing import Optional

from telethon import TelegramClient
from telethon.errors import SessionPasswordNeededError
from telethon.network import ConnectionTcpMTProxyRandomizedIntermediate

# 尝试导入 PySocks 以支持 SOCKS5 代理
try:
    import socks
    PYSOCKS_AVAILABLE = True
except ImportError:
    PYSOCKS_AVAILABLE = False


def load_telegram_config() -> tuple[int, str, str, str, str, Optional[dict]]:
    """从环境变量或 .env 文件加载 Telegram 配置。"""
    # 尝试从环境变量读取
    api_id = os.getenv("TELEGRAM_API_ID")
    api_hash = os.getenv("TELEGRAM_API_HASH")
    phone_number = os.getenv("TELEGRAM_PHONE_NUMBER")
    data_dir = os.getenv("TELEGRAM_DATA_DIR", "./.telegram")
    session_name = os.getenv("TELEGRAM_SESSION_NAME", "pendle_tool")

    # 代理配置（可选）
    proxy_type = os.getenv("TELEGRAM_PROXY_TYPE")  # http, socks5, mtproxy
    proxy_host = os.getenv("TELEGRAM_PROXY_HOST")
    proxy_port = os.getenv("TELEGRAM_PROXY_PORT")
    proxy_username = os.getenv("TELEGRAM_PROXY_USERNAME")
    proxy_password = os.getenv("TELEGRAM_PROXY_PASSWORD")
    proxy_secret = os.getenv("TELEGRAM_PROXY_SECRET")  # MTProxy 专用

    # 如果环境变量没有，尝试从 .env 文件读取
    if not all([api_id, api_hash, phone_number]):
        env_path = Path(".env")
        if env_path.exists():
            from dotenv import load_dotenv
            load_dotenv(env_path)
            api_id = api_id or os.getenv("TELEGRAM_API_ID")
            api_hash = api_hash or os.getenv("TELEGRAM_API_HASH")
            phone_number = phone_number or os.getenv("TELEGRAM_PHONE_NUMBER")
            data_dir = os.getenv("TELEGRAM_DATA_DIR", data_dir)
            session_name = os.getenv("TELEGRAM_SESSION_NAME", session_name)
            proxy_type = proxy_type or os.getenv("TELEGRAM_PROXY_TYPE")
            proxy_host = proxy_host or os.getenv("TELEGRAM_PROXY_HOST")
            proxy_port = proxy_port or os.getenv("TELEGRAM_PROXY_PORT")
            proxy_username = proxy_username or os.getenv("TELEGRAM_PROXY_USERNAME")
            proxy_password = proxy_password or os.getenv("TELEGRAM_PROXY_PASSWORD")
            proxy_secret = proxy_secret or os.getenv("TELEGRAM_PROXY_SECRET")

    # 验证必需的配置
    if not api_id:
        print("错误：未找到 TELEGRAM_API_ID")
        print("请确保：")
        print("1. 已创建 .env 文件并填入 TELEGRAM_API_ID")
        print("2. 或设置环境变量 TELEGRAM_API_ID")
        print("\n详细说明请参考：backend/SETUP_GUIDE.md")
        raise ValueError("缺少 TELEGRAM_API_ID")

    if not api_hash:
        print("错误：未找到 TELEGRAM_API_HASH")
        print("请确保：")
        print("1. 已创建 .env 文件并填入 TELEGRAM_API_HASH")
        print("2. 或设置环境变量 TELEGRAM_API_HASH")
        print("\n详细说明请参考：backend/SETUP_GUIDE.md")
        raise ValueError("缺少 TELEGRAM_API_HASH")

    if not phone_number:
        print("错误：未找到 TELEGRAM_PHONE_NUMBER")
        print("请确保：")
        print("1. 已创建 .env 文件并填入 TELEGRAM_PHONE_NUMBER")
        print("2. 或设置环境变量 TELEGRAM_PHONE_NUMBER")
        print("\n详细说明请参考：backend/SETUP_GUIDE.md")
        raise ValueError("缺少 TELEGRAM_PHONE_NUMBER")

    try:
        api_id_int = int(api_id)
    except ValueError:
        print(f"错误：TELEGRAM_API_ID 必须是数字，当前值：{api_id}")
        raise ValueError("TELEGRAM_API_ID 格式错误")

    # 构建代理配置
    proxy_config = None
    if proxy_type and proxy_host and proxy_port:
        proxy_config = {
            "proxy_type": proxy_type.lower(),
            "addr": proxy_host,
            "port": int(proxy_port),
        }
        if proxy_username:
            proxy_config["username"] = proxy_username
        if proxy_password:
            proxy_config["password"] = proxy_password
        if proxy_secret:
            proxy_config["secret"] = proxy_secret
    else:
        # 如果没有配置代理，尝试检测 Clash 默认端口
        # Clash 默认：HTTP 7890, SOCKS5 7891
        clash_socks5 = "127.0.0.1"
        clash_port = 7891
        # 简单检测：尝试连接本地 Clash SOCKS5 端口（不实际连接，只是提示）
        print("提示：未检测到代理配置")
        print(f"如果你使用 Clash，可以尝试在 .env 中添加：")
        print(f"TELEGRAM_PROXY_TYPE=socks5")
        print(f"TELEGRAM_PROXY_HOST=127.0.0.1")
        print(f"TELEGRAM_PROXY_PORT=7891")
        print()

    return api_id_int, api_hash, phone_number, data_dir, session_name, proxy_config


def ensure_data_dir(data_dir: str) -> Path:
    data_dir_path = Path(data_dir)
    data_dir_path.mkdir(parents=True, exist_ok=True)
    return data_dir_path


def test_proxy_connection(host: str, port: int, proxy_type: str = "socks5") -> bool:
    """测试代理服务器是否可达"""
    try:
        sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        sock.settimeout(3)
        result = sock.connect_ex((host, port))
        sock.close()
        if result == 0:
            print(f"✓ 代理服务器 {host}:{port} 可达")
            return True
        else:
            print(f"✗ 代理服务器 {host}:{port} 不可达（连接失败）")
            return False
    except Exception as e:
        print(f"✗ 测试代理连接时出错：{e}")
        return False


async def run() -> None:
    try:
        api_id, api_hash, phone_number, data_dir, session_name, proxy_config = load_telegram_config()
    except ValueError as e:
        return

    data_dir_path = ensure_data_dir(data_dir)
    session_path = data_dir_path / session_name

    # 配置代理（如果提供）
    connection = None
    proxy = None  # Telethon 的 proxy 参数
    
    if proxy_config:
        proxy_type = proxy_config["proxy_type"]
        if proxy_type == "mtproxy":
            # MTProxy 连接（Telegram 官方推荐）
            # 注意：connection 参数需要是类型，不是实例
            secret_hex = proxy_config.get("secret", "")
            if not secret_hex:
                print("错误：MTProxy 必须提供 secret")
                print("请在 .env 文件中配置 TELEGRAM_PROXY_SECRET")
                print("详细说明请参考：backend/MTPROXY_SETUP.md")
                raise ValueError("MTProxy secret 未提供")
            
            try:
                # 确保 secret_hex 是字符串类型
                # 打印调试信息
                print(f"调试：secret_hex 原始类型: {type(secret_hex)}")
                
                # 先转换为字符串
                if isinstance(secret_hex, bytes):
                    secret_hex = secret_hex.decode('utf-8')
                else:
                    secret_hex = str(secret_hex)
                
                # 再次确保是字符串
                if not isinstance(secret_hex, str):
                    raise TypeError(f"secret_hex 必须是字符串，当前类型: {type(secret_hex)}")
                
                print(f"调试：secret_hex 转换后类型: {type(secret_hex)}, 长度: {len(secret_hex)}")
                
                # 移除可能的 0x 前缀和空格
                secret_hex = secret_hex.replace("0x", "").replace(" ", "").replace("-", "")
                
                # 最终检查：确保是字符串
                if not isinstance(secret_hex, str):
                    raise TypeError(f"replace() 后 secret_hex 必须是字符串，当前类型: {type(secret_hex)}")
                
                # 验证 secret_hex 格式（但不转换为 bytes，因为 Telethon 期望字符串）
                # 只验证长度和格式
                if len(secret_hex) not in [32, 64]:  # 16 或 32 字节的十六进制字符串
                    print(f"警告：Secret 长度异常（{len(secret_hex)} 字符），通常应为 32 或 64 字符")
            except (ValueError, TypeError) as e:
                print(f"错误：MTProxy secret 格式不正确")
                print(f"Secret 必须是十六进制字符串（只包含 0-9 和 a-f）")
                print(f"当前值：{secret_hex[:20] if secret_hex else 'None'}...")
                print("详细说明请参考：backend/MTPROXY_SETUP.md")
                raise ValueError("MTProxy secret 格式错误") from e
            
            # 对于 MTProxy，Telethon 需要同时传递 connection 和 proxy 参数
            # proxy 参数格式：(ip, port, secret_string)
            # Telethon 期望 secret 是字符串格式的十六进制字符串，而不是 bytes
            proxy_addr = proxy_config["addr"]
            proxy_port = int(proxy_config["port"])
            
            # 使用标准的 ConnectionTcpMTProxyRandomizedIntermediate
            connection = ConnectionTcpMTProxyRandomizedIntermediate
            # secret_hex 已经是清理后的字符串格式
            proxy = (proxy_addr, proxy_port, secret_hex)
            
            print(f"使用 MTProxy 代理：{proxy_config['addr']}:{proxy_config['port']}")
            print(f"Secret 长度：{len(secret_hex)} 字符（十六进制字符串）")
        elif proxy_type == "socks5":
            # SOCKS5 代理支持（需要 PySocks）
            if not PYSOCKS_AVAILABLE:
                print("错误：检测到 SOCKS5 代理配置，但未安装 PySocks")
                print("请运行：pip install pysocks")
                print("或者使用 MTProxy 代理")
                raise ImportError("需要安装 PySocks 以支持 SOCKS5 代理")
            
            proxy_addr = proxy_config["addr"]
            proxy_port = proxy_config["port"]
            proxy_username = proxy_config.get("username")
            proxy_password = proxy_config.get("password")
            
            print(f"使用 SOCKS5 代理：{proxy_addr}:{proxy_port}")
            
            # 检查端口是否是常见的 HTTP 端口
            if proxy_port == 7890:
                print("ℹ️  提示：端口 7890 通常用于 HTTP，但 Clash 可能也支持 SOCKS5")
                print("根据诊断，端口 7890 可以作为 SOCKS5 使用")
                print()
            
            # 先测试代理服务器是否可达
            print("正在测试代理连接...")
            if not test_proxy_connection(proxy_addr, proxy_port):
                print("\n警告：无法连接到代理服务器")
                print("请检查：")
                print(f"1. Clash 是否正在运行")
                print(f"2. Allow LAN 是否已开启")
                print(f"3. SOCKS5 端口是否为 {proxy_port}（可在 Clash 设置中查看）")
                print(f"4. 防火墙是否阻止了连接")
                print("\n继续尝试连接（可能失败）...\n")
            else:
                print("代理服务器可达，但连接 Telegram 可能仍会失败")
                print("如果连接超时，请确认：")
                print("1. 使用的是 SOCKS5 端口（通常是 7891），不是 HTTP 端口（7890）")
                print("2. Clash 的 SOCKS5 代理已启用")
                print()
            
            # Telethon 支持通过 proxy 参数使用 SOCKS5
            # 格式：(socks_type, host, port) 或 (socks_type, host, port, rdns, username, password)
            if proxy_username and proxy_password:
                proxy = (
                    socks.SOCKS5,
                    proxy_addr,
                    proxy_port,
                    True,  # rdns
                    proxy_username,
                    proxy_password,
                )
            else:
                # 简单格式：(socks_type, host, port)
                proxy = (
                    socks.SOCKS5,
                    proxy_addr,
                    proxy_port,
                )
            
        elif proxy_type == "http":
            # HTTP 代理
            proxy_addr = proxy_config["addr"]
            proxy_port = proxy_config["port"]
            print(f"使用 HTTP 代理：{proxy_addr}:{proxy_port}")
            
            # 测试代理连接
            print("正在测试代理连接...")
            if not test_proxy_connection(proxy_addr, proxy_port):
                print(f"警告：无法连接到代理服务器 {proxy_addr}:{proxy_port}")
            else:
                print(f"✓ 代理服务器 {proxy_addr}:{proxy_port} 可达")
            
            # HTTP 代理使用 HTTP 类型
            if PYSOCKS_AVAILABLE:
                proxy = (
                    socks.HTTP,
                    proxy_addr,
                    proxy_port,
                )
            else:
                print("需要安装 PySocks 以支持 HTTP 代理")
                raise ImportError("需要安装 PySocks 以支持 HTTP 代理")

    # 如果没有配置代理，尝试从系统代理自动配置
    if not proxy_config:
        # 检查系统代理
        import urllib.request
        system_proxies = urllib.request.getproxies()
        if system_proxies and ('http' in system_proxies or 'https' in system_proxies):
            print(f"\n检测到系统代理：{system_proxies}")
            # 从系统代理中提取代理信息
            http_proxy = system_proxies.get('http', '') or system_proxies.get('https', '')
            if http_proxy and http_proxy.startswith('http://'):
                # 解析代理地址和端口
                try:
                    proxy_url = http_proxy.replace('http://', '')
                    if ':' in proxy_url:
                        proxy_host, proxy_port = proxy_url.split(':')
                        proxy_port = int(proxy_port)
                        
                        # 根据诊断结果，端口 7890 可以作为 SOCKS5 使用
                        # 使用 SOCKS5 比 HTTP 更可靠
                        if PYSOCKS_AVAILABLE:
                            print(f"自动使用系统代理端口 {proxy_port} 作为 SOCKS5")
                            print("（根据诊断，端口 7890 可以作为 SOCKS5 使用）")
                            proxy = (
                                socks.SOCKS5,
                                proxy_host,
                                proxy_port,
                            )
                            print("已自动配置 SOCKS5 代理，Telethon 将使用此代理连接")
                        else:
                            print("警告：需要安装 PySocks 才能使用代理")
                            print("请运行：pip install pysocks")
                except Exception as e:
                    print(f"解析系统代理失败：{e}")
                    print("建议在 .env 中手动配置代理")
            else:
                print("无法从系统代理中提取有效信息")
                print("建议在 .env 中手动配置：")
                print("TELEGRAM_PROXY_TYPE=socks5")
                print("TELEGRAM_PROXY_HOST=127.0.0.1")
                print("TELEGRAM_PROXY_PORT=7890")
        else:
            print("\n提示：未检测到代理配置和系统代理")
            print("建议在 .env 中添加 SOCKS5 代理配置：")
            print("TELEGRAM_PROXY_TYPE=socks5")
            print("TELEGRAM_PROXY_HOST=127.0.0.1")
            print("TELEGRAM_PROXY_PORT=7890")
        print()
    
    try:
        # Telethon 的 connection 参数必须是类型（class），不是实例
        # 对于 MTProxy，需要同时传递 connection 和 proxy
        # 对于 SOCKS5/HTTP，只需要 proxy
        client_kwargs = {
            "session": str(session_path),
            "api_id": api_id,
            "api_hash": api_hash,
        }
        
        if connection is not None:
            client_kwargs["connection"] = connection
            if proxy is not None:
                client_kwargs["proxy"] = proxy
        elif proxy is not None:
            # 对于 SOCKS5/HTTP，只需要 proxy
            client_kwargs["proxy"] = proxy
        
        client = TelegramClient(**client_kwargs)
        
        print("正在连接 Telegram...")
        print(f"代理配置：{proxy if proxy else '无（使用系统代理）'}")
        
        # 设置连接超时
        try:
            await asyncio.wait_for(client.connect(), timeout=15.0)
        except asyncio.TimeoutError:
            print("\n" + "=" * 60)
            print("连接超时！")
            print("=" * 60)
            print("\n根据诊断，代理服务器可达，但 Telethon 无法连接 Telegram。")
            print("这可能是 Telethon 与 Clash 代理的兼容性问题。")
            print("\n解决方案：")
            print("1. 【推荐】在 Clash 中启用真正的 SOCKS5 代理（端口 7891）")
            print("   然后在 .env 中配置：")
            print("   TELEGRAM_PROXY_TYPE=socks5")
            print("   TELEGRAM_PROXY_PORT=7891")
            print("\n2. 使用 MTProxy（最可靠，Telegram 官方推荐）")
            print("   在 .env 中配置：")
            print("   TELEGRAM_PROXY_TYPE=mtproxy")
            print("   TELEGRAM_PROXY_HOST=your.proxy.server")
            print("   TELEGRAM_PROXY_PORT=443")
            print("   TELEGRAM_PROXY_SECRET=你的secret")
            print("\n3. 手动获取 Chat ID（临时方案）")
            print("   在能访问 Telegram 的环境中查看群组信息")
            print("\n详细说明请参考：backend/FINAL_SOLUTION.md")
            print("=" * 60)
            raise
        
        if not await client.is_user_authorized():
            print("尚未授权，正在尝试登录...")
            await client.send_code_request(phone_number)
            code = input("請輸入 Telegram 發送的登入驗證碼： ")
            try:
                await client.sign_in(phone_number, code)
            except SessionPasswordNeededError:
                password = input("帳號啟用了二階段驗證，請輸入密碼： ")
                await client.sign_in(password=password)

        print("\n正在获取你的群组和频道列表...\n")
        print("=" * 60)

        # 获取所有对话（包括私聊、群组、频道）
        dialogs = await client.get_dialogs()

        # 分别筛选群组和频道
        groups = [d for d in dialogs if d.is_group]
        channels = [d for d in dialogs if d.is_channel]
        groups_and_channels = groups + channels

        if not groups_and_channels:
            print("未找到任何群组或频道。")
            return

        print(f"找到 {len(groups)} 个群组，{len(channels)} 个频道，共 {len(groups_and_channels)} 个：\n")
        
        # 先显示群组
        if groups:
            print("=" * 60)
            print("📱 群组列表（Group）：")
            print("=" * 60)
            for idx, dialog in enumerate(groups, 1):
                chat_id = dialog.id
                title = dialog.title or "（无标题）"
                username = f"@{dialog.entity.username}" if hasattr(dialog.entity, "username") and dialog.entity.username else "（无用户名）"
                
                print(f"{idx}. {title}")
                print(f"   Chat ID: {chat_id}")
                print(f"   用户名: {username}")
                print()
        
        # 再显示频道
        if channels:
            print("=" * 60)
            print("📢 频道列表（Channel）：")
            print("=" * 60)
            for idx, dialog in enumerate(channels, 1):
                chat_id = dialog.id
                title = dialog.title or "（无标题）"
                username = f"@{dialog.entity.username}" if hasattr(dialog.entity, "username") and dialog.entity.username else "（无用户名）"
                
                print(f"{idx}. {title}")
                print(f"   Chat ID: {chat_id}")
                print(f"   用户名: {username}")
                
                # 尝试获取关联的讨论群组
                try:
                    entity = dialog.entity
                    # 检查是否有讨论群组（linked_chat）
                    if hasattr(entity, 'linked_chat_id') and entity.linked_chat_id:
                        print(f"   ⚠️  这是频道，关联的讨论群组 Chat ID: {entity.linked_chat_id}")
                    # 或者尝试通过 get_entity 获取完整信息
                    try:
                        full_entity = await client.get_entity(dialog.entity)
                        if hasattr(full_entity, 'linked_chat_id') and full_entity.linked_chat_id:
                            print(f"   ⚠️  这是频道，关联的讨论群组 Chat ID: {full_entity.linked_chat_id}")
                    except:
                        pass
                except Exception as e:
                    # 如果无法获取讨论群组信息，忽略错误
                    pass
                
                print()

        print("=" * 60)
        print("\n重要提示：")
        print("- 如果群组是私密群组（无用户名），请使用上面的 Chat ID")
        print("- Chat ID 通常是负数（例如：-1001234567890）")
        print("- 频道和群组是不同的：")
        print("  * 频道（Channel）：通常是广播式的，只有管理员可以发消息")
        print("  * 群组（Group）：多人聊天，所有成员都可以发消息")
        print("- 如果频道有关联的讨论群组，请使用讨论群组的 Chat ID（不是频道的）")
        print("- 将正确的 Chat ID 填入 .env 文件的 TELEGRAM_TARGET_CHAT_ID")
        print("\n💡 建议：如果要监听群聊消息，请使用群组的 Chat ID，而不是频道的 Chat ID")
        
    except Exception as e:
        print(f"\n连接失败：{e}")
        print("\n可能的解决方案：")
        print("1. 检查网络连接")
        print("2. 如果 Telegram 在你的地区被限制，请配置代理")
        print("3. 在 .env 文件中添加代理配置（参考 SETUP_GUIDE.md）")
        print("4. 或使用 VPN/代理工具")
        raise
    finally:
        if 'client' in locals():
            await client.disconnect()


if __name__ == "__main__":
    asyncio.run(run())

