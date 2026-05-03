# 任务进度记录

记录每次 commit 的目标、范围和验证情况。

## 实施计划总览

按依赖顺序分多次 commit 推进：

1. **项目初始化** —— uv 项目骨架、依赖声明、CLI 占位入口
2. **纯函数模块** —— `filenames` / `text_cleaning` / `markdown`
3. **网络模块：videos** —— `yt-dlp` 封装，频道/播放列表/单视频解析
4. **网络模块：transcripts** —— `youtube-transcript-api` 封装
5. **CLI 主流程** —— 串联所有模块、参数解析、summary 输出
6. **手动验证 & 微调** —— 单视频 / 播放列表 / 频道三类场景

每次 commit 完成后，在本文件追加一节，记录范围、关键决策和验证结果。

---

## Commit 1: 项目初始化 (2026-05-01)

### 范围

- `uv init --package youtube-subs-md --python ">=3.10"` 创建项目骨架
- 在 `pyproject.toml` 声明依赖：`yt-dlp` / `youtube-transcript-api` / `typer` / `rich`
- 配置 `[project.scripts]` 入口指向 `youtube_subs_md.cli:app`
- 创建 `cli.py` 占位实现，保证 `uv run youtube-subs-md` 可执行
- 编写 `README.md` 和本进度文档

### 关键决策（来自规格对齐）

1. **跳过判定用 video_id glob 匹配**（`*[<video_id>].md`），与日期/标题解耦，
   避免"为了判断跳过先 hydrate"的悖论
2. **频道目录名**优先 `uploader`，fallback `channel_id`，做文件名清洗
3. **段落分割**：MVP 先全部合并为一段，后续优化
4. **自动字幕去重**：MVP 仅做完全相同的相邻去重，后续考虑后缀-前缀重叠合并
5. Python `>=3.10`；不写 `_summary.json`；语言变体（`en-US`/`en-GB`）归一为 `en`；hydrate 串行 + rich 进度条

### 验证

- `uv sync` 能拉取依赖
- `uv run youtube-subs-md` 能输出占位提示

### 下一步

实现纯函数模块 `filenames.py` / `text_cleaning.py` / `markdown.py`。

---

## Commit 2: 纯函数模块 (2026-05-01)

### 范围

- `filenames.py`: 字符清洗、日期格式化、文件名构造、`find_existing_for_video_id`（用 `*[VIDEOID].md` glob）
- `text_cleaning.py`: 标签剥离、空白规整、相邻去重、合并为单段
- `markdown.py`: `VideoMeta` dataclass + `render()` 固定格式

### 关键决策

- `sanitize()` 在结果只剩标点/分隔符时回退到 `fallback`（避免目录名变成 `-`）
- 中文等 CJK 字符通过 `\w` + `\u4e00-\u9fff` 正则白名单保留
- `format_upload_date(None|invalid) -> "0000-00-00"`，保持文件名格式稳定
- `find_existing_for_video_id` 使用 `glob("*[[]VIDEOID[]].md")` 转义中括号

### 验证

- 内联 Python 脚本对所有公开函数做 smoke test：
  - 文件名构造、CJK / emoji / 非法字符 / 空标题
  - glob 命中已存在文件，未命中返回 None
  - text_cleaning 正确去除 `<c>` 标签和相邻重复
  - markdown 输出符合规格

### 下一步

实现 `videos.py`：`yt-dlp` 封装，频道/播放列表/单视频解析。

---

## Commit 3: videos.py — yt-dlp 封装 (2026-05-01)

### 范围

- `list_recent_videos(url, limit)`: flat extraction，自动处理裸频道 URL → Videos tab
- `hydrate_video(video_id)`: 单视频完整 metadata 提取（拿 `upload_date` 等）
- `metadata_from_entry(entry, source)`: hydrate 失败时的 fallback 构造器
- 三个 dataclass: `VideoEntry` / `VideoMetadata` / `SourceInfo`
- 两个异常: `VideoListError` / `VideoHydrateError`

### 关键决策

