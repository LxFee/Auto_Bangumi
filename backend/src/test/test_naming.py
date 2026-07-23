"""Public behavior tests for custom naming templates."""

import pytest

from module.naming import (
    NamingContext,
    NamingTemplateError,
    render_custom_name,
    validate_custom_template,
)


def test_renders_direct_fields():
    context = NamingContext(
        title="Frieren",
        season=2,
        episode=3,
        year="2026",
        group="Sousou",
        torrent_hash="abcdef123456",
    )

    assert render_custom_name("{title} S{season}E{episode}", context) == "Frieren S2E3"


def test_zero_pads_season_and_episode():
    context = NamingContext(title="Frieren", season=2, episode=3)

    assert render_custom_name("S{season:02}E{episode:02}", context) == "S02E03"


def test_wraps_present_fields_with_two_configured_characters():
    context = NamingContext(title="Frieren", episode=3, year="2026", group="Sousou")

    assert (
        render_custom_name("{title} {year:[]} {group:()} {episode:【】}", context)
        == "Frieren [2026] (Sousou) 【3】"
    )


def test_omits_missing_fields_and_their_wrappers_without_extra_spaces():
    context = NamingContext(title="Frieren", episode=None, year=None, group=None)

    assert (
        render_custom_name("{title}  {year:[]}  {group:()}  {episode:【】}", context)
        == "Frieren"
    )


def test_hash_is_truncated_to_six_characters():
    context = NamingContext(title="Frieren", torrent_hash="ABCDEF1234567890")

    assert render_custom_name("{title} {hash:[]}", context) == "Frieren [ABCDEF]"


def test_rejects_zero_padding_for_non_numeric_fields():
    with pytest.raises(NamingTemplateError, match="title.*02"):
        render_custom_name("{title:02}", NamingContext(title="Frieren"))


def test_rejects_combined_zero_padding_and_wrappers():
    with pytest.raises(NamingTemplateError, match="episode:02\\[\\]"):
        render_custom_name("{episode:02[]}", NamingContext(title="Frieren", episode=3))


def test_appends_the_original_file_extension_after_rendering():
    context = NamingContext(title="Frieren", episode=3)

    assert (
        render_custom_name("{title} E{episode:02}", context, suffix=".MKV")
        == "Frieren E03.MKV"
    )


def test_sanitizes_reserved_characters_in_field_values():
    context = NamingContext(title="Fate/Zero: Part?2", group='A<B>"C|D*', episode=1)

    assert (
        render_custom_name("{title} {group:[]}", context, suffix=".mkv")
        == "Fate Zero Part 2 [A B C D].mkv"
    )


def test_folder_templates_preserve_safe_relative_subdirectories():
    context = NamingContext(title="Fate/Zero", season=2, year="2026")

    assert (
        render_custom_name(
            "{title} {year:()}/Season {season}", context, allow_path=True
        )
        == "Fate Zero (2026)/Season 2"
    )


def test_validation_rejects_unknown_fields_before_runtime_values_exist():
    with pytest.raises(NamingTemplateError, match="Unknown template field: name"):
        validate_custom_template("{name} S{season}")


def test_folder_template_omits_a_segment_whose_field_is_missing():
    context = NamingContext(title="Frieren", group=None)

    assert (
        render_custom_name("{group:[]}/{title}", context, allow_path=True) == "Frieren"
    )
