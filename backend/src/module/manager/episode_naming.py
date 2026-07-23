import json
import logging
import re
import uuid
from datetime import datetime, timedelta, timezone
from pathlib import PurePosixPath
from typing import Any

from pydantic import BaseModel, Field, ValidationError
from sqlalchemy import or_, update
from sqlalchemy.ext.asyncio import AsyncSession
from sqlmodel import col, select

from module.conf import settings
from module.database.episode_naming import EpisodeNamingDatabase
from module.models import (
    Bangumi,
    BangumiGroup,
    BangumiGroupMember,
    NamingExecution,
    NamingPlan,
    NamingPlanRevision,
    Torrent,
)
from module.naming import (
    NamingContext,
    NamingTemplateError,
    custom_template_fields,
    render_custom_name,
)
from module.parser.analyser.torrent_parser import get_subtitle_lang, torrent_parser

logger = logging.getLogger(__name__)

_MEDIA_SUFFIXES = {".mkv", ".mp4"}
_SUBTITLE_SUFFIXES = {".ass", ".srt"}
_RULE_TAG = re.compile(r"(?:^|,\s*)ab:(\d+)(?:,|$)")
_EDITABLE_FIELDS = frozenset({"episode"})


def utc_now() -> datetime:
    return datetime.now(timezone.utc)


class BangumiGroupSummary(BaseModel):
    group: BangumiGroup
    rule_ids: list[int]
    rule_count: int
    plan_count: int
    anomaly_count: int


class BangumiGroupDetail(BaseModel):
    group: BangumiGroup
    rules: list[Bangumi]
    plans: list[NamingPlan]


class ObservedFile(BaseModel):
    index: int = Field(ge=0)
    name: str


class ObservedTask(BaseModel):
    downloader_type: str
    task_id: str
    rule_id: int
    torrent_name: str
    files: list[ObservedFile]
    legacy: bool = False


class NamingCorrection(BaseModel):
    fields: dict[str, str | int | float | None]


class GroupMetadataUpdate(BaseModel):
    official_title: str | None = None
    year: str | None = None
    season: int | None = Field(default=None, ge=0)
    episode_type: str | None = None


class SubtitleAssociation(BaseModel):
    video_plan_id: int | None