- **复用规格 §17 验证脚本的成熟逻辑**：`_is_channel_tab_listing` + `_videos_tab_url`
  自动跳转裸频道 URL 到 `/videos` tab
- **hydrate 失败必须可降级**：实测 YouTube 当前会对 yt-dlp 的完整 extract 触发
  "Sign in to confirm you're not a bot" 反爬。此时使用 `metadata_from_entry`
  保证仍可生成 Markdown（只是文件名日期变 `0000-00-00`）
- flat extraction 已包含 `id` + `title`，频道级 `uploader` / `channel_id` 也能拿到，
  所以即便 hydrate 全失败，主要功能仍可工作

### 验证

- 模块 import 通过
- 实跑 `list_recent_videos('https://www.youtube.com/@lexfridman', 2)`：
  - SourceInfo 正确解析 (uploader='Lex Fridman', channel_id='UCSHZ...')
  - 返回 2 条视频，含 id 与 title
- `hydrate_video` 对该视频失败（YouTube 反爬），符合预期 → CLI 层将 fallback

### 下一步

实现 `transcripts.py`：`youtube-transcript-api` 封装。

---

## Commit 4: transcripts.py — 字幕获取 (2026-05-01)

### 范围

- `fetch_english_transcript(video_id) -> FetchedTranscript`
- 优先人工字幕，fallback 自动字幕，都没有则 `NoEnglishTranscript`
- 网络/反爬错误归类为 `TranscriptFetchError`
- 兼容新旧 `youtube-transcript-api` 返回结构（`.snippets` 对象 vs `list[dict]`）

### 关键决策

- 三种错误状态明确区分，便于 CLI 显示不同 summary 类别：
  - `NoEnglishTranscript`: 跳过该视频，记入 "Skipped no subtitles"
  - `TranscriptFetchError`: 网络/反爬，记入 "Failed"
  - 成功: 返回结构化 snippet text 列表
- snippet 对象与 dict 都用 `_snippet_text` 兼容

### 验证

- 实跑 `fetch_english_transcript('iKx3gAODybU')`：当前 IP 被 YouTube 屏蔽，
  正确抛出 `TranscriptFetchError` ✓ 错误分类符合预期
- 这进一步验证 CLI 必须能逐视频 fail-soft，整体流程不中断

### 已知环境问题

当前测试 IP 被 YouTube 阻断（反爬 + IP block），影响 hydrate 与 transcript fetch
两个真实网络路径。flat extraction（仅获取视频列表）目前仍可工作。
**这是网络环境问题而非代码问题**，CLI 必须在这种环境下也能优雅退出并输出 summary。

### 下一步

实现 `cli.py` 主流程：串联各模块、参数解析、跳过判定、summary 输出。

---

## Commit 5: cli.py 主流程 + 输出降噪 (2026-05-01)

### 范围

- `cli.py` 完整实现：参数解析、URL 解析、目录构造、逐视频处理、summary
- `RunSummary` dataclass 收集计数与失败明细
- 单视频处理流程：跳过已存在 → hydrate (失败降级) → fetch transcript → 清洗 → 渲染 → 写文件
- `--dry-run` 仅列视频不下载；`--overwrite` 覆盖现有同 video_id 文件
- `videos.py` 新增 `_BASE_OPTS` + `_NullLogger` 静默 yt-dlp 错误输出
- `transcripts.py` 新增 `_short()` 截取异常首行非空摘要
- `cli.py` 新增 `_short_exc()` 同上语义，并对所有用户/异常文本调用 `rich.markup.escape`

### 关键决策与坑

- **Rich markup 与 video_id 冲突**：`[iKx3gAODybU]` 会被 Rich 解析为不存在的 style
  并被吞掉。所有出现 video_id 的输出必须 `escape()`。
- **CLI 状态前缀**：`[skip existing]` / `[failed]` 等同样需要 escape，但要保留外层
  颜色 markup → 写法 `[yellow]{escape('[skip existing]')}[/]`
