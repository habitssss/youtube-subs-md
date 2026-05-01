"""Markdown 渲染。

固定输出格式（不使用 YAML frontmatter）::

    # Title

    URL: ...
    Channel: ...
    Published: ...
    Subtitle: en, manual

    ---

    Transcript text...
"""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class VideoMeta:
    """渲染 Markdown 所需的视频元信息。"""

    title: str
    url: str
    channel: str
    published: str  # YYYY-MM-DD 或 "unknown"
    subtitle_source: str  # "manual" | "auto-generated"
    language: str = "en"


def render(meta: VideoMeta, transcript: str) -> str:
    """生成 Markdown 文本。

    每个元信息行末尾保留两个空格，方便 Markdown 渲染时强制换行。
    """
    header_lines = [
        f"URL: {meta.url}  ",
        f"Channel: {meta.channel}  ",
        f"Published: {meta.published}  ",
        f"Subtitle: {meta.language}, {meta.subtitle_source}",
    ]
    parts = [
        f"# {meta.title}",
        "",
        "\n".join(header_lines),
        "",
        "---",
        "",
        transcript.strip(),
        "",
    ]
    return "\n".join(parts)
