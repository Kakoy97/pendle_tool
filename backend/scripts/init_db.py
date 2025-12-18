"""初始化数据库脚本

用于创建数据库表和初始化默认数据
"""

import asyncio
import logging
import sys
from pathlib import Path

# 添加项目根目录到 Python 路径
backend_dir = Path(__file__).parent.parent
sys.path.insert(0, str(backend_dir))

from app.core.db import init_models

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s"
)
logger = logging.getLogger(__name__)


async def main():
    """初始化数据库"""
    try:
        logger.info("开始初始化数据库...")
        await init_models()
        logger.info("数据库初始化完成！")
        logger.info("数据库文件位置: ./pendle_tool.db")
    except Exception as e:
        logger.error(f"数据库初始化失败: {e}", exc_info=True)
        sys.exit(1)


if __name__ == "__main__":
    asyncio.run(main())

