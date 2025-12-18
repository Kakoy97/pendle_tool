"""Pendle 项目监控 API 路由"""

import logging
from datetime import datetime

from fastapi import APIRouter, Depends, HTTPException, Query
from fastapi.responses import StreamingResponse

from app.core.db import get_session
from app.models.pendle_project import PendleProject
from app.models.project_group import ProjectGroup
from app.models.chain_id import ChainId
from app.models.sync_log import SyncLog
from app.schemas.pendle_project import (
    PendleProjectListResponse,
    PendleProjectResponse,
    ToggleMonitorRequest,
)
from app.services.pendle_client import pendle_client
from app.services.repositories.pendle_project_repository import PendleProjectRepository
from sqlalchemy import delete, select
from sqlalchemy.ext.asyncio import AsyncSession

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/pendle", tags=["pendle"])


@router.get("/projects", response_model=PendleProjectListResponse)
async def get_projects(
    sync: bool = False,
    session: AsyncSession = Depends(get_session),
) -> PendleProjectListResponse:
    """
    获取所有项目列表
    
    Args:
        sync: 是否从 Pendle API 同步最新数据（默认 False）
    """
    repo = PendleProjectRepository(session)
    
    # 如果需要同步，先从 API 获取最新数据
    if sync:
        try:
            # 获取市场列表（已过滤过期）
            markets = await pendle_client.get_all_markets(filter_expired=True)
            
            # 尝试获取项目分组信息
            projects = None
            try:
                projects = await pendle_client.get_all_projects()
            except Exception as e:
                logger.debug(f"获取项目分组信息失败（将使用名称分组）: {e}")
            
            await repo.sync_from_api(markets, projects)
            # 记录同步日志
            sync_log = SyncLog(
                sync_type="pendle_projects",
                sync_time=datetime.utcnow(),
                status="success",
                message=f"成功同步 {len(markets)} 个项目",
            )
            session.add(sync_log)
            await session.commit()
            logger.info(f"已同步 {len(markets)} 个市场")
        except Exception as e:
            logger.error(f"同步项目列表失败: {e}", exc_info=True)
            # 即使同步失败，也返回现有数据
    
    # 获取监控和未监控的项目（已过滤过期）
    monitored = await repo.get_monitored(filter_expired=True)
    unmonitored = await repo.get_unmonitored(filter_expired=True)
    
    return PendleProjectListResponse(
        monitored=[PendleProjectResponse.model_validate(p) for p in monitored],
        unmonitored=[PendleProjectResponse.model_validate(p) for p in unmonitored],
    )


@router.post("/projects/{address}/monitor")
async def toggle_monitor(
    address: str,
    request: ToggleMonitorRequest,
    session: AsyncSession = Depends(get_session),
) -> PendleProjectResponse:
    """
    切换项目的监控状态
    
    Args:
        address: 项目地址
        request: 监控状态请求
    """
    repo = PendleProjectRepository(session)
    
    # 确保项目存在
    project = await repo.get_by_address(address)
    if not project:
        # 如果项目不存在，尝试从 API 获取并创建
        try:
            market_details = await pendle_client.get_market_details(address)
            if not market_details:
                raise HTTPException(status_code=404, detail=f"项目 {address} 不存在")
            
            project = await repo.create_or_update(
                address=address,
                name=market_details.get("name") or market_details.get("symbol"),
                symbol=market_details.get("symbol"),
                description=market_details.get("description"),
                extra_data=market_details,
            )
        except HTTPException:
            raise
        except Exception as e:
            logger.error(f"获取项目详情失败: {e}", exc_info=True)
            raise HTTPException(status_code=500, detail="无法获取项目信息")
    
    # 更新监控状态
    updated_project = await repo.set_monitored(address, request.is_monitored)
    if not updated_project:
        raise HTTPException(status_code=404, detail=f"项目 {address} 不存在")
    
    return PendleProjectResponse.model_validate(updated_project)


@router.post("/projects/groups")
async def create_project_group(
    group_name: str = Query(..., description="分组名称"),
    session: AsyncSession = Depends(get_session),
) -> dict:
    """
    创建新的项目分组
    
    Args:
        group_name: 分组名称
    """
    # 检查分组是否已存在
    result = await session.execute(select(ProjectGroup).where(ProjectGroup.name == group_name))
    existing = result.scalar_one_or_none()
    
    if existing:
        raise HTTPException(status_code=400, detail=f"分组 '{group_name}' 已存在")
    
    # 创建新分组
    new_group = ProjectGroup(name=group_name)
    session.add(new_group)
    await session.commit()
    await session.refresh(new_group)
    
    return {
        "success": True,
        "message": f"分组 '{group_name}' 已创建",
        "group": {"name": new_group.name, "id": new_group.id},
    }


@router.patch("/projects/{address}/group")
async def update_project_group(
    address: str,
    group_name: str = Query(..., description="新的分组名称"),
    session: AsyncSession = Depends(get_session),
) -> PendleProjectResponse:
    """
    更新项目的分组
    
    Args:
        address: 项目地址
        group_name: 新的分组名称（如果分组不存在，会自动创建）
    """
    repo = PendleProjectRepository(session)
    
    project = await repo.get_by_address(address)
    if not project:
        raise HTTPException(status_code=404, detail=f"项目 {address} 不存在")
    
    # 如果分组不存在，创建它
    result = await session.execute(select(ProjectGroup).where(ProjectGroup.name == group_name))
    existing_group = result.scalar_one_or_none()
    
    if not existing_group:
        # 创建新分组
        logger.info(f"创建新分组: {group_name}")
        new_group = ProjectGroup(name=group_name)
        session.add(new_group)
        await session.flush()  # 刷新以获取 ID
        logger.info(f"分组 '{group_name}' 已创建，ID: {new_group.id}")
    
    # 更新项目分组
    logger.info(f"更新项目 {address} 的分组为: {group_name}")
    project.project_group = group_name
    project.updated_at = datetime.utcnow()
    await session.commit()
    await session.refresh(project)
    
    logger.info(f"项目分组更新成功: {project.name} -> {group_name}")
    return PendleProjectResponse.model_validate(project)


@router.get("/chain-ids")
async def get_chain_ids(session: AsyncSession = Depends(get_session)) -> dict:
    """获取所有链 ID 列表"""
    result = await session.execute(select(ChainId).order_by(ChainId.id))
    chains = result.scalars().all()
    
    return {
        "chains": [
            {
                "id": chain.id,
                "name": chain.name,
                "token_address": chain.token_address,
            }
            for chain in chains
        ]
    }


@router.get("/projects/last-sync")
async def get_last_sync_time(session: AsyncSession = Depends(get_session)) -> dict:
    """获取最后一次同步时间"""
    result = await session.execute(
        select(SyncLog)
        .where(SyncLog.sync_type == "pendle_projects")
        .order_by(SyncLog.sync_time.desc())
        .limit(1)
    )
    last_sync = result.scalar_one_or_none()
    
    if last_sync:
        return {
            "last_sync_time": last_sync.sync_time.isoformat(),
            "status": last_sync.status,
            "message": last_sync.message,
        }
    else:
        return {
            "last_sync_time": None,
            "status": None,
            "message": None,
        }


@router.get("/projects/groups")
async def get_project_groups(session: AsyncSession = Depends(get_session)) -> dict:
    """
    获取所有项目分组列表（包括用户手动创建的空分组）
    """
    repo = PendleProjectRepository(session)
    all_projects = await repo.get_all(filter_expired=True)
    
    # 从数据库获取所有用户创建的分组（包括空分组）
    result = await session.execute(select(ProjectGroup))
    db_groups = {g.name: g for g in result.scalars().all()}
    
    logger.debug(f"从数据库获取到 {len(db_groups)} 个分组: {list(db_groups.keys())}")
    
    # 确保"其他"分组存在
    if "其他" not in db_groups:
        logger.info("创建默认分组'其他'")
        default_group = ProjectGroup(name="其他")
        session.add(default_group)
        await session.commit()
        await session.refresh(default_group)
        db_groups["其他"] = default_group
    
    # 统计每个分组的项目数量
    # 首先初始化所有数据库中的分组（包括空分组）
    groups = {}
    for group_name in db_groups.keys():
        groups[group_name] = {
            "name": group_name,
            "count": 0,
            "monitored_count": 0,
        }
    
    # 统计项目数量
    for project in all_projects:
        group = project.project_group or "其他"
        if group not in groups:
            # 如果项目的分组不在数据库中，添加到统计中（但不保存到数据库）
            # 这种情况不应该发生，因为修改分组时会自动创建
            logger.warning(f"项目 {project.name} 的分组 '{group}' 不在数据库中，添加到统计中")
            groups[group] = {
                "name": group,
                "count": 0,
                "monitored_count": 0,
            }
        groups[group]["count"] += 1
        if project.is_monitored:
            groups[group]["monitored_count"] += 1
    
    logger.debug(f"返回 {len(groups)} 个分组: {list(groups.keys())}")
    
    return {
        "groups": list(groups.values()),
        "total_groups": len(groups),
    }


