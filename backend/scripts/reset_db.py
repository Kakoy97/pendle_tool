"""清空并重新初始化数据库脚本

警告：此操作会删除所有数据，包括：
- 所有项目记录
- 所有聪明钱记录
- 所有交易记录
- 所有限价订单记录
- 所有历史记录
- 所有分组信息（除了默认的"其他"分组）

使用方法：
    python -m scripts.reset_db
"""

import asyncio
import logging
import sys
from pathlib import Path

# 添加项目根目录到 Python 路径
backend_dir = Path(__file__).parent.parent
sys.path.insert(0, str(backend_dir))

from app.core.db import get_engine, init_models
from sqlalchemy import text

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s"
)
logger = logging.getLogger(__name__)


async def reset_database():
    """清空并重新初始化数据库"""
    try:
        # 确认操作
        print("\n" + "=" * 60)
        print("⚠️  警告：此操作将删除所有数据库数据！")
        print("=" * 60)
        confirm = input("\n确认要清空数据库吗？输入 'YES' 继续: ")
        
        if confirm != "YES":
            print("操作已取消")
            return
        
        logger.info("开始清空数据库...")
        engine = get_engine()
        
        async with engine.begin() as conn:
            # 获取所有表名
            result = await conn.execute(
                text("SELECT name FROM sqlite_master WHERE type='table' AND name NOT LIKE 'sqlite_%'")
            )
            tables = [row[0] for row in result.fetchall()]
            
            logger.info(f"找到 {len(tables)} 个表: {', '.join(tables)}")
            
            # 删除所有表
            for table in tables:
                try:
                    await conn.execute(text(f"DROP TABLE IF EXISTS {table}"))
                    logger.info(f"已删除表: {table}")
                except Exception as e:
                    logger.warning(f"删除表 {table} 失败: {e}")
            
            # 删除所有索引（除了系统索引）
            result = await conn.execute(
                text("SELECT name FROM sqlite_master WHERE type='index' AND name NOT LIKE 'sqlite_%'")
            )
            indexes = [row[0] for row in result.fetchall()]
            
            for index in indexes:
                try:
                    await conn.execute(text(f"DROP INDEX IF EXISTS {index}"))
                    logger.info(f"已删除索引: {index}")
                except Exception as e:
                    logger.warning(f"删除索引 {index} 失败: {e}")
        
        logger.info("数据库已清空，开始重新初始化...")
        
        # 重新初始化数据库
        await init_models()
        
        logger.info("✅ 数据库重置完成！")
        logger.info("数据库文件位置: ./pendle_tool.db")
        
    except Exception as e:
        logger.error(f"数据库重置失败: {e}", exc_info=True)
        sys.exit(1)


if __name__ == "__main__":
    asyncio.run(reset_database())