class EpisodeNamingWorkbench:
    """Stable group aggregation, naming intent, and resumable execution."""

    def __init__(self, session: AsyncSession):
        self.session = session
        self.repo = EpisodeNamingDatabase(session)

    async def ensure_groups(self) -> None:
        ungrouped = await self.session.execute(
            select(col(Bangumi.id))
            .outerjoin(
                BangumiGroupMember,
                col(BangumiGroupMember.rule_id) == col(Bangumi.id),
            )
            .where(col(BangumiGroupMember.rule_id).is_(None))
        )
        for rule_id in ungrouped.scalars().all():
            await self.repo.ensure_rule_group(rule_id)

    async def list_groups(self) -> list[BangumiGroupSummary]:
        await self.ensure_groups()
        summaries: list[BangumiGroupSummary] = []
        for group in await self.repo.list_groups():
            if group.id is None:
                continue
            rules = await self.repo.get_member_rule_ids(group.id)
            plans = await self.repo.get_group_plans(group.id)
            videos = [plan for plan in plans if plan.file_kind == "video"]
            summaries.append(
                BangumiGroupSummary(
                    group=group,
                    rule_ids=rules,
                    rule_count=len(rules),
                    plan_count=len(videos),
                    anomaly_count=sum(bool(plan.anomaly_reason) for plan in videos),
                )
            )
        return summaries

    async def get_rule_group(self, rule_id: int) -> BangumiGroup:
        return await self.repo.ensure_rule_group(rule_id)

    async def get_group(self, group_id: int) -> BangumiGroupDetail | None:
        group = await self.repo.get_group(group_id)
        if group is None:
            return None
        rules = await self.repo.get_member_rules(group_id)
        plans = await self.repo.get_group_plans(group_id)
        rule_map = {rule.id: rule for rule in rules}
        plan_map = {plan.id: plan for plan in plans}
        for plan in plans:
            rule = rule_map.get(plan.rule_id)
            if rule is not None:
                if plan.file_kind == "video":
                    self._refresh_preview(plan, group, rule)
                else:
                    self._refresh_subtitle_preview(
                        plan, plan_map.get(plan.subtitle_of_id), group, rule
                    )
        await self.session.commit()
        return BangumiGroupDetail(group=group, rules=rules, plans=plans)

    async def update_group(
        self, group_id: int, data: GroupMetadataUpdate
    ) -> BangumiGroup:
        group = await self.repo.get_group(group_id)
        if group is None:
            raise LookupError(f"Bangumi group {group_id} not found")
        changes = data.model_dump(exclude_unset=True)
        if changes.get("episode_type") not in (None, "episode", "movie", "special"):
            raise ValueError("Unsupported episode type")
        for key, value in changes.items():
            setattr(group, key, value)
        group.updated_at = utc_now()
        group.migration_review = False
        group.migration_review_reason = None
        self.session.add(group)
        await self.session.commit()
        await self.session.refresh(group)
        return group

    async def move_rule(self, rule_id: int, group_id: int) -> None:
        await self.repo.move_rule(rule_id, group_id)

    async def separate_rule(self, rule_id: int) -> BangumiGroup:
        rule = await self.session.get(Bangumi, rule_id)
        current = await self.repo.get_rule_group(rule_id)
        if rule is None or current is None:
            raise LookupError(f"Bangumi rule {rule_id} not found")
        if current.id is None:
            raise RuntimeError("Bangumi group has no id")
        members = await self.repo.get_member_rule_ids(current.id)
        if len(members) == 1:
            return current
        group = BangumiGroup(
            official_title=current.official_title,
            year=current.year,
            season=current.season,
            episode_type=current.episode_type,
            poster_link=current.poster_link,
            air_weekday=current.air_weekday,
        )
        self.session.add(group)
        await self.session.flush()
        if group.id is None:
            raise RuntimeError("Bangumi group did not receive an id")
        await self.repo.move_rule(rule_id, group.id)
        return group

    async def get_group_torrents(self, group_id: int) -> list[Torrent]:
        rule_ids = await self.repo.get_member_rule_ids(group_id)
        if not rule_ids and await self.repo.get_group(group_id) is None:
            raise LookupError(f"Bangumi group {group_id} not found")
        result = await self.session.execute(
            select(Torrent)
            .where(col(Torrent.bangumi_id).in_(rule_ids))
            .order_by(col(Torrent.id).desc())
        )
        return list(result.scalars().all())

    async def delete_group_torrents(
        self, group_id: int, torrent_id: int | None = None
    ) -> int:
        torrents = await self.get_group_torrents(group_id)
        selected = (
            [item for item in torrents if item.id == torrent_id]
            if torrent_id is not None
            else torrents
        )
        if torrent_id is not None and not selected:
            raise LookupError(f"Torrent {torrent_id} not found in group {group_id}")
        for item in selected:
            await self.session.delete(item)
        await self.session.commit()
        return len(selected)

    async def observe_task(self, task: ObservedTask) -> BangumiGroupDetail:
        group = await self.repo.ensure_rule_group(task.rule_id)
        if group.id is None:
            raise RuntimeError("Bangumi group did not receive an id")
        rule = await self.session.get(Bangumi, task.rule_id)
        if rule is None:
            raise LookupError(f"Bangumi rule {task.rule_id} not found")

        observed_indexes: set[int] = set()
        for item in task.files:
            normalized = item.name.replace("\\", "/")
            suffix = PurePosixPath(normalized).suffix.lower()
            file_kind = (
                "video"
                if suffix in _MEDIA_SUFFIXES
                else "subtitle" if suffix in _SUBTITLE_SUFFIXES else None
            )
            if file_kind is None:
                continue
            observed_indexes.add(item.index)
            plan = await self.repo.find_plan(
                task.downloader_type, task.task_id, item.index
            )
            if plan is None:
                snapshot = self._parse_snapshot(
                    normalized, task.torrent_name, group, rule, file_kind
                )
                plan = NamingPlan(
                    group_id=group.id,
                    rule_id=task.rule_id,
                    downloader_type=task.downloader_type,
                    task_id=task.task_id,
                    file_index=item.index,
                    file_kind=file_kind,
                    baseline_path=normalized,
                    current_path=normalized,
                    default_snapshot=self._dump(snapshot),
                    required_fields=self._dump(self._required_fields()),
                    origin="legacy" if task.legacy else "new",
                )
            else:
                plan.group_id = group.id
                plan.rule_id = task.rule_id
                plan.current_path = normalized
                plan.discovery_state = "active"
                plan.updated_at = utc_now()
            self.session.add(plan)
            await self.session.flush()

        await self.repo.mark_unobserved_missing(
            task.downloader_type, task.task_id, observed_indexes
        )
        await self._associate_subtitles(task.downloader_type, task.task_id)
        await self._refresh_task(task.downloader_type, task.task_id, group, rule)
        await self.session.commit()
        detail = await self.get_group(group.id)
        if detail is None:
            raise RuntimeError("Observed group disappeared")
        return detail

    async def correct(self, plan_id: int, correction: NamingCorrection) -> NamingPlan:
        plan, group, rule = await self._plan_context(plan_id)
        if plan.file_kind != "video":
            raise ValueError("Only video fields can be corrected directly")
        unknown = set(correction.fields) - _EDITABLE_FIELDS
        if unknown:
            raise ValueError(
                "Unsupported per-file fields: " + ", ".join(sorted(unknown))
            )
        cleaned = {
            key: value
            for key, value in correction.fields.items()
            if value not in (None, "")
        }
        episode = cleaned.get("episode")
        if episode is not None:
            try:
                cleaned["episode"] = float(episode)
            except (TypeError, ValueError) as error:
                raise ValueError("episode must be a number") from error
        plan.manual_fields = self._dump(cleaned) if cleaned else None
        plan.updated_at = utc_now()
        self._refresh_preview(plan, group, rule)
        await self._refresh_subtitles(plan, group, rule)
        self.session.add(plan)
        await self.session.commit()
        await self.session.refresh(plan)
        return plan

    async def restore_default(self, plan_id: int) -> NamingPlan:
        return await self.correct(plan_id, NamingCorrection(fields={}))

    async def reparse(self, plan_id: int) -> NamingPlan:
        plan, group, rule = await self._plan_context(plan_id)
        plan.default_snapshot = self._dump(
            self._parse_snapshot(
                plan.current_path,
                None,
                group,
                rule,
                plan.file_kind,
            )
        )
        plan.updated_at = utc_now()
        self._refresh_preview(plan, group, rule)
        if plan.file_kind == "video":
            await self._refresh_subtitles(plan, group, rule)
        self.session.add(plan)
        await self.session.commit()
        await self.session.refresh(plan)
        return plan

    async def associate_subtitle(
        self, subtitle_id: int, association: SubtitleAssociation
    ) -> NamingPlan:
        subtitle = await self.repo.get_plan(subtitle_id)
        if subtitle is None or subtitle.file_kind != "subtitle":
            raise LookupError(f"Subtitle plan {subtitle_id} not found")
        manual = self._loads(subtitle.manual_fields)
        video = None
        if association.video_plan_id is not None:
            video = await self.repo.get_plan(association.video_plan_id)
            if (
                video is None
                or video.file_kind != "video"
                or video.task_id != subtitle.task_id
                or video.downloader_type != subtitle.downloader_type
            ):
                raise ValueError("Subtitle and video must belong to the same task")
            subtitle.subtitle_of_id = video.id
            manual["_subtitle_of_id"] = video.id
        else:
            subtitle.subtitle_of_id = None
            manual["_subtitle_of_id"] = None
        subtitle.manual_fields = self._dump(manual)
        group = await self.repo.get_group(subtitle.group_id)
        rule = await self.session.get(Bangumi, subtitle.rule_id)
        if group and rule:
            self._refresh_subtitle_preview(subtitle, video, group, rule)
        self.session.add(subtitle)
        await self.session.commit()
        await self.session.refresh(subtitle)
        return subtitle

    async def approve(self, plan_id: int) -> NamingPlanRevision:
        plan, group, rule = await self._plan_context(plan_id)
        if plan.file_kind != "video":
            raise ValueError("Only a video plan can lead a naming unit")
        self._refresh_preview(plan, group, rule)
        await self._refresh_subtitles(plan, group, rule)
        subtitles = await self._subtitles(plan_id)
        unit = [plan, *subtitles]
        anomalies = [item.anomaly_reason for item in unit if item.anomaly_reason]
        if anomalies:
            raise ValueError("; ".join(dict.fromkeys(anomalies)))
        targets = [item.target_path for item in unit]
        if len(set(targets)) != len(targets):
            raise ValueError("命名单元内存在重复目标名称")

        result = await self.session.execute(
            select(NamingPlanRevision.revision)
            .where(col(NamingPlanRevision.plan_id) == plan_id)
            .order_by(col(NamingPlanRevision.revision).desc())
        )
        revision_number = (result.scalars().first() or 0) + 1
        await self.session.execute(
            update(NamingPlanRevision)
            .where(
                col(NamingPlanRevision.plan_id) == plan_id,
                col(NamingPlanRevision.state).in_(
                    ("approved", "running", "retry", "blocked")
                ),
            )
            .values(state="superseded")
        )
        manifest = [
            {
                "plan_id": item.id,
                "file_index": item.file_index,
                "source": item.current_path,
                "target": item.target_path,
            }
            for item in unit
        ]
        now = utc_now()
        revision = NamingPlanRevision(
            plan_id=plan_id,
            revision=revision_number,
            state="approved",
            field_snapshot=self._dump(self._effective_fields(plan)),
            target_manifest=self._dump(manifest),
            approved_at=now,
        )
        self.session.add(revision)
        await self.session.flush()
        execution = await self.session.get(NamingExecution, plan_id)
        if execution is None:
            execution = NamingExecution(plan_id=plan_id)
        execution.approved_revision_id = revision.id
        execution.state = "pending"
        execution.retry_at = None
        execution.last_error = None
        execution.updated_at = now
        self.session.add(execution)
        await self.session.commit()
        await self.session.refresh(revision)
        return revision

    async def execute_approved(self, plan_id: int, client: Any) -> NamingPlanRevision:
        execution = await self.session.get(NamingExecution, plan_id)
        if execution is None or execution.approved_revision_id is None:
            raise LookupError(f"Naming plan {plan_id} has no approved revision")
        revision = await self.session.get(
            NamingPlanRevision, execution.approved_revision_id
        )
        if revision is None:
            raise LookupError("Approved revision not found")

        owner = uuid.uuid4().hex
        now = utc_now()
        claimed = await self.session.execute(
            update(NamingExecution)
            .where(
                col(NamingExecution.plan_id) == plan_id,
                col(NamingExecution.approved_revision_id) == revision.id,
                or_(
                    col(NamingExecution.state).in_(("pending", "retry")),
                    (col(NamingExecution.state) == "running")
                    & (col(NamingExecution.lease_expires_at) < now),
                ),
            )
            .values(
                state="running",
                lease_owner=owner,
                lease_expires_at=now + timedelta(minutes=5),
                fence_token=NamingExecution.fence_token + 1,
                updated_at=now,
            )
        )
        await self.session.commit()
        if not getattr(claimed, "rowcount", 0):
            return revision
        await self.session.refresh(execution)
        revision.state = "running"
        self.session.add(revision)
        await self.session.commit()
        fence = execution.fence_token
        manifest: list[dict[str, Any]] = self._loads(revision.target_manifest)
        leader = await self.repo.get_plan(plan_id)
        if leader is None:
            raise LookupError(f"Naming plan {plan_id} not found")

        files = await client.get_torrent_files(leader.task_id)
        by_index = {
            int(item.get("index", index)): str(item.get("name", "")).replace("\\", "/")
            for index, item in enumerate(files)
        }
        visible = set(by_index.values())
        sources = {str(item["source"]) for item in manifest}
        for item in manifest:
            current = by_index.get(int(item["file_index"]))
            target = str(item["target"])
            source = str(item["source"])
            if current == target:
                continue
            if current != source:
                await self._finish_execution(
                    execution,
                    revision,
                    "blocked",
                    f"文件序号 {item['file_index']} 当前路径已变化: {current or '不可见'}",
                )
                return revision
            if target in visible and target not in sources:
                await self._finish_execution(
                    execution, revision, "blocked", f"目标已存在: {target}"
                )
                return revision

        for item in manifest:
            if not await self._owns_execution(execution, revision, owner, fence):
                return revision
            plan = await self.repo.get_plan(int(item["plan_id"]))
            if plan is None:
                await self._finish_execution(
                    execution, revision, "blocked", "命名计划已不存在"
                )
                return revision
            target = str(item["target"])
            if by_index.get(int(item["file_index"])) == target:
                plan.current_path = target
                self.session.add(plan)
                await self.session.commit()
                continue
            result = await client.rename_torrent_file(
                leader.task_id, str(item["source"]), target
            )
            if not result.succeeded:
                await self._finish_execution(
                    execution,
                    revision,
                    "retry",
                    result.detail or "下载器重命名失败",
                )
                return revision
            # The external mutation already happened. Persist that fact before
            # checking whether a newer revision superseded this worker.
            plan.current_path = target
            plan.updated_at = utc_now()
            self.session.add(plan)
            await self.session.commit()
            by_index[int(item["file_index"])] = target

        if not await self._owns_execution(execution, revision, owner, fence):
            return revision
        now = utc_now()
        revision.state = "applied"
        revision.applied_at = now
        revision.last_error = None
        execution.state = "done"
        execution.applied_revision_id = revision.id
        execution.lease_owner = None
        execution.lease_expires_at = None
        execution.retry_at = None
        execution.last_error = None
        execution.updated_at = now
        self.session.add_all([revision, execution])
        await self.session.commit()
        await self.session.refresh(revision)
        return revision

    async def retry_approved(self, client: Any) -> None:
        for plan_id in await self.repo.retryable_plan_ids():
            try:
                await self.execute_approved(plan_id, client)
            except Exception:
                logger.warning("Failed retrying naming plan %s", plan_id, exc_info=True)

    async def sync_from_downloader(
        self,
        client: Any,
        *,
        group_id: int | None = None,
        legacy: bool = False,
    ) -> None:
        await self.ensure_groups()
        rules = (
            await self.repo.get_member_rules(group_id)
            if group_id is not None
            else list((await self.session.execute(select(Bangumi))).scalars().all())
        )
        rule_ids = {rule.id for rule in rules if rule.id is not None}
        if not rule_ids:
            return

        torrent_rows = list(
            (
                await self.session.execute(
                    select(Torrent).where(col(Torrent.bangumi_id).in_(rule_ids))
                )
            )
            .scalars()
            .all()
        )
        task_to_rule = {
            item.qb_hash: item.bangumi_id
            for item in torrent_rows
            if item.qb_hash and item.bangumi_id
        }
        infos: list[dict[str, Any]] = []
        for category in ("Bangumi", "BangumiCollection"):
            items = await client.get_torrent_info(
                category=category, status_filter="all"
            )
            infos.extend(items or [])

        seen_tasks: set[str] = set()
        for info in infos:
            task_id = str(info.get("hash") or "")
            if not task_id:
                continue
            rule_id = self._rule_from_tags(str(info.get("tags") or ""))
            rule_id = rule_id or task_to_rule.get(task_id)
            if rule_id not in rule_ids:
                continue
            files = await client.get_torrent_files(task_id)
            if not files:
                continue
            seen_tasks.add(task_id)
            observed = [
                ObservedFile(
                    index=int(item.get("index", index)),
                    name=str(item.get("name", "")),
                )
                for index, item in enumerate(files)
                if item.get("name")
            ]
            await self.observe_task(
                ObservedTask(
                    downloader_type=str(settings.downloader.type),
                    task_id=task_id,
                    rule_id=int(rule_id),
                    torrent_name=str(info.get("name") or task_id),
                    files=observed,
                    legacy=legacy or self._has_renamed_tag(str(info.get("tags") or "")),
                )
            )

        # A successful complete snapshot is evidence of temporary absence, not
        # deletion. Keep plans and manual fields for later reattachment.
        result = await self.session.execute(
            select(NamingPlan).where(col(NamingPlan.rule_id).in_(rule_ids))
        )
        for plan in result.scalars().all():
            if plan.task_id not in seen_tasks:
                plan.discovery_state = "missing"
                plan.updated_at = utc_now()
                self.session.add(plan)
        await self.session.commit()

    async def _plan_context(
        self, plan_id: int
    ) -> tuple[NamingPlan, BangumiGroup, Bangumi]:
        plan = await self.repo.get_plan(plan_id)
        if plan is None:
            raise LookupError(f"Naming plan {plan_id} not found")
        group = await self.repo.get_group(plan.group_id)
        rule = await self.session.get(Bangumi, plan.rule_id)
        if group is None or rule is None:
            raise LookupError("Naming plan group or rule not found")
        return plan, group, rule

    async def _subtitles(self, plan_id: int) -> list[NamingPlan]:
        result = await self.session.execute(
            select(NamingPlan).where(NamingPlan.subtitle_of_id == plan_id)
        )
        return list(result.scalars().all())

    async def _refresh_subtitles(
        self, video: NamingPlan, group: BangumiGroup, rule: Bangumi
    ) -> None:
        if video.id is None:
            return
        for subtitle in await self._subtitles(video.id):
            self._refresh_subtitle_preview(subtitle, video, group, rule)
            self.session.add(subtitle)

    async def _refresh_task(
        self,
        downloader_type: str,
        task_id: str,
        group: BangumiGroup,
        rule: Bangumi,
    ) -> None:
        result = await self.session.execute(
            select(NamingPlan).where(
                NamingPlan.downloader_type == downloader_type,
                NamingPlan.task_id == task_id,
            )
        )
        plans = list(result.scalars().all())
        by_id = {plan.id: plan for plan in plans}
        for plan in plans:
            if plan.file_kind == "video":
                self._refresh_preview(plan, group, rule)
            else:
                self._refresh_subtitle_preview(
                    plan, by_id.get(plan.subtitle_of_id), group, rule
                )
            self.session.add(plan)

    async def _associate_subtitles(self, downloader_type: str, task_id: str) -> None:
        result = await self.session.execute(
            select(NamingPlan).where(
                NamingPlan.downloader_type == downloader_type,
                NamingPlan.task_id == task_id,
            )
        )
        plans = list(result.scalars().all())
        videos = [item for item in plans if item.file_kind == "video"]
        for subtitle in (item for item in plans if item.file_kind == "subtitle"):
            manual = self._loads(subtitle.manual_fields)
            if "_subtitle_of_id" in manual:
                subtitle.subtitle_of_id = manual["_subtitle_of_id"]
                self.session.add(subtitle)
                continue
            episode = self._effective_fields(subtitle).get("episode")
            candidates = [
                video
                for video in videos
                if episode is not None
                and self._effective_fields(video).get("episode") == episode
            ]
            if not candidates and episode is None:
                subtitle_stem = self._association_stem(subtitle.current_path)
                candidates = [
                    video
                    for video in videos
                    if self._association_stem(video.current_path) == subtitle_stem
                ]
            if len(candidates) == 1:
                subtitle.subtitle_of_id = candidates[0].id
                subtitle.anomaly_reason = None
            elif len(videos) == 1 and episode is None:
                subtitle.subtitle_of_id = videos[0].id
                subtitle.anomaly_reason = None
            else:
                subtitle.subtitle_of_id = None
                subtitle.target_path = None
                subtitle.anomaly_reason = "字幕无法唯一关联到视频"
            self.session.add(subtitle)

    def _parse_snapshot(
        self,
        path: str,
        torrent_name: str | None,
        group: BangumiGroup,
        rule: Bangumi,
        file_kind: str,
    ) -> dict[str, Any]:
        parsed = None
        try:
            parsed = torrent_parser(
                path,
                torrent_name,
                season=group.season,
                file_type="media" if file_kind == "video" else "subtitle",
                episode_type=group.episode_type,
            )
        except (ValidationError, ValueError, TypeError):
            logger.debug("Unable to parse naming plan path %s", path, exc_info=True)
        return {
            "episode": parsed.episode if parsed else None,
            "language": (
                getattr(parsed, "language", None)
                if parsed
                else (
                    get_subtitle_lang(PurePosixPath(path).name)
                    if file_kind == "subtitle"
                    else None
                )
            ),
            "parsed_title": parsed.title if parsed else None,
            "parsed_group": parsed.group if parsed else rule.group_name,
        }

    def _required_fields(self) -> tuple[str, ...]:
        method = settings.bangumi_manage.rename_method
        if method == "custom":
            return custom_template_fields(settings.bangumi_manage.custom_bangumi_file)
        if method in ("none", "normal"):
            return ()
        return ("title", "season", "episode")

    def _effective_fields(self, plan: NamingPlan) -> dict[str, Any]:
        values = self._loads(plan.default_snapshot)
        values.update(
            {
                key: value
                for key, value in self._loads(plan.manual_fields).items()
                if not key.startswith("_")
            }
        )
        return values

    def _refresh_preview(
        self, plan: NamingPlan, group: BangumiGroup, rule: Bangumi
    ) -> None:
        required = self._required_fields()
        plan.required_fields = self._dump(required)
        if plan.discovery_state == "missing":
            plan.anomaly_reason = "下载器中暂时找不到该任务"
            plan.target_path = None
            return
        values = self._effective_fields(plan)
        parsed_episode = values.get("episode")
        effective_episode = None
        if parsed_episode is not None:
            effective_episode = self._adjust_episode(
                parsed_episode, rule.episode_offset
            )
        context: dict[str, Any] = {
            "title": group.official_title,
            "year": group.year,
            "season": group.season,
            "episode": effective_episode,
            "group": rule.group_name or values.get("parsed_group"),
            "hash": plan.task_id,
        }
        missing = [field for field in required if context.get(field) in (None, "")]
        if missing:
            plan.target_path = None
            plan.anomaly_reason = "缺少字段: " + ", ".join(missing)
            return
        suffix = PurePosixPath(plan.current_path).suffix
        try:
            if settings.bangumi_manage.rename_method in ("none", "normal"):
                target_name = PurePosixPath(plan.current_path).name
            elif settings.bangumi_manage.rename_method == "custom":
                target_name = render_custom_name(
                    settings.bangumi_manage.custom_bangumi_file,
                    NamingContext(
                        title=str(context["title"]),
                        year=context["year"],
                        season=context["season"],
                        episode=context["episode"],
                        group=context["group"],
                        torrent_hash=context["hash"],
                    ),
                    suffix=suffix,
                )
            else:
                target_name = f"{context['title']} S{int(context['season']):02}E{self._format_episode(context['episode'])}{suffix}"
        except (NamingTemplateError, TypeError, ValueError) as error:
            plan.target_path = None
            plan.anomaly_reason = f"目标名称无效: {error}"
            return
        plan.target_path = str(PurePosixPath(plan.current_path).with_name(target_name))
        plan.anomaly_reason = None
        plan.updated_at = utc_now()

    def _refresh_subtitle_preview(
        self,
        subtitle: NamingPlan,
        video: NamingPlan | None,
        group: BangumiGroup,
        rule: Bangumi,
    ) -> None:
        if video is None or video.target_path is None:
            subtitle.target_path = None
            subtitle.anomaly_reason = "字幕无法唯一关联到视频"
            return
        language = self._effective_fields(subtitle).get("language")
        if not language:
            subtitle.target_path = None
            subtitle.anomaly_reason = "缺少字段: language"
            return
        video_target = PurePosixPath(video.target_path)
        suffix = PurePosixPath(subtitle.current_path).suffix
        target_name = f"{video_target.stem}.{language}{suffix}"
        subtitle.target_path = str(
            PurePosixPath(subtitle.current_path).with_name(target_name)
        )
        subtitle.required_fields = self._dump(("language",))
        subtitle.anomaly_reason = None
        subtitle.updated_at = utc_now()

    async def _owns_execution(
        self,
        execution: NamingExecution,
        revision: NamingPlanRevision,
        owner: str,
        fence: int,
    ) -> bool:
        await self.session.refresh(execution)
        return (
            execution.lease_owner == owner
            and execution.fence_token == fence
            and execution.approved_revision_id == revision.id
        )

    async def _finish_execution(
        self,
        execution: NamingExecution,
        revision: NamingPlanRevision,
        state: str,
        reason: str,
    ) -> None:
        execution.state = state
        execution.last_error = reason
        execution.lease_owner = None
        execution.lease_expires_at = None
        execution.retry_at = (
            utc_now() + timedelta(minutes=1) if state == "retry" else None
        )
        execution.updated_at = utc_now()
        revision.state = state
        revision.last_error = reason
        self.session.add_all([execution, revision])
        await self.session.commit()

    @staticmethod
    def _adjust_episode(value: int | float, offset: int) -> int | float:
        result = float(value) + offset
        if result <= 0 and float(value) != 0:
            return value
        return int(result) if result.is_integer() else result

    @staticmethod
    def _format_episode(value: Any) -> str:
        number = float(value)
        return f"{int(number):02}" if number.is_integer() else str(number)

    @staticmethod
    def _association_stem(path: str) -> str:
        stem = PurePosixPath(path.replace("\\", "/")).stem.lower()
        stem = re.sub(r"(?:[._ -](?:zh(?:-tw)?|chs|cht|sc|tc))+$", "", stem)
        return re.sub(r"[^a-z0-9\u4e00-\u9fff]+", "", stem)

    @staticmethod
    def _rule_from_tags(tags: str) -> int | None:
        match = _RULE_TAG.search(tags)
        return int(match.group(1)) if match else None

    @staticmethod
    def _has_renamed_tag(tags: str) -> bool:
        return "ab:renamed" in (part.strip() for part in tags.split(","))

    @staticmethod
    def _dump(value: Any) -> str:
        return json.dumps(value, ensure_ascii=False, separators=(",", ":"))

    @staticmethod
    def _loads(value: str | None) -> Any:
        if not value:
            return {}
        try:
            return json.loads(value)
        except (TypeError, json.JSONDecodeError):
            return {}
