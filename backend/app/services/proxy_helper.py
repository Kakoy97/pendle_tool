"""代理配置辅助工具"""

import os
from typing import Optional, Tuple
from urllib.request import getproxies

from telethon.network import ConnectionTcpMTProxyRandomizedIntermediate

# 尝试导入 PySocks
try:
    import socks
    PYSOCKS_AVAILABLE = True
except ImportError:
    PYSOCKS_AVAILABLE = False


def build_telegram_client_proxy(
    proxy_type: Optional[str] = None,
    proxy_host: Optional[str] = None,
    proxy_port: Optional[int] = None,
    proxy_secret: Optional[str] = None,
) -> Tuple[Optional[type], Optional[tuple]]:
    """
    构建 Telethon 客户端所需的代理配置。
    
    返回: (connection_class, proxy_tuple)
    - connection_class: 用于 MTProxy 的连接类（类型）
    - proxy_tuple: 用于 SOCKS5/HTTP 的代理元组
    """
    connection = None
    proxy = None
    
    # 如果没有明确配置，尝试从系统代理获取
    if not proxy_type and not proxy_host:
        system_proxies = getproxies()
        if system_proxies and ('http' in system_proxies or 'https' in system_proxies):
            http_proxy = system_proxies.get('http', '') or system_proxies.get('https', '')
            if http_proxy and http_proxy.startswith('http://'):
                try:
                    proxy_url = http_proxy.replace('http://', '')
                    if ':' in proxy_url:
                        proxy_host, proxy_port_str = proxy_url.split(':')
                        proxy_port = int(proxy_port_str)
                        # 尝试使用 SOCKS5（根据诊断，端口 7890 可以作为 SOCKS5）
                        if PYSOCKS_AVAILABLE:
                            proxy = (socks.SOCKS5, proxy_host, proxy_port)
                except Exception:
                    pass
    
    # 如果明确配置了代理
    if proxy_type and proxy_host and proxy_port:
        if proxy_type.lower() == "mtproxy":
            # MTProxy 连接
            if not proxy_secret:
                raise ValueError("MTProxy 必须提供 secret")
            
            try:
                # 确保 proxy_secret 是字符串类型
                if isinstance(proxy_secret, bytes):
                    proxy_secret = proxy_secret.decode('utf-8')
                elif not isinstance(proxy_secret, str):
                    proxy_secret = str(proxy_secret)
                # 移除可能的 0x 前缀和空格
                secret_hex = proxy_secret.replace("0x", "").replace(" ", "").replace("-", "")
                secret = bytes.fromhex(secret_hex)
            except (ValueError, AttributeError, TypeError) as e:
                raise ValueError(f"MTProxy secret 格式不正确（应为十六进制字符串）: {e}")
            
            proxy_addr = proxy_host
            proxy_port_int = int(proxy_port)
            
            # 对于 MTProxy，Telethon 需要同时传递 connection 和 proxy 参数
            # proxy 参数格式：Telethon 期望 secret 是字符串格式的十六进制字符串，而不是 bytes
            # 使用清理后的十六进制字符串
            secret_hex_clean = proxy_secret.replace("0x", "").replace(" ", "").replace("-", "")
            if isinstance(secret_hex_clean, bytes):
                secret_hex_clean = secret_hex_clean.decode('utf-8')
            else:
                secret_hex_clean = str(secret_hex_clean)
            
            connection = ConnectionTcpMTProxyRandomizedIntermediate
            proxy = (proxy_addr, proxy_port_int, secret_hex_clean)
            
        elif proxy_type.lower() == "socks5":
            if not PYSOCKS_AVAILABLE:
                raise ImportError("需要安装 PySocks 以支持 SOCKS5 代理：pip install pysocks")
            
            proxy = (socks.SOCKS5, proxy_host, int(proxy_port))
            
        elif proxy_type.lower() == "http":
            if not PYSOCKS_AVAILABLE:
                raise ImportError("需要安装 PySocks 以支持 HTTP 代理：pip install pysocks")
            
            proxy = (socks.HTTP, proxy_host, int(proxy_port))
    
    return connection, proxy

