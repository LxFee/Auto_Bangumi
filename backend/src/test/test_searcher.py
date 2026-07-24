"""Tests for search providers: URL construction, keyword handling."""

import json
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch
from urllib.parse import parse_qs, urlsplit

import pytest

from module.conf import settings
from module.models import Bangumi, Movie, RSSItem
from module.searcher.provider import search_url

# ---------------------------------------------------------------------------
# search_url
# ---------------------------------------------------------------------------


class TestSearchUrl:
    @pytest.fixture(autouse=True)
    def mock_search_config(self):
        """Ensure SEARCH_CONFIG has default providers."""
        config = {
            "mikan": {
                "url": "https://mikanani.me/RSS/Search?searchstr=%s",
                "parser": "mikan",
            },
            "nyaa": {
                "url": "https://nyaa.si/?page=rss&q=%s&c=0_0&f=0",
                "parser": "tmdb",
            },
            "dmhy": {
                "url": "http://dmhy.org/topics/rss/rss.xml?keyword=%s",
                "parser": "tmdb",
            },
        }
        # search_url() calls get_provider(), whose authoritative state lives
        # in module.conf.search_provider. Patching the compatibility re-export
        # made this test depend on the user's local provider configuration.
        with patch("module.conf.search_provider.SEARCH_CONFIG", config):
            yield

    def test_mikan_url(self):
        """Mikan search URL is constructed correctly."""
        result = search_url("mikan", ["Mushoku", "Tensei"])
        assert isinstance(result, RSSItem)
        assert "mikanani.me" in result.url
        assert "Mushoku" in result.url
        assert "Tensei" in result.url
        assert result.parser == "mikan"

    def test_nyaa_url(self):
        """Nyaa search URL is constructed correctly."""
        result = search_url("nyaa", ["Mushoku", "Tensei"])
        assert "nyaa.si" in result.url
        assert result.parser == "tmdb"

    def test_dmhy_url(self):
        """DMHY search URL is constructed correctly."""
        result = search_url("dmhy", ["Mushoku", "Tensei"])
        assert "dmhy.org" in result.url
        assert result.parser == "tmdb"

    def test_unsupported_site_raises(self):
        """Unknown site raises ValueError."""
        with pytest.raises(ValueError, match="not supported"):
            search_url("unknown_site", ["test"])

    def test_keyword_sanitization(self):
        """Non-word characters are replaced with +."""
        result = search_url("mikan", ["Test Anime (2024)"])
        # Spaces and parentheses should be replaced with +
        assert "(" not in result.url
        assert ")" not in result.url

    def test_multiple_keywords_joined(self):
        """Multiple keywords are joined with +."""
        result = search_url("mikan", ["word1", "word2", "word3"])
        # All keywords should appear in the URL
        url = result.url
        assert "word1" in url
        assert "word2" in url
        assert "word3" in url

    def test_aggregate_is_false(self):
        """Search RSS items have aggregate=False."""
        result = search_url("mikan", ["test"])
        assert result.aggregate is False


class TestSearchUrlPerProviderParser:
    """search_url reads the parser from each provider's own {url, parser}
    config instead of the old hardcoded "mikan-or-tmdb" rule."""

    def test_uses_providers_declared_parser(self):
        """A custom provider's declared parser is honored, not the default."""
        with patch(
            "module.searcher.provider.get_provider",
            return_value={
                "custom": {"url": "https://custom.example/?q=%s", "parser": "openai"}
            },
        ):
            result = search_url("custom", ["test"])

        assert result.parser == "openai"

    def test_mikan_site_uses_declared_parser_not_hardcoded(self):
        """Even the "mikan" site name honors the configured parser value."""
        with patch(
            "module.searcher.provider.get_provider",
            return_value={
                "mikan": {
                    "url": "https://mikanani.me/RSS/Search?searchstr=%s",
                    "parser": "tmdb",
                }
            },
        ):
            result = search_url("mikan", ["test"])

        assert result.parser == "tmdb"


# ---------------------------------------------------------------------------
# Mikan HTML catalogue search
# ---------------------------------------------------------------------------


