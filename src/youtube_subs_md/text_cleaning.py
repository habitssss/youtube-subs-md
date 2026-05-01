"""字幕文本清洗与合并。

输入: ``youtube-transcript-api`` 返回的 snippet text 列表（已无时间戳）。
输出: 适合写入 Markdown 的纯文本段落。

MVP 策略:
    - 完全相同的相邻片段去重（弱去重，足以应对手动字幕、部分自动字幕）
    - 全部合并为一段（不做基于时间间隔的分段）

后续可扩展:
    - 后缀-前缀重叠合并（YouTube 自动字幕的滚动重复模式）
    - 按时间间隔或句号自动分段
"""

from __future__ import annotations

import re

# 多个连续空白（含换行）压缩为单个空格
_WHITESPACE = re.compile(r"\s+")


def normalize_snippet(text: str) -> str:
    """规整单个 snippet: 去除 HTML/VTT 残留标签、折叠空白。"""
    if not text:
        return ""
    # 去除常见 VTT/HTML 标签 (例如 <c>, </c>, <00:00:01.000>)
    cleaned = re.sub(r"<[^>]+>", "", text)
    # 折叠空白
    cleaned = _WHITESPACE.sub(" ", cleaned).strip()
    return cleaned


def dedupe_adjacent(snippets: list[str]) -> list[str]:
    """去除完全相同的相邻片段。

    YouTube 部分字幕（尤其自动字幕）会在相邻 cue 之间重复整段文字，
    这里仅做最简单的"上一条 == 当前条"判断。
    """
    result: list[str] = []
    prev: str | None = None
    for text in snippets:
        if not text:
            continue
        if text == prev:
            continue
        result.append(text)
        prev = text
    return result


def merge_to_paragraph(snippets: list[str]) -> str:
    """将清洗后的 snippet 列表合并为单段纯文本。"""
    normalized = [normalize_snippet(s) for s in snippets]
    deduped = dedupe_adjacent([s for s in normalized if s])
    return " ".join(deduped).strip()
