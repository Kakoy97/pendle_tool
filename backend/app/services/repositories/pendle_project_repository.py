"""Pendle 项目仓库"""

import logging
from collections.abc import Sequence
from datetime import datetime

from sqlalchemy import and_, select, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import settings
from app.models.pendle_project import PendleProject

logger = logging.getLogger(__name__)


class PendleProjectRepository:
    """Pendle 项目数据访问层"""

    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def get_all(self, filter_expired: bool = True) -> Sequence[PendleProject]:
        """获取所有项目"""
        query = select(PendleProject)
        
        # 过滤 24hvol 低于阈值的项目
        min_volume = settings.project_min_volume_24h
        query = query.where(
            PendleProject.trading_volume_24h.isnot(None),
            PendleProject.trading_volume_24h > min_volume
        )
        
        # 过滤已过期的项目
        if filter_expired:
            from datetime import datetime, timezone
            # 使用 naive datetime 进行比较，因为 SQLite 存储的可能是 naive datetime
            # 或者使用 UTC 的 aware datetime，但需要确保数据库中的 expiry 也是 aware
            now_utc = datetime.now(timezone.utc)
            # 转换为 naive UTC datetime 用于 SQLite 比较（SQLite 不存储时区信息）
            now_naive = now_utc.replace(tzinfo=None)
            # 只显示 expiry 为 None 或 expiry > now 的项目
            # 如果 expiry 存在且 <= now，则过滤掉
            query = query.where(
                (PendleProject.expiry.is_(None)) | (PendleProject.expiry > now_naive)
            )
            logger.debug(f"过滤过期项目: 当前时间 {now_utc}, 条件: expiry IS NULL OR expiry > {now_naive}")
        
        result = await self._session.execute(query.order_by(PendleProject.project_group, PendleProject.name))
        projects = result.scalars().all()
        
        # 调试：检查是否有过期项目被返回
        if filter_expired:
            from datetime import datetime, timezone
            now = datetime.now(timezone.utc)
            # 确保 expiry 是 aware datetime，如果是 naive，则假设为 UTC
            expired_found = []
            for p in projects:
                if p.expiry:
                    # 如果 expiry 是 naive，假设为 UTC
                    expiry = p.expiry
                    if expiry.tzinfo is None:
                        expiry = expiry.replace(tzinfo=timezone.utc)
                    if expiry <= now:
                        expired_found.append(p)
            if expired_found:
                logger.warning(f"发现 {len(expired_found)} 个过期项目未被过滤: {[p.name for p in expired_found[:5]]}")
        
        return projects

    async def get_by_address(self, address: str) -> PendleProject | None:
        """根据地址获取项目"""
        result = await self._session.execute(
            select(PendleProject).where(PendleProject.address == address)
        )
        return result.scalar_one_or_none()

    async def get_monitored(self, filter_expired: bool = True) -> Sequence[PendleProject]:
        """获取所有正在监控的项目"""
        query = select(PendleProject).where(PendleProject.is_monitored.is_(True))
        
        # 过滤 24hvol 低于阈值的项目
        min_volume = settings.project_min_volume_24h
        query = query.where(
            PendleProject.trading_volume_24h.isnot(None),
            PendleProject.trading_volume_24h > min_volume
        )
        
        # 过滤已过期的项目
        if filter_expired:
            from datetime import datetime, timezone
            now_utc = datetime.now(timezone.utc)
            # 转换为 naive UTC datetime 用于 SQLite 比较
            now_naive = now_utc.replace(tzinfo=None)
            # 只显示 expiry 为 None 或 expiry > now 的项目
            # 如果 expiry 存在且 <= now，则过滤掉
            query = query.where(
                (PendleProject.expiry.is_(None)) | (PendleProject.expiry > now_naive)
            )
        
        result = await self._session.execute(query.order_by(PendleProject.project_group, PendleProject.name))
        return result.scalars().all()

    async def get_unmonitored(self, filter_expired: bool = True) -> Sequence[PendleProject]:
        """获取所有未监控的项目"""
        query = select(PendleProject).where(PendleProject.is_monitored.is_(False))
        
        # 过滤 24hvol 低于阈值的项目
        min_volume = settings.project_min_volume_24h
        query = query.where(
            PendleProject.trading_volume_24h.isnot(None),
            PendleProject.trading_volume_24h > min_volume
        )
        
        # 过滤已过期的项目
        if filter_expired:
            from datetime import datetime, timezone
            now_utc = datetime.now(timezone.utc)
            # 转换为 naive UTC datetime 用于 SQLite 比较
            now_naive = now_utc.replace(tzinfo=None)
            # 只显示 expiry 为 None 或 expiry > now 的项目
            # 如果 expiry 存在且 <= now，则过滤掉
            query = query.where(
                (PendleProject.expiry.is_(None)) | (PendleProject.expiry > now_naive)
            )
        
        result = await self._session.execute(query.order_by(PendleProject.project_group, PendleProject.name))
        return result.scalars().all()

    async def create_or_update(
        self,
        *,
        address: str,
        name: str | None = None,
        symbol: str | None = None,
        description: str | None = None,
        extra_data: dict | None = None,
    ) -> PendleProject:
        """创建或更新项目"""
        project = await self.get_by_address(address)
        
        if project:
            # 更新现有项目
            project.name = name or project.name
            project.symbol = symbol or project.symbol
            project.description = description or project.description
            if extra_data:
                import json
                project.extra_data = json.dumps(extra_data)
            project.updated_at = datetime.utcnow()
        else:
            # 创建新项目
            import json
            project = PendleProject(
                address=address,
                name=name,
                symbol=symbol,
                description=description,
                extra_data=json.dumps(extra_data) if extra_data else None,
            )
            self._session.add(project)
        
        await self._session.commit()
        await self._session.refresh(project)
        return project

    async def set_monitored(self, address: str, is_monitored: bool) -> PendleProject | None:
        """设置项目的监控状态"""
        project = await self.get_by_address(address)
        if not project:
            return None
        
        project.is_monitored = is_monitored
        project.updated_at = datetime.utcnow()
        await self._session.commit()
        await self._session.refresh(project)
        return project

    def _extract_project_group(self, name: str) -> str:
        """
        从市场名称提取项目分组名称
        
        默认返回 "其他"，让用户手动分组
        """
        # 所有项目默认放在"其他"组，用户可以手动修改
        return "其他"

    async def sync_from_api(self, markets: list[dict], projects: list[dict] | None = None) -> None:
        """从 API 数据同步项目列表（批量处理，避免数据库锁定）"""
        import json
        from datetime import date, datetime, timedelta, timezone
        
        from app.models.project_history import ProjectHistory
        
        # 创建项目分组映射（如果提供了项目列表）
        project_group_map = {}
        if projects:
            for proj in projects:
                # 根据项目数据结构提取分组信息
                # 这里需要根据实际 API 响应调整
                proj_name = proj.get("name") or proj.get("symbol") or ""
                proj_id = proj.get("id") or proj.get("address") or ""
                if proj_name:
                    project_group_map[proj_name.lower()] = proj_name
        
        # 批量处理所有市场，在一个事务中完成
        updated_count = 0
        created_count = 0
        expired_count = 0
        
        now = datetime.now(timezone.utc)
        now_naive = now.replace(tzinfo=None)
        today = date.today()  # 今天的日期（用于历史记录）
        yesterday = date.today() - timedelta(days=1)  # 昨天的日期（用于对比新增）
        
        # 获取当前数据库中所有项目的地址（用于判断删除）
        existing_projects_result = await self._session.execute(
            select(PendleProject.address)
        )
        existing_addresses = {row[0] for row in existing_projects_result.fetchall()}
        
        # 获取昨天数据库中所有项目的地址（用于对比新增）
        # 查询昨天或之前的历史记录，找出昨天存在的项目
        yesterday_projects_result = await self._session.execute(
            select(ProjectHistory.project_address).where(
                ProjectHistory.record_date <= yesterday,
                ProjectHistory.action == "added"
            ).distinct()
        )
        yesterday_added_addresses = {row[0] for row in yesterday_projects_result.fetchall()}
        
        # 查询昨天或之前的所有项目（包括今天之前创建的项目）
        # 获取所有项目的创建时间，找出昨天之前就存在的项目
        all_projects_before_today_result = await self._session.execute(
            select(PendleProject.address).where(
                PendleProject.created_at < datetime.combine(today, datetime.min.time())
            )
        )
        yesterday_existing_addresses = {row[0] for row in all_projects_before_today_result.fetchall()}
        
        # 合并：昨天存在的项目 = 昨天之前创建的项目 + 昨天之前记录为新增的项目
        # 但需要排除昨天之前记录为删除的项目
        yesterday_deleted_result = await self._session.execute(
            select(ProjectHistory.project_address).where(
                ProjectHistory.record_date <= yesterday,
                ProjectHistory.action == "deleted"
            ).distinct()
        )
        yesterday_deleted_addresses = {row[0] for row in yesterday_deleted_result.fetchall()}
        
        # 昨天存在的项目 = 昨天之前创建的项目 + 昨天之前新增的项目 - 昨天之前删除的项目
        yesterday_existing_addresses = (yesterday_existing_addresses | yesterday_added_addresses) - yesterday_deleted_addresses
        
        # 收集新增和删除的项目
        added_projects = []  # 新增的项目列表（相对于昨天）
        deleted_projects = []  # 删除的项目列表
        
        for market in markets:
            # 根据 Pendle API 响应格式：address 是唯一标识
            address = market.get("address")
            if not address:
                logger.warning(f"市场数据缺少 address 字段，跳过: {market.get('name', '未知')}")
                continue
            
            # 检查是否过期
            expiry_str = market.get("expiry")
            expiry = None
            if expiry_str:
                try:
                    # 解析 ISO 格式的时间字符串
                    expiry_aware = datetime.fromisoformat(expiry_str.replace("Z", "+00:00"))
                    # 转换为 naive UTC datetime 用于存储到 SQLite（SQLite 不存储时区信息）
                    expiry = expiry_aware.replace(tzinfo=None)
                    # 比较时也使用 naive datetime
                    now_naive = now.replace(tzinfo=None)
                    if expiry <= now_naive:
                        expired_count += 1
                        continue  # 跳过已过期的项目
                except (ValueError, TypeError) as e:
                    logger.warning(f"无法解析到期时间 {expiry_str}: {e}")
            
            # 提取市场信息
            name = market.get("name")
            
            # 所有新项目默认放在"其他"组
            project_group = "其他"
            
            # 提取链 ID（注意：API 返回的可能是字符串或数字）
            chain_id_raw = market.get("chainId") or market.get("chain_id") or market.get("chain")
            chain_id = None
            if chain_id_raw is not None:
                try:
                    chain_id = int(chain_id_raw)
                except (ValueError, TypeError):
                    logger.warning(f"无法解析链 ID: {chain_id_raw} (类型: {type(chain_id_raw)})")
                    chain_id = None
            
            # 提取市场数据（TVL、24h交易量、Fixed APY）
            # 从 details 或其他字段提取
            tvl = None
            trading_volume_24h = None
            implied_apy = None
            
            # 从 details 或其他字段提取市场数据
            details = market.get("details", {}) if market.get("details") else {}
            
            # 调试：记录第一个市场的结构
            if updated_count == 0 and created_count == 0:
                logger.info(f"市场数据结构示例 - 顶层字段: {list(market.keys())[:20]}")
                if details:
                    logger.info(f"市场数据结构示例 - details 字段: {list(details.keys())[:20]}")
            
            # TVL (liquidity) - 从 details.totalTvl 获取（根据 API 响应结构）
            # 注意：必须使用 "in" 检查，因为值可能为 0（falsy 值），使用 or 会跳过
            if "totalTvl" in details:
                tvl = details["totalTvl"]
            elif "liquidity" in details:
                tvl = details["liquidity"]
            elif "tvl" in details:
                tvl = details["tvl"]
            elif "liquidity" in market:
                tvl = market["liquidity"]
            elif "totalTvl" in market:
                tvl = market["totalTvl"]
            elif "tvl" in market:
                tvl = market["tvl"]
            else:
                tvl = None
            
            # 24h 交易量 (tradingVolume) - 从 details.tradingVolume 获取
            # 注意：必须使用 "in" 检查，因为 tradingVolume 可能为 0（falsy 值），使用 or 会跳过
            if "tradingVolume" in details:
                trading_volume_24h = details["tradingVolume"]
            elif "volume24h" in details:
                trading_volume_24h = details["volume24h"]
            elif "trading_volume_24h" in details:
                trading_volume_24h = details["trading_volume_24h"]
            elif "tradingVolume" in market:
                trading_volume_24h = market["tradingVolume"]
            elif "volume24h" in market:
                trading_volume_24h = market["volume24h"]
            elif "trading_volume_24h" in market:
                trading_volume_24h = market["trading_volume_24h"]
            else:
                trading_volume_24h = None
            
            # 验证 24h VOL 值
            # 注意：即使值低于阈值，也要同步到数据库（更新旧数据），但会在查询时过滤
            min_volume = settings.project_min_volume_24h
            if trading_volume_24h is not None:
                try:
                    volume_float = float(trading_volume_24h)
                    # 记录低交易量项目（用于调试）
                    if volume_float <= min_volume:
                        logger.debug(f"项目 {name} ({address}) 24hVOL={volume_float} <= {min_volume}，但仍会同步到数据库")
                except (ValueError, TypeError):
                    logger.warning(f"无法转换 24hVOL 值: {trading_volume_24h} (类型: {type(trading_volume_24h)})")
                    # 如果无法转换，设置为 None
                    trading_volume_24h = None
            
            # 如果 trading_volume_24h 是 None，也记录日志
            if trading_volume_24h is None:
                logger.debug(f"项目 {name} ({address}) 24hVOL 为 NULL，但仍会同步到数据库（如果项目已存在）")
            
            # Fixed APY (impliedApy) - 优先使用 aggregatedApy，如果没有则使用 impliedApy
            # 根据 API 响应，aggregatedApy 是聚合后的 APY，更适合显示
            implied_apy = details.get("aggregatedApy")
            if implied_apy is None:
                implied_apy = details.get("impliedApy") or details.get("implied_apy")
            
            if implied_apy is None:
                implied_apy = market.get("impliedApy") or market.get("implied_apy")
            
            # 如果 impliedApy 是小数形式（如 0.05 表示 5%），转换为百分比
            if implied_apy is not None and isinstance(implied_apy, (int, float)):
                # 如果值小于 1，假设是小数形式，转换为百分比
                if implied_apy < 1:
                    implied_apy = implied_apy * 100
            
            # 构建描述信息（用于显示，但数据已保存在独立字段中）
            description = None
            desc_parts = []
            if tvl:
                desc_parts.append(f"TVL: ${float(tvl):,.2f}")
            if implied_apy:
                desc_parts.append(f"APY: {float(implied_apy):.2f}%")
            if expiry_str:
                desc_parts.append(f"到期: {expiry_str[:10]}")
            if desc_parts:
                description = " | ".join(desc_parts)
            
            # 记录提取的数据以便调试（只记录前几个，避免日志过多）
            if (updated_count + created_count) < 3:
                logger.info(f"提取市场数据 - {name}: chain_id={chain_id}, TVL={tvl}, 24hVOL={trading_volume_24h}, APY={implied_apy}")
            
            # 检查项目是否已存在
            project = await self.get_by_address(address)
            
            if project:
                # 更新现有项目
                # 注意：这里不会修改 is_monitored 字段，保留用户设置的监控状态
                # 如果项目在已监控区域，同步后仍然在已监控区域
                # 如果项目在未监控区域，同步后仍然在未监控区域
                project.name = name or project.name
                project.symbol = name or project.symbol
                project.description = description or project.description
                # 如果项目还没有分组（为None），则设置为"其他"
                # 如果已经有分组，保留用户手动设置的分组（不覆盖）
                if project.project_group is None:
                    project.project_group = "其他"
                # 更新 expiry 字段（即使项目已过期，也更新以便后续过滤）
                project.expiry = expiry
                # 更新链 ID（如果 API 提供了）
                if chain_id is not None:
                    project.chain_id = chain_id
                # 更新市场数据（即使值为 0 也更新，确保数据同步）
                # 注意：使用 is not None 检查，因为 0 也是有效值
                if tvl is not None:
                    try:
                        project.tvl = float(tvl)
                    except (ValueError, TypeError):
                        logger.warning(f"无法转换 TVL 值: {tvl} (类型: {type(tvl)})")
                # 即使 trading_volume_24h 为 0，也要更新（覆盖数据库中的旧值）
                # 注意：0 是有效值，必须更新以覆盖数据库中的旧数据
                if trading_volume_24h is not None:
                    try:
                        project.trading_volume_24h = float(trading_volume_24h)
                    except (ValueError, TypeError):
                        logger.warning(f"无法转换 24hVOL 值: {trading_volume_24h} (类型: {type(trading_volume_24h)})")
                if implied_apy is not None:
                    try:
                        project.implied_apy = float(implied_apy)
                    except (ValueError, TypeError):
                        logger.warning(f"无法转换 APY 值: {implied_apy} (类型: {type(implied_apy)})")
                # 如果项目已过期，记录日志但不更新其他字段
                if expiry:
                    # 确保比较时使用相同类型的 datetime（naive）
                    expiry_naive = expiry if expiry.tzinfo is None else expiry.replace(tzinfo=None)
                    now_naive = now.replace(tzinfo=None)
                    if expiry_naive <= now_naive:
                        logger.debug(f"项目 {name} ({address}) 已过期，expiry={expiry_naive}, now={now_naive}")
                project.extra_data = json.dumps(market)
                project.updated_at = datetime.utcnow()
                # is_monitored 字段保持不变，保留用户设置的监控状态
                updated_count += 1
            else:
                # 创建新项目
                # 注意：新项目默认 is_monitored=True，project_group="其他"
                project = PendleProject(
                    address=address,
                    name=name,
                    symbol=name,  # Pendle API 中没有单独的 symbol 字段，使用 name
                    description=description,
                    project_group=project_group,  # 默认"其他"分组
                    expiry=expiry,
                    chain_id=chain_id,
                    tvl=float(tvl) if tvl is not None else None,
                    # 注意：即使 trading_volume_24h 为 0，也要保存（0 是有效值）
                    trading_volume_24h=float(trading_volume_24h) if trading_volume_24h is not None else None,
                    implied_apy=float(implied_apy) if implied_apy is not None else None,
                    extra_data=json.dumps(market),
                    is_monitored=True,  # 新项目默认监控
                )
                
                # 设置 yt_address_full 字段
                yt_raw = market.get("yt")
                if yt_raw:
                    # 如果已经是完整格式（chain_id-address），直接存储
                    if isinstance(yt_raw, str) and "-" in yt_raw:
                        project.yt_address_full = yt_raw
                    elif chain_id is not None:
                        # 如果是纯地址，组合成完整格式
                        project.yt_address_full = f"{chain_id}-{yt_raw}"
                    else:
                        # 如果没有 chain_id，尝试从 yt_raw 中提取
                        project.yt_address_full = yt_raw
                else:
                    project.yt_address_full = None
                self._session.add(project)
                created_count += 1
                # 只有项目不在昨天的列表中时，才记录为新增（相对于昨天）
                # 并且只有符合过滤条件的项目才记录为新增（24hvol > 阈值）
                min_volume = settings.project_min_volume_24h
                meets_filter = trading_volume_24h is not None and float(trading_volume_24h) > min_volume
                
                if address not in yesterday_existing_addresses:
                    if meets_filter:
                        added_projects.append({
                            "address": address,
                            "name": name or "未知项目"
                        })
                        logger.debug(f"项目 {name} ({address}) 不在昨天的列表中且符合过滤条件，记录为新增")
                    else:
                        logger.debug(f"项目 {name} ({address}) 不在昨天的列表中但不符合过滤条件（24hVOL={trading_volume_24h} <= {min_volume}），不记录为新增")
                else:
                    logger.debug(f"项目 {name} ({address}) 在昨天的列表中已存在，不记录为新增")
        
        # 检查删除的项目（检查数据库中所有项目，找出符合删除规则的项目）
        # 删除规则：1. 项目到期时间 < 当前时间，2. 项目24h VOL <= 阈值
        # 注意：排除本次同步中新增的项目，避免新增后立即被删除
        added_addresses = {p["address"] for p in added_projects}
        min_volume = settings.project_min_volume_24h
        
        all_projects_result = await self._session.execute(
            select(PendleProject)
        )
        all_projects = all_projects_result.scalars().all()
        
        for project in all_projects:
            # 跳过本次同步中新增的项目，避免新增后立即被删除
            if project.address in added_addresses:
                logger.debug(f"跳过检查删除：项目 {project.name} ({project.address}) 是本次新增的，不检查删除规则")
                continue
            
            should_delete = False
            delete_reason = []
            
            # 规则1：项目到期时间 < 当前时间
            if project.expiry:
                expiry_naive = project.expiry if project.expiry.tzinfo is None else project.expiry.replace(tzinfo=None)
                if expiry_naive <= now_naive:
                    should_delete = True
                    delete_reason.append("已过期")
            
            # 规则2：项目24h VOL <= 阈值
            if project.trading_volume_24h is not None and project.trading_volume_24h <= min_volume:
                should_delete = True
                delete_reason.append(f"24h VOL={project.trading_volume_24h} <= {min_volume}")
            
            if should_delete:
                # 检查今天是否已经记录过这个项目的删除
                existing_delete_today = await self._session.execute(
                    select(ProjectHistory).where(
                        and_(
                            ProjectHistory.record_date == today,
                            ProjectHistory.action == "deleted",
                            ProjectHistory.project_address == project.address
                        )
                    )
                )
                if not existing_delete_today.scalar_one_or_none():
                    # 检查是否之前记录过删除（检查所有日期的删除记录）
                    existing_delete_any = await self._session.execute(
                        select(ProjectHistory).where(
                            and_(
                                ProjectHistory.action == "deleted",
                                ProjectHistory.project_address == project.address
                            )
                        ).order_by(ProjectHistory.record_date.desc())
                    )
                    # 使用 first() 获取最新的删除记录（可能有多条，取最新的）
                    existing_delete_record = existing_delete_any.scalars().first()
                    
                    # 如果之前记录过删除，且项目仍然符合删除规则，说明项目已经被删除过了，不需要再次记录
                    if existing_delete_record:
                        logger.debug(f"项目 {project.name} ({project.address}) 已经记录过删除（日期: {existing_delete_record.record_date}），跳过重复记录")
                        continue
                    
                    # 在删除前，保存当前的监控状态
                    if project.last_monitored_state is None:
                        project.last_monitored_state = project.is_monitored
                        logger.debug(f"保存项目 {project.name} ({project.address}) 的删除前监控状态: {project.is_monitored}")
                    
                    deleted_projects.append({
                        "address": project.address,
                        "name": project.name or "未知项目"
                    })
                    logger.info(f"项目 {project.name} ({project.address}) 符合删除规则: {', '.join(delete_reason)}")
            else:
                # 项目不符合删除规则，检查是否之前被删除过
                # 如果之前被删除过，但现在不符合删除规则了，应该记录为新增
                existing_delete_any = await self._session.execute(
                    select(ProjectHistory).where(
                        and_(
                            ProjectHistory.action == "deleted",
                            ProjectHistory.project_address == project.address
                        )
                    ).order_by(ProjectHistory.record_date.desc())
                )
                # 使用 first() 获取最新的删除记录（可能有多条，取最新的）
                existing_delete_record = existing_delete_any.scalars().first()
                
                # 如果之前被删除过，但现在不符合删除规则了，记录为新增
                if existing_delete_record:
                    # 检查今天是否已经记录过新增
                    existing_add_today = await self._session.execute(
                        select(ProjectHistory).where(
                            and_(
                                ProjectHistory.record_date == today,
                                ProjectHistory.action == "added",
                                ProjectHistory.project_address == project.address
                            )
                        )
                    )
                    if not existing_add_today.scalar_one_or_none():
                        # 检查是否在本次同步中已经作为新增项目处理了
                        if project.address not in added_addresses:
                            logger.info(f"项目 {project.name} ({project.address}) 之前被删除过（日期: {existing_delete_record.record_date}），但现在不符合删除规则，记录为新增")
                            
                            # 恢复删除前的监控状态
                            if project.last_monitored_state is not None:
                                project.is_monitored = project.last_monitored_state
                                logger.info(f"恢复项目 {project.name} ({project.address}) 的监控状态: {project.is_monitored} (从 last_monitored_state 恢复)")
                                # 恢复后清空 last_monitored_state
                                project.last_monitored_state = None
                            
                            added_projects.append({
                                "address": project.address,
                                "name": project.name or "未知项目"
                            })
        
        # 一次性提交所有更改（避免数据库锁定）
        try:
            await self._session.commit()
            logger.info(f"同步完成: 创建 {created_count} 个新项目，更新 {updated_count} 个现有项目，跳过 {expired_count} 个过期项目")
            
            # 记录历史记录（新增和删除的项目）
            # 先检查今天是否已经有记录，避免重复记录
            # 如果同一个项目在同一天既有新增又有删除，只记录删除（删除优先级更高）
            if added_projects or deleted_projects:
                # 获取删除项目的地址集合，用于过滤新增记录
                deleted_addresses_set = {p["address"] for p in deleted_projects}
                
                for project_info in added_projects:
                    # 如果这个项目在同一天被删除，跳过新增记录（删除优先级更高）
                    if project_info["address"] in deleted_addresses_set:
                        logger.debug(f"跳过新增记录：项目 {project_info['name']} ({project_info['address']}) 在同一天被删除，只记录删除")
                        continue
                    
                    # 检查今天是否已经记录过这个项目的新增
                    existing_add = await self._session.execute(
                        select(ProjectHistory).where(
                            ProjectHistory.record_date == today,
                            ProjectHistory.action == "added",
                            ProjectHistory.project_address == project_info["address"]
                        )
                    )
                    if not existing_add.scalar_one_or_none():
                        history = ProjectHistory(
                            record_date=today,
                            action="added",
                            project_address=project_info["address"],
                            project_name=project_info["name"]
                        )
                        self._session.add(history)
                
                for project_info in deleted_projects:
                    # 检查今天是否已经记录过这个项目的删除
                    existing_delete = await self._session.execute(
                        select(ProjectHistory).where(
                            ProjectHistory.record_date == today,
                            ProjectHistory.action == "deleted",
                            ProjectHistory.project_address == project_info["address"]
                        )
                    )
                    if not existing_delete.scalar_one_or_none():
                        # 如果今天已经有新增记录，先删除新增记录（删除优先级更高）
                        existing_add = await self._session.execute(
                            select(ProjectHistory).where(
                                ProjectHistory.record_date == today,
                                ProjectHistory.action == "added",
                                ProjectHistory.project_address == project_info["address"]
                            )
                        )
                        existing_add_record = existing_add.scalar_one_or_none()
                        if existing_add_record:
                            # 删除新增记录
                            await self._session.delete(existing_add_record)
                            logger.debug(f"删除新增记录：项目 {project_info['name']} ({project_info['address']}) 在同一天被删除，删除优先级更高")
                        
                        history = ProjectHistory(
                            record_date=today,
                            action="deleted",
                            project_address=project_info["address"],
                            project_name=project_info["name"]
                        )
                        self._session.add(history)
                
                await self._session.commit()
                logger.info(f"历史记录已保存: 新增 {len(added_projects)} 个项目，删除 {len(deleted_projects)} 个项目")
            
            # 清理数据库中已过期的项目（可选：如果希望自动删除过期项目）
            # 注意：这里只是记录，不删除，因为用户可能想保留历史数据
            # 如果需要删除，可以取消下面的注释
            # from sqlalchemy import delete
            # delete_result = await self._session.execute(
            #     delete(PendleProject).where(
            #         PendleProject.expiry.isnot(None),
            #         PendleProject.expiry <= datetime.now(timezone.utc)
            #     )
            # )
            # deleted_count = delete_result.rowcount
            # if deleted_count > 0:
            #     await self._session.commit()
            #     logger.info(f"清理了 {deleted_count} 个过期项目")
        except Exception as e:
            await self._session.rollback()
            logger.error(f"同步失败，已回滚: {e}", exc_info=True)
            raise