- **yt-dlp 默认会向 stderr 直接打印 ERROR**：用自定义 `_NullLogger` 注入到 `ydl_opts['logger']`
- **异常消息可能多行多页**：`_short_exc` 只取首行非空摘要 + 200 字符上限
- **hydrate 全失败仍出 markdown**：通过 `metadata_from_entry` 降级，仅文件名日期变 `0000-00-00`

### 验证

- `--help` 输出符合规格
- `--dry-run` 正确显示 3 个视频 ID 与标题（修 escape 前会丢失）
- 实跑 `--limit 1`：当前 IP 被 YouTube 封锁
  → `[hydrate fallback]` + `[failed]` 标签均正确显示
  → exit 0，summary 完整打印 (Processed=1, Failed=1)
- 整体流程 fail-soft 验证通过

### 下一步

加跑成熟环境（如能获得未被封锁的网络）做端到端验证；或现状下补充
README "Known Issues" 说明 IP/反爬限制。

---

## Commit 6: 切换到 yt-dlp + Chrome cookies 架构 (2026-05-02)

### 触发原因

5 月 1 日实测发现：
- yt-dlp 完整 extract 触发 "Sign in to confirm you're not a bot"
- youtube-transcript-api 触发 RequestBlocked

后续 web 调研 + 11 种组合实验定位到突破口：**Chrome cookies-from-browser
+ `process=False`** 可以一次性拿到 metadata + 字幕 URL。
youtube-transcript-api 因为不能复用浏览器 Cookie，无救。

### 范围

- `videos.py` 重构：
  - 新增 `make_base_opts(cookies_from_browser)` 工厂函数
  - 新增 `VideoData` dataclass（metadata + subtitles + automatic_captions）
  - 新增 `fetch_video_data(video_id, cookies_from_browser)`
    一次 `extract_info(process=False)` 同时返回元数据和字幕 URL
  - 删除原来注定失败的 `hydrate_video`，保留 `metadata_from_entry` 作为 fallback
  - `list_recent_videos` 也接受 `cookies_from_browser`
- `transcripts.py` 完全重写：
  - 不再依赖 `youtube-transcript-api`
  - `fetch_english_transcript(video_data, cookies_from_browser)` 接受
    `VideoData`，从其字幕字典中挑英文轨道
  - 通过 `yt_dlp.YoutubeDL.urlopen` 下载 `json3` 字幕（复用同一份 Cookie）
  - 自实现 `_parse_json3` + `_parse_vtt` 两个解析器
- `cli.py`：
  - `_process_one` 改用新的 `fetch_video_data` + 新签名的 `fetch_english_transcript`
  - 暂时硬编码 `cookies_from_browser="chrome"`，下个 commit 换成 CLI 参数

### 关键决策

- **每个视频只做一次完整 extract**：metadata 与 caption URL 同源，避免重复网络请求
- **`process=False`**：跳过 yt-dlp 内部的 format 选择/字幕下载流程，
  防止 "Requested format is not available" 误报，且更快
- **字幕格式优先级**：`json3` > `srv3` > `srv2` > `srv1` > `vtt`，json3 解析最可靠
- **Cookie 来源**：MVP 默认 Chrome；下一 commit 暴露为 CLI 参数

### 验证

`uv run youtube-subs-md "https://www.youtube.com/@t3dotgg" --limit 2 --out /tmp/yt-test`：

```
Resolving: https://www.youtube.com/@t3dotgg
Channel: Theo - t3․gg → /tmp/yt-test/Theo - t3․gg
Videos: 2
[ok] Seriously, Anthropic?? [J8O9LLpJNrg] → 2026-05-01 - ...md
[ok] I give up. [R7ex-Gt8dtw] → 2026-04-30 - I give up [R7ex-Gt8dtw].md

Processed=2, Downloaded=2, Failed=0
```

✅ 文件名格式符合规格（含日期 + 标题 + video_id）
✅ Markdown header 完整（URL/Channel/Published/Subtitle 字段齐全）
✅ Subtitle 来源正确标注 `en, auto-generated`
✅ Transcript 文本干净，无时间戳，正常段落

