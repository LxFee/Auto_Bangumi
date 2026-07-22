# File Renaming

AB provides the `pn`, `advance`, `custom`, and `none` renaming methods.

### pn

Short for `pure name`. This method uses the torrent download name for renaming.

Example:
```
[Lilith-Raws] 86 - Eighty Six - 01 [Baha][WEB-DL][1080p][AVC AAC][CHT][MKV].mkv
>>
86 - Eighty Six S01E01.mkv
```

### advance

Advanced renaming. This method uses the parent folder name for renaming.

```
/downloads/Bangumi/86 - Eighty Six(2023)/Season 1/[Lilith-Raws] 86 - Eighty Six - 01 [Baha][WEB-DL][1080p][AVC AAC][CHT][MKV].mkv
>>
86 - Eighty Six(2023) S01E01.mkv
```

### none

No renaming. Files are left as-is.

### custom

`custom` uses four separate templates: anime folder, anime file, movie folder, and movie file. See [Bangumi Manager](../config/manager.md#custom-template-fields) for fields and syntax.

The default anime templates preserve the standard stable layout:

```text
Frieren (2026)/Season 2/Frieren S02E03.mkv
```

When the file template contains `hash`, V1 and V2 normally resolve to different paths, so same-target revision replacement is not triggered.

## Collection Renaming

AB supports renaming collections. Collection renaming requires:
- Episodes are in the collection's first-level directory
- Episode numbers can be parsed from file names

AB can also rename subtitle files in the first-level directory.

After renaming, episodes and directories are placed in the `Season` folder.

Renamed collections are moved and categorized under `BangumiCollection`.

## Episode Offset

Since v3.2, AB supports episode offset for renaming. This is useful when:
- RSS shows different episode numbers than expected (e.g., S2E01 should be S1E29)
- Anime has "virtual seasons" due to broadcast gaps

When an offset is configured for a bangumi, AB automatically applies it during renaming:

```
Original: S02E01.mkv
With offset (season: -1, episode: +28): S01E29.mkv
```

To configure offset:
1. Click on the anime poster
2. Open Advanced Settings
3. Set Season Offset and/or Episode Offset values
4. Or use "Auto Detect" to let AB suggest the correct offset

See [Bangumi Management](./bangumi.md#episode-offset-auto-detection) for more details on auto-detection.
