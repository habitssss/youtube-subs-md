"""``youtube-transcript-api`` 封装：按 video_id 获取英文字幕。

字幕优先级：

1. 人工英文字幕 (``manual``)
2. 自动英文字幕 (``auto-generated``)
3. 都没有 → 抛出 :class:`NoEnglishTranscript`

返回结果 :class:`FetchedTranscript` 包含原始 snippet text 列表与来源标记，
供上层调用 ``text_cleaning`` / ``markdown`` 模块进一步处理。
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from youtube_transcript_api import YouTubeTranscriptApi


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
    """请求被阻止 / 视频不可访问 / 其他底层异常。"""


def _snippet_text(snippet: Any) -> str:
    """兼容 dict 和对象两种 snippet 表示。"""
    if isinstance(snippet, dict):
        return str(snippet.get("text") or "")
    return str(getattr(snippet, "text", ""))


def fetch_english_transcript(video_id: str) -> FetchedTranscript:
    """获取指定视频的英文字幕。

    参数:
        video_id: YouTube 视频 ID。

    异常:
        :class:`NoEnglishTranscript` 当人工和自动英文字幕都不存在时。
        :class:`TranscriptFetchError` 当 list/fetch 调用失败（网络/反爬/视频不可达）。
    """
    api = YouTubeTranscriptApi()

    try:
        transcript_list = api.list(video_id)
    except Exception as exc:
        # 区分"无字幕"和"请求失败"困难，这里全部归类为请求异常；
        # NoEnglishTranscript 留给明确没找到英文条目的情况。
        raise TranscriptFetchError(
            f"list transcripts failed for {video_id}: {exc}"
        ) from exc

    selected = None
    source: str | None = None

    # 优先人工字幕
    try:
        selected = transcript_list.find_manually_created_transcript(["en"])
        source = "manual"
    except Exception:
        selected = None

    # fallback 到自动字幕
    if selected is None:
        try:
            selected = transcript_list.find_generated_transcript(["en"])
            source = "auto-generated"
        except Exception:
            selected = None

    if selected is None or source is None:
        raise NoEnglishTranscript(f"no English transcript for {video_id}")

    try:
        fetched = selected.fetch()
    except Exception as exc:
        raise TranscriptFetchError(
            f"fetch transcript failed for {video_id}: {exc}"
        ) from exc

    # fetched 可能是 FetchedTranscript-like 对象 (含 .snippets) 或可迭代 snippet 列表
    snippets_obj = getattr(fetched, "snippets", None)
    if snippets_obj is None:
        # 旧版 API 直接返回 list[dict]
        snippets_iter = fetched
    else:
        snippets_iter = snippets_obj

    snippet_texts = [_snippet_text(s) for s in snippets_iter]

    language_code = (
        getattr(fetched, "language_code", None)
        or getattr(selected, "language_code", None)
        or "en"
    )

    return FetchedTranscript(
        video_id=video_id,
        language_code=str(language_code),
        source=source,
        snippets=snippet_texts,
    )