class TestMikanCatalogueParser:
    def test_build_search_url_uses_provider_origin_and_utf8_keyword(self):
        from module.searcher.mikan import build_mikan_search_url

        url = build_mikan_search_url(
            "https://mirror.example/proxy/RSS/Search?searchstr=%s",
            ["描绘", "生命"],
        )

        parsed = urlsplit(url)
        assert parsed.path == "/proxy/Home/Search"
        assert parse_qs(parsed.query) == {"searchstr": ["描绘 生命"]}

    def test_search_results_are_bangumi_pages_and_are_deduplicated(self):
        from module.searcher.mikan import parse_mikan_search_results

        html = """
        <ul class="an-ul">
          <li>
            <a href="/Home/Bangumi/3993">
              <span data-src="/images/Bangumi/poster.jpg"></span>
              <div class="an-text">描绘直至生命尽头</div>
            </a>
          </li>
          <li><a href="/Home/Bangumi/3993"><div class="an-text">重复</div></a></li>
        </ul>
        """

        results = parse_mikan_search_results(
            html, "https://mikanani.me/Home/Search?searchstr=test"
        )

        assert len(results) == 1
        assert results[0].bangumi_id == 3993
        assert results[0].title == "描绘直至生命尽头"
        assert results[0].page_url == "https://mikanani.me/Home/Bangumi/3993"
        assert results[0].poster_url == (
            "https://mikanani.me/images/Bangumi/poster.jpg"
        )

    def test_bangumi_page_exposes_one_exact_rss_per_subgroup(self):
        from module.searcher.mikan import parse_mikan_bangumi_page

        html = """
        <div class="bangumi-poster"
             style="background-image: url('/images/Bangumi/poster.jpg');"></div>
        <p class="bangumi-title">描绘直至生命尽头
          <a href="/RSS/Bangumi?bangumiId=3993"></a>
        </p>
        <p class="bangumi-info">放送开始：7/3/2026</p>
        <div class="subgroup-text" id="615">
          <a href="/Home/PublishGroup/392">Kirara Fantasia</a>
          <a href="/RSS/Bangumi?bangumiId=3993&amp;subgroupid=615">RSS</a>
        </div>
        <div class="episode-table"><table><tbody><tr>
          <td><a href="/Home/Episode/abc">[Group] Show - 01 [1080p]</a></td>
          <td><a href="/Download/abc.torrent">下载</a></td>
        </tr></tbody></table></div>
        <div class="subgroup-text" id="370">
          <a href="/Home/PublishGroup/1">LoliHouse</a>
          <a href="/RSS/Bangumi?bangumiId=3993&amp;subgroupid=370">RSS</a>
        </div>
        <div class="episode-table"><table><tbody><tr>
          <td><a href="/Home/Episode/def">[LoliHouse] Show - 01 [1080p]</a></td>
          <td><a href="/Download/def.torrent">下载</a></td>
        </tr></tbody></table></div>
        """

        page = parse_mikan_bangumi_page(
            html,
            "https://mikanani.me/Home/Bangumi/3993",
            3993,
        )

        assert page.title == "描绘直至生命尽头"
        assert page.year == "2026"
        assert page.poster_url == ("https://mikanani.me/images/Bangumi/poster.jpg")
        assert [(item.subgroup_id, item.name) for item in page.subgroups] == [
            (615, "Kirara Fantasia"),
            (370, "LoliHouse"),
        ]
        assert page.subgroups[0].rss_url == (
            "https://mikanani.me/RSS/Bangumi?bangumiId=3993&subgroupid=615"
        )
        assert page.subgroups[0].torrents[0].homepage == (
            "https://mikanani.me/Home/Episode/abc"
        )


