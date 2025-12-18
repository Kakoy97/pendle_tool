from functools import lru_cache
from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
        case_sensitive=False,  # 环境变量名不区分大小写
    )

    # Telegram Bot API 配置（必需）
    telegram_bot_token: str  # Bot Token，从 @BotFather 获取
    telegram_bot_chat_id: int  # 目标 Chat ID，接收通知的群组或频道 ID

    # 代理配置（可选，如果需要代理访问 Telegram）
    telegram_proxy_type: str | None = None  # mtproxy, socks5, http
    telegram_proxy_host: str | None = None
    telegram_proxy_port: int | None = None
    telegram_proxy_username: str | None = None
    telegram_proxy_password: str | None = None
    telegram_proxy_secret: str | None = None  # MTProxy 专用

    # 项目过滤配置（可选）
    # 使用 validation_alias 显式指定环境变量名，确保能从 .env 文件读取
    # 环境变量名：PROJECT_MIN_VOLUME_24H
    project_min_volume_24h: float = Field(
        default=0,
        description="最小 24h 交易量（美元），低于此值的项目会被过滤",
        validation_alias="PROJECT_MIN_VOLUME_24H",  # 显式指定环境变量名
    )

    # 数据库配置（可选，默认使用 SQLite）
    database_url: str = "sqlite+aiosqlite:///./pendle_tool.db"
    
    @classmethod
    def settings_customise_sources(
        cls,
        settings_cls,
        init_settings,
        env_settings,
        dotenv_settings,
        file_secret_settings,
    ):
        """
        自定义设置源优先级
        确保环境变量和 .env 文件都能正确读取
        """
        return (
            init_settings,
            env_settings,
            dotenv_settings,  # .env 文件
            file_secret_settings,
        )


@lru_cache
def get_settings() -> Settings:
    return Settings()


settings = get_settings()
