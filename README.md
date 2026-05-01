# youtube-subs-md

个人使用的 Python CLI 工具：输入一个 YouTube 频道链接，下载最近 50 个视频的英文字幕，
保存为不含时间戳的干净 Markdown 文件。

## 特性

- 基于 `yt-dlp` 解析频道、播放列表或单视频
- 通过 `youtube-transcript-api` 获取英文字幕（优先人工，fallback 自动）
- 输出为纯文本 Markdown，每个视频一个文件
- 默认处理最近 50 个视频，已存在文件默认跳过

## 用法

```bash
uv run youtube-subs-md <youtube-channel-url>
```

可选参数：

```bash
uv run youtube-subs-md <url> --out ./transcripts --limit 50 --overwrite --dry-run
```

| 参数 | 默认值 | 说明 |
|---|---:|---|
| `<url>` | 必填 | YouTube 频道、播放列表或单视频链接 |
| `--out` | `./transcripts` | Markdown 输出目录 |
| `--limit` | `50` | 最多处理最近多少个视频 |
| `--overwrite` | `false` | 是否覆盖已存在文件 |
| `--dry-run` | `false` | 只列出将要处理的视频，不下载字幕 |

## 开发

```bash
uv sync
uv run youtube-subs-md --help
```

任务进度记录见 [PROGRESS.md](./PROGRESS.md)。
