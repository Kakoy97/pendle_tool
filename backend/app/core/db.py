import logging
from typing import AsyncIterator

from sqlalchemy.ext.asyncio import AsyncEngine, AsyncSession, async_sessionmaker, create_async_engine
from sqlalchemy.orm import declarative_base

from app.core.config import settings

logger = logging.getLogger(__name__)


Base = declarative_base()

_engine: AsyncEngine | None = None
_SessionLocal: async_sessionmaker[AsyncSession] | None = None


def get_engine() -> AsyncEngine:
    global _engine
    if _engine is None:
        _engine = create_async_engine(settings.database_url, future=True, echo=False)
    return _engine


def get_sessionmaker() -> async_sessionmaker[AsyncSession]:
    global _SessionLocal
    if _SessionLocal is None:
        _SessionLocal = async_sessionmaker(get_engine(), expire_on_commit=False)
    return _SessionLocal


async def get_session() -> AsyncIterator[AsyncSession]:
    session_maker = get_sessionmaker()
    async with session_maker() as session:
        yield session


async def init_models() -> None:
    import app.models.message  # noqa: F401
    import app.models.pendle_project  # noqa: F401
    import app.models.project_group  # noqa: F401
    import app.models.chain_id  # noqa: F401
    import app.models.sync_log  # noqa: F401
    import app.models.project_history  # noqa: F401
    import app.models.smart_money  # noqa: F401
    import app.models.wallet_transaction  # noqa: F401
    import app.models.limit_order  # noqa: F401

    engine = get_engine()
    async with engine.begin() as conn:
        # 创建所有表
        await conn.run_sync(Base.metadata.create_all)
        
        # 检查并添加缺失的字段（用于现有数据库的迁移）
        await _migrate_pendle_projects_table(conn)
        
        # 确保"其他"分组存在
        await _ensure_default_group(conn)
        
        # 初始化 chain_ids 表数据
        await _ensure_chain_ids(conn)


async def _migrate_pendle_projects_table(conn) -> None:
    """迁移 pendle_projects 表，添加新字段"""
    from sqlalchemy import text
    
    # 检查表是否存在
    result = await conn.execute(
        text("SELECT name FROM sqlite_master WHERE type='table' AND name='pendle_projects'")
    )
    table_exists = result.scalar() is not None
    
    if not table_exists:
        return  # 表不存在，会在 create_all 中创建
    
    # 获取当前表的字段
    result = await conn.execute(text("PRAGMA table_info(pendle_projects)"))
    columns = [row[1] for row in result.fetchall()]
    
    # 添加缺失的字段
    if "project_group" not in columns:
        await conn.execute(text("ALTER TABLE pendle_projects ADD COLUMN project_group VARCHAR(255)"))
    
    if "expiry" not in columns:
        await conn.execute(text("ALTER TABLE pendle_projects ADD COLUMN expiry DATETIME"))
    
    if "chain_id" not in columns:
        await conn.execute(text("ALTER TABLE pendle_projects ADD COLUMN chain_id INTEGER"))
    
    if "tvl" not in columns:
        await conn.execute(text("ALTER TABLE pendle_projects ADD COLUMN tvl REAL"))
    
    if "trading_volume_24h" not in columns:
        await conn.execute(text("ALTER TABLE pendle_projects ADD COLUMN trading_volume_24h REAL"))
    
    if "implied_apy" not in columns:
        await conn.execute(text("ALTER TABLE pendle_projects ADD COLUMN implied_apy REAL"))
    
    if "yt_address_full" not in columns:
        await conn.execute(text("ALTER TABLE pendle_projects ADD COLUMN yt_address_full VARCHAR(255)"))
    
    if "last_monitored_state" not in columns:
        await conn.execute(text("ALTER TABLE pendle_projects ADD COLUMN last_monitored_state BOOLEAN"))
    
    if "last_transaction_check_time" not in columns:
        await conn.execute(text("ALTER TABLE pendle_projects ADD COLUMN last_transaction_check_time DATETIME"))
    
    if "last_implied_apy" not in columns:
        await conn.execute(text("ALTER TABLE pendle_projects ADD COLUMN last_implied_apy REAL"))
    
    # 创建索引（如果不存在）
    try:
        await conn.execute(
            text("CREATE INDEX IF NOT EXISTS ix_pendle_projects_project_group ON pendle_projects(project_group)")
        )
    except Exception:
        pass  # 索引可能已存在
    
    try:
        await conn.execute(
            text("CREATE INDEX IF NOT EXISTS ix_pendle_projects_expiry ON pendle_projects(expiry)")
        )
    except Exception:
        pass  # 索引可能已存在


