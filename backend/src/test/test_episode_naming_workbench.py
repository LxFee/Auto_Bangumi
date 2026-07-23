import json
from typing import TypeVar
from unittest.mock import AsyncMock

import pytest

from module.downloader import RenameOutcome, RenameResult
from module.manager.episode_naming import (
    EpisodeNamingWorkbench,
    GroupMetadataUpdate,
    NamingCorrection,
    ObservedFile,
    ObservedTask,
    SubtitleAssociation,
)
from module.models import Bangumi, NamingExecution, Torrent

T = TypeVar("T")


def required(value: T | None) -> T:
    assert value is not None
    return value


def rule(title_raw: str, group_name: str) -> Bangumi:
    return Bangumi(
        official_title="尼古喵喵",
        title_raw=title_raw,
        year="2026",
        season=1,
        season_raw="S01",
        group_name=group_name,
        dpi="1080p",
        source="WebRip",
        subtitle="简繁日内封",
        rss_link="",
    )


@pytest.mark.asyncio
async def test_group_aggregates_rules_and_observed_episode_plans(
    db_session, monkeypatch
):
    monkeypatch.setattr(
        "module.manager.episode_naming.settings.bangumi_manage.custom_bangumi_file",
        "{title} S{season:02}E{episode:02}",
    )
    first = rule("Neko", "NEST")
    second = rule("Neko alt", "樱桃花字幕组")
    db_session.add_all([first, second])
    await db_session.commit()
    await db_session.refresh(first)
    await db_session.refresh(second)
    workbench = EpisodeNamingWorkbench(db_session)

    detail = await workbench.observe_task(
        ObservedTask(
            downloader_type="qbittorrent",
            task_id="abcdef123456",
            rule_id=first.id,
            torrent_name="[NEST] Neko - 02 [1080p]",
            files=[
                ObservedFile(index=0, name="Neko/[NEST] Neko - 02.mkv"),
                ObservedFile(index=1, name="Neko/[NEST] Neko - 02 [CHS].ass"),
            ],
        )
    )
    await workbench.observe_task(
        ObservedTask(
            downloader_type="qbittorrent",
            task_id="fedcba654321",
            rule_id=second.id,
            torrent_name="[樱桃花字幕组] Neko alt - 03 [1080p]",
            files=[ObservedFile(index=0, name="Neko/Neko alt - 03.mkv")],
        )
    )
    refreshed = await workbench.get_group(required(detail.group.id))
    assert refreshed is not None
    detail = refreshed
    assert [item.id for item in detail.rules] == [first.id, second.id]
    assert len(detail.plans) == 3
    video = next(
        item
        for item in detail.plans
        if item.file_index == 0 and item.task_id.startswith("abc")
    )
    subtitle = next(item for item in detail.plans if item.file_kind == "subtitle")
    assert video.target_path == "Neko/尼古喵喵 S01E02.mkv"
    assert subtitle.subtitle_of_id == video.id
    assert video.anomaly_reason is None


@pytest.mark.asyncio
async def test_switching_group_to_movie_rebuilds_plan_with_movie_template(
    db_session, monkeypatch
):
    monkeypatch.setattr(
        "module.manager.episode_naming.settings.bangumi_manage.rename_method",
        "custom",
    )
    monkeypatch.setattr(
        "module.manager.episode_naming.settings.bangumi_manage.custom_bangumi_file",
        "{title} S{season:02}E{episode:02}",
    )
    monkeypatch.setattr(
        "module.manager.episode_naming.settings.bangumi_manage.custom_movie_file",
        "{title} {year:()} {group:[]} {hash:[]}",
    )
    item = rule("Look Back", "SweetSub")
    item.official_title = "蓦然回首"
    item.year = "2024"
    db_session.add(item)
    await db_session.commit()
    await db_session.refresh(item)
    workbench = EpisodeNamingWorkbench(db_session)
    detail = await workbench.observe_task(
        ObservedTask(
            downloader_type="qbittorrent",
            task_id="movie1234567890",
            rule_id=item.id,
            torrent_name="[SweetSub] Look Back",
            files=[ObservedFile(index=0, name="Look Back.mkv")],
        )
    )
    plan = detail.plans[0]
    assert plan.anomaly_reason == "缺少字段: episode"

    await workbench.update_group(
        required(detail.group.id), GroupMetadataUpdate(episode_type="movie")
    )
    await db_session.refresh(plan)

    assert json.loads(plan.required_fields) == ["title", "year", "group", "hash"]
    assert plan.target_path == "蓦然回首 (2024) [SweetSub] [movie1].mkv"
    assert plan.anomaly_reason is None


