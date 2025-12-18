"""
临时脚本：批量整理未监控项目
1. 找到"其他"分组中所有未监控的项目
2. 根据项目名称创建新分组
3. 将项目移动到对应分组
4. 将所有项目设置为监控状态
"""

import asyncio
import logging
import sys
from pathlib import Path

# 添加项目根目录到路径
backend_dir = Path(__file__).parent.parent
sys.path.insert(0, str(backend_dir))

from sqlalchemy import select
from sqlalchemy.ext.asyncio import create_async_engine, AsyncSession, async_sessionmaker

from app.models.pendle_project import PendleProject
from app.models.project_group import ProjectGroup

logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)


def extract_group_name(project_name: str) -> str:
    """
    从项目名称提取分组名称
    
    策略：
    - 提取名称中的主要代币符号（如 reUSDe -> reUSD, eETH -> eETH）
    - 如果名称包含常见代币，返回对应的分组名
    - 其他情况，使用名称本身（去除后缀如日期等）
    """
    if not project_name:
        return "其他"
    
    name_lower = project_name.lower()
    name_upper = project_name.upper()
    
    # 检查常见模式（按优先级排序）
    patterns = [
        ("reusd", "reUSD"),
        ("re-usd", "reUSD"),
        ("usde", "USDe"),
        ("eeth", "eETH"),
        ("e-eth", "eETH"),
        ("steth", "stETH"),
        ("st-eth", "stETH"),
        ("weth", "wETH"),
        ("w-eth", "wETH"),
        ("usdc", "USDC"),
        ("usdt", "USDT"),
        ("dai", "DAI"),
        ("btc", "BTC"),
        ("eth", "ETH"),
    ]
    
    for pattern, group_name in patterns:
        if pattern in name_lower:
            return group_name
    
    # 如果没有匹配到常见模式，尝试提取名称的主要部分
    # 例如 "reUSDe-2024-12-31" -> "reUSDe"
    # 或者 "PT-eETH-2024" -> "eETH"
    
    # 移除常见的后缀（日期、版本号等）
    import re
    # 移除日期格式：-2024-12-31, -20241231 等
    cleaned = re.sub(r'-\d{4}(-\d{2})?(-\d{2})?$', '', project_name)
    # 移除版本号：-v1, -v2.0 等
    cleaned = re.sub(r'-[vV]\d+(\.\d+)?$', '', cleaned)
    
    # 如果清理后的名称仍然有意义，使用它
    if cleaned and len(cleaned) > 2:
        # 如果清理后的名称很短，直接使用
        if len(cleaned) <= 15:
            return cleaned
        else:
            # 尝试提取前15个字符
            return cleaned[:15].strip()
    
    # 最后，使用原始名称（如果不太长）
    if len(project_name) <= 20:
        return project_name
    else:
        return project_name[:20].strip()


async def batch_organize_projects():
    """批量整理项目"""
    # 使用与主应用相同的数据库配置
    database_url = "sqlite+aiosqlite:///./pendle_tool.db"
    
    engine = create_async_engine(database_url, echo=False)
    async_session_maker = async_sessionmaker(engine, expire_on_commit=False)
    
    try:
        async with async_session_maker() as session:
            # 1. 查找所有未监控且分组为"其他"的项目
            result = await session.execute(
                select(PendleProject).where(
                    PendleProject.is_monitored.is_(False),
                    PendleProject.project_group == "其他"
                )
            )
            projects = result.scalars().all()
            
            logger.info(f"找到 {len(projects)} 个未监控且分组为'其他'的项目")
            
            if not projects:
                logger.info("没有需要处理的项目")
                return
            
            # 2. 按项目名称分组
            projects_by_group = {}
            for project in projects:
                group_name = extract_group_name(project.name or project.symbol or "未知")
                if group_name not in projects_by_group:
                    projects_by_group[group_name] = []
                projects_by_group[group_name].append(project)
            
            logger.info(f"将创建 {len(projects_by_group)} 个新分组: {list(projects_by_group.keys())}")
            
            # 3. 确保所有新分组在 project_groups 表中存在
            for group_name in projects_by_group.keys():
                # 检查分组是否已存在
                result = await session.execute(
                    select(ProjectGroup).where(ProjectGroup.name == group_name)
                )
                existing_group = result.scalar_one_or_none()
                
                if not existing_group:
                    # 创建新分组
                    new_group = ProjectGroup(name=group_name)
                    session.add(new_group)
                    logger.info(f"创建新分组: {group_name}")
            
            # 提交新分组
            await session.commit()
            
            # 4. 更新每个项目的分组和监控状态
            updated_count = 0
            for group_name, group_projects in projects_by_group.items():
                for project in group_projects:
                    project.project_group = group_name
                    project.is_monitored = True
                    updated_count += 1
                    logger.debug(f"更新项目: {project.name} -> 分组: {group_name}, 监控: True")
            
            # 提交所有更改
            await session.commit()
            
            logger.info(f"✓ 处理完成！")
            logger.info(f"  - 创建了 {len(projects_by_group)} 个新分组")
            logger.info(f"  - 更新了 {updated_count} 个项目的分组和监控状态")
            
            # 显示统计信息
            logger.info("\n分组统计:")
            for group_name, group_projects in sorted(projects_by_group.items()):
                logger.info(f"  {group_name}: {len(group_projects)} 个项目")
    
    except Exception as e:
        logger.error(f"处理失败: {e}", exc_info=True)
        raise
    finally:
        await engine.dispose()


if __name__ == "__main__":
    print("=" * 60)
    print("批量整理未监控项目")
    print("=" * 60)
    print("此脚本将：")
    print("1. 找到所有未监控且分组为'其他'的项目")
    print("2. 根据项目名称创建新分组")
    print("3. 将项目移动到对应分组")
    print("4. 将所有项目设置为监控状态")
    print("=" * 60)
    
    confirm = input("\n确认执行？(yes/no): ")
    if confirm.lower() != "yes":
        print("已取消")
        sys.exit(0)
    
    asyncio.run(batch_organize_projects())