class TestMikanCatalogueSearch:
    async def test_mikan_variants_keep_exact_subgroup_rss_links(self):
        from module.searcher.searcher import SearchTorrent
        from test.factories import make_bangumi

        search_html = """
        <ul class="an-ul"><li>
          <a href="/Home/Bangumi/3993">
            <span data-src="/images/Bangumi/poster.jpg"></span>
            <div class="an-text">描绘直至生命尽头</div>
          </a>
        </li></ul>
        """
        page_html = """
        <p class="bangumi-title">描绘直至生命尽头</p>
        <div class="subgroup-text" id="615">
          <a href="/Home/PublishGroup/392">Kirara Fantasia</a>
          <a href="/RSS/Bangumi?bangumiId=3993&amp;subgroupid=615">RSS</a>
        </div>
        <div class="episode-table"><table><tr>
          <td><a href="/Home/Episode/abc">[Group] Show - 01 [1080p]</a></td>
          <td><a href="/Download/abc.torrent">下载</a></td>
        </tr></table></div>
        <div class="subgroup-text" id="370">
          <a href="/Home/PublishGroup/1">LoliHouse</a>
          <a href="/RSS/Bangumi?bangumiId=3993&amp;subgroupid=370">RSS</a>
        </div>
        <div class="episode-table"><table><tr>
          <td><a href="/Home/Episode/def">[LoliHouse] Show - 01 [1080p]</a></td>
          <td><a href="/Download/def.torrent">下载</a></td>
        </tr></table></div>
        """

        class FakeRequest:
            async def __aenter__(self):
                return self

            async def __aexit__(self, *_args):
                return None

            async def get_html(self, url):
                return page_html if "/Home/Bangumi/" in url else search_html

        search = SearchTorrent()
        search.analyser.torrent_to_data = AsyncMock(
            side_effect=[
                make_bangumi(group_name="raw-a"),
                make_bangumi(group_name="raw-b"),
            ]
        )
        search._fetch_tmdb_preview = AsyncMock(return_value=(None, None, None))

        with (
            patch(
                "module.searcher.searcher.get_provider",
                return_value={
                    "mikan": {
                        "url": "https://mikanani.me/RSS/Search?searchstr=%s",
                        "parser": "mikan",
                    }
                },
            ),
            patch(
                "module.searcher.searcher.RequestContent",
                return_value=FakeRequest(),
            ),
        ):
            results = [
                json.loads(item)
                async for item in search.analyse_keyword(["描绘"], site="mikan")
            ]

        assert [item["group_name"] for item in results] == [
            "Kirara Fantasia",
            "LoliHouse",
        ]
        assert [item["rss_link"] for item in results] == [
            "https://mikanani.me/RSS/Bangumi?bangumiId=3993&subgroupid=615",
            "https://mikanani.me/RSS/Bangumi?bangumiId=3993&subgroupid=370",
        ]


# ---------------------------------------------------------------------------
# SearchTorrent.special_url
# ---------------------------------------------------------------------------


class TestSpecialUrl:
    def test_uses_bangumi_fields(self):
        """special_url builds keywords from SEARCH_KEY fields of Bangumi."""
        from module.searcher.searcher import SEARCH_KEY, SearchTorrent
        from test.factories import make_bangumi

        bangumi = make_bangumi(
            group_name="SubGroup",
            title_raw="Test Raw",
            season_raw="S2",
            dpi="1080p",
            source="Web",
            subtitle="CHT",
        )

        with patch(
            "module.searcher.provider.SEARCH_CONFIG",
            {
                "mikan": "https://mikanani.me/RSS/Search?searchstr=%s",
            },
        ):
            result = SearchTorrent.special_url(bangumi, "mikan")

        assert isinstance(result, RSSItem)
        # All non-None SEARCH_KEY fields should contribute to the URL
        assert "SubGroup" in result.url
        assert "Test" in result.url

    def test_skips_none_fields(self):
        """special_url skips fields that are None."""
        from module.searcher.searcher import SearchTorrent
        from test.factories import make_bangumi

        bangumi = make_bangumi(
            group_name=None,
            title_raw="Test",
            season_raw=None,
            dpi=None,
            source=None,
            subtitle=None,
        )

        with patch(
            "module.searcher.provider.SEARCH_CONFIG",
            {
                "mikan": "https://mikanani.me/RSS/Search?searchstr=%s",
            },
        ):
            result = SearchTorrent.special_url(bangumi, "mikan")

        # Only title_raw should be in the URL
        assert "Test" in result.url

    def test_supports_movie_without_season_fields(self):
        """Movie search results do not expose Bangumi-only season fields."""
        from module.searcher.searcher import SearchTorrent

        movie = Movie(
            official_title="Movie Title",
            title_raw="Movie Title",
            group_name="MovieGroup",
            dpi="1080p",
        )
        with patch(
            "module.searcher.provider.SEARCH_CONFIG",
            {"mikan": "https://mikanani.me/RSS/Search?searchstr=%s"},
        ):
            result = SearchTorrent.special_url(movie, "mikan")

        assert "Movie" in result.url