@pytest.mark.asyncio
async def test_manual_episode_correction_can_be_approved_as_one_naming_unit(
    db_session, monkeypatch
):
    monkeypatch.setattr(
        "module.manager.episode_naming.settings.bangumi_manage.custom_bangumi_file",
        "{title} S{season:02}E{episode:02}",
    )
    item = rule("Neko", "NEST")
    db_session.add(item)
    await db_session.commit()
    await db_session.refresh(item)
    workbench = EpisodeNamingWorkbench(db_session)
    detail = await workbench.observe_task(
        ObservedTask(
            downloader_type="qbittorrent",
            task_id="task-with-bad-title",
            rule_id=item.id,
            torrent_name="Neko unknown",
            files=[ObservedFile(index=0, name="Neko/unknown.mkv")],
        )
    )
    plan = detail.plans[0]
    assert plan.anomaly_reason == "缺少字段: episode"
    plan_id = required(plan.id)

    corrected = await workbench.correct(
        plan_id, NamingCorrection(fields={"episode": 2})
    )
    revision = await workbench.approve(plan_id)

    assert json.loads(required(corrected.manual_fields)) == {"episode": 2}
    assert corrected.target_path == "Neko/尼古喵喵 S01E02.mkv"
    assert revision.revision == 1
    assert revision.state == "approved"
    assert json.loads(revision.target_manifest) == [
        {
            "plan_id": plan_id,
            "file_index": 0,
            "source": "Neko/unknown.mkv",
            "target": "Neko/尼古喵喵 S01E02.mkv",
        }
    ]

    client = AsyncMock()
    client.get_torrent_files.return_value = [{"index": 0, "name": "Neko/unknown.mkv"}]
    client.rename_torrent_file.return_value = RenameResult(RenameOutcome.RENAMED)
    applied = await workbench.execute_approved(plan_id, client)
    assert applied.state == "applied"
    client.rename_torrent_file.assert_awaited_once_with(
        "task-with-bad-title",
        "Neko/unknown.mkv",
        "Neko/尼古喵喵 S01E02.mkv",
    )


@pytest.mark.asyncio
async def test_manual_episode_and_rule_offset_remain_independent(
    db_session, monkeypatch
):
    monkeypatch.setattr(
        "module.manager.episode_naming.settings.bangumi_manage.custom_bangumi_file",
        "{title} S{season:02}E{episode:02}",
    )
    item = rule("Neko", "NEST")
    item.episode_offset = 2
    db_session.add(item)
    await db_session.commit()
    await db_session.refresh(item)
    workbench = EpisodeNamingWorkbench(db_session)
    detail = await workbench.observe_task(
        ObservedTask(
            downloader_type="qbittorrent",
            task_id="offset-task",
            rule_id=item.id,
            torrent_name="Neko - 02",
            files=[ObservedFile(index=0, name="Neko - 02.mkv")],
        )
    )
    plan = detail.plans[0]
    plan_id = required(plan.id)

    assert json.loads(plan.default_snapshot)["episode"] == 2
    assert plan.target_path == "尼古喵喵 S01E04.mkv"

    corrected = await workbench.correct(
        plan_id, NamingCorrection(fields={"episode": 5})
    )
    assert json.loads(required(corrected.manual_fields))["episode"] == 5
    assert corrected.target_path == "尼古喵喵 S01E07.mkv"


