"""文件名 / 目录名清洗工具。

负责将 YouTube 视频标题、频道名等含特殊字符的字符串
转换为跨平台安全的文件名片段，并构造最终输出路径。
"""

from __future__ import annotations

import re
from pathlib import Path

# 跨平台不允许出现在文件名中的字符（含控制字符）
_ILLEGAL_CHARS = re.compile(r'[<>:"/\\|?*\x00-\x1f]')

# 保留文件名长度上限，避免某些文件系统的 255 字节限制
# 留出余量给日期前缀、video id、扩展名
_MAX_TITLE_LEN = 120


def sanitize(name: str, *, fallback: str = "untitled") -> str:
    """清洗任意字符串为安全文件名片段。

    参数:
        name: 原始字符串（可能含 / : ? emoji 换行等）。
        fallback: 清洗后为空时使用的占位值。

    返回:
        移除非法字符、折叠空白、去除首尾点号/空格的安全字符串。
    """
    if not name:
        return fallback

    # 替换非法字符为短横线
    cleaned = _ILLEGAL_CHARS.sub("-", name)
    # 折叠所有空白为单个空格
    cleaned = re.sub(r"\s+", " ", cleaned).strip()
    # 去除首尾的点号（Windows 不允许文件名以点结尾）
    cleaned = cleaned.strip(". ")

    # 如果清洗结果只剩标点/分隔符，视为无效，回退到 fallback
    if not cleaned or not re.search(r"[\w\u4e00-\u9fff]", cleaned):
        return fallback
    return cleaned


def truncate(name: str, max_len: int = _MAX_TITLE_LEN) -> str:
    """按字符数截断文件名片段，保留可读性。"""
    if len(name) <= max_len:
        return name
    return name[:max_len].rstrip(". ")


def format_upload_date(upload_date: str | None) -> str:
    """将 yt-dlp 的 ``YYYYMMDD`` 转为 ``YYYY-MM-DD``。

    无效输入返回 ``"0000-00-00"``，避免文件名格式破坏。
    """
    if not upload_date or len(upload_date) != 8 or not upload_date.isdigit():
        return "0000-00-00"
    return f"{upload_date[:4]}-{upload_date[4:6]}-{upload_date[6:8]}"


def build_video_filename(
    upload_date: str | None,
    title: str,
    video_id: str,
) -> str:
    """构造单个视频的 Markdown 文件名。

    格式: ``YYYY-MM-DD - <sanitized title> [<video_id>].md``
    """
    date_str = format_upload_date(upload_date)
    title_part = truncate(sanitize(title))
    return f"{date_str} - {title_part} [{video_id}].md"


def channel_dir_name(uploader: str | None, channel_id: str | None) -> str:
    """构造频道输出子目录名。

    优先使用 ``uploader`` (显示名)，fallback 到 ``channel_id``。
    """
    if uploader:
        candidate = sanitize(uploader, fallback="")
        if candidate:
            return truncate(candidate)
    if channel_id:
        return sanitize(channel_id, fallback="unknown-channel")
    return "unknown-channel"


def find_existing_for_video_id(out_dir: Path, video_id: str) -> Path | None:
    """在输出目录中查找是否已存在该 video_id 的 Markdown 文件。

    通过 glob ``*[<video_id>].md`` 实现跳过判定，避免依赖标题/日期。

    返回:
        已存在的第一个匹配路径；若不存在返回 ``None``。
    """
    if not out_dir.exists():
        return None
    matches = list(out_dir.glob(f"*[[]{video_id}[]].md"))
    return matches[0] if matches else None
