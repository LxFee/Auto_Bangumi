import asyncio
import logging

from fastapi import APIRouter, Depends, HTTPException

from module.database import Database, get_db
from module.downloader import DownloadClient
from module.manager.episode_naming import (
    BangumiGroupDetail,
    BangumiGroupSummary,
    EpisodeNamingWorkbench,
    GroupMetadataUpdate,
    NamingCorrection,
    ObservedTask,
    SubtitleAssociation,
)
from module.models import BangumiGroup, NamingPlan, NamingPlanRevision, Torrent
from module.security.api import get_current_user

router = APIRouter(
    prefix="/bangumi-groups",
    tags=["episode-naming"],
    dependencies=[Depends(get_current_user)],
)
logger = logging.getLogger(__name__)
_apply_tasks: set[asyncio.Task] = set()


def workbench(db: Database) -> EpisodeNamingWorkbench:
    return EpisodeNamingWorkbench(db.session)


async def _execute_plan(plan_id: int) -> NamingPlanRevision | None:
    try:
        async with DownloadClient() as client, Database() as db:
            return await workbench(db).execute_approved(plan_id, client)
    except Exception:
        logger.warning(
            "Naming plan %s background execution failed", plan_id, exc_info=True
        )
        return None


def _track_task(task: asyncio.Task) -> None:
    _apply_tasks.add(task)
    task.add_done_callback(_apply_tasks.discard)


@router.get("", response_model=list[BangumiGroupSummary])
async def list_groups(db: Database = Depends(get_db)):
    return await workbench(db).list_groups()


@router.get("/by-rule/{rule_id}", response_model=BangumiGroup)
async def get_rule_group(rule_id: int, db: Database = Depends(get_db)):
    try:
        return await workbench(db).get_rule_group(rule_id)
    except LookupError as error:
        raise HTTPException(404, str(error)) from error


@router.post("/plans/{plan_id}/apply", response_model=NamingPlanRevision)
async def apply_plan(plan_id: int, db: Database = Depends(get_db)):
    try:
        manager = workbench(db)
        approved = await manager.approve(plan_id)
        task = asyncio.create_task(_execute_plan(plan_id))
        _track_task(task)
        try:
            completed = await asyncio.wait_for(asyncio.shield(task), timeout=5)
        except TimeoutError:
            return approved
        return completed or approved
    except LookupError as error:
        raise HTTPException(404, str(error)) from error
    except ValueError as error:
        raise HTTPException(409, str(error)) from error


@router.post("/plans/{plan_id}/restore", response_model=NamingPlan)
async def restore_plan(plan_id: int, db: Database = Depends(get_db)):
    try:
        return await workbench(db).restore_default(plan_id)
    except LookupError as error:
        raise HTTPException(404, str(error)) from error
    except ValueError as error:
        raise HTTPException(422, str(error)) from error


@router.post("/plans/{plan_id}/reparse", response_model=NamingPlan)
async def reparse_plan(plan_id: int, db: Database = Depends(get_db)):
    try:
        return await workbench(db).reparse(plan_id)
    except LookupError as error:
        raise HTTPException(404, str(error)) from error


@router.patch("/plans/{plan_id}", response_model=NamingPlan)
async def correct_plan(
    plan_id: int,
    correction: NamingCorrection,
    db: Database = Depends(get_db),
):
    try:
        return await workbench(db).correct(plan_id, correction)
    except LookupError as error:
        raise HTTPException(404, str(error)) from error
    except ValueError as error:
        raise HTTPException(422, str(error)) from error


@router.put("/subtitles/{subtitle_id}/association", response_model=NamingPlan)
async def associate_subtitle(
    subtitle_id: int,
    association: SubtitleAssociation,
    db: Database = Depends(get_db),
):
    try:
        return await workbench(db).associate_subtitle(subtitle_id, association)
    except LookupError as error:
        raise HTTPException(404, str(error)) from error
    except ValueError as error:
        raise HTTPException(422, str(error)) from error


@router.post("/observe", response_model=BangumiGroupDetail)
async def observe_task(task: ObservedTask, db: Database = Depends(get_db)):
    """Internal integration seam; stable enough for downloader adapter tests."""

    try:
        return await workbench(db).observe_task(task)
    except LookupError as error:
        raise HTTPException(404, str(error)) from error


@router.post("/rules/{rule_id}/separate", response_model=BangumiGroup)
async def separate_rule(rule_id: int, db: Database = Depends(get_db)):
    try:
        return await workbench(db).separate_rule(rule_id)
    except LookupError as error:
        raise HTTPException(404, str(error)) from error


@router.get("/{group_id}/torrents", response_model=list[Torrent])
async def get_group_torrents(group_id: int, db: Database = Depends(get_db)):
    try:
        return await workbench(db).get_group_torrents(group_id)
    except LookupError as error:
        raise HTTPException(404, str(error)) from error


@router.delete("/{group_id}/torrents", status_code=204)
async def delete_group_torrents(group_id: int, db: Database = Depends(get_db)):
    try:
        await workbench(db).delete_group_torrents(group_id)
    except LookupError as error:
        raise HTTPException(404, str(error)) from error


@router.delete("/{group_id}/torrents/{torrent_id}", status_code=204)
async def delete_group_torrent(
    group_id: int, torrent_id: int, db: Database = Depends(get_db)
):
    try:
        await workbench(db).delete_group_torrents(group_id, torrent_id)
    except LookupError as error:
        raise HTTPException(404, str(error)) from error


@router.post("/{group_id}/refresh", response_model=BangumiGroupDetail)
async def refresh_group(group_id: int, db: Database = Depends(get_db)):
    manager = workbench(db)
    try:
        async with DownloadClient() as client:
            await manager.sync_from_downloader(client, group_id=group_id, legacy=True)
    except Exception as error:
        # A temporarily offline downloader must not hide already persisted
        # plans. The UI falls back to the persisted detail after surfacing
        # this refresh failure to the user.
        detail = await manager.get_group(group_id)
        if detail is None:
            raise HTTPException(404, "Bangumi group not found") from error
        raise HTTPException(503, f"下载器文件列表刷新失败: {error}") from error
    detail = await manager.get_group(group_id)
    if detail is None:
        raise HTTPException(404, "Bangumi group not found")
    return detail


@router.patch("/{group_id}", response_model=BangumiGroup)
async def update_group(
    group_id: int,
    data: GroupMetadataUpdate,
    db: Database = Depends(get_db),
):
    try:
        return await workbench(db).update_group(group_id, data)
    except LookupError as error:
        raise HTTPException(404, str(error)) from error
    except ValueError as error:
        raise HTTPException(422, str(error)) from error


@router.put("/{group_id}/rules/{rule_id}", status_code=204)
async def move_rule(group_id: int, rule_id: int, db: Database = Depends(get_db)):
    try:
        await workbench(db).move_rule(rule_id, group_id)
    except LookupError as error:
        raise HTTPException(404, str(error)) from error


@router.get("/{group_id}", response_model=BangumiGroupDetail)
async def get_group(group_id: int, db: Database = Depends(get_db)):
    result = await workbench(db).get_group(group_id)
    if result is None:
        raise HTTPException(404, "Bangumi group not found")
    return result
