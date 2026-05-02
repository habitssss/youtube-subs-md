"""字幕提取：从 yt-dlp 返回的 caption 字典中选英文轨道并下载解析。

为什么不再使用 ``youtube-transcript-api``：

- 该库直接调用 YouTube 的非公开 timedtext 接口，无法复用浏览器 Cookie，
  在被 YouTube 标记的 IP 上几乎一定遭遇 ``RequestBlocked``。
- yt-dlp 已经能拿到 ``automatic_captions`` 中的 ``json3`` 直链，
  通过 :meth:`yt_dlp.YoutubeDL.urlopen` 下载即可复用同一份 Cookie 与 UA。
- 因此 transcripts 模块改为消费 :class:`videos.VideoData` 已经持有的字幕字典。

字幕优先级保持不变：

1. 人工英文字幕 (``manual``)
2. 自动英文字幕 (``auto-generated``)
3. 都没有 → 抛出 :class:`NoEnglishTranscript`
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from typing import Any

import yt_dlp

from .videos import VideoData, make_base_opts


@dataclass(frozen=True)
class FetchedTranscript:
    """已获取的字幕。"""

    video_id: str
    language_code: str  # 例如 "en", "en-US"；上层可归一为 "en"
    source: str  # "manual" 或 "auto-generated"
    snippets: list[str]


class NoEnglishTranscript(RuntimeError):
    """目标视频没有英文字幕（人工或自动均无）。"""


class TranscriptFetchError(RuntimeError):
    """下载或解析字幕过程中失败。"""


# yt-dlp 在 caption 字典里支持多种格式，按优先级选最便于解析的
_PREFERRED_FORMATS = ("json3", "srv3", "srv2", "srv1", "vtt")


def _pick_english_track(
    captions: dict[str, list[dict[str, Any]]],
) -> tuple[str, dict[str, Any]] | None:
    """从字幕字典里挑英文轨道。

    返回 ``(language_code, format_dict)``；找不到返回 ``None``。
    优先精确匹配 ``en``，再考虑 ``en-US`` / ``en-GB`` 等变体。
    """
    if not captions:
        return None

    # 1. 精确 "en"
    if "en" in captions:
        return "en", _pick_format(captions["en"])

    # 2. 任何以 "en" 开头的变体
    for code, formats in captions.items():
        if code.lower().split("-", 1)[0] == "en":
            return code, _pick_format(formats)

    return None


def _pick_format(formats: list[dict[str, Any]]) -> dict[str, Any]:
    """按 ``_PREFERRED_FORMATS`` 顺序选最易解析的字幕格式条目。"""
    by_ext = {f.get("ext"): f for f in formats if f.get("url")}
    for ext in _PREFERRED_FORMATS:
        if ext in by_ext:
            return by_ext[ext]
    # fallback: 第一个有 url 的
    for f in formats:
        if f.get("url"):
            return f
    raise TranscriptFetchError("no usable caption format with URL")


def _parse_json3(data: bytes) -> list[str]:
    """解析 YouTube json3 字幕，返回 snippet 文本列表（不含时间戳）。"""
    obj = json.loads(data)
    events = obj.get("events") or []
    snippets: list[str] = []
    for event in events:
        segs = event.get("segs") or []
        text = "".join(s.get("utf8", "") for s in segs)
        # json3 中常见 "\n" 单独成 segment，去掉并保留为段间空白
        text = text.replace("\n", " ").strip()
        if text:
            snippets.append(text)
    return snippets


def _parse_vtt(data: bytes) -> list[str]:
    """非常简化的 VTT fallback 解析：剥离时间戳与序号、保留文本行。"""
    lines = data.decode("utf-8", errors="replace").splitlines()
    snippets: list[str] = []
    buf: list[str] = []
    for line in lines:
        s = line.strip()
        # 跳过空行 / 头部 / 时间戳 / cue id
        if not s:
            if buf:
                snippets.append(" ".join(buf).strip())
                buf = []
            continue
        if s.upper().startswith("WEBVTT") or s.startswith("NOTE"):
            continue
        if "-->" in s:
            continue
        if s.isdigit():
            continue
        # 简单去掉常见标签 <c> </c> <00:00:00.000>
        import re

        s = re.sub(r"<[^>]+>", "", s)
        if s:
            buf.append(s)
    if buf:
        snippets.append(" ".join(buf).strip())
    return snippets


def fetch_english_transcript(
    video_data: VideoData,
    *,
    cookies_from_browser: str | None = None,
) -> FetchedTranscript:
    """从 :class:`VideoData` 中选英文字幕并下载。

    优先 manual EN，其次 auto-generated EN；下载所选 URL 后按 ``ext`` 解析。

    异常:
        :class:`NoEnglishTranscript` 当 manual / auto 都无英文轨道。
        :class:`TranscriptFetchError` 当下载或解析过程出错。
    """
    video_id = video_data.metadata.id

    # 1. manual EN 优先
    pick = _pick_english_track(video_data.subtitles)
    source = "manual"

    # 2. fallback 到 auto-generated
    if pick is None:
        pick = _pick_english_track(video_data.automatic_captions)
        source = "auto-generated"

    if pick is None:
        raise NoEnglishTranscript(f"no English transcript for {video_id}")

    language_code, fmt = pick
    url = fmt.get("url")
    ext = (fmt.get("ext") or "").lower()
    if not url:
        raise TranscriptFetchError(f"caption track without URL for {video_id}")

    # 3. 用 yt-dlp 的 urlopen 下载，保证复用同一份 Cookie 与 UA
    ydl_opts = {**make_base_opts(cookies_from_browser), "noplaylist": True}
    try:
        with yt_dlp.YoutubeDL(ydl_opts) as ydl:
            data = ydl.urlopen(url).read()
    except Exception as exc:
        raise TranscriptFetchError(
            f"download caption failed for {video_id}: {exc}"
        ) from exc

    # 4. 按格式解析
    try:
        if ext in ("json3", "srv3"):
            # srv3 与 json3 在新版 yt-dlp 中实际同源，按 json3 解析
            snippets = _parse_json3(data)
        elif ext == "vtt":
            snippets = _parse_vtt(data)
        else:
            # 其它 srv1/srv2 是 XML/简化文本，做最朴素的兜底
            snippets = _parse_vtt(data)  # 通常仍能拿到大部分文本
    except Exception as exc:
        raise TranscriptFetchError(
            f"parse caption failed for {video_id} (ext={ext}): {exc}"
        ) from exc

    return FetchedTranscript(
        video_id=video_id,
        language_code=language_code,
        source=source,
        snippets=snippets,
    )
