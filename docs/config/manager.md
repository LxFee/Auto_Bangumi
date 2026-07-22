# 番剧管理设置

## WebUI 配置

![manager](/image/config/manager.png){width=700}{class=ab-shadow-card}

- **启用**：启用番剧管理器。关闭后，重命名与整理相关设置不会生效。
- **重命名方式**：
  - `normal`：使用较保守的番剧标题与集数命名。
  - `pn`：保留更多发布标题信息，使用 `种子标题 S0XE0X` 风格。
  - `advance`：使用官方标题与标准季集格式。
  - `custom`：分别配置番剧/电影的文件夹与文件模板。
  - `none`：不重命名文件。
- **番剧补全**：检测当季缺失集数并尝试补全下载。
- **添加组标签**：为下载器中的任务添加字幕组相关标签。
- **删除坏种**：移除下载器中状态异常的种子。
- **记录未匹配种子**：把当前没有匹配到规则的种子记录为“未匹配种子”。关闭后，后续新增规则可以立即接住 RSS 中仍存在的旧条目，但这些旧条目会在每轮 RSS 刷新时重新尝试匹配。
- [关于文件路径][1]
- [关于重命名][2]

## `config.json` 配置选项

配置节：`bangumi_manage`

| 参数 | 说明 | 类型 | WebUI 选项 | 默认值 |
| --- | --- | --- | --- | --- |
| `enable` | 启用番剧管理器 | 布尔值 | 启用 | `true` |
| `eps_complete` | 启用剧集补全 | 布尔值 | 番剧补全 | `false` |
| `rename_method` | 重命名方式 | 字符串 | 重命名方式 | `pn` |
| `custom_bangumi_folder` | 番剧文件夹模板 | 字符串 | 番剧文件夹模板 | `{title} {year:()}/Season {season}` |
| `custom_bangumi_file` | 番剧文件模板 | 字符串 | 番剧文件模板 | `{title} S{season:02}E{episode:02}` |
| `custom_movie_folder` | 电影文件夹模板 | 字符串 | 电影文件夹模板 | `{title} {year:()}` |
| `custom_movie_file` | 电影文件模板 | 字符串 | 电影文件模板 | `{title} {year:()}` |
| `group_tag` | 添加字幕组标签 | 布尔值 | 添加组标签 | `false` |
| `remove_bad_torrent` | 删除错误种子 | 布尔值 | 删除坏种 | `false` |
| `track_orphans` | 记录未匹配种子 | 布尔值 | 记录未匹配种子 | `true` |

## Custom 模板字段

WebUI 中的问号帮助使用实际应填写的英文标识符，并按行展示以下字段：

| 字段 | 值 |
| --- | --- |
| `title` | 媒体标题 |
| `season` | 季号 |
| `episode` | 集号 |
| `year` | 年份 |
| `group` | 字幕组 |
| `hash` | torrent hash 的前 6 个字符 |

- 直接使用：`{title}`。
- 仅 `season` 和 `episode` 支持 `:02` 补零，例如 `{episode:02}`。
- 两字符包裹符写在冒号后，例如 `{year:[]}`、`{group:()}`、`{hash:【】}`。
- 缺失字段会连同包裹符一起省略，连续空白折叠为一个；`{episode:[]}` 不会留下空的 `[]`。
- `{title:02}` 和 `{episode:02[]}` 非法，保存配置时会返回校验错误。
- 扩展名不属于模板，AB 会原样追加；路径保留字符会被安全替换。
- 共享文件夹路径创建时没有单集 `episode` 或 torrent `hash`，电影文件夹也没有 `season`，因此这些字段会按缺失字段处理。
- 文件模板包含 `hash` 时，不同修订版通常生成不同目标路径并共存；`replace` 只在目标路径相同时进入替换流程。

[1]: https://www.autobangumi.org/faq/#download-path
[2]: https://www.autobangumi.org/faq/#file-renaming