# ---------------------------------------------------------------------------
# _poster_cache: bounded LRU + reset_cache()
# ---------------------------------------------------------------------------


class TestPosterCache:
    @pytest.fixture(autouse=True)
    def _clean_poster_cache(self):
        """Isolate the module-level poster cache between tests."""
        from module.searcher import searcher as searcher_module

        searcher_module.reset_cache()
        yield
        searcher_module.reset_cache()

    def test_reset_cache_clears_poster_cache(self):
        from module.searcher import searcher as searcher_module

        searcher_module._poster_cache["Test Anime"] = {
            "zh": (None, None, "http://example.com/p.jpg")
        }
        assert len(searcher_module._poster_cache) > 0

        searcher_module.reset_cache()

        assert len(searcher_module._poster_cache) == 0

    async def test_poster_cache_evicts_oldest_when_full(self, monkeypatch):
        """_poster_cache is bounded (LRU-ish) like _tmdb_cache/_mikan_cache,
        instead of growing without limit for the life of the process."""
        from module.searcher import searcher as searcher_module
        from module.searcher.searcher import SearchTorrent

        monkeypatch.setattr(searcher_module, "_POSTER_CACHE_MAX", 3)
        torrent = SearchTorrent()

        with patch(
            "module.searcher.searcher.tmdb_parser", new=AsyncMock(return_value=None)
        ):
            for i in range(4):
                await torrent._fetch_tmdb_poster(f"Title {i}")

        assert len(searcher_module._poster_cache) == 3
        # The oldest entry ("Title 0") was evicted; the rest remain.
        assert "Title 0" not in searcher_module._poster_cache
        assert "Title 3" in searcher_module._poster_cache


class TestSearchLocalization:
    async def test_search_result_uses_configured_tmdb_language(self, monkeypatch):
        """Interactive search should not fall back to raw-parser zh/en titles for jp."""
        from module.searcher.searcher import SearchTorrent
        from test.factories import make_bangumi, make_torrent

        monkeypatch.setattr(settings.rss_parser, "language", "jp")
        search = SearchTorrent()
        search.search_torrents = AsyncMock(
            return_value=[make_torrent(name="[Group] English Raw - 01 [1080p]")]
        )

        raw_bangumi = make_bangumi(
            official_title="中文标题",
            title_raw="English Raw",
            year=None,
            poster_link=None,
        )
        tmdb_info = SimpleNamespace(
            title="日本語タイトル",
            year="2026",
            poster_link="https://image.tmdb.org/t/p/w780/poster.jpg",
        )

        with (
            patch(
                "module.searcher.searcher.search_url",
                return_value=RSSItem(
                    url="https://example.com/rss",
                    parser="mikan",
                    aggregate=False,
                ),
            ),
            patch(
                "module.rss.analyser.TitleParser.raw_parser",
                new=AsyncMock(return_value=raw_bangumi),
            ),
            patch(
                "module.searcher.searcher.tmdb_parser",
                new=AsyncMock(return_value=tmdb_info),
            ) as mock_tmdb_parser,
        ):
            results = [
                json.loads(item)
                async for item in search.analyse_keyword(
                    ["English", "Raw"], site="nyaa"
                )
            ]

        assert results[0]["official_title"] == "日本語タイトル"
        assert results[0]["year"] == "2026"
        assert results[0]["poster_link"] == tmdb_info.poster_link
        mock_tmdb_parser.assert_awaited_once_with("中文标题", "jp", test=True)
