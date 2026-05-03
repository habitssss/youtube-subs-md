# youtube-subs-md

个人使用的 Python CLI 工具：输入一个 YouTube 频道链接，下载最近 50 个视频的英文字幕，
保存为不含时间戳的干净 Markdown 文件。

## 特性

- 基于 `yt-dlp` 解析频道、播放列表或单视频
- 通过 `yt-dlp` 拿到字幕直链后下载并解析 `json3`，自带 VTT fallback
- 默认借用本机 Chrome 的 YouTube 登录态绕过反爬（可换其他浏览器或禁用）
- 输出为纯文本 Markdown，每个视频一个文件
- 默认处理最近 50 个视频，已存在文件默认跳过

## 用法

```bash
uv run youtube-subs-md <youtube-channel-url>
```

可选参数：

```bash
uv run youtube-subs-md <url> \
  --out ./transcripts \
  --limit 50 \
  --overwrite \
  --dry-run \
  --cookies-from-browser chrome
```

| 参数 | 默认值 | 说明 |
|---|---:|---|
| `<url>` | 必填 | YouTube 频道、播放列表或单视频链接 |
| `--out` | `./transcripts` | Markdown 输出根目录 |
| `--limit` | `50` | 最多处理最近多少个视频 |
| `--overwrite` | `false` | 是否覆盖已存在文件 |
| `--dry-run` | `false` | 只列出将要处理的视频，不下载字幕 |
| `--cookies-from-browser` | `chrome` | 借用浏览器 Cookie；传空字符串可禁用 |

## 已知问题与前置条件

### 必须配合本机浏览器登录态

YouTube 当前对 yt-dlp 的完整 metadata extract 普遍触发
"Sign in to confirm you're not a bot" 反爬；`youtube-transcript-api` 也会被
`RequestBlocked` 拦截。本工具因此默认通过 `--cookies-from-browser chrome`
读取本机浏览器的 YouTube Cookie。

**使用前请先在你选择的浏览器中登录 youtube.com**。支持的浏览器名遵循 yt-dlp 文档
（`chrome` / `firefox` / `safari` / `edge` / `brave` / ...）。

如果你的网络/IP 没有被 YouTube 限制，可显式禁用：

```bash
uv run youtube-subs-md <url> --cookies-from-browser ""
```

### macOS Chrome Cookie 解密

首次使用 `chrome` 时 macOS 会弹窗要求允许访问 Keychain（用于解密 Cookie 数据库）。
点击"始终允许"即可。

### 账号封禁风险

yt-dlp 官方文档警示：长期用同一个 Google 账号的 Cookie 高频请求 YouTube，
可能导致**账号被封**。如果担心，建议使用一个专门的 throwaway Google 账号登录浏览器。

### IP 严重被封时

如果 cookies 也救不了（例如服务器节点 IP 已被深度拉黑），可考虑：

- 切换网络（家用宽带 / 移动数据通常更干净）
- 配置 yt-dlp PO Token 提供方
  （参考 [bgutil-ytdlp-pot-provider](https://github.com/Brainicism/bgutil-ytdlp-pot-provider)）
- 使用住宅代理

这些都不在本 MVP 的内置范围内。

## 输出示例

```
transcripts/
└── Lex Fridman/
    ├── 2026-05-01 - Some Video Title [abc123].md
    └── 2026-04-30 - Another Video [def456].md
```

每个 Markdown 文件结构：

```markdown
# Video Title

URL: https://www.youtube.com/watch?v=abc123
Channel: Lex Fridman
Published: 2026-05-01
Subtitle: en, manual

---

Transcript text goes here...
```

## 开发

```bash
uv sync
uv run youtube-subs-md --help
```