@router.post("/projects/clear")
async def clear_projects(session: AsyncSession = Depends(get_session)) -> dict:
    """
    清空所有项目数据（保留分组信息）
    """
    try:
        # 删除所有项目
        result = await session.execute(delete(PendleProject))
        deleted_count = result.rowcount
        await session.commit()
        
        logger.info(f"已清空 {deleted_count} 个项目")
        
        return {
            "success": True,
            "message": f"已清空 {deleted_count} 个项目",
            "deleted_count": deleted_count,
        }
    except Exception as e:
        await session.rollback()
        logger.error(f"清空项目失败: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail=f"清空失败: {str(e)}")


@router.post("/projects/sync")
async def sync_projects(session: AsyncSession = Depends(get_session)) -> dict:
    """
    从 Pendle API 同步所有项目列表
    
    这个端点会：
    1. 从 Pendle API 获取所有市场（已过滤过期）
    2. 尝试获取项目分组信息
    3. 更新或创建本地项目记录
    4. 保持现有的监控状态
    """
    repo = PendleProjectRepository(session)
    
    try:
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
        
        # 记录同步日志
        sync_log = SyncLog(
            sync_type="pendle_projects",
            sync_time=datetime.utcnow(),
            status="success",
            message=f"成功同步 {len(markets)} 个项目",
        )
        session.add(sync_log)
        await session.commit()
        
        return {
            "success": True,
            "message": f"已同步 {len(markets)} 个市场（已过滤过期项目）",
            "count": len(markets),
        }
    except Exception as e:
        logger.error(f"同步项目列表失败: {e}", exc_info=True)
        # 记录失败的同步日志
        try:
            sync_log = SyncLog(
                sync_type="pendle_projects",
                sync_time=datetime.utcnow(),
                status="failed",
                message=f"同步失败: {str(e)}",
            )
            session.add(sync_log)
            await session.commit()
        except Exception:
            pass  # 如果记录日志失败，忽略
        
        raise HTTPException(status_code=500, detail=f"同步失败: {str(e)}")


@router.get("/projects/history")
async def get_project_history(
    limit: int = Query(30, description="返回的历史记录天数（默认 30 天）"),
    session: AsyncSession = Depends(get_session),
) -> dict:
    """
    获取项目历史记录（每日新增/删除的项目）
    
    Args:
        limit: 返回的历史记录天数（默认 30 天）
    
    Returns:
        按日期分组的历史记录
    """
    from collections import defaultdict
    from datetime import date, timedelta
    
    from app.models.project_history import ProjectHistory
    from sqlalchemy import select, func
    
    try:
        # 计算起始日期
        end_date = date.today()
        start_date = end_date - timedelta(days=limit - 1)
        
        # 查询历史记录
        query = select(ProjectHistory).where(
            ProjectHistory.record_date >= start_date,
            ProjectHistory.record_date <= end_date
        ).order_by(ProjectHistory.record_date.desc(), ProjectHistory.created_at.desc())
        
        result = await session.execute(query)
        history_records = result.scalars().all()
        
        # 按日期分组
        history_by_date = defaultdict(lambda: {"added": [], "deleted": []})
        
        # 获取所有项目的 chain_id 映射（用于生成超链接）
        from app.models.pendle_project import PendleProject
        address_to_chain_id = {}
        if history_records:
            projects_result = await session.execute(
                select(PendleProject.address, PendleProject.chain_id).where(
                    PendleProject.address.in_([r.project_address for r in history_records])
                )
            )
            address_to_chain_id = {row[0]: row[1] for row in projects_result.fetchall()}
        
        # 先收集所有记录，然后过滤脏数据（同一天同一项目既有新增又有删除的，只保留删除）
        for record in history_records:
            chain_id = address_to_chain_id.get(record.project_address)
            project_info = {
                "name": record.project_name or "未知项目",
                "address": record.project_address,
                "chain_id": chain_id
            }
            
            if record.action == "added":
                history_by_date[record.record_date]["added"].append(project_info)
            elif record.action == "deleted":
                history_by_date[record.record_date]["deleted"].append(project_info)
        
        # 清理脏数据：如果同一项目在同一天既有新增又有删除，只保留删除（删除优先级更高）
        for record_date, data in history_by_date.items():
            added_addresses = {p["address"] for p in data["added"]}
            deleted_addresses = {p["address"] for p in data["deleted"]}
            
            # 找出既在新增又在删除中的项目
            conflict_addresses = added_addresses & deleted_addresses
            
            if conflict_addresses:
                # 从新增列表中移除这些项目（只保留删除）
                data["added"] = [p for p in data["added"] if p["address"] not in conflict_addresses]
                logger.debug(f"清理脏数据：日期 {record_date}，移除了 {len(conflict_addresses)} 个冲突项目的新增记录（保留删除记录）")
        
        # 转换为列表格式，按日期倒序排列
        history_list = []
        for record_date in sorted(history_by_date.keys(), reverse=True):
            history_list.append({
                "date": record_date.isoformat(),
                "added": history_by_date[record_date]["added"],
                "deleted": history_by_date[record_date]["deleted"]
            })
        
        return {
            "success": True,
            "history": history_list,
            "total_days": len(history_list)
        }
    except Exception as e:
        logger.error(f"获取历史记录失败: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail=f"获取历史记录失败: {str(e)}")


@router.post("/projects/history/cleanup")
async def cleanup_history_duplicates(
    session: AsyncSession = Depends(get_session),
) -> dict:
    """
    清理历史记录中的脏数据（同一天同一项目既有新增又有删除的，删除新增记录，只保留删除记录）
    """
    from collections import defaultdict
    from datetime import date
    
    from app.models.project_history import ProjectHistory
    from sqlalchemy import select, delete, and_
    
    try:
        # 查询所有历史记录
        result = await session.execute(
            select(ProjectHistory).order_by(ProjectHistory.record_date, ProjectHistory.project_address)
        )
        all_records = result.scalars().all()
        
        # 按日期和地址分组，找出冲突的记录
        records_by_date_address = defaultdict(lambda: {"added": None, "deleted": None})
        
        for record in all_records:
            key = (record.record_date, record.project_address)
            if record.action == "added":
                records_by_date_address[key]["added"] = record
            elif record.action == "deleted":
                records_by_date_address[key]["deleted"] = record
        
        # 找出冲突的记录（同一天同一项目既有新增又有删除）
        conflict_records = []
        for (record_date, address), actions in records_by_date_address.items():
            if actions["added"] and actions["deleted"]:
                # 删除新增记录，保留删除记录
                conflict_records.append(actions["added"])
        
        # 删除冲突的新增记录
        deleted_count = 0
        if conflict_records:
            for record in conflict_records:
                await session.delete(record)
                deleted_count += 1
        
        await session.commit()
        
        logger.info(f"清理历史记录脏数据：删除了 {deleted_count} 条冲突的新增记录")
        
        return {
            "success": True,
            "message": f"已清理 {deleted_count} 条冲突的历史记录",
            "deleted_count": deleted_count
        }
    except Exception as e:
        await session.rollback()
        logger.error(f"清理历史记录失败: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail=f"清理失败: {str(e)}")
    except Exception as e:
        logger.error(f"获取项目历史记录失败: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail=f"获取历史记录失败: {str(e)}")


def _check_yt_value_warning(agg_result: dict, project_name: str = None):
    """
    检查 YT 价值是否异常（< $10），如果是则打印警告信息
    
    Args:
        agg_result: 聚合器结果字典
        project_name: 项目名称（可选）
    """
    yt_value_usd = agg_result.get("yt_value_usd")
    if yt_value_usd is not None and yt_value_usd < 10:
        yt_amount = agg_result.get("yt_amount")
        yt_amount_raw = agg_result.get("yt_amount_raw")
        aggregator = agg_result.get("aggregator", "unknown")
        project_info = f"[项目: {project_name}] " if project_name else ""
        logger.warning(f"⚠️ {project_info}聚合器 {aggregator} 计算的价值 ${yt_value_usd:.2f} < $10，可能存在格式化问题！")
        logger.warning(f"⚠️ YT数量: {yt_amount}, 原始 amount: {yt_amount_raw}")


async def _check_and_notify_high_value(
    agg_result: dict,
    project: PendleProject,
    chains: dict[int, ChainId] | None = None,
) -> None:
    """
    检查 YT 价值是否超过 $102，如果是则发送 Telegram 通知
    
    Args:
        agg_result: 聚合器结果字典
        project: 项目对象
        chains: 链信息字典（可选，用于获取链名称）
    """
    yt_value_usd = agg_result.get("yt_value_usd")
    if yt_value_usd is None or yt_value_usd <= 102:
        return
    
    try:
        from app.services.telegram_notifier import send_formatted_notification
        
        # 获取链名称
        chain_name = None
        if chains and project.chain_id:
            chain = chains.get(project.chain_id)
            if chain:
                chain_name = chain.name
        
        # 构建跳转链接
        chain_param = ""
        if chain_name:
            chain_param = f"&chain={chain_name}"
        
        url = f"https://app.pendle.finance/trade/markets/{project.address}/swap?view=yt{chain_param}"
        
        # 构建通知消息
        aggregator = agg_result.get("aggregator", "unknown")
        yt_amount = agg_result.get("yt_amount", 0)
        
        message = (
            f"💰 <b>高价值兑换机会</b>\n\n"
            f"项目: <code>{project.name or project.address}</code>\n"
            f"聚合器: {aggregator}\n"
            f"100 USDT 可兑换 YT 价值: <b>${yt_value_usd:.2f}</b>\n"
            f"YT 数量: {yt_amount:.4f}\n\n"
            f"🔗 <a href=\"{url}\">查看详情</a>"
        )
        
        # 发送通知
        success = await send_formatted_notification(
            title="🚀 价格提醒",
            content=message,
            parse_mode="HTML"
        )
        
        if success:
            logger.info(f"✅ 已发送高价值通知: {project.name} - ${yt_value_usd:.2f}")
        else:
            logger.warning(f"⚠️ 发送高价值通知失败: {project.name} - ${yt_value_usd:.2f}")
            
    except Exception as e:
        logger.error(f"发送高价值通知时出错: {e}", exc_info=True)


def _process_convert_result(convert_result: dict, requested_aggregators: list[str]) -> list[dict]:
    """
    处理价格转换 API 的返回结果
    
    Args:
        convert_result: API 返回的结果
        requested_aggregators: 请求的聚合器列表
    
    Returns:
        聚合器结果列表
    """
    results = []
    
    # 按聚合器分组处理结果
    aggregator_routes = {}
    
    for route in convert_result.get("routes", []):
        route_data = route.get("data", {})
        aggregator_type = route_data.get("aggregatorType", "unknown")
        
        if aggregator_type not in aggregator_routes:
            aggregator_routes[aggregator_type] = []
        aggregator_routes[aggregator_type].append(route)
    
    # 记录返回的聚合器类型，用于调试
    returned_aggregators = list(aggregator_routes.keys())
    logger.info(f"API 返回的聚合器类型: {returned_aggregators}, 请求的聚合器: {requested_aggregators}")
    
    # 对每个请求的聚合器，找到 outputs[0].amount 最大的路由
    for aggregator in requested_aggregators:
        # 匹配聚合器名称（不区分大小写）
        aggregator_lower = aggregator.lower()
        matched_routes = []
        matched_agg_type = None
        
        for agg_type, routes in aggregator_routes.items():
            agg_type_lower = agg_type.lower().replace("_", "").replace("-", "")
            if agg_type_lower == aggregator_lower:
                matched_routes = routes
                matched_agg_type = agg_type
                break
        
        # 如果没有找到匹配的路由，说明该聚合器没有返回结果
        if not matched_routes:
            logger.warning(f"聚合器 {aggregator} 在 API 响应中未找到（可能因为限流、无报价或其他原因）")
            results.append({
                "aggregator": aggregator,
                "error": f"API 未返回该聚合器的结果（返回的聚合器: {returned_aggregators}）",
            })
            continue
        
        max_amount = None
        max_route = None
        
        for route in matched_routes:
            outputs = route.get("outputs", [])
            if outputs and len(outputs) > 0:
                amount_str = outputs[0].get("amount")
                if amount_str:
                    try:
                        amount = int(amount_str)
                        if max_amount is None or amount > max_amount:
                            max_amount = amount
                            max_route = route
                    except (ValueError, TypeError):
                        pass
        
        if max_amount is not None:
            # 打印原始 amount 值用于调试
            amount_str = str(max_amount)
            amount_digits = len(amount_str)
            logger.info(f"📊 [原始数据] 聚合器 {aggregator}: amount={max_amount}, 位数={amount_digits}")
            print(f"📊 [原始数据] 聚合器 {aggregator}: amount={max_amount}, 位数={amount_digits}")
            
            # 根据 amount 位数确定应该使用的小数位数
            # 规则：
            # - 23位 -> 5位整数（使用 18 位小数：23-18=5）
            # - 22位 -> 4位整数（使用 18 位小数：22-18=4）
            # - 19位 -> 1位整数（使用 18 位小数：19-18=1）
            # - 18位 -> 0位整数（使用 18 位小数：18-18=0）
            # - 12位 -> 6位整数（使用 6 位小数：12-6=6）
            # - 11位 -> 5位整数（使用 6 位小数：11-6=5）
            # - 10位 -> 4位整数（使用 6 位小数：10-6=4）
            # - 8位 -> 0位整数（使用 8 位小数：8-8=0）
            # - 其他位数 >= 18 的，使用 18 位小数
            # - 其他位数 < 18 的，根据位数推断合理的小数位数
            
            if amount_digits >= 18:
                # 18位及以上，统一使用 18 位小数
                decimals = 18
            elif amount_digits == 12:
                # 12位，使用 6 位小数（得到 6 位整数）
                decimals = 6
            elif amount_digits == 11:
                # 11位，使用 6 位小数（得到 5 位整数）
                decimals = 6
            elif amount_digits == 10:
                # 10位，使用 6 位小数（得到 4 位整数）
                decimals = 6
            elif amount_digits == 8:
                # 8位，使用 8 位小数（得到 0 位整数）
                decimals = 8
            else:
                # 其他位数，尝试推断合理的小数位数
                # 优先尝试使结果在合理范围内（0.001 到 10000）
                decimals = 18  # 默认值
                for test_decimals in [18, 8, 6]:
                    test_amount = max_amount / 10**test_decimals
                    if 0.001 <= test_amount <= 10000:
                        decimals = test_decimals
                        break
            
            # 转换为可读格式
            yt_amount = max_amount / 10**decimals
            expected_integer_digits = amount_digits - decimals
            
            # 打印转换后的结果用于调试
            logger.info(f"📊 [转换结果] 聚合器 {aggregator}: 使用 {decimals} 位小数, YT数量={yt_amount}, 预期整数位数={expected_integer_digits}")
            print(f"📊 [转换结果] 聚合器 {aggregator}: 使用 {decimals} 位小数, YT数量={yt_amount}, 预期整数位数={expected_integer_digits}")
            
            # 移除旧的修正逻辑，直接使用根据规则计算的结果
            if False:  # 禁用旧的修正逻辑
                logger.info(f"🔍 [调试] 检测到异常 YT 数量: 原始 amount={max_amount} ({amount_digits} 位), 使用 {decimals} 位小数得到 {yt_amount}, 预期整数位数={expected_integer_digits}")
                # 尝试其他常见的小数位数：从大到小尝试（18, 17, 16, ..., 8, 7, 6）
                found_decimals = None
                best_decimals = decimals
                best_amount = yt_amount
                
                # 根据原始 amount 位数和原始结果，决定优先选择的范围
                # 如果原始 amount 位数 <= 8 且原始结果 < 0.001，优先选择使结果在 0.001 到 1 之间的小数位数（0 位整数）
                # 如果原始 amount 位数 >= 18 且原始结果在 1 到 10 之间，优先选择使结果在 0.001 到 1 之间的小数位数（0 位整数，使用 18 位小数）
                # 如果原始 amount 位数 >= 9 且 < 18，且原始结果 < 1，优先选择使结果在 1 到 10000 之间的小数位数（1-5 位整数）
                # 如果原始 amount 位数 >= 10 且 < 18，且原始结果在 1 到 10 之间，优先选择使结果在 100 到 10000 之间的小数位数（更大的整数）
                prefer_small_range_0_int = (amount_digits <= 8 and original_yt_amount < 0.001) or (amount_digits >= 18 and 1 <= original_yt_amount <= 10)
                prefer_large_range = (amount_digits >= 9 and amount_digits < 18 and original_yt_amount < 1)
                prefer_very_large_range = (amount_digits >= 10 and amount_digits < 18 and 1 <= original_yt_amount <= 10)
                
                for test_decimals in range(18, 5, -1):  # 从 18 到 6
                    test_amount = max_amount / 10**test_decimals
                    expected_int_digits = amount_digits - test_decimals
                    logger.debug(f"🔍 [调试] 尝试 {test_decimals} 位小数: 结果={test_amount}, 预期整数位数={expected_int_digits}")
                    # 如果结果在合理范围内（0.001 到 10000），且预期整数位数 >= 0
                    if 0.001 <= test_amount <= 10000 and expected_int_digits >= 0:
                        # 如果原始 amount 位数 <= 8 且原始结果 < 0.001，或 >= 18 且原始结果在 1-10 之间，优先选择使结果在 0.001 到 1 之间的小数位数（0 位整数）
                        if prefer_small_range_0_int and 0.001 <= test_amount < 1 and expected_int_digits == 0:
                            found_decimals = test_decimals
                            yt_amount = test_amount
                            logger.info(f"✅ 检测到异常 YT 数量（使用 {decimals} 位小数得到 {original_yt_amount}），修正为使用 {test_decimals} 位小数，结果: {yt_amount}")
                            break
                        # 如果原始 amount 位数 >= 10 且 < 18，且原始结果在 1 到 10 之间，优先选择使结果在 100 到 10000 之间的小数位数（更大的整数）
                        elif prefer_very_large_range and 100 <= test_amount <= 10000 and 2 <= expected_int_digits <= 5:
                            found_decimals = test_decimals
                            yt_amount = test_amount
                            logger.info(f"✅ 检测到异常 YT 数量（使用 {decimals} 位小数得到 {original_yt_amount}），修正为使用 {test_decimals} 位小数，结果: {yt_amount}")
                            break
                        # 如果原始 amount 位数 >= 9 且 < 18，且原始结果 < 1，优先选择使结果在 1 到 10000 之间的小数位数（1-5 位整数）
                        elif prefer_large_range and 1 <= test_amount <= 10000 and 1 <= expected_int_digits <= 5:
                            found_decimals = test_decimals
                            yt_amount = test_amount
                            logger.info(f"✅ 检测到异常 YT 数量（使用 {decimals} 位小数得到 {original_yt_amount}），修正为使用 {test_decimals} 位小数，结果: {yt_amount}")
                            break
                        # 如果不在优先范围内，但预期整数位数在 1-5 之间，也认为是合理的（用于其他情况）
                        elif not prefer_small_range_0_int and not prefer_large_range and not prefer_very_large_range and 1 <= expected_int_digits <= 5:
                            found_decimals = test_decimals
                            yt_amount = test_amount
                            logger.info(f"✅ 检测到异常 YT 数量（使用 {decimals} 位小数得到 {original_yt_amount}），修正为使用 {test_decimals} 位小数，结果: {yt_amount}")
                            break
                        # 记录最接近合理范围的值
                        elif expected_int_digits >= 0:
                            if abs(test_amount - 100) < abs(best_amount - 100):
                                best_amount = test_amount
                                best_decimals = test_decimals
                
                if found_decimals:
                    decimals = found_decimals
                    logger.info(f"✅ 成功修正：使用 {decimals} 位小数，YT 数量: {yt_amount}（原始: {original_yt_amount}）")
                elif best_decimals != decimals:
                    # 如果没找到完全符合的，使用最接近的值
                    decimals = best_decimals
                    yt_amount = best_amount
                    logger.info(f"⚠️ 使用最接近合理范围的小数位数 {decimals}，YT 数量: {yt_amount}（原始: {original_yt_amount}）")
                else:
                    # 如果都没找到合适的，但对于 18 位数字且结果在 1-10 之间，强制使用 18 位小数
                    if amount_digits >= 18 and 1 <= original_yt_amount <= 10:
                        decimals = 18
                        yt_amount = max_amount / 10**18
                        logger.warning(f"⚠️ 强制使用 18 位小数修正：原始 amount: {max_amount}，修正后 YT 数量: {yt_amount}")
                    else:
                        # 如果都没找到合适的，记录警告但继续使用原始值
                        logger.warning(f"⚠️ 无法确定正确的小数位数，原始 amount: {max_amount}，使用 {decimals} 位小数得到: {yt_amount}")
            
            # 如果 YT 数量为 0（原始 amount 为 0），打印返回数据用于排查
            # 注意：检查原始 max_amount 是否为 0，而不是转换后的 yt_amount
            # 因为小数量除以 10**18 后会非常小，可能被误判为 0
            if max_amount == 0:
                import json
                logger.warning(f"⚠️ 聚合器 {aggregator} 返回的 YT 数量为 0（原始 amount: {max_amount}）")
                logger.warning(f"⚠️ 匹配的路由数量: {len(matched_routes)}")
                logger.warning(f"⚠️ 完整的 convert_result 数据: {json.dumps(convert_result, indent=2, ensure_ascii=False)}")
                print(f"⚠️ [调试] 聚合器 {aggregator} YT数量为0（原始amount为0），完整返回数据:")
                print(json.dumps(convert_result, indent=2, ensure_ascii=False))
            results.append({
                "aggregator": aggregator,
                "yt_amount": yt_amount,
                "yt_amount_raw": str(max_amount),
                "effective_apy": max_route.get("data", {}).get("effectiveApy") if max_route else None,
                "implied_apy": max_route.get("data", {}).get("impliedApy", {}).get("after") if max_route else None,
                "price_impact": max_route.get("data", {}).get("priceImpact") if max_route else None,
                "yt_value_usd": None,  # 将在调用处计算
            })
        else:
            results.append({
                "aggregator": aggregator,
                "error": "无法从响应中提取 YT 数量",
            })
    
    # 如果部分聚合器没有返回结果，记录警告
    missing_aggregators = set(agg.lower() for agg in requested_aggregators) - {agg.lower() for agg in returned_aggregators}
    if missing_aggregators:
        logger.warning(f"部分聚合器未返回结果: {missing_aggregators}，可能原因：API 限流、聚合器无报价、或网络问题")
    
    return results


@router.post("/projects/test-prices")
async def test_project_prices(
    limit: int = Query(3, description="测试的项目数量（默认 3）"),
    session: AsyncSession = Depends(get_session),
) -> dict:
    """
    测试监控项目的价格转换
    
    对前 N 个监控的项目进行价格测试，测试 100 USDT 能兑换多少 YT
    
    Args:
        limit: 测试的项目数量（默认 3）
    """
    from app.services.price_test_client import price_test_client
    from app.models.chain_id import ChainId
    
    repo = PendleProjectRepository(session)
    
    # 获取监控的项目（限制数量）
    monitored_projects = await repo.get_monitored(filter_expired=True)
    projects_to_test = list(monitored_projects)[:limit]
    
    if not projects_to_test:
        return {
            "success": False,
            "message": "没有监控的项目",
            "results": [],
        }
    
    # 获取所有链信息
    chain_result = await session.execute(select(ChainId))
    chains = {chain.id: chain for chain in chain_result.scalars().all()}
    
    results = []
    
    for project_idx, project in enumerate(projects_to_test):
        # 项目之间添加延迟，避免请求过快
        if project_idx > 0:
            import asyncio
            await asyncio.sleep(3)  # 每个项目之间延迟 3 秒
        
        try:
            # 获取项目的 chain_id 和 YT 地址
            if not project.chain_id:
                logger.warning(f"项目 {project.name} 没有 chain_id，跳过")
                results.append({
                    "project_name": project.name,
                    "project_address": project.address,
                    "success": False,
                    "error": "项目没有 chain_id",
                })
                continue
            
            # 获取链的代币地址（USDT 地址）
            chain = chains.get(project.chain_id)
            if not chain or not chain.token_address:
                logger.warning(f"链 {project.chain_id} 没有代币地址，跳过")
                results.append({
                    "project_name": project.name,
                    "project_address": project.address,
                    "success": False,
                    "error": f"链 {project.chain_id} 没有代币地址",
                })
                continue
            
            tokens_in = chain.token_address
            
            # 获取聚合器列表（暂时只使用 kyberswap）
            aggregators_list = ["kyberswap"]  # 强制只使用 kyberswap
            
            # 获取 YT 地址（优先使用 yt_address_full，否则从 extra_data 提取）
            import json
            yt_address = None
            yt_address_full = None  # 用于价格查询 API 的完整格式
            
            # 优先使用 yt_address_full 字段
            if project.yt_address_full:
                yt_address_full = project.yt_address_full
                # 提取纯地址用于兑换 API
                if "-" in yt_address_full:
                    yt_address = yt_address_full.split("-", 1)[1]
                else:
                    yt_address = yt_address_full
            elif project.extra_data:
                # 回退到从 extra_data 提取
                try:
                    extra_data = json.loads(project.extra_data)
                    yt_raw = extra_data.get("yt")
                    if yt_raw:
                        if isinstance(yt_raw, str) and "-" in yt_raw:
                            yt_address_full = yt_raw
                            yt_address = yt_raw.split("-", 1)[1]
                        else:
                            # 如果是纯地址，组合成完整格式
                            if project.chain_id:
                                yt_address_full = f"{project.chain_id}-{yt_raw}"
                            else:
                                yt_address_full = yt_raw
                            yt_address = yt_raw
                except (json.JSONDecodeError, KeyError, AttributeError) as e:
                    logger.warning(f"无法从 extra_data 提取 YT 地址: {e}")
            
            if not yt_address or not yt_address_full:
                logger.warning(f"项目 {project.name} 没有 YT 地址，跳过")
                results.append({
                    "project_name": project.name,
                    "project_address": project.address,
                    "success": False,
                    "error": "项目没有 YT 地址",
                })
                continue
            
            # 先请求 YT 价格 API（每个项目只请求一次）
            from app.services.assets_price_client import assets_price_client
            import asyncio
            import time
            from datetime import datetime
            project_start_time = time.time()
            start_time_str = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
            logger.info(f"🚀 [项目: {project.name}] 请求开始 - {start_time_str}")
            print(f"🚀 [项目: {project.name}] 请求开始 - {start_time_str}")  # 同时打印到控制台
            start_time = time.time()
            
            yt_price = None
            try:
                logger.info(f"📊 [项目: {project.name}] 开始查询 YT 价格（每个项目只请求一次）")
                logger.info(f"📊 请求参数: ids={yt_address_full}, chain_id={project.chain_id}, type=YT")
                price_result = await assets_price_client.get_assets_prices(
                    ids=yt_address_full,
                    chain_id=project.chain_id,
                    asset_type="YT",
                )
                # 解析价格数据（API 返回格式：{"prices": {"1-0x...": 0.9989, ...}, ...}）
                logger.info(f"🔍 价格 API 响应类型: {type(price_result)}")
                logger.info(f"🔍 价格 API 响应内容: {price_result}")
                
                yt_price = None
                
                if isinstance(price_result, dict):
                    # API 返回格式：{"prices": {"1-0x...": 0.9989, ...}, ...}
                    if "prices" in price_result:
                        prices_dict = price_result["prices"]
                        logger.info(f"✅ 从 'prices' 字段获取价格字典: {prices_dict}")
                        if isinstance(prices_dict, dict) and yt_address_full in prices_dict:
                            yt_price = float(prices_dict[yt_address_full])
                            logger.info(f"✅✅✅ 成功从 prices['{yt_address_full}'] 获取价格: {yt_price}")
                        else:
                            logger.warning(f"⚠️ prices 字典中没有找到键 '{yt_address_full}'，可用键: {list(prices_dict.keys()) if isinstance(prices_dict, dict) else 'N/A'}")
                    # 兼容其他可能的格式
                    elif yt_address_full in price_result:
                        price_data = price_result[yt_address_full]
                        logger.info(f"✅ 从键 '{yt_address_full}' 获取价格数据: {price_data}")
                        if isinstance(price_data, (int, float)):
                            yt_price = float(price_data)
                        elif isinstance(price_data, str):
                            try:
                                yt_price = float(price_data)
                            except (ValueError, TypeError):
                                pass
                    elif "price" in price_result:
                        price_data = price_result["price"]
                        logger.info(f"✅ 从键 'price' 获取价格数据: {price_data}")
                        if isinstance(price_data, (int, float)):
                            yt_price = float(price_data)
                        elif isinstance(price_data, str):
                            try:
                                yt_price = float(price_data)
                            except (ValueError, TypeError):
                                pass
                elif isinstance(price_result, list) and len(price_result) > 0:
                    # 如果是列表，取第一个元素
                    price_data = price_result[0]
                    logger.info(f"✅ 从列表第一个元素获取价格数据: {price_data}")
                    if isinstance(price_data, dict):
                        yt_price = price_data.get("price") or price_data.get("usd") or price_data.get("value")
                        if yt_price is None:
                            # 尝试查找所有数字值
                            for k, v in price_data.items():
                                if isinstance(v, (int, float)):
                                    yt_price = float(v)
                                    logger.info(f"✅ 从列表元素字典键 '{k}' 获取价格: {yt_price}")
                                    break
                                elif isinstance(v, str):
                                    try:
                                        yt_price = float(v)
                                        logger.info(f"✅ 从列表元素字典键 '{k}' 字符串转换获取价格: {yt_price}")
                                        break
                                    except (ValueError, TypeError):
                                        pass
                    elif isinstance(price_data, (int, float)):
                        yt_price = float(price_data)
                    elif isinstance(price_data, str):
                        try:
                            yt_price = float(price_data)
                        except (ValueError, TypeError):
                            pass
                
                if yt_price:
                    logger.info(f"✅✅✅ 成功获取到 YT 价格: ${yt_price}")
                else:
                    logger.error(f"❌❌❌ 无法从价格 API 响应中提取价格")
                    logger.error(f"响应类型: {type(price_result)}")
                    logger.error(f"响应内容: {price_result}")
                    logger.error(f"YT 地址: {yt_address_full}")
                    logger.error(f"链 ID: {project.chain_id}")
            except Exception as e:
                logger.warning(f"查询 YT 价格失败: {e}，继续执行兑换测试")
            
            # 价格 API 请求完成，现在开始请求聚合器（聚合器只请求 YT 数量，不请求价格）
            logger.info(f"📊 [项目: {project.name}] 价格查询完成，YT价格: ${yt_price if yt_price else 'None'}")
            logger.info(f"📊 [项目: {project.name}] 开始请求聚合器（只请求 YT 数量，不请求价格）")
            
            # 只使用 kyberswap 聚合器
            aggregator_results = []
            
            # 计算总延迟时间
            # 单个聚合器：价格api+单个聚合器api请求，控制在30s（可以小于30s，但不要大于30s）
            price_api_time = time.time() - start_time
            
            # 请求 kyberswap（只请求 YT 数量）
            try:
                logger.info(f"🔄 [项目: {project.name}] 请求聚合器 kyberswap（只请求 YT 数量）")
                convert_result = await price_test_client.test_convert(
                    chain_id=project.chain_id,
                    tokens_in=tokens_in,
                    tokens_out=yt_address,
                    amounts_in=100000000,  # 100 USDT (6 decimals)
                    aggregators="kyberswap",
                )
                agg_results = _process_convert_result(convert_result, ["kyberswap"])
                # 计算 YT 价值
                for agg_result in agg_results:
                    yt_amount = agg_result.get("yt_amount")
                    # 如果 YT 数量为 0，打印详细信息用于排查
                    if yt_amount == 0 or (yt_amount is not None and abs(yt_amount) < 1e-10):
                        import json
                        logger.warning(f"⚠️ [项目: {project.name}] 聚合器 {agg_result.get('aggregator')} 返回的 YT 数量为 0")
                        logger.warning(f"⚠️ 完整的 convert_result 数据: {json.dumps(convert_result, indent=2, ensure_ascii=False)}")
                        print(f"⚠️ [调试] [项目: {project.name}] 聚合器 {agg_result.get('aggregator')} YT数量为0，完整返回数据:")
                        print(json.dumps(convert_result, indent=2, ensure_ascii=False))
                    if yt_amount is not None and yt_price is not None:
                        agg_result["yt_value_usd"] = yt_amount * yt_price
                        logger.info(f"✅ 计算价值: {agg_result['aggregator']} - YT数量: {yt_amount}, YT价格: ${yt_price}, 价值: ${agg_result['yt_value_usd']}")
                        # 检查价值是否异常（< $10）
                        _check_yt_value_warning(agg_result, project.name)
                        # 检查价值是否超过 $102，如果是则发送通知
                        await _check_and_notify_high_value(agg_result, project, chains)
                    else:
                        logger.warning(f"⚠️ 无法计算 {agg_result['aggregator']} 的价值 - YT数量: {yt_amount}, YT价格: {yt_price}")
                        agg_result["yt_value_usd"] = None
                aggregator_results.extend(agg_results)
                
                # 价格测试部分控制在30秒内（test_project_prices_stream不调用V5 API，但保持一致性）
                elapsed = time.time() - start_time
                if elapsed >= 30:
                    logger.warning(f"⚠️ [项目: {project.name}] 价格测试耗时超过30秒（{elapsed:.2f}秒），跳过剩余处理")
                elif elapsed < 8:
                    # 如果完成得太快（少于8秒），等待到8秒
                    await asyncio.sleep(8 - elapsed)
                    logger.info(f"✅ [项目: {project.name}] 价格测试完成，耗时: {elapsed:.2f}秒，等待到8秒后返回")
                else:
                    logger.info(f"✅ [项目: {project.name}] 价格测试完成，耗时: {elapsed:.2f}秒（在8-30秒范围内）")
            except Exception as e:
                logger.error(f"kyberswap 请求失败: {e}")
                aggregator_results.append({
                    "aggregator": "kyberswap",
                    "error": str(e),
                })
            
            # 注释掉其他聚合器的请求逻辑
            if False:  # 暂时禁用其他聚合器
                try:
                    # 如果只有单个聚合器（kyberswap），已经处理完成
                    # 如果有多个聚合器，需要控制总时间在45s
                    elapsed = time.time() - start_time
                    if elapsed < 3:
                        await asyncio.sleep(3 - elapsed)  # 至少延迟3秒
                    
                    logger.info(f"🔄 [项目: {project.name}] 合并请求其他聚合器: {other_aggregators}（只请求 YT 数量）")
                    convert_result = await price_test_client.test_convert(
                        chain_id=project.chain_id,
                        tokens_in=tokens_in,
                        tokens_out=yt_address,
                        amounts_in=100000000,  # 100 USDT (6 decimals)
                        aggregators=other_aggregators,  # 其他聚合器列表
                    )
                    agg_results = _process_convert_result(convert_result, other_aggregators)
                    # 计算 YT 价值
                    for agg_result in agg_results:
                        yt_amount = agg_result.get("yt_amount")
                        if yt_amount is not None and yt_price is not None:
                            agg_result["yt_value_usd"] = yt_amount * yt_price
                            logger.info(f"✅ 计算价值: {agg_result['aggregator']} - YT数量: {yt_amount}, YT价格: ${yt_price}, 价值: ${agg_result['yt_value_usd']}")
                            # 检查价值是否异常（< $10）
                            _check_yt_value_warning(agg_result, project.name)
                        else:
                            logger.warning(f"⚠️ 无法计算 {agg_result['aggregator']} 的价值 - YT数量: {yt_amount}, YT价格: {yt_price}")
                            agg_result["yt_value_usd"] = None
                    aggregator_results.extend(agg_results)
                    
                    # 控制总时间在45s（多个聚合器）
                    elapsed = time.time() - start_time
                    if elapsed < 45:
                        await asyncio.sleep(45 - elapsed)
                        logger.info(f"多个聚合器请求完成，总耗时控制在45s")
                except Exception as e:
                    logger.error(f"其他聚合器请求失败: {e}")
                    # 如果合并请求失败，回退到逐个请求
                    logger.warning(f"合并请求失败，回退到逐个请求: {e}")
                    
                    for idx, aggregator in enumerate(other_aggregators):
                        if idx > 0:
                            await asyncio.sleep(5)  # 延迟 5 秒
                        
                        try:
                            convert_result = await price_test_client.test_convert(
                                chain_id=project.chain_id,
                                tokens_in=tokens_in,
                                tokens_out=yt_address,
                                amounts_in=100000000,  # 100 USDT (6 decimals)
                                aggregators=aggregator,
                            )
                            agg_results = _process_convert_result(convert_result, [aggregator])
                            # 计算 YT 价值
                            for agg_result in agg_results:
                                if agg_result.get("yt_amount") and yt_price:
                                    agg_result["yt_value_usd"] = agg_result["yt_amount"] * yt_price
                                    # 检查价值是否异常（< $10）
                                    _check_yt_value_warning(agg_result, project.name)
                                    # 检查价值是否超过 $102，如果是则发送通知
                                    await _check_and_notify_high_value(agg_result, project, chains)
                            aggregator_results.extend(agg_results)
                        except Exception as e2:
                            logger.error(f"测试聚合器 {aggregator} 失败: {e2}")
                            aggregator_results.append({
                                "aggregator": aggregator,
                                "error": str(e2),
                            })
                    
                    # 回退到逐个请求后，也控制总时间在30s
                    elapsed = time.time() - start_time
                    if elapsed < 30:
                        await asyncio.sleep(30 - elapsed)
                        logger.info(f"逐个请求完成，总耗时控制在30s")
            
            # 如果有成功的聚合器结果，添加到结果列表
            if aggregator_results:
                # 按 YT 价值由高到低排序（确保排序前所有价值都已计算）
                logger.debug(f"排序前聚合器结果: {[(r.get('aggregator'), r.get('yt_value_usd')) for r in aggregator_results]}")
                aggregator_results.sort(
                    key=lambda x: (x.get("yt_value_usd") or 0) if x.get("yt_value_usd") is not None else 0,
                    reverse=True
                )
                logger.debug(f"排序后聚合器结果: {[(r.get('aggregator'), r.get('yt_value_usd')) for r in aggregator_results]}")
                
                results.append({
                    "project_name": project.name,
                    "project_address": project.address,
                    "chain_id": project.chain_id,
                    "success": True,
                    "aggregator_results": aggregator_results,
                    "yt_price": yt_price,  # 传递 YT 价格到前端
                })
            else:
                results.append({
                    "project_name": project.name,
                    "project_address": project.address,
                    "success": False,
                    "error": "所有聚合器测试失败",
                })
                
        except Exception as e:
            logger.error(f"测试项目 {project.name} 价格失败: {e}", exc_info=True)
            results.append({
                "project_name": project.name,
                "project_address": project.address,
                "success": False,
                "error": str(e),
            })
            # 即使失败也打印结束信息
            project_end_time = time.time()
            project_elapsed = project_end_time - project_start_time
            end_time_str = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
            logger.info(f"❌ [项目: {project.name}] 请求结束（失败） - {end_time_str}，耗时: {project_elapsed:.2f}秒")
            print(f"❌ [项目: {project.name}] 请求结束（失败） - {end_time_str}，耗时: {project_elapsed:.2f}秒")  # 同时打印到控制台
    
    return {
        "success": True,
        "message": f"已测试 {len(results)} 个项目",
        "results": results,
        "test_time": datetime.utcnow().isoformat(),
    }


@router.post("/projects/test-prices-stream")
async def test_project_prices_stream(
    limit: int = Query(3, description="测试的项目数量（默认 3）"),
    session: AsyncSession = Depends(get_session),
):
    """
    测试监控项目的价格转换（流式响应，支持动态更新）
    
    对前 N 个监控的项目进行价格测试，测试 100 USDT 能兑换多少 YT
    使用流式响应，每个项目完成后立即返回结果
    
    Args:
        limit: 测试的项目数量（默认 3）
    """
    import json
    from app.services.price_test_client import price_test_client
    from app.services.assets_price_client import assets_price_client
    from app.models.chain_id import ChainId
    
    async def generate():
        repo = PendleProjectRepository(session)
        
        # 获取监控的项目（限制数量）
        monitored_projects = await repo.get_monitored(filter_expired=True)
        projects_to_test = list(monitored_projects)[:limit]
        
        if not projects_to_test:
            yield json.dumps({
                "type": "error",
                "message": "没有监控的项目",
            }) + "\n"
            return
        
        # 获取所有链信息
        chain_result = await session.execute(select(ChainId))
        chains = {chain.id: chain for chain in chain_result.scalars().all()}
        
        for project_idx, project in enumerate(projects_to_test):
            # 项目之间添加延迟，避免请求过快
            if project_idx > 0:
                import asyncio
                await asyncio.sleep(3)  # 每个项目之间延迟 3 秒
            
            project_result = {
                "project_name": project.name,
                "project_address": project.address,
                "chain_id": project.chain_id,
                "success": False,
                "aggregator_results": [],
            }
            
            # 记录项目请求开始时间
            import time
            from datetime import datetime
            project_start_time = time.time()
            start_time_str = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
            logger.info(f"🚀 [项目: {project.name}] 请求开始 - {start_time_str}")
            
            try:
                # 获取项目的 chain_id 和 YT 地址
                if not project.chain_id:
                    logger.warning(f"项目 {project.name} 没有 chain_id，跳过")
                    project_result["error"] = "项目没有 chain_id"
                    yield json.dumps({
                        "type": "project_result",
                        **project_result,
                    }) + "\n"
                    continue
                
                # 获取链的代币地址（USDT 地址）
                chain = chains.get(project.chain_id)
                if not chain or not chain.token_address:
                    logger.warning(f"链 {project.chain_id} 没有代币地址，跳过")
                    project_result["error"] = f"链 {project.chain_id} 没有代币地址"
                    yield json.dumps({
                        "type": "project_result",
                        **project_result,
                    }) + "\n"
                    continue
                
                tokens_in = chain.token_address
                aggregators_list = ["kyberswap"]  # 强制只使用 kyberswap
                
                # 获取 YT 地址（优先使用 yt_address_full，否则从 extra_data 提取）
                yt_address = None
                yt_address_full = None
                
                if project.yt_address_full:
                    yt_address_full = project.yt_address_full
                    if "-" in yt_address_full:
                        yt_address = yt_address_full.split("-", 1)[1]
                    else:
                        yt_address = yt_address_full
                elif project.extra_data:
                    try:
                        extra_data = json.loads(project.extra_data)
                        yt_raw = extra_data.get("yt")
                        if yt_raw:
                            if isinstance(yt_raw, str) and "-" in yt_raw:
                                yt_address_full = yt_raw
                                yt_address = yt_raw.split("-", 1)[1]
                            else:
                                if project.chain_id:
                                    yt_address_full = f"{project.chain_id}-{yt_raw}"
                                else:
                                    yt_address_full = yt_raw
                                yt_address = yt_raw
                    except (json.JSONDecodeError, KeyError, AttributeError) as e:
                        logger.warning(f"无法从 extra_data 提取 YT 地址: {e}")
                
                if not yt_address or not yt_address_full:
                    logger.warning(f"项目 {project.name} 没有 YT 地址，跳过")
                    project_result["error"] = "项目没有 YT 地址"
                    yield json.dumps({
                        "type": "project_result",
                        **project_result,
                    }) + "\n"
                    continue
                
                # 先请求 YT 价格 API（每个项目只请求一次）
                import asyncio
                import time
                start_time = time.time()
                
                yt_price = None
                try:
                    logger.info(f"📊 [项目: {project.name}] 开始查询 YT 价格（每个项目只请求一次）")
                    logger.info(f"📊 请求参数: ids={yt_address_full}, chain_id={project.chain_id}, type=YT")
                    price_result = await assets_price_client.get_assets_prices(
                        ids=yt_address_full,
                        chain_id=project.chain_id,
                        asset_type="YT",
                    )
                    # 解析价格数据（API 返回格式：{"prices": {"1-0x...": 0.9989, ...}, ...}）
                    logger.info(f"🔍 价格 API 响应类型: {type(price_result)}")
                    logger.info(f"🔍 价格 API 响应内容: {price_result}")
                    
                    yt_price = None
                    if isinstance(price_result, dict):
                        # API 返回格式：{"prices": {"1-0x...": 0.9989, ...}, ...}
                        if "prices" in price_result:
                            prices_dict = price_result["prices"]
                            logger.info(f"✅ 从 'prices' 字段获取价格字典: {prices_dict}")
                            if isinstance(prices_dict, dict) and yt_address_full in prices_dict:
                                yt_price = float(prices_dict[yt_address_full])
                                logger.info(f"✅✅✅ 成功从 prices['{yt_address_full}'] 获取价格: {yt_price}")
                            else:
                                logger.warning(f"⚠️ prices 字典中没有找到键 '{yt_address_full}'，可用键: {list(prices_dict.keys()) if isinstance(prices_dict, dict) else 'N/A'}")
                        # 兼容其他可能的格式
                        elif yt_address_full in price_result:
                            price_data = price_result[yt_address_full]
                            logger.info(f"✅ 从键 '{yt_address_full}' 获取价格数据: {price_data}")
                            if isinstance(price_data, (int, float)):
                                yt_price = float(price_data)
                            elif isinstance(price_data, str):
                                try:
                                    yt_price = float(price_data)
                                except (ValueError, TypeError):
                                    pass
                    elif isinstance(price_result, list) and len(price_result) > 0:
                        price_data = price_result[0]
                        if isinstance(price_data, dict):
                            yt_price = price_data.get("price") or price_data.get("usd") or price_data.get("value")
                        else:
                            yt_price = float(price_data) if price_data else None
                    
                    if yt_price:
                        logger.info(f"✅✅✅ 成功获取到 YT 价格: ${yt_price}")
                    else:
                        logger.error(f"❌❌❌ 无法从价格 API 响应中提取价格")
                        logger.error(f"响应类型: {type(price_result)}")
                        logger.error(f"响应内容: {price_result}")
                        logger.error(f"YT 地址: {yt_address_full}")
                        logger.error(f"链 ID: {project.chain_id}")
                except Exception as e:
                    logger.warning(f"查询 YT 价格失败: {e}，继续执行兑换测试")
                
                # 价格 API 请求完成，现在开始请求聚合器（聚合器只请求 YT 数量，不请求价格）
                logger.info(f"📊 [项目: {project.name}] 价格查询完成，YT价格: ${yt_price if yt_price else 'None'}")
                logger.info(f"📊 [项目: {project.name}] 开始请求聚合器（只请求 YT 数量，不请求价格）")
                
                # 只使用 kyberswap 聚合器
                aggregator_results = []
                
                # 计算总延迟时间
                # 单个聚合器：价格api+单个聚合器api请求，控制在45s（可以小于45s，但不要大于45s）
                price_api_time = time.time() - start_time
                
                # 请求 kyberswap（只请求 YT 数量）
                try:
                    logger.info(f"🔄 [项目: {project.name}] 请求聚合器 kyberswap（只请求 YT 数量）")
                    convert_result = await price_test_client.test_convert(
                        chain_id=project.chain_id,
                        tokens_in=tokens_in,
                        tokens_out=yt_address,
                        amounts_in=100000000,  # 100 USDT (6 decimals)
                        aggregators="kyberswap",
                    )
                    agg_results = _process_convert_result(convert_result, ["kyberswap"])
                    for agg_result in agg_results:
                        yt_amount = agg_result.get("yt_amount")
                        if yt_amount is not None and yt_price is not None:
                            agg_result["yt_value_usd"] = yt_amount * yt_price
                            logger.info(f"✅ 计算价值: {agg_result['aggregator']} - YT数量: {yt_amount}, YT价格: ${yt_price}, 价值: ${agg_result['yt_value_usd']}")
                            # 检查价值是否异常（< $10）
                            _check_yt_value_warning(agg_result, project.name)
                            # 检查价值是否超过 $102，如果是则发送通知
                            await _check_and_notify_high_value(agg_result, project, chains)
                        else:
                            logger.warning(f"⚠️ 无法计算 {agg_result['aggregator']} 的价值 - YT数量: {yt_amount}, YT价格: {yt_price}")
                            agg_result["yt_value_usd"] = None
                    aggregator_results.extend(agg_results)
                    
                    # 价格测试部分控制在30秒内（test_project_prices_stream不调用V5 API，但保持一致性）
                    elapsed = time.time() - start_time
                    if elapsed >= 30:
                        logger.warning(f"⚠️ [项目: {project.name}] 价格测试耗时超过30秒（{elapsed:.2f}秒），跳过剩余处理")
                    elif elapsed < 8:
                        # 如果完成得太快（少于8秒），等待到8秒
                        await asyncio.sleep(8 - elapsed)
                        final_elapsed = time.time() - start_time
                        logger.info(f"✅ [项目: {project.name}] 价格测试完成，耗时: {elapsed:.2f}秒，等待到8秒后返回（总耗时: {final_elapsed:.2f}秒）")
                    else:
                        logger.info(f"✅ [项目: {project.name}] 价格测试完成，耗时: {elapsed:.2f}秒（在8-30秒范围内）")
                except Exception as e:
                    logger.error(f"kyberswap 请求失败: {e}")
                    aggregator_results.append({
                        "aggregator": "kyberswap",
                        "error": str(e),
                    })
                
                # 注释掉其他聚合器的请求逻辑
                if False:  # 暂时禁用其他聚合器
                    try:
                        # 如果只有单个聚合器（kyberswap），已经处理完成
                        # 如果有多个聚合器，需要控制总时间在45s
                        elapsed = time.time() - start_time
                        if elapsed < 3:
                            await asyncio.sleep(3 - elapsed)  # 至少延迟3秒
                        
                        logger.info(f"合并请求其他聚合器: {other_aggregators}")
                        convert_result = await price_test_client.test_convert(
                            chain_id=project.chain_id,
                            tokens_in=tokens_in,
                            tokens_out=yt_address,
                            amounts_in=100000000,  # 100 USDT (6 decimals)
                            aggregators=other_aggregators,
                        )
                        agg_results = _process_convert_result(convert_result, other_aggregators)
                        for agg_result in agg_results:
                            yt_amount = agg_result.get("yt_amount")
                            if yt_amount is not None and yt_price is not None:
                                agg_result["yt_value_usd"] = yt_amount * yt_price
                                logger.info(f"✅ 计算价值: {agg_result['aggregator']} - YT数量: {yt_amount}, YT价格: ${yt_price}, 价值: ${agg_result['yt_value_usd']}")
                                # 检查价值是否异常（< $10）
                                _check_yt_value_warning(agg_result, project.name)
                            else:
                                logger.warning(f"⚠️ 无法计算 {agg_result['aggregator']} 的价值 - YT数量: {yt_amount}, YT价格: {yt_price}")
                                agg_result["yt_value_usd"] = None
                        aggregator_results.extend(agg_results)
                        
                        # 控制总时间在30s（多个聚合器）
                        elapsed = time.time() - start_time
                        if elapsed < 30:
                            await asyncio.sleep(30 - elapsed)
                            logger.info(f"多个聚合器请求完成，总耗时控制在30s")
                    except Exception as e:
                        logger.error(f"其他聚合器请求失败: {e}")
                        logger.warning(f"合并请求失败，回退到逐个请求: {e}")
                        
                        for idx, aggregator in enumerate(other_aggregators):
                            if idx > 0:
                                await asyncio.sleep(5)  # 延迟 5 秒
                            
                            try:
                                convert_result = await price_test_client.test_convert(
                                    chain_id=project.chain_id,
                                    tokens_in=tokens_in,
                                    tokens_out=yt_address,
                                    amounts_in=100000000,  # 100 USDT (6 decimals)
                                    aggregators=aggregator,
                                )
                                agg_results = _process_convert_result(convert_result, [aggregator])
                                for agg_result in agg_results:
                                    yt_amount = agg_result.get("yt_amount")
                                    if yt_amount is not None and yt_price is not None:
                                        agg_result["yt_value_usd"] = yt_amount * yt_price
                                        logger.info(f"✅ 计算价值: {agg_result['aggregator']} - YT数量: {yt_amount}, YT价格: ${yt_price}, 价值: ${agg_result['yt_value_usd']}")
                                        # 检查价值是否异常（< $10）
                                        _check_yt_value_warning(agg_result, project.name)
                                        # 检查价值是否超过 $102，如果是则发送通知
                                        await _check_and_notify_high_value(agg_result, project, chains)
                                    else:
                                        logger.warning(f"⚠️ 无法计算 {agg_result['aggregator']} 的价值 - YT数量: {yt_amount}, YT价格: {yt_price}")
                                        agg_result["yt_value_usd"] = None
                                aggregator_results.extend(agg_results)
                            except Exception as e2:
                                logger.error(f"测试聚合器 {aggregator} 失败: {e2}")
                                aggregator_results.append({
                                    "aggregator": aggregator,
                                    "error": str(e2),
                                })
                        
                        # 回退到逐个请求后，也控制总时间在30s
                        elapsed = time.time() - start_time
                        if elapsed < 30:
                            await asyncio.sleep(30 - elapsed)
                            logger.info(f"逐个请求完成，总耗时控制在30s")
                
                # 按 YT 价值由高到低排序（确保排序前所有价值都已计算）
                logger.debug(f"排序前聚合器结果: {[(r.get('aggregator'), r.get('yt_value_usd')) for r in aggregator_results]}")
                aggregator_results.sort(
                    key=lambda x: (x.get("yt_value_usd") or 0) if x.get("yt_value_usd") is not None else 0,
                    reverse=True
                )
                logger.debug(f"排序后聚合器结果: {[(r.get('aggregator'), r.get('yt_value_usd')) for r in aggregator_results]}")
                
                project_result["success"] = True
                project_result["aggregator_results"] = aggregator_results
                project_result["yt_price"] = yt_price
                project_result["test_time"] = datetime.utcnow().isoformat()
                
            except Exception as e:
                logger.error(f"测试项目 {project.name} 价格失败: {e}", exc_info=True)
                project_result["error"] = str(e)
            
            # 打印请求结束信息
            project_end_time = time.time()
            project_elapsed = project_end_time - project_start_time
            end_time_str = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
            if project_result.get("success"):
                logger.info(f"✅ [项目: {project.name}] 请求结束 - {end_time_str}，耗时: {project_elapsed:.2f}秒")
                print(f"✅ [项目: {project.name}] 请求结束 - {end_time_str}，耗时: {project_elapsed:.2f}秒")  # 同时打印到控制台
            else:
                logger.info(f"❌ [项目: {project.name}] 请求结束（失败） - {end_time_str}，耗时: {project_elapsed:.2f}秒")
                print(f"❌ [项目: {project.name}] 请求结束（失败） - {end_time_str}，耗时: {project_elapsed:.2f}秒")  # 同时打印到控制台
            
            # 立即返回单个项目的结果
            yield json.dumps({
                "type": "project_result",
                **project_result,
            }) + "\n"
        
        # 发送完成消息
        yield json.dumps({
            "type": "complete",
            "test_time": datetime.utcnow().isoformat(),
            "message": f"已测试 {len(projects_to_test)} 个项目",
        }) + "\n"
    
    return StreamingResponse(generate(), media_type="application/x-ndjson")


@router.post("/projects/test-single-price")
async def test_single_project_price(
    address: str = Query(..., description="项目地址"),
    session: AsyncSession = Depends(get_session),
) -> dict:
    """
    测试单个项目的价格转换（用于自动更新）
    
    Args:
        address: 项目地址
    """
    from app.services.price_test_client import price_test_client
    from app.services.assets_price_client import assets_price_client
    from app.models.chain_id import ChainId
    import json
    
    repo = PendleProjectRepository(session)
    project = await repo.get_by_address(address)
    
    if not project:
        return {
            "success": False,
            "message": "项目不存在",
            "result": None,
        }
    
    if not project.chain_id:
        return {
            "success": False,
            "message": "项目没有 chain_id",
            "result": {
                "project_name": project.name,
                "project_address": project.address,
                "success": False,
                "error": "项目没有 chain_id",
            },
        }
    
    # 获取链信息（用于通知和代币地址）
    chain_result = await session.execute(select(ChainId))
    chains = {chain.id: chain for chain in chain_result.scalars().all()}
    
    chain_result = await session.execute(select(ChainId).where(ChainId.id == project.chain_id))
    chain = chain_result.scalar_one_or_none()
    
    if not chain or not chain.token_address:
        return {
            "success": False,
            "message": f"链 {project.chain_id} 没有代币地址",
            "result": {
                "project_name": project.name,
                "project_address": project.address,
                "success": False,
                "error": f"链 {project.chain_id} 没有代币地址",
            },
        }
    
    tokens_in = chain.token_address
    aggregators_list = ["kyberswap"]  # 强制只使用 kyberswap
    
    # 获取 YT 地址
    yt_address = None
    yt_address_full = None
    
    if project.yt_address_full:
        yt_address_full = project.yt_address_full
        if "-" in yt_address_full:
            yt_address = yt_address_full.split("-", 1)[1]
        else:
            yt_address = yt_address_full
    elif project.extra_data:
        try:
            extra_data = json.loads(project.extra_data)
            yt_raw = extra_data.get("yt")
            if yt_raw:
                if isinstance(yt_raw, str) and "-" in yt_raw:
                    yt_address_full = yt_raw
                    yt_address = yt_raw.split("-", 1)[1]
                else:
                    if project.chain_id:
                        yt_address_full = f"{project.chain_id}-{yt_raw}"
                    else:
                        yt_address_full = yt_raw
                    yt_address = yt_raw
        except (json.JSONDecodeError, KeyError, AttributeError) as e:
            logger.warning(f"无法从 extra_data 提取 YT 地址: {e}")
    
    if not yt_address or not yt_address_full:
        return {
            "success": False,
            "message": "项目没有 YT 地址",
            "result": {
                "project_name": project.name,
                "project_address": project.address,
                "success": False,
                "error": "项目没有 YT 地址",
            },
        }
    
    # 先请求 YT 价格 API（每个项目只请求一次）
    import asyncio
    import time
    from datetime import datetime
    project_start_time = time.time()
    start_time_str = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    logger.info(f"🚀 [项目: {project.name}] 请求开始 - {start_time_str}")
    print(f"🚀 [项目: {project.name}] 请求开始 - {start_time_str}")  # 同时打印到控制台
    start_time = time.time()
    
    yt_price = None
    try:
        logger.info(f"📊 [项目: {project.name}] 开始查询 YT 价格（每个项目只请求一次）")
        logger.info(f"📊 请求参数: ids={yt_address_full}, chain_id={project.chain_id}, type=YT")
        price_result = await assets_price_client.get_assets_prices(
            ids=yt_address_full,
            chain_id=project.chain_id,
            asset_type="YT",
        )
        # 解析价格数据（API 返回格式：{"prices": {"1-0x...": 0.9989, ...}, ...}）（API 返回格式：{"prices": {"1-0x...": 0.9989, ...}, ...}）
        logger.info(f"🔍 价格 API 响应类型: {type(price_result)}")
        logger.info(f"🔍 价格 API 响应内容: {price_result}")
        
        yt_price = None
        if isinstance(price_result, dict):
            # API 返回格式：{"prices": {"1-0x...": 0.9989, ...}, ...}
            if "prices" in price_result:
                prices_dict = price_result["prices"]
                logger.info(f"✅ 从 'prices' 字段获取价格字典: {prices_dict}")
                if isinstance(prices_dict, dict) and yt_address_full in prices_dict:
                    yt_price = float(prices_dict[yt_address_full])
                    logger.info(f"✅✅✅ 成功从 prices['{yt_address_full}'] 获取价格: {yt_price}")
                else:
                    logger.warning(f"⚠️ prices 字典中没有找到键 '{yt_address_full}'，可用键: {list(prices_dict.keys()) if isinstance(prices_dict, dict) else 'N/A'}")
            # 兼容其他可能的格式
            elif yt_address_full in price_result:
                price_data = price_result[yt_address_full]
                logger.info(f"✅ 从键 '{yt_address_full}' 获取价格数据: {price_data}")
                if isinstance(price_data, (int, float)):
                    yt_price = float(price_data)
                elif isinstance(price_data, str):
                    try:
                        yt_price = float(price_data)
                    except (ValueError, TypeError):
                        pass
        elif isinstance(price_result, list) and len(price_result) > 0:
            price_data = price_result[0]
            if isinstance(price_data, dict):
                yt_price = price_data.get("price") or price_data.get("usd") or price_data.get("value")
            else:
                yt_price = float(price_data) if price_data else None
        
        if yt_price:
            logger.info(f"✅✅✅ 成功获取到 YT 价格: ${yt_price}")
        else:
            logger.error(f"❌❌❌ 无法从价格 API 响应中提取价格")
            logger.error(f"响应类型: {type(price_result)}")
            logger.error(f"响应内容: {price_result}")
            logger.error(f"YT 地址: {yt_address_full}")
    except Exception as e:
        logger.warning(f"查询 YT 价格失败: {e}，继续执行兑换测试")
    
    # 价格 API 请求完成，现在开始请求聚合器（聚合器只请求 YT 数量，不请求价格）
    logger.info(f"📊 [项目: {project.name}] 价格查询完成，YT价格: ${yt_price if yt_price else 'None'}")
    logger.info(f"📊 [项目: {project.name}] 开始请求聚合器（只请求 YT 数量，不请求价格）")
    
    # 只使用 kyberswap 聚合器
    aggregator_results = []
    
    # 请求 kyberswap（只请求 YT 数量）
    try:
        logger.info(f"🔄 [项目: {project.name}] 请求聚合器 kyberswap（只请求 YT 数量）")
        convert_result = await price_test_client.test_convert(
            chain_id=project.chain_id,
            tokens_in=tokens_in,
            tokens_out=yt_address,
            amounts_in=100000000,
            aggregators="kyberswap",
        )
        agg_results = _process_convert_result(convert_result, ["kyberswap"])
        for agg_result in agg_results:
            yt_amount = agg_result.get("yt_amount")
            # 如果 YT 数量为 0（原始 amount 为 0），打印详细信息用于排查
            # 注意：检查原始 amount 值，而不是转换后的小数值
            yt_amount_raw = agg_result.get("yt_amount_raw")
            if yt_amount_raw and int(yt_amount_raw) == 0:
                import json
                logger.warning(f"⚠️ [项目: {project.name}] 聚合器 {agg_result.get('aggregator')} 返回的 YT 数量为 0（原始 amount: {yt_amount_raw}）")
                logger.warning(f"⚠️ 完整的 convert_result 数据: {json.dumps(convert_result, indent=2, ensure_ascii=False)}")
                print(f"⚠️ [调试] [项目: {project.name}] 聚合器 {agg_result.get('aggregator')} YT数量为0（原始amount为0），完整返回数据:")
                print(json.dumps(convert_result, indent=2, ensure_ascii=False))
            if yt_amount is not None and yt_price is not None:
                agg_result["yt_value_usd"] = yt_amount * yt_price
                logger.info(f"✅ 计算价值: {agg_result['aggregator']} - YT数量: {yt_amount}, YT价格: ${yt_price}, 价值: ${agg_result['yt_value_usd']}")
                # 检查价值是否异常（< $10）
                _check_yt_value_warning(agg_result, project.name)
                # 检查价值是否超过 $102，如果是则发送通知
                await _check_and_notify_high_value(agg_result, project, chains)
            else:
                logger.warning(f"⚠️ 无法计算 {agg_result['aggregator']} 的价值 - YT数量: {yt_amount}, YT价格: {yt_price}")
                agg_result["yt_value_usd"] = None
            aggregator_results.extend(agg_results)
            
            # 价格测试部分控制在30秒内（留出时间给后续的API调用）
            elapsed = time.time() - start_time
            if elapsed >= 30:
                logger.warning(f"⚠️ [项目: {project.name}] 价格测试耗时超过30秒（{elapsed:.2f}秒），跳过剩余处理")
            elif elapsed < 8:
                # 如果完成得太快（少于8秒），等待到8秒
                await asyncio.sleep(8 - elapsed)
                final_elapsed = time.time() - start_time
                logger.info(f"✅ [项目: {project.name}] 价格测试完成，耗时: {elapsed:.2f}秒，等待到8秒后继续（总耗时: {final_elapsed:.2f}秒）")
            else:
                logger.info(f"✅ [项目: {project.name}] 价格测试完成，耗时: {elapsed:.2f}秒（在8-30秒范围内）")
    except Exception as e:
        logger.error(f"kyberswap 请求失败: {e}")
        aggregator_results.append({
            "aggregator": "kyberswap",
            "error": str(e),
        })
    
    # 注释掉其他聚合器的请求逻辑
    if False:  # 暂时禁用其他聚合器
        try:
            elapsed = time.time() - start_time
            if elapsed < 3:
                await asyncio.sleep(3 - elapsed)  # 至少延迟3秒
            
            logger.info(f"合并请求其他聚合器: {other_aggregators}")
            convert_result = await price_test_client.test_convert(
                chain_id=project.chain_id,
                tokens_in=tokens_in,
                tokens_out=yt_address,
                amounts_in=100000000,
                aggregators=other_aggregators,
            )
            agg_results = _process_convert_result(convert_result, other_aggregators)
            for agg_result in agg_results:
                yt_amount = agg_result.get("yt_amount")
                if yt_amount is not None and yt_price is not None:
                    agg_result["yt_value_usd"] = yt_amount * yt_price
                    logger.info(f"✅ 计算价值: {agg_result['aggregator']} - YT数量: {yt_amount}, YT价格: ${yt_price}, 价值: ${agg_result['yt_value_usd']}")
                    # 检查价值是否异常（< $10）
                    _check_yt_value_warning(agg_result, project.name)
                else:
                    logger.warning(f"⚠️ 无法计算 {agg_result['aggregator']} 的价值 - YT数量: {yt_amount}, YT价格: {yt_price}")
                    agg_result["yt_value_usd"] = None
            aggregator_results.extend(agg_results)
            
            # 控制总时间在30s（多个聚合器）
            elapsed = time.time() - start_time
            if elapsed < 30:
                await asyncio.sleep(30 - elapsed)
                logger.info(f"多个聚合器请求完成，总耗时控制在30s")
        except Exception as e:
            logger.error(f"其他聚合器请求失败: {e}")
            logger.warning(f"合并请求失败，回退到逐个请求: {e}")
            
            for idx, aggregator in enumerate(other_aggregators):
                if idx > 0:
                    await asyncio.sleep(5)
                
                try:
                    convert_result = await price_test_client.test_convert(
                        chain_id=project.chain_id,
                        tokens_in=tokens_in,
                        tokens_out=yt_address,
                        amounts_in=100000000,  # 100 USDT (6 decimals)
                        aggregators=aggregator,
                    )
                    agg_results = _process_convert_result(convert_result, [aggregator])
                    for agg_result in agg_results:
                        yt_amount = agg_result.get("yt_amount")
                        if yt_amount is not None and yt_price is not None:
                            agg_result["yt_value_usd"] = yt_amount * yt_price
                            logger.info(f"✅ 计算价值: {agg_result['aggregator']} - YT数量: {yt_amount}, YT价格: ${yt_price}, 价值: ${agg_result['yt_value_usd']}")
                            # 检查价值是否异常（< $10）
                            _check_yt_value_warning(agg_result, project.name)
                            # 检查价值是否超过 $102，如果是则发送通知
                            await _check_and_notify_high_value(agg_result, project, chains)
                        else:
                            logger.warning(f"⚠️ 无法计算 {agg_result['aggregator']} 的价值 - YT数量: {yt_amount}, YT价格: {yt_price}")
                            agg_result["yt_value_usd"] = None
                    aggregator_results.extend(agg_results)
                except Exception as e2:
                    logger.error(f"测试聚合器 {aggregator} 失败: {e2}")
                    aggregator_results.append({
                        "aggregator": aggregator,
                        "error": str(e2),
                    })
            
            # 回退到逐个请求后，也控制总时间在45s
            elapsed = time.time() - start_time
            if elapsed < 45:
                await asyncio.sleep(45 - elapsed)
                logger.info(f"逐个请求完成，总耗时控制在45s")
    
    # 按 YT 价值由高到低排序（确保排序前所有价值都已计算）
    logger.info(f"排序前聚合器结果: {[(r.get('aggregator'), r.get('yt_value_usd'), r.get('yt_amount')) for r in aggregator_results]}")
    aggregator_results.sort(
        key=lambda x: (x.get("yt_value_usd") or 0) if x.get("yt_value_usd") is not None else 0,
        reverse=True
    )
    logger.info(f"排序后聚合器结果: {[(r.get('aggregator'), r.get('yt_value_usd'), r.get('yt_amount')) for r in aggregator_results]}")
    
    result = {
        "project_name": project.name,
        "project_address": project.address,
        "chain_id": project.chain_id,
        "success": True if aggregator_results else False,
        "aggregator_results": aggregator_results,
        "yt_price": yt_price,
    }
    
    if not aggregator_results:
        result["error"] = "所有聚合器测试失败"
    
    # 打印请求结束信息
    project_end_time = time.time()
    project_elapsed = project_end_time - project_start_time
    end_time_str = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    if result.get("success"):
        logger.info(f"✅ [项目: {project.name}] 请求结束 - {end_time_str}，耗时: {project_elapsed:.2f}秒")
        print(f"✅ [项目: {project.name}] 请求结束 - {end_time_str}，耗时: {project_elapsed:.2f}秒")  # 同时打印到控制台
    else:
        logger.info(f"❌ [项目: {project.name}] 请求结束（失败） - {end_time_str}，耗时: {project_elapsed:.2f}秒")
        print(f"❌ [项目: {project.name}] 请求结束（失败） - {end_time_str}，耗时: {project_elapsed:.2f}秒")  # 同时打印到控制台
    
    # 调用 V5 交易记录 API 检查新订单和 APR 变化
    # 检查总时间（价格测试 + API调用）是否在45秒内
    total_elapsed = time.time() - project_start_time
    print(f"📊 [项目: {project.name}] 价格测试完成，总耗时: {total_elapsed:.2f}秒，开始检查交易记录...")
    logger.info(f"📊 [项目: {project.name}] 价格测试完成，总耗时: {total_elapsed:.2f}秒，开始检查交易记录")
    
    if total_elapsed >= 45:
        print(f"⚠️ [项目: {project.name}] 总耗时已超过45秒（{total_elapsed:.2f}秒），跳过交易记录检查")
        logger.warning(f"⚠️ [项目: {project.name}] 总耗时已超过45秒（{total_elapsed:.2f}秒），跳过交易记录检查")
    else:
        try:
            from app.services.pendle_transaction_v5_client import pendle_transaction_v5_client
            from app.services.telegram_notifier import send_notification
            from datetime import timezone as tz
            
            remaining_time = 45 - total_elapsed
            print(f"📊 [项目: {project.name}] 开始检查交易记录和 APR 变化（剩余时间: {remaining_time:.2f}秒）")
            logger.info(f"📊 [项目: {project.name}] 开始检查交易记录和 APR 变化（剩余时间: {remaining_time:.2f}秒）")
            transactions_data = await pendle_transaction_v5_client.get_project_transactions(
                chain_id=project.chain_id,
                address=project.address,
                type="TRADES",
                limit=1,
                min_value=50000,
                action="SHORT_YIELD",
            )
            
            if transactions_data and transactions_data.get("results"):
                results = transactions_data.get("results", [])
                print(f"✅ [项目: {project.name}] 成功获取交易记录，共 {len(results)} 条")
                logger.info(f"✅ [项目: {project.name}] 成功获取交易记录，共 {len(results)} 条")
                if results:
                    latest_transaction = results[0]  # 最新的交易记录
                    transaction_timestamp_str = latest_transaction.get("timestamp")
                    transaction_value = latest_transaction.get("value", 0)
                    transaction_implied_apy = latest_transaction.get("impliedApy")
                    
                    if transaction_timestamp_str:
                        # 解析时间戳
                        transaction_timestamp = datetime.fromisoformat(transaction_timestamp_str.replace("Z", "+00:00"))
                        
                        # 检查是否有新订单（订单时间 > 上次检查时间）
                        last_check_time = project.last_transaction_check_time
                        if last_check_time:
                            # 确保 last_check_time 是 aware datetime
                            if last_check_time.tzinfo is None:
                                last_check_time = last_check_time.replace(tzinfo=tz.utc)
                            else:
                                last_check_time = last_check_time.astimezone(tz.utc)
                        
                        has_new_order = not last_check_time or transaction_timestamp > last_check_time
                        
                        if has_new_order:
                            print(f"📨 [项目: {project.name}] 发现新订单，时间: {transaction_timestamp_str}, 价值: ${transaction_value:.2f}")
                            logger.info(f"📨 [项目: {project.name}] 发现新订单，时间: {transaction_timestamp_str}, 价值: ${transaction_value:.2f}")
                            
                            # 检查 APR 变化
                            if transaction_implied_apy is not None:
                                last_apy = project.last_implied_apy
                                
                                # 计算 APR 变化（百分比）
                                if last_apy is not None:
                                    apy_change = last_apy - transaction_implied_apy  # 上次 - 这次
                                    apy_change_percent = abs(apy_change) * 100  # 转换为百分比
                                    
                                    print(f"📊 [项目: {project.name}] APR 变化: 上次 {last_apy*100:.2f}% -> 这次 {transaction_implied_apy*100:.2f}%, 变化: {apy_change_percent:.2f}%")
                                    logger.info(f"📊 [项目: {project.name}] APR 变化: 上次 {last_apy*100:.2f}% -> 这次 {transaction_implied_apy*100:.2f}%, 变化: {apy_change_percent:.2f}%")
                                    
                                    # 如果 APR 变化 >= 2%，发送通知
                                    if apy_change_percent >= 2.0:
                                        print(f"🚨 [项目: {project.name}] APR 变化 >= 2%（{apy_change_percent:.2f}%），准备发送通知")
                                        logger.info(f"🚨 [项目: {project.name}] APR 变化 >= 2%（{apy_change_percent:.2f}%），准备发送通知")
                                        # 构建项目链接
                                        chain_obj = chains.get(project.chain_id)
                                        chain_name = chain_obj.name if chain_obj else None
                                        chain_param = f"&chain={chain_name}" if chain_name else ""
                                        project_url = f"https://app.pendle.finance/trade/markets/{project.address}/swap?view=yt{chain_param}"
                                        
                                        # 转换为北京时间
                                        beijing_time = transaction_timestamp.astimezone(tz.utc).replace(tzinfo=None)
                                        from datetime import timedelta
                                        beijing_offset = timedelta(hours=8)
                                        beijing_time = transaction_timestamp + beijing_offset
                                        time_str = beijing_time.strftime("%Y-%m-%d %H:%M:%S")
                                        
                                        # 构建消息
                                        message = (
                                            f"<b>📊 大额订单 APR 变化通知</b>\n\n"
                                            f"时间: {time_str} (北京时间)\n"
                                            f"项目: <a href=\"{project_url}\">{project.name}</a>\n"
                                            f"出现大额订单价值: ${transaction_value:.2f}\n"
                                            f"APR 变化: {last_apy*100:.2f}% → {transaction_implied_apy*100:.2f}% (变化: {apy_change_percent:.2f}%)"
                                        )
                                        
                                        success = await send_notification(message, parse_mode="HTML")
                                        if success:
                                            print(f"✅ [项目: {project.name}] 已发送 APR 变化通知")
                                            logger.info(f"✅ [项目: {project.name}] 已发送 APR 变化通知")
                                        else:
                                            print(f"⚠️ [项目: {project.name}] 发送 APR 变化通知失败")
                                            logger.warning(f"⚠️ [项目: {project.name}] 发送 APR 变化通知失败")
                                
                                # 更新数据库中的 APR（无论是否发送通知）
                                project.last_implied_apy = transaction_implied_apy
                                print(f"✅ [项目: {project.name}] 已更新 last_implied_apy: {transaction_implied_apy*100:.2f}%")
                                logger.info(f"✅ [项目: {project.name}] 已更新 last_implied_apy: {transaction_implied_apy*100:.2f}%")
                            
                            # 更新检查时间
                            project.last_transaction_check_time = transaction_timestamp.replace(tzinfo=None)  # 存储为 naive datetime
                            await session.commit()
                            print(f"✅ [项目: {project.name}] 已更新 last_transaction_check_time: {transaction_timestamp_str}")
                            logger.info(f"✅ [项目: {project.name}] 已更新 last_transaction_check_time")
                        else:
                            print(f"ℹ️ [项目: {project.name}] 没有新订单（订单时间: {transaction_timestamp_str} <= 上次检查时间）")
                            logger.debug(f"ℹ️ [项目: {project.name}] 没有新订单（订单时间: {transaction_timestamp_str} <= 上次检查时间）")
                    else:
                        logger.warning(f"⚠️ [项目: {project.name}] 交易记录中没有时间戳")
                else:
                    print(f"ℹ️ [项目: {project.name}] 没有符合条件的交易记录")
                    logger.debug(f"ℹ️ [项目: {project.name}] 没有符合条件的交易记录")
            else:
                print(f"ℹ️ [项目: {project.name}] 未获取到交易记录数据")
                logger.debug(f"ℹ️ [项目: {project.name}] 未获取到交易记录数据")
            
            # 检查总时间是否超过45秒
            final_total_elapsed = time.time() - project_start_time
            if final_total_elapsed > 45:
                print(f"⚠️ [项目: {project.name}] 总耗时超过45秒（{final_total_elapsed:.2f}秒）")
                logger.warning(f"⚠️ [项目: {project.name}] 总耗时超过45秒（{final_total_elapsed:.2f}秒）")
            else:
                print(f"✅ [项目: {project.name}] 价格测试+交易记录检查完成，总耗时: {final_total_elapsed:.2f}秒（在45秒内）")
                logger.info(f"✅ [项目: {project.name}] 价格测试+交易记录检查完成，总耗时: {final_total_elapsed:.2f}秒（在45秒内）")
        except Exception as e:
            print(f"❌ [项目: {project.name}] 检查交易记录和 APR 变化失败: {e}")
            logger.error(f"❌ [项目: {project.name}] 检查交易记录和 APR 变化失败: {e}", exc_info=True)
            # 不中断主流程，继续返回结果
    
    return {
        "success": True,
        "result": result,
        "test_time": datetime.utcnow().isoformat(),
    }

