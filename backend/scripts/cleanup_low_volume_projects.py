"""
清理 24hvol <= 3000 的项目

使用方式:
    python -m scripts.cleanup_low_volume_projects
"""

import asyncio
import sys
from pathlib import Path

# 添加项目根目录到路径
backend_dir = Path(__file__).parent.parent
sys.path.insert(0, str(backend_dir))

from sqlalchemy import delete, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.db import get_sessionmaker, init_models
from app.models.pendle_project import PendleProject
import logging

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)


async def cleanup_low_volume_projects():
    """清理 24hvol <= 3000 的项目"""
    SessionLocal = get_sessionmaker()
    
    async with SessionLocal() as session:
        try:
            # 查询 24hvol <= 3000 的项目（包括 NULL 值，视为 0）
            # 使用 OR 条件：trading_volume_24h IS NULL OR trading_volume_24h <= 3000
            from sqlalchemy import or_
            query = select(PendleProject).where(
                or_(
                    PendleProject.trading_volume_24h.is_(None),
                    PendleProject.trading_volume_24h <= 3000
                )
            )
            result = await session.execute(query)
            projects_to_delete = result.scalars().all()
            
            if not projects_to_delete:
                logger.info("没有找到 24hvol <= 3000 的项目")
                return
            
            logger.info(f"找到 {len(projects_to_delete)} 个 24hvol <= 3000 的项目（包括 NULL 值）:")
            for project in projects_to_delete[:10]:  # 只显示前10个
                vol_display = project.trading_volume_24h if project.trading_volume_24h is not None else "NULL"
                logger.info(f"  - {project.name} ({project.address}): 24hVOL={vol_display}")
            if len(projects_to_delete) > 10:
                logger.info(f"  ... 还有 {len(projects_to_delete) - 10} 个项目")
            
            # 删除这些项目（包括 NULL 值）
            from sqlalchemy import or_
            delete_query = delete(PendleProject).where(
                or_(
                    PendleProject.trading_volume_24h.is_(None),
                    PendleProject.trading_volume_24h <= 3000
                )
            )
            await session.execute(delete_query)
            await session.commit()
            
            logger.info(f"✅ 成功删除 {len(projects_to_delete)} 个 24hvol <= 3000 的项目")
        except Exception as e:
            await session.rollback()
            logger.error(f"清理失败: {e}", exc_info=True)
            raise


if __name__ == "__main__":
    async def main():
        # 初始化数据库模型
        await init_models()
        
        # 清理低交易量项目
        await cleanup_low_volume_projects()
    
    asyncio.run(main())

