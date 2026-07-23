from datetime import datetime, timezone

from sqlalchemy import delete, func, update
from sqlalchemy.ext.asyncio import AsyncSession
from sqlmodel import col, select

from module.models import (
    Bangumi,
    BangumiGroup,
    BangumiGroupMember,
    NamingExecution,
    NamingPlan,
    NamingPlanRevision,
)


def utc_now() -> datetime:
    return datetime.now(timezone.utc)


class EpisodeNamingDatabase:
    """Persistence boundary for stable groups and per-downloader-file plans."""

    def __init__(self, session: AsyncSession):
        self.session = session

    async def list_groups(self) -> list[BangumiGroup]:
        result = await self.session.execute(
            select(BangumiGroup).order_by(
                col(BangumiGroup.official_title), col(BangumiGroup.id)
            )
        )
        return list(result.scalars().all())

    async def get_group(self, group_id: int) -> BangumiGroup | None:
        return await self.session.get(BangumiGroup, group_id)

    async def get_member_rules(self, group_id: int) -> list[Bangumi]:
        result = await self.session.execute(
            select(Bangumi)
            .join(
                BangumiGroupMember,
                col(BangumiGroupMember.rule_id) == col(Bangumi.id),
            )
            .where(col(BangumiGroupMember.group_id) == group_id)
            .order_by(col(Bangumi.id))
        )
        return list(result.scalars().all())

    async def get_member_rule_ids(self, group_id: int) -> list[int]:
        result = await self.session.execute(
            select(col(BangumiGroupMember.rule_id)).where(
                col(BangumiGroupMember.group_id) == group_id
            )
        )
        return list(result.scalars().all())

    async def get_group_plans(self, group_id: int) -> list[NamingPlan]:
        result = await self.session.execute(
            select(NamingPlan)
            .where(col(NamingPlan.group_id) == group_id)
            .order_by(col(NamingPlan.task_id), col(NamingPlan.file_index))
        )
        return list(result.scalars().all())

    async def get_rule_group(self, rule_id: int) -> BangumiGroup | None:
        result = await self.session.execute(
            select(BangumiGroup)
            .join(
                BangumiGroupMember,
                col(BangumiGroupMember.group_id) == col(BangumiGroup.id),
            )
            .where(col(BangumiGroupMember.rule_id) == rule_id)
        )
        return result.scalar_one_or_none()

    async def ensure_rule_group(self, rule_id: int) -> BangumiGroup:
        existing = await self.get_rule_group(rule_id)
        if existing is not None:
            return existing
        rule = await self.session.get(Bangumi, rule_id)
        if rule is None:
            raise LookupError(f"Bangumi rule {rule_id} not found")

        group = None
        if rule.year:
            result = await self.session.execute(
                select(BangumiGroup).where(
                    col(BangumiGroup.official_title) == rule.official_title,
                    col(BangumiGroup.year) == rule.year,
                    col(BangumiGroup.season) == rule.season,
                    col(BangumiGroup.episode_type) == rule.episode_type,
                )
            )
            group = result.scalars().first()
        if group is None:
            group = BangumiGroup(
                official_title=rule.official_title,
                year=rule.year,
                season=rule.season,
                episode_type=rule.episode_type,
                poster_link=rule.poster_link,
                air_weekday=rule.air_weekday,
                migration_review=not bool(rule.year),
                migration_review_reason="missing_year" if not rule.year else None,
            )
            self.session.add(group)
            await self.session.flush()
        if group.id is None:
            raise RuntimeError("Bangumi group did not receive an id")
        self.session.add(BangumiGroupMember(rule_id=rule_id, group_id=group.id))
        await self.session.commit()
        await self.session.refresh(group)
        return group

    async def move_rule(self, rule_id: int, group_id: int) -> None:
        if await self.get_group(group_id) is None:
            raise LookupError(f"Bangumi group {group_id} not found")
        member = await self.session.get(BangumiGroupMember, rule_id)
        old_group_id = member.group_id if member else None
        if member is None:
            member = BangumiGroupMember(rule_id=rule_id, group_id=group_id)
        else:
            member.group_id = group_id
        member.created_at = utc_now()
        self.session.add(member)
        await self.session.execute(
            update(NamingPlan)
            .where(col(NamingPlan.rule_id) == rule_id)
            .values(group_id=group_id, updated_at=utc_now())
        )
        await self.session.flush()
        if old_group_id and old_group_id != group_id:
            count = await self.session.scalar(
                select(func.count())
                .select_from(BangumiGroupMember)
                .where(col(BangumiGroupMember.group_id) == old_group_id)
            )
            if count == 0:
                await self.session.execute(
                    delete(BangumiGroup).where(col(BangumiGroup.id) == old_group_id)
                )
        await self.session.commit()

    async def delete_rule_state(self, rule_id: int) -> None:
        """Remove workbench state that owns foreign keys to a legacy rule."""

        member = await self.session.get(BangumiGroupMember, rule_id)
        group_id = member.group_id if member is not None else None
        result = await self.session.execute(
            select(col(NamingPlan.id)).where(col(NamingPlan.rule_id) == rule_id)
        )
        plan_ids = list(result.scalars().all())
        if plan_ids:
            # A subtitle from another rule may have been explicitly associated
            # with a video owned by this rule. Preserve that plan as an anomaly.
            await self.session.execute(
                update(NamingPlan)
                .where(col(NamingPlan.subtitle_of_id).in_(plan_ids))
                .values(
                    subtitle_of_id=None,
                    target_path=None,
                    anomaly_reason="字幕无法唯一关联到视频",
                    updated_at=utc_now(),
                )
            )
            await self.session.execute(
                delete(NamingExecution).where(
                    col(NamingExecution.plan_id).in_(plan_ids)
                )
            )
            await self.session.execute(
                delete(NamingPlanRevision).where(
                    col(NamingPlanRevision.plan_id).in_(plan_ids)
                )
            )
            await self.session.execute(
                delete(NamingPlan).where(col(NamingPlan.id).in_(plan_ids))
            )
        if member is not None:
            await self.session.delete(member)
        await self.session.flush()
        if group_id is not None:
            member_count = await self.session.scalar(
                select(func.count())
                .select_from(BangumiGroupMember)
                .where(col(BangumiGroupMember.group_id) == group_id)
            )
            if member_count == 0:
                await self.session.execute(
                    delete(BangumiGroup).where(col(BangumiGroup.id) == group_id)
                )
        await self.session.flush()

    async def get_plan(self, plan_id: int) -> NamingPlan | None:
        return await self.session.get(NamingPlan, plan_id)

    async def find_plan(
        self, downloader_type: str, task_id: str, file_index: int
    ) -> NamingPlan | None:
        result = await self.session.execute(
            select(NamingPlan).where(
                col(NamingPlan.downloader_type) == downloader_type,
                col(NamingPlan.task_id) == task_id,
                col(NamingPlan.file_index) == file_index,
            )
        )
        return result.scalar_one_or_none()

    async def mark_unobserved_missing(
        self, downloader_type: str, task_id: str, observed_indexes: set[int]
    ) -> None:
        statement = update(NamingPlan).where(
            col(NamingPlan.downloader_type) == downloader_type,
            col(NamingPlan.task_id) == task_id,
        )
        if observed_indexes:
            statement = statement.where(
                col(NamingPlan.file_index).not_in(observed_indexes)
            )
        await self.session.execute(
            statement.values(discovery_state="missing", updated_at=utc_now())
        )

    async def retryable_plan_ids(self) -> list[int]:
        now = utc_now()
        result = await self.session.execute(
            select(col(NamingExecution.plan_id)).where(
                col(NamingExecution.state).in_(("pending", "retry")),
                col(NamingExecution.retry_at).is_(None)
                | (col(NamingExecution.retry_at) <= now),
            )
        )
        return list(result.scalars().all())
