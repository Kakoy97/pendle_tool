"""定时任务"""

import logging

from app.core.db import get_session
from app.services.pendle_client import pendle_client
from app.services.pipeline import message_pipeline
from app.services.repositories.pendle_project_repository import PendleProjectRepository

logger = logging.getLogger(__name__)


async def process_messages_job() -> None:
    """处理消息并生成摘要的定时任务"""
    logger.info("开始执行消息处理任务...")
    try:
        await message_pipeline.run_once()
        logger.info("消息处理任务完成")
    except Exception as e:
        logger.error(f"处理消息时出错: {e}", exc_info=True)


async def sync_projects_job() -> None:
    """每天00:00同步项目列表的定时任务"""
    logger.info("开始执行项目同步任务...")
    
    async for session in get_session():
        try:
            repo = PendleProjectRepository(session)
            
            # 获取市场列表（已过滤过期）
            markets = await pendle_client.get_all_markets(filter_expired=True)
            
            # 尝试获取项目分组信息
            projects = None
            try:
                projects = await pendle_client.get_all_projects()
                logger.info(f"获取到 {len(projects) if projects else 0} 个项目分组信息")
            except Exception as e:
                logger.debug(f"获取项目分组信息失败（将使用名称分组）: {e}")
            
            await repo.sync_from_api(markets, projects)
            
            logger.info(f"项目同步完成: 已同步 {len(markets)} 个市场（已过滤过期项目）")
        except Exception as e:
            logger.error(f"同步项目列表失败: {e}", exc_info=True)
        finally:
            break  # 只处理一次
