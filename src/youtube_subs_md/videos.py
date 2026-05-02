"""yt-dlp 封装：解析频道/播放列表/单视频 URL，获取视频列表与完整数据。

设计要点（融合规格 §17 与 commit 6 的反爬绕过实测）:

1. 使用 ``extract_flat='in_playlist'`` 快速拿到视频 ID 列表，避免逐个完整解析。
2. 裸频道 URL（如 ``https://www.youtube.com/@handle``）会被 yt-dlp 解析为 tab 列表
   （Videos/Live/Shorts/Playlists），需要识别后跳转到 ``Videos`` tab。
3. **YouTube 当前会对完整 extract 触发 bot 检测**：必须传 ``cookiesfrombrowser``
   （读取已登录浏览器的 Cookie）才能拿到 metadata 和 caption URL。
4. 单次完整 extract 同时返回 metadata + ``subtitles`` + ``automatic_captions``，
   :func:`fetch_video_data` 因此只做一次网络往返就足够上层渲染 Markdown。
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

import yt_dlp


class _NullLogger:
    """提供给 yt-dlp 的静默 logger，避免错误信息直接打到 stderr。

    yt-dlp 即使设置 ``quiet=True``，部分 ERROR 日志仍会通过默认 logger 输出。
    使用此 logger 后，错误只会通过 :func:`yt_dlp.YoutubeDL.extract_info` 的
    返回值（None）或异常体现，由调用方决定如何展示给用户。
    """

    def debug(self, _msg: str) -> None: ...
    def info(self, _msg: str) -> None: ...
    def warning(self, _msg: str) -> None: ...
    def error(self, _msg: str) -> None: ...


_BASE_OPTS: dict[str, Any] = {
    "quiet": True,
    "no_warnings": True,
    "skip_download": True,
    "ignoreerrors": True,
    "logger": _NullLogger(),
}


def make_base_opts(cookies_from_browser: str | None = None) -> dict[str, Any]:
    """构造一份 yt-dlp 选项基线。

    参数:
        cookies_from_browser: 浏览器名（``chrome`` / ``firefox`` / ``safari`` ...）。
            为 ``None`` 时不附加 cookies，仅适合未触发反爬的简单场景。

    返回:
        新的字典副本，可被各调用点继续 ``{**base, ...}`` 扩展。
    """
    opts = dict(_BASE_OPTS)
    if cookies_from_browser:
        # yt-dlp 接受 (browser, profile, keyring, container) 元组
        opts["cookiesfrombrowser"] = (cookies_from_browser,)
    return opts


@dataclass(frozen=True)
class VideoEntry:
    """flat extraction 阶段返回的轻量条目，仅保证有 id 和可用 url。"""

    id: str
    url: str
    title: str | None = None


@dataclass(frozen=True)
class VideoMetadata:
    """完整 metadata，由 :func:`fetch_video_data` 暴露给上层。"""

    id: str
    url: str
    title: str
    uploader: str | None
    channel_id: str | None
    upload_date: str | None  # YYYYMMDD
    duration: int | None


@dataclass(frozen=True)
class VideoData:
    """单视频完整数据：metadata + 原始 caption 字典。

    ``subtitles`` / ``automatic_captions`` 直接保留 yt-dlp 返回的格式
    （``{lang: [{ext, url, ...}, ...]}``），由 transcripts 模块继续选择。
    """

    metadata: VideoMetadata
    subtitles: dict[str, list[dict[str, Any]]] = field(default_factory=dict)
    automatic_captions: dict[str, list[dict[str, Any]]] = field(default_factory=dict)


@dataclass(frozen=True)
class SourceInfo:
    """输入 URL 解析出的"源"信息，用于决定输出子目录名。"""

    uploader: str | None
    channel_id: str | None


def _video_url(video_id: str) -> str:
    return f"https://www.youtube.com/watch?v={video_id}"


def _is_channel_tab_listing(info: dict[str, Any]) -> bool:
    """判断 yt-dlp 返回的是不是频道 tab 列表（而非视频列表）。"""
    entries = [e for e in (info.get("entries") or []) if e]
    if not entries:
        return False

    tab_markers = ("/videos", "/streams", "/shorts", "/playlists")
    tab_count = 0
    for entry in entries:
        entry_url = str(entry.get("url") or entry.get("webpage_url") or "")
        entry_title = str(entry.get("title") or "").lower()
        if any(m in entry_url for m in tab_markers) or any(
            entry_title.endswith(s)
            for s in (" - videos", " - live", " - shorts", " - playlists")
        ):
            tab_count += 1

    return tab_count == len(entries)


def _videos_tab_url(info: dict[str, Any]) -> str | None:
    """从 tab 列表中找出 Videos tab 的 URL。"""
    for entry in info.get("entries") or []:
        if not entry:
            continue
        entry_url = str(entry.get("url") or entry.get("webpage_url") or "")
        entry_title = str(entry.get("title") or "").lower()
        if "/videos" in entry_url or entry_title.endswith(" - videos"):
            return entry_url
    return None


def _entry_to_video_entry(entry: dict[str, Any]) -> VideoEntry | None:
    video_id = entry.get("id")
    if not video_id:
        return None
    return VideoEntry(
        id=video_id,
        url=entry.get("webpage_url") or entry.get("url") or _video_url(video_id),
        title=entry.get("title"),
    )


class VideoListError(RuntimeError):
    """yt-dlp 解析输入 URL 失败时抛出。"""


def list_recent_videos(
    url: str,
    limit: int,
    *,
    cookies_from_browser: str | None = None,
) -> tuple[SourceInfo, list[VideoEntry]]:
    """解析输入 URL，返回最多 ``limit`` 个视频条目。

    支持的输入：

    - 频道 URL（``@handle`` / ``/channel/UCxxx`` / ``/c/`` / ``/user/``）
    - 播放列表 URL
    - 单视频 URL

    参数:
        url: YouTube 链接。
        limit: 最多返回多少个视频。
        cookies_from_browser: 可选，浏览器名（用于绕过 bot 检测）。
            实测 flat extraction 通常不触发反爬，因此默认 ``None``。

    返回:
        ``(source_info, entries)`` 元组。

    异常:
        :class:`VideoListError` 当 yt-dlp 无法解析或返回空。
    """
    ydl_opts: dict[str, Any] = {
        **make_base_opts(cookies_from_browser),
        "extract_flat": "in_playlist",
        "playlistend": limit,
    }

    with yt_dlp.YoutubeDL(ydl_opts) as ydl:
        info = ydl.extract_info(url, download=False)
        if not info:
            raise VideoListError(f"yt-dlp returned no info for: {url}")

        # 裸频道 URL 会拿到 tab 列表，自动跳转到 Videos tab
        if _is_channel_tab_listing(info):
            tab_url = _videos_tab_url(info)
            if tab_url:
                info = ydl.extract_info(tab_url, download=False)
                if not info:
                    raise VideoListError(
                        f"yt-dlp returned no info for videos tab: {tab_url}"
                    )

    source = SourceInfo(
        uploader=info.get("uploader") or info.get("channel") or info.get("title"),
        channel_id=info.get("channel_id") or info.get("uploader_id"),
    )

    entries = info.get("entries")
    if entries is None:
        # 单视频 URL 路径
        single = _entry_to_video_entry(info)
        return source, ([single] if single else [])

    videos: list[VideoEntry] = []
    for entry in entries:
        if not entry:
            continue
        v = _entry_to_video_entry(entry)
        if v:
            videos.append(v)
        if len(videos) >= limit:
            break

    return source, videos


class VideoFetchError(RuntimeError):
    """单个视频完整数据获取失败时抛出。"""


def fetch_video_data(
    video_id: str,
    *,
    cookies_from_browser: str | None = None,
) -> VideoData:
    """单视频完整数据：metadata + 原始字幕字典。

    一次 ``extract_info(process=False)`` 即同时返回视频元信息与字幕 URL，
    由 :mod:`transcripts` 后续选择并下载。

    参数:
        video_id: YouTube 视频 ID（11 位字符串）。
        cookies_from_browser: 浏览器名（如 ``chrome``）。当前 YouTube 反爬
            通常要求此项；不传时极易遇到 "Sign in to confirm you're not a bot"。

    异常:
        :class:`VideoFetchError` 当视频不可访问、被删除或 yt-dlp 失败时。
    """
    ydl_opts: dict[str, Any] = {
        **make_base_opts(cookies_from_browser),
        "noplaylist": True,
        # process=False 仍可能触发 format 选择；保险起见显式置空
        "format": None,
    }
    url = _video_url(video_id)
    try:
        with yt_dlp.YoutubeDL(ydl_opts) as ydl:
            # process=False: 跳过格式选择/字幕下载等耗时步骤，只取原始 info
            info = ydl.extract_info(url, download=False, process=False)
    except Exception as exc:
        raise VideoFetchError(f"fetch failed for {video_id}: {exc}") from exc

    if not info:
        raise VideoFetchError(f"fetch returned no info for {video_id}")

    metadata = VideoMetadata(
        id=info.get("id") or video_id,
        url=info.get("webpage_url") or url,
        title=info.get("title") or "Untitled",
        uploader=info.get("uploader") or info.get("channel"),
        channel_id=info.get("channel_id") or info.get("uploader_id"),
        upload_date=info.get("upload_date") or info.get("release_date"),
        duration=info.get("duration"),
    )

    return VideoData(
        metadata=metadata,
        subtitles=dict(info.get("subtitles") or {}),
        automatic_captions=dict(info.get("automatic_captions") or {}),
    )


def metadata_from_entry(entry: VideoEntry, source: SourceInfo) -> VideoMetadata:
    """从 flat extract 的轻量条目 + 源信息构造 fallback metadata。

    用途：当 :func:`fetch_video_data` 失败时，仍可以基于 flat extraction
    已有的 title 与频道级 uploader 信息生成 Markdown，
    只是文件名日期前缀会变成 ``0000-00-00``，且没有字幕。
    """
    return VideoMetadata(
        id=entry.id,
        url=entry.url,
        title=entry.title or "Untitled",
        uploader=source.uploader,
        channel_id=source.channel_id,
        upload_date=None,
        duration=None,
    )
