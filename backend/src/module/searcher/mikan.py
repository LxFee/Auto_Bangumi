import re
from dataclasses import dataclass
from urllib.parse import quote_plus, urljoin, urlsplit, urlunsplit

from bs4 import BeautifulSoup, Tag

from module.models import Torrent

_BANGUMI_PATH = re.compile(r"/Home/Bangumi/(\d+)", re.IGNORECASE)
_SUBGROUP_QUERY = re.compile(r"(?:[?&])subgroupid=(\d+)", re.IGNORECASE)
_POSTER_STYLE = re.compile(r"url\((?:['\"])?([^'\")]+)")
_YEAR = re.compile(r"\b(19|20)\d{2}\b")


@dataclass(frozen=True, slots=True)
class MikanBangumiRef:
    bangumi_id: int
    title: str
    page_url: str
    poster_url: str | None


@dataclass(frozen=True, slots=True)
class MikanSubgroupRef:
    subgroup_id: int
    name: str
    rss_url: str
    torrents: tuple[Torrent, ...]


@dataclass(frozen=True, slots=True)
class MikanBangumiPage:
    bangumi_id: int
    title: str
    poster_url: str | None
    year: str | None
    subgroups: tuple[MikanSubgroupRef, ...]


def build_mikan_search_url(provider_url: str, keywords: list[str]) -> str:
    """Build Mikan's HTML catalogue search URL from the configured RSS origin."""
    parsed = urlsplit(provider_url)
    if not parsed.scheme or not parsed.netloc:
        raise ValueError("Mikan provider URL must be absolute")

    # A reverse proxy may expose Mikan below a path prefix. Preserve the part
    # before /RSS/ while replacing the RSS endpoint with the HTML search page.
    rss_index = parsed.path.lower().find("/rss/")
    prefix = parsed.path[:rss_index].rstrip("/") if rss_index >= 0 else ""
    path = f"{prefix}/Home/Search"
    keyword = " ".join(part for part in keywords if part).strip()
    return urlunsplit(
        (parsed.scheme, parsed.netloc, path, f"searchstr={quote_plus(keyword)}", "")
    )


def parse_mikan_search_results(
    content: str | None, search_url: str
) -> list[MikanBangumiRef]:
    """Extract the distinct Bangumi cards returned by Mikan's HTML search."""
    soup = BeautifulSoup(content or "", "html.parser")
    results: list[MikanBangumiRef] = []
    seen_ids: set[int] = set()

    for anchor in soup.select('ul.an-ul li a[href*="/Home/Bangumi/"]'):
        href = anchor.get("href")
        if not isinstance(href, str):
            continue
        match = _BANGUMI_PATH.search(href)
        if match is None:
            continue
        bangumi_id = int(match.group(1))
        if bangumi_id in seen_ids:
            continue

        title_node = anchor.select_one(".an-text")
        title = title_node.get_text(" ", strip=True) if title_node else ""
        poster_node = anchor.select_one("[data-src]")
        poster_path = poster_node.get("data-src") if poster_node else None
        poster_url = (
            urljoin(search_url, poster_path)
            if isinstance(poster_path, str) and poster_path
            else None
        )
        results.append(
            MikanBangumiRef(
                bangumi_id=bangumi_id,
                title=title,
                page_url=urljoin(search_url, href),
                poster_url=poster_url,
            )
        )
        seen_ids.add(bangumi_id)

    return results


def _poster_url(soup: BeautifulSoup, page_url: str) -> str | None:
    poster = soup.select_one("div.bangumi-poster[style]")
    if poster is None:
        return None
    style = poster.get("style")
    if not isinstance(style, str):
        return None
    match = _POSTER_STYLE.search(style)
    return urljoin(page_url, match.group(1)) if match else None


def _page_year(soup: BeautifulSoup) -> str | None:
    for info in soup.select("p.bangumi-info"):
        text = info.get_text(" ", strip=True)
        if "放送开始" not in text:
            continue
        match = _YEAR.search(text)
        if match:
            return match.group(0)
    return None


def _subgroup_name(node: Tag) -> str:
    publisher = node.select_one('a[href*="/Home/PublishGroup/"]')
    if publisher is not None:
        return publisher.get_text(" ", strip=True)
    return ""


def _subgroup_torrents(node: Tag, page_url: str) -> tuple[Torrent, ...]:
    table = node.find_next_sibling("div", class_="episode-table")
    if not isinstance(table, Tag):
        return ()

    torrents: list[Torrent] = []
    # A few newest releases are enough to survive an unusual/unparseable title
    # without turning catalogue search into a full-season parse.
    for row in table.select("tr"):
        episode = row.select_one('a[href*="/Home/Episode/"]')
        download = row.select_one('a[href*="/Download/"]')
        if episode is None or download is None:
            continue
        episode_href = episode.get("href")
        download_href = download.get("href")
        if not isinstance(episode_href, str) or not isinstance(download_href, str):
            continue
        torrents.append(
            Torrent(
                name=episode.get_text(" ", strip=True),
                url=urljoin(page_url, download_href),
                homepage=urljoin(page_url, episode_href),
            )
        )
        if len(torrents) >= 5:
            break
    return tuple(torrents)


def parse_mikan_bangumi_page(
    content: str | None,
    page_url: str,
    bangumi_id: int,
) -> MikanBangumiPage:
    """Parse one Mikan Bangumi page into exact per-subgroup RSS choices."""
    soup = BeautifulSoup(content or "", "html.parser")
    title_node = soup.select_one("p.bangumi-title")
    title = title_node.get_text(" ", strip=True) if title_node else ""
    subgroups: list[MikanSubgroupRef] = []
    seen_ids: set[int] = set()

    # subgroup-text is the desktop section and contains both the exact RSS link
    # and that subgroup's episode table. The mobile markup duplicates the same
    # data, so intentionally parsing only this section also deduplicates it.
    for node in soup.select("div.subgroup-text[id]"):
        if not isinstance(node, Tag):
            continue
        rss_anchor = node.select_one('a[href*="/RSS/Bangumi"][href*="subgroupid="]')
        if rss_anchor is None:
            continue
        href = rss_anchor.get("href")
        if not isinstance(href, str):
            continue
        match = _SUBGROUP_QUERY.search(href)
        if match is None:
            continue
        subgroup_id = int(match.group(1))
        if subgroup_id in seen_ids:
            continue
        name = _subgroup_name(node)
        if not name:
            continue
        subgroups.append(
            MikanSubgroupRef(
                subgroup_id=subgroup_id,
                name=name,
                rss_url=urljoin(page_url, href),
                torrents=_subgroup_torrents(node, page_url),
            )
        )
        seen_ids.add(subgroup_id)

    return MikanBangumiPage(
        bangumi_id=bangumi_id,
        title=title,
        poster_url=_poster_url(soup, page_url),
        year=_page_year(soup),
        subgroups=tuple(subgroups),
    )
