"""
更新 chain_ids 表的聚合器字段

使用方法：
    python -m scripts.update_chain_aggregators
"""

import asyncio
import json
import sys
from pathlib import Path

# 添加项目根目录到路径
backend_dir = Path(__file__).parent.parent
sys.path.insert(0, str(backend_dir))

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.db import get_sessionmaker, init_models
from app.models.chain_id import ChainId


async def update_chain_aggregators():
    """更新 chain_ids 表的聚合器字段"""
    
    # 初始化数据库模型
    await init_models()
    
    # 获取 session maker
    session_maker = get_sessionmaker()
    
    # 聚合器配置
    # id 为 9745、999、80094 的聚合器字段值为 ["kyberswap"]
    # 其他的都是 ["kyberswap", "odos", "okx", "paraswap"]
    special_chain_ids = {9745, 999, 80094}
    default_aggregators = ["kyberswap"]
    normal_aggregators = ["kyberswap", "odos", "okx", "paraswap"]
    
    async with session_maker() as session:
        # 获取所有链
        result = await session.execute(select(ChainId))
        chains = result.scalars().all()
        
        updated_count = 0
        
        for chain in chains:
            if chain.id in special_chain_ids:
                aggregators = default_aggregators
            else:
                aggregators = normal_aggregators
            
            chain.set_aggregators_list(aggregators)
            updated_count += 1
            print(f"更新链 {chain.id} ({chain.name}): {aggregators}")
        
        # 提交更改
        await session.commit()
        print(f"\n已更新 {updated_count} 条链的聚合器配置")


if __name__ == "__main__":
    asyncio.run(update_chain_aggregators())