@pytest.mark.asyncio
async def test_collection_anomaly_is_isolated_per_video(db_session, monkeypatch):
    monkeypatch.setattr(
        "module.manager.episode_naming.settings.bangumi_manage.custom_bangumi_file",
        "{title} S{season:02}E{episode:02}",
    )
    item = rule("Neko", "NEST")
    db_session.add(item)
    await db_session.commit()
    await db_session.refresh(item)
    workbench = EpisodeNamingWorkbench(db_session)
    detail = await workbench.observe_task(
        ObservedTask(
            downloader_type="qbittorrent",
            task_id="collection-task",
            rule_id=item.id,
            torrent_name="Neko collection",
            files=[
                ObservedFile(index=0, name="Neko - 03.mkv"),
                ObservedFile(index=1, name="unknown.mkv"),
            ],
        )
    )
    valid = next(plan for plan in detail.plans if plan.file_index == 0)
    invalid = next(plan for plan in detail.plans if plan.file_index == 1)

    assert valid.anomaly_reason is None
    assert invalid.anomaly_reason == "缺少字段: episode"
    assert (await workbench.approve(required(valid.id))).state == "approved"


@pytest.mark.asyncio
async def test_ambiguous_subtitle_requires_explicit_association(
    db_session, monkeypatch
):
    monkeypatch.setattr(
        "module.manager.episode_naming.settings.bangumi_manage.custom_bangumi_file",
        "{title} S{season:02}E{episode:02}",
    )
    item = rule("Neko", "NEST")
    db_session.add(item)
    await db_session.commit()
    await db_session.refresh(item)
    workbench = EpisodeNamingWorkbench(db_session)
    detail = await workbench.observe_task(
        ObservedTask(
            downloader_type="qbittorrent",
            task_id="subtitle-task",
            rule_id=item.id,
            torrent_name="Neko collection",
            files=[
                ObservedFile(index=0, name="Neko - 01.mkv"),
                ObservedFile(index=1, name="Neko - 02.mkv"),
                ObservedFile(index=2, name="Subs/unknown [CHS].ass"),
            ],
        )
    )
    subtitle = next(plan for plan in detail.plans if plan.file_kind == "subtitle")
    video = next(
        plan
        for plan in detail.plans
        if plan.file_kind == "video" and plan.file_index == 1
    )
    assert subtitle.subtitle_of_id is None
    assert subtitle.anomaly_reason == "字幕无法唯一关联到视频"
    subtitle_id = required(subtitle.id)
    video_id = required(video.id)

    associated = await workbench.associate_subtitle(
        subtitle_id, SubtitleAssociation(video_plan_id=video_id)
    )
    assert associated.subtitle_of_id == video_id
    assert associated.target_path == "Subs/尼古喵喵 S01E02.zh.ass"