### 下一步

将 `--cookies-from-browser` 暴露为 CLI 参数；更新 README；
可选地从 `pyproject.toml` 删除 `youtube-transcript-api` 依赖。

---

## Commit 7: CLI 参数 + README + 清理依赖 (2026-05-02)

### 范围

- `cli.py`：新增 `--cookies-from-browser` 选项（默认 `chrome`，传空字符串禁用），
  同时传给 `list_recent_videos` 和 `fetch_video_data` / `fetch_english_transcript`
- `pyproject.toml`：删除 `youtube-transcript-api` 依赖
- `uv sync`：移除 8 个相关传递依赖（certifi/idna/requests/urllib3/...）
- `README.md` 重写：增加"已知问题与前置条件"章节，覆盖
  - Chrome 登录态前置要求
  - macOS Keychain 弹窗
  - 账号封禁风险
  - IP 严重被封时的进阶方案（PO Token / 住宅代理）

### 验证

- `uv run youtube-subs-md --help` 输出包含 `--cookies-from-browser` 选项与说明
- 实跑 t3dotgg `--limit 1`：成功生成 1 个 Markdown
- 二次运行 → 正确输出 `[skip existing]`，Skipped existing=1

### MVP 完成度对照规格 §13

| 验收项 | 状态 |
|---|---|
| 通过 `uv run youtube-subs-md <channel-url>` 运行 | ✅ |
| 默认处理最近 50 个视频 | ✅ |
| 每个成功视频生成一个 `.md` | ✅ |
| Markdown 不含时间戳 | ✅ |
| 单视频失败不中断整体 | ✅ |
| 已存在文件默认跳过 | ✅ |
| 终端清晰 summary | ✅ |
| 区分 manual / auto-generated | ✅ |

MVP 完成。后续可考虑加 `--player-client` / `--proxy` / PO Token 等扩展。

---

## Commit 8: 隐私清理 + 发布到 GitHub (2026-05-02)

### 范围

- 重写全部历史 commit 的 author / committer 邮箱与名字
  （`habits <1021869329@qq.com>` → `habitssss <48110386+habitssss@users.noreply.github.com>`）
- 修改 `pyproject.toml` 中的 author 字段为 GitHub noreply 邮箱
- 仓库 local `git config` 设置 `user.name` / `user.email` 为同一身份，
  避免后续 commit 重新带上原邮箱
- `gh repo create habitssss/youtube-subs-md --public --push`
- 默认分支从 `master` 重命名为 `main`，删除远端 `master`，
  `origin/HEAD` 重新指向 `origin/main`

### 操作步骤

1. `git stash` 暂存 `pyproject.toml` 修改
2. `git filter-branch --env-filter ...` 重写 7 个历史 commit 的 author + committer
3. 校验 `git log --format='%ae %ce'` 已无 `qq.com`
4. `git stash pop` 恢复 + `git commit` 8 号 commit（pyproject.toml 改动）
5. `git update-ref -d refs/original/...` 清理 filter-branch backup
6. `gh repo create ... --public --source=. --push` 推送
7. `git branch -m main` + `git push -u origin main` + `gh repo edit --default-branch main`
   + `git push origin --delete master` + `git remote set-head origin -a`

### 验证

- 文件层面：`grep "qq.com\|1021869329"` 全空
- git 历史：`git log --format='%ae %ce' | sort -u` 只剩 noreply 邮箱
- GitHub：`gh repo view` 确认 `visibility=PUBLIC` / `defaultBranchRef.name=main`
- 仓库 URL: <https://github.com/habitssss/youtube-subs-md>

### 教训

- 之前 7 个 commit 后只回顾了"代码进度"忘了"流程操作"，这次的邮箱改写
  + 推送 + 分支重命名都没立即写 PROGRESS。**只要历史/远端有动作就该补记**。
- `git filter-branch` 仍可用，但官方推荐迁到 `git filter-repo`；MVP 阶段
  脚本一次性使用足够。
