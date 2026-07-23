# Bangumi Manager

## WebUI

![manager](/image/config/manager.png){width=700}{class=ab-shadow-card}

- **Enable**: enables file organization and rename behavior.
- **Rename Method**:
  - `normal`: conservative title and episode naming.
  - `pn`: keeps more release-title information, using a `Torrent title S0XE0X` style.
  - `advance`: uses official title and standard season/episode naming.
  - `custom`: configures separate folder and file templates for anime and movies.
  - `none`: do not rename files.
- **EPS complete**: tries to backfill missing episodes in the current season.
- **Add Group Tag**: adds subgroup-related tags to downloader tasks.
- **Delete Bad Torrent**: removes errored downloader tasks.
- **Track Unmatched Torrents**: stores torrents that do not match any rule as orphan records. Disable it if you want newly added rules to catch old feed items immediately, at the cost of rechecking those old items on each RSS refresh.

## `config.json`

Section: `bangumi_manage`

| Key | Description | Type | WebUI field | Default |
| --- | --- | --- | --- | --- |
| `enable` | Enable manager | boolean | Enable | `true` |
| `eps_complete` | Enable episode completion | boolean | EPS complete | `false` |
| `rename_method` | Rename method | string | Rename Method | `pn` |
| `custom_bangumi_folder` | Anime folder template | string | Anime Folder Template | `{title} {year:()}/Season {season}` |
| `custom_bangumi_file` | Anime file template | string | Anime File Template | `{title} S{season:02}E{episode:02}` |
| `custom_movie_folder` | Movie folder template | string | Movie Folder Template | `{title} {year:()}` |
| `custom_movie_file` | Movie file template | string | Movie File Template | `{title} {year:()}` |
| `group_tag` | Add subgroup tags | boolean | Add Group Tag | `false` |
| `remove_bad_torrent` | Delete errored torrents | boolean | Delete Bad Torrent | `false` |
| `track_orphans` | Track unmatched torrents | boolean | Track Unmatched Torrents | `true` |

## Custom template fields

The WebUI question-mark help lists the exact identifiers that can be entered:

| Field | Value |
| --- | --- |
| `title` | Media title |
| `season` | Season number |
| `episode` | Episode number |
| `year` | Release year |
| `group` | Subtitle group |
| `hash` | First 6 characters of the torrent hash |

- Direct use: `{title}`.
- Only `season` and `episode` support `:02` zero padding, for example `{episode:02}`.
- Put any two wrapper characters after the colon, for example `{year:[]}`, `{group:()}`, or `{hash:【】}`.
- A missing field and its wrappers are omitted, and repeated whitespace collapses; `{episode:[]}` never leaves empty `[]`.
- `{title:02}` and `{episode:02[]}` are invalid and produce a validation error when configuration is saved.
- File extensions are outside the template and are appended unchanged. Reserved path characters are replaced safely.
- A shared folder path has no per-episode `episode` or torrent `hash` yet, and movie folders have no `season`, so those fields follow the missing-field rule there.
- When a file template contains `hash`, revisions normally produce different target paths and coexist. `replace` runs only when target paths match.
