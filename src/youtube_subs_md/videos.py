"""yt-dlp 封装：解析频道/播放列表/单视频 URL，获取视频列表与元数据。

设计要点（来自规格 §17 技术验证结果）:

1. 使用 ``extract_flat='in_playlist'`` 快速拿到视频 ID 列表，避免逐个完整解析。
2. 裸频道 URL（如 ``https://www.youtube.com/@handle``）会被 yt-dlp 解析为 tab 列表
   （Videos/Live/Shorts/Playlists），需要识别后跳转到 ``Videos`` tab。
3. flat extraction 不包含 ``upload_date`` 等字段；正式流程在过滤已存在文件后，
   再对剩余视频调用 :func:`hydrate_video` 补全元数据。
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

import yt_dlp


@dataclass(frozen=True)
class VideoEntry:
    """flat extraction 阶段返回的轻量条目，仅保证有 id 和可用 url。"""

    id: str
    url: str
    title: str | None = None


@dataclass(frozen=True)
class VideoMetadata:
    """完整 metadata，由 :func:`hydrate_video` 返回。"""

    id: str
    url: str
    title: str
    uploader: str | None
    channel_id: str | None
    upload_date: str | None  # YYYYMMDD
    duration: int | None


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


def list_recent_videos(url: str, limit: int) -> tuple[SourceInfo, list[VideoEntry]]:
    """解析输入 URL，返回最多 ``limit`` 个视频条目。

    支持的输入：

    - 频道 URL（``@handle`` / ``/channel/UCxxx`` / ``/c/`` / ``/user/``）
    - 播放列表 URL
    - 单视频 URL

    参数:
        url: YouTube 链接。
        limit: 最多返回多少个视频。

    返回:
        ``(source_info, entries)`` 元组。``source_info`` 用于构造输出目录名。

    异常:
        :class:`VideoListError` 当 yt-dlp 无法解析或返回空。
    """
    ydl_opts: dict[str, Any] = {
        "quiet": True,
        "no_warnings": True,
        "skip_download": True,
        "ignoreerrors": True,
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


class VideoHydrateError(RuntimeError):
    """单个视频 hydrate metadata 失败时抛出。"""


def hydrate_video(video_id: str) -> VideoMetadata:
    """对单个视频做完整 metadata 提取，主要为了拿 ``upload_date``。

    参数:
        video_id: YouTube 视频 ID（11 位字符串）。

    异常:
        :class:`VideoHydrateError` 当视频不可访问、被删除或 yt-dlp 失败时。
    """
    ydl_opts: dict[str, Any] = {
        "quiet": True,
        "no_warnings": True,
        "skip_download": True,
        "ignoreerrors": True,
        "noplaylist": True,
    }
    url = _video_url(video_id)
    try:
        with yt_dlp.YoutubeDL(ydl_opts) as ydl:
            info = ydl.extract_info(url, download=False)
    except Exception as exc:
        raise VideoHydrateError(f"hydrate failed for {video_id}: {exc}") from exc

    if not info:
        raise VideoHydrateError(f"hydrate returned no info for {video_id}")

    return VideoMetadata(
        id=info.get("id") or video_id,
        url=info.get("webpage_url") or url,
        title=info.get("title") or "Untitled",
        uploader=info.get("uploader") or info.get("channel"),
        channel_id=info.get("channel_id") or info.get("uploader_id"),
        upload_date=info.get("upload_date") or info.get("release_date"),
        duration=info.get("duration"),
    )


def metadata_from_entry(entry: VideoEntry, source: SourceInfo) -> VideoMetadata:
    """从 flat extract 的轻量条目 + 源信息构造 fallback metadata。

    用途：当 :func:`hydrate_video` 因 YouTube 反爬等原因失败时，
    仍可使用 flat extraction 已有的 title + 频道级 uploader 继续生成 Markdown，
    只是文件名日期前缀会是 ``0000-00-00``。
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
