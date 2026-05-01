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