async def _ensure_default_group(conn) -> None:
    """确保默认的"其他"分组存在"""
    from sqlalchemy import text
    
    # 检查 project_groups 表是否存在
    result = await conn.execute(
        text("SELECT name FROM sqlite_master WHERE type='table' AND name='project_groups'")
    )
    table_exists = result.scalar() is not None
    
    if not table_exists:
        return  # 表不存在，会在 create_all 中创建
    
    # 检查"其他"分组是否存在
    result = await conn.execute(
        text("SELECT COUNT(*) FROM project_groups WHERE name = '其他'")
    )
    count = result.scalar()
    
    if count == 0:
        # 插入"其他"分组
        await conn.execute(
            text("INSERT INTO project_groups (name, created_at) VALUES ('其他', datetime('now'))")
        )


async def _ensure_chain_ids(conn) -> None:
    """确保 chain_ids 表有默认数据"""
    from sqlalchemy import text
    
    # 检查 chain_ids 表是否存在
    result = await conn.execute(
        text("SELECT name FROM sqlite_master WHERE type='table' AND name='chain_ids'")
    )
    table_exists = result.scalar() is not None
    
    if not table_exists:
        return  # 表不存在，会在 create_all 中创建
    
    # 检查并添加 aggregators 字段（如果不存在）
    try:
        result = await conn.execute(
            text("PRAGMA table_info(chain_ids)")
        )
        columns = [row[1] for row in result.fetchall()]
        
        if "aggregators" not in columns:
            await conn.execute(
                text("ALTER TABLE chain_ids ADD COLUMN aggregators TEXT")
            )
    except Exception:
        pass  # 字段可能已存在
    
    # 检查并添加 smart_money.last_update_timestamp 字段（如果不存在）
    try:
        result = await conn.execute(
            text("SELECT name FROM sqlite_master WHERE type='table' AND name='smart_money'")
        )
        table_exists = result.scalar() is not None
        
        if table_exists:
            result = await conn.execute(
                text("PRAGMA table_info(smart_money)")
            )
            columns = [row[1] for row in result.fetchall()]
            
            if "last_update_timestamp" not in columns:
                await conn.execute(
                    text("ALTER TABLE smart_money ADD COLUMN last_update_timestamp DATETIME")
                )
                logger.info("已添加 smart_money.last_update_timestamp 字段")
    except Exception as e:
        logger.warning(f"添加 smart_money.last_update_timestamp 字段时出错: {e}")
        pass  # 字段可能已存在
    
    # 默认的 chain_id 数据
    default_chain_ids = [
        (1, "ethereum", "0xdac17f958d2ee523a2206206994597c13d831ec7"),
        (9745, "plasma", "0xb8ce59fc3717ada4c02eadf9682a9e934f625ebb"),
        (999, "hyperevm", "0xb88339cb7199b77e23db6e890353e22632ba630f"),
        (42161, "arbitrum", "0xfd086bc7cd5c481dcc9c85ebe478a1c0b69fcbb9"),
        (56, "bnbchain", "0x55d398326f99059ff775485246999027b3197955"),
        (8453, "base", "0xfde4c96c8593536e31f229ea8f37b2ada2699bb2"),
        (80094, "bera", "0x549943e04f40284185054145c6e4e9568c1d3241"),
        (146, "sonic", "0x6047828dc181963ba44974801ff68e538da5eaf9"),
    ]
    
    for chain_id, name, token_address in default_chain_ids:
        # 检查是否已存在
        result = await conn.execute(
            text("SELECT COUNT(*) FROM chain_ids WHERE id = :id"),
            {"id": chain_id}
        )
        count = result.scalar()
        
        if count == 0:
            # 插入数据
            await conn.execute(
                text(
                    "INSERT INTO chain_ids (id, name, token_address) VALUES (:id, :name, :token_address)"
                ),
                {"id": chain_id, "name": name, "token_address": token_address}
            )
        else:
            # 更新已存在的数据（特别是 id=1 的 name 需要更新为 ethereum）
            await conn.execute(
                text("UPDATE chain_ids SET name = :name, token_address = :token_address WHERE id = :id"),
                {"id": chain_id, "name": name, "token_address": token_address}
            )