@pytest.mark.asyncio
async def test_partial_unit_failure_retries_only_remaining_file(
    db_session, monkeypatch
):
    monkeypatch.setattr(
        "module.manager.episode_naming.settings.bangumi_manage.custom_bangumi_file",
        "{title} S{season:02}E{episode:02}",
    )
    item = rule("Neko", "NEST")
    db_session.add(item)
    await db_session.commit()
    await db_session.refresh(item)
    workbench = EpisodeNamingWorkbench(db_session)
    detail = await workbench.observe_task(
        ObservedTask(
            downloader_type="qbittorrent",
            task_id="retry-task",
            rule_id=item.id,
            torrent_name="Neko - 02",
            files=[
                ObservedFile(index=0, name="Neko - 02.mkv"),
                ObservedFile(index=1, name="Neko - 02 [CHS].ass"),
            ],
        )
    )
    video = next(plan for plan in detail.plans if plan.file_kind == "video")
    video_id = required(video.id)
    await workbench.approve(video_id)

    first = AsyncMock()
    first.get_torrent_files.return_value = [
        {"index": 0, "name": "Neko - 02.mkv"},
        {"index": 1, "name": "Neko - 02 [CHS].ass"},
    ]
    first.rename_torrent_file.side_effect = [
        RenameResult(RenameOutcome.RENAMED),
        RenameResult(RenameOutcome.RETRYABLE_FAILURE, detail="offline"),
    ]
    failed = await workbench.execute_approved(video_id, first)
    assert failed.state == "retry"

    execution = await db_session.get(NamingExecution, video_id)
    assert execution is not None
    execution.retry_at = None
    db_session.add(execution)
    await db_session.commit()
    second = AsyncMock()
    second.get_torrent_files.return_value = [
        {"index": 0, "name": "尼古喵喵 S01E02.mkv"},
        {"index": 1, "name": "Neko - 02 [CHS].ass"},
    ]
    second.rename_torrent_file.return_value = RenameResult(RenameOutcome.RENAMED)
    applied = await workbench.execute_approved(video_id, second)

    assert applied.state == "applied"
    second.rename_torrent_file.assert_awaited_once_with(
        "retry-task",
        "Neko - 02 [CHS].ass",
        "尼古喵喵 S01E02.zh.ass",
    )


@pytest.mark.asyncio
async def test_moving_last_rule_moves_plans_and_removes_empty_group(
    db_session, monkeypatch
):
    monkeypatch.setattr(
        "module.manager.episode_naming.settings.bangumi_manage.custom_bangumi_file",
        "{title} S{season:02}E{episode:02}",
    )
    first = rule("Neko", "NEST")
    second = rule("Other", "OtherGroup")
    second.official_title = "另一部番剧"
    db_session.add_all([first, second])
    await db_session.commit()
    await db_session.refresh(first)
    await db_session.refresh(second)
    workbench = EpisodeNamingWorkbench(db_session)
    first_group = await workbench.get_rule_group(first.id)
    second_group = await workbench.get_rule_group(second.id)
    first_group_id = required(first_group.id)
    second_group_id = required(second_group.id)
    await workbench.observe_task(
        ObservedTask(
            downloader_type="qbittorrent",
            task_id="move-task",
            rule_id=first.id,
            torrent_name="Neko - 01",
            files=[ObservedFile(index=0, name="Neko - 01.mkv")],
        )
    )

    await workbench.move_rule(first.id, second_group_id)

    assert await workbench.get_group(first_group_id) is None
    moved = await workbench.get_group(second_group_id)
    assert moved is not None
    assert {item.id for item in moved.rules} == {first.id, second.id}
    assert moved.plans[0].group_id == second_group_id


@pytest.mark.asyncio
async def test_group_torrent_records_aggregate_member_rules(db_session):
    first = rule("Neko", "NEST")
    second = rule("Neko alt", "OtherGroup")
    db_session.add_all([first, second])
    await db_session.commit()
    await db_session.refresh(first)
    await db_session.refresh(second)
    workbench = EpisodeNamingWorkbench(db_session)
    group = await workbench.get_rule_group(first.id)
    group_id = required(group.id)
    await workbench.move_rule(second.id, group_id)
    first_torrent = Torrent(bangumi_id=first.id, name="episode 1", url="https://a")
    second_torrent = Torrent(bangumi_id=second.id, name="episode 2", url="https://b")
    db_session.add_all([first_torrent, second_torrent])
    await db_session.commit()
    await db_session.refresh(first_torrent)

    assert len(await workbench.get_group_torrents(group_id)) == 2
    assert await workbench.delete_group_torrents(group_id, first_torrent.id) == 1
    assert [item.name for item in await workbench.get_group_torrents(group_id)] == [
        "episode 2"
    ]
