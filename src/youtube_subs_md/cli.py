"""CLI 入口与主流程编排。

命令::

    youtube-subs-md <url> [--out PATH] [--limit N] [--overwrite] [--dry-run]

主流程::

    解析参数
      ↓
    list_recent_videos(url, limit)        # flat extraction
      ↓
    构造 channel 输出目录
      ↓
    对每个视频：
      ├─ 已存在 + 未指定 overwrite      → skip existing
      ├─ dry-run                        → print, 不下载
      ├─ hydrate_video (失败时 fallback)
      ├─ fetch_english_transcript
      │   ├─ NoEnglishTranscript        → skip no subtitles
      │   └─ TranscriptFetchError       → record failed
      ├─ 文本清洗 + 渲染 Markdown
      └─ 写文件
      ↓
    输出 summary
"""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path

import typer
from rich.console import Console
from rich.markup import escape
from rich.progress import (
    BarColumn,
    Progress,
    SpinnerColumn,
    TextColumn,
    TimeElapsedColumn,
)

from . import filenames, markdown, text_cleaning, transcripts, videos

console = Console()

app = typer.Typer(
    add_completion=False,
    help="Download recent YouTube channel English subtitles to Markdown.",
)


@dataclass
class RunSummary:
    """运行结果计数与失败明细。"""

    processed: int = 0
    downloaded: int = 0
    skipped_existing: int = 0
    skipped_no_subtitles: int = 0
    failed: int = 0
    output_dir: Path | None = None
    failures: list[str] = field(default_factory=list)
    no_subtitle_videos: list[str] = field(default_factory=list)


def _short_exc(exc: BaseException, max_len: int = 200) -> str:
    """提取异常短摘要，避免 yt-dlp / transcript-api 的多页错误污染输出。"""
    text = str(exc).strip()
    if not text:
        return exc.__class__.__name__
    first = text.splitlines()[0].strip() or exc.__class__.__name__
    return first if len(first) <= max_len else first[: max_len - 3] + "..."


def _normalize_lang(code: str) -> str:
    """``en-US`` / ``en-GB`` 统一归一为 ``en``。"""
    return code.split("-", 1)[0].lower() if code else "en"


def _build_meta(
    video_meta: videos.VideoMetadata,
    fetched: transcripts.FetchedTranscript,
) -> markdown.VideoMeta:
    """将 videos / transcripts 模块结果映射为 markdown 渲染所需的 VideoMeta。"""
    return markdown.VideoMeta(
        title=video_meta.title,
        url=video_meta.url,
        channel=video_meta.uploader or "Unknown Channel",
        published=filenames.format_upload_date(video_meta.upload_date),
        subtitle_source=fetched.source,
        language=_normalize_lang(fetched.language_code),
    )


def _process_one(
    entry: videos.VideoEntry,
    source: videos.SourceInfo,
    channel_dir: Path,
    overwrite: bool,
    summary: RunSummary,
    *,
    cookies_from_browser: str | None,
) -> None:
    """处理单个视频：fetch (metadata + caption URLs) → fetch transcript → render → write。

    所有可恢复错误都在此函数内部捕获并写入 summary，确保不会中断整体流程。
    """
    # label 同时用于带样式的 console.print 与纯文本失败明细，
    # 这里预先转义防止 Rich 将 video_id 中的方括号当作 markup
    label = escape(f"{entry.title or entry.id} [{entry.id}]")
    raw_label = f"{entry.title or entry.id} [{entry.id}]"

    # 1. 跳过已存在
    existing = filenames.find_existing_for_video_id(channel_dir, entry.id)
    if existing and not overwrite:
        summary.skipped_existing += 1
        console.print(f"[yellow]{escape('[skip existing]')}[/] {label}")
        return

    # 2. 一次性拿到 metadata + caption URLs（需要 Chrome cookies 绕过 bot 检测）
    try:
        video_data = videos.fetch_video_data(
            entry.id, cookies_from_browser=cookies_from_browser
        )
    except videos.VideoFetchError as exc:
        # 元数据拿不到 → 没法继续做字幕（caption URL 也在这一步返回）
        summary.failed += 1
        short = _short_exc(exc)
        summary.failures.append(f"{raw_label}: {short}")
        console.print(f"[red]{escape('[failed fetch]')}[/] {label}: {escape(short)}")
        return

    video_meta = video_data.metadata

    # 3. 从已拿到的字幕字典里选英文 + 下载
    try:
        fetched = transcripts.fetch_english_transcript(
            video_data, cookies_from_browser=cookies_from_browser
        )
    except transcripts.NoEnglishTranscript:
        summary.skipped_no_subtitles += 1
        summary.no_subtitle_videos.append(label)
        console.print(f"[yellow]{escape('[skip no-subs]')}[/] {label}")
        return
    except transcripts.TranscriptFetchError as exc:
        summary.failed += 1
        short = _short_exc(exc)
        summary.failures.append(f"{raw_label}: {short}")
        console.print(f"[red]{escape('[failed]')}[/] {label}: {escape(short)}")
        return

    # 4. 清洗 + 渲染
    transcript_text = text_cleaning.merge_to_paragraph(fetched.snippets)
    if not transcript_text:
        # 字幕存在但清洗后为空，按"无字幕"处理
        summary.skipped_no_subtitles += 1
        summary.no_subtitle_videos.append(label)
        console.print(f"[yellow]{escape('[skip empty-subs]')}[/] {label}")
        return

    meta = _build_meta(video_meta, fetched)
    md = markdown.render(meta, transcript_text)

    # 5. 写文件（覆盖时复用同名；新建时按规格命名）
    if existing and overwrite:
        target = existing
    else:
        fname = filenames.build_video_filename(
            video_meta.upload_date, video_meta.title, entry.id
        )
        target = channel_dir / fname

    channel_dir.mkdir(parents=True, exist_ok=True)
    target.write_text(md, encoding="utf-8")

    summary.downloaded += 1
    console.print(
        f"[green]{escape('[ok]')}[/] {label} → {escape(target.name)}"
    )


def _print_summary(summary: RunSummary) -> None:
    """终端打印最终 summary。"""
    console.print()
    console.rule("[bold]Done")
    console.print(f"Processed:           {summary.processed}")
    console.print(f"Downloaded:          {summary.downloaded}")
    console.print(f"Skipped existing:    {summary.skipped_existing}")
    console.print(f"Skipped no subtitles:{summary.skipped_no_subtitles}")
    console.print(f"Failed:              {summary.failed}")
    if summary.output_dir:
        console.print(f"Output:              {summary.output_dir}")

    if summary.failures:
        console.print()
        console.print("[red]Failures:[/]")
        for f in summary.failures:
            console.print(f"  - {f}")


@app.command()
def main(
    url: str = typer.Argument(..., help="YouTube channel / playlist / video URL"),
    out: Path = typer.Option(
        Path("./transcripts"),
        "--out",
        help="Markdown 输出根目录",
    ),
    limit: int = typer.Option(50, "--limit", help="最多处理最近多少个视频"),
    overwrite: bool = typer.Option(False, "--overwrite", help="覆盖已存在文件"),
    dry_run: bool = typer.Option(
        False, "--dry-run", help="只列出将处理的视频，不下载字幕"
    ),
    cookies_from_browser: str = typer.Option(
        "chrome",
        "--cookies-from-browser",
        help=(
            "读取已登录 YouTube 的浏览器 Cookie，用于绕过 bot 检测。"
            "支持 chrome / firefox / safari / edge / brave 等 yt-dlp 接受的值。"
            "传空字符串可禁用（仅适合不触发反爬的网络）。"
        ),
    ),
) -> None:
    """主命令：下载频道最近 N 个视频的英文字幕为 Markdown。"""
    summary = RunSummary()

    # 空字符串 → None，表示不附加 Cookie
    cookies: str | None = cookies_from_browser.strip() or None

    console.print(f"[bold]Resolving:[/] {escape(url)}")
    try:
        source, entries = videos.list_recent_videos(
            url, limit, cookies_from_browser=cookies
        )
    except videos.VideoListError as exc:
        console.print(f"[red]Failed to resolve URL:[/] {escape(_short_exc(exc))}")
        raise typer.Exit(code=1)

    if not entries:
        console.print("[yellow]No videos found for the given URL.[/]")
        raise typer.Exit(code=0)

    channel_dir = out / filenames.channel_dir_name(
        source.uploader, source.channel_id
    )
    summary.output_dir = channel_dir

    console.print(
        f"[bold]Channel:[/] {escape(str(source.uploader or source.channel_id))} "
        f"→ [cyan]{escape(str(channel_dir))}[/]"
    )
    console.print(f"[bold]Videos:[/] {len(entries)}")

    if dry_run:
        console.rule("[bold]Dry run")
        for e in entries:
            console.print(
                f"  - {escape(f'[{e.id}]')} {escape(e.title or '(no title)')}"
            )
        console.print(f"\nWould write into: {channel_dir}")
        return

    # 串行处理，使用 rich 进度条
    with Progress(
        SpinnerColumn(),
        TextColumn("[progress.description]{task.description}"),
        BarColumn(),
        TextColumn("{task.completed}/{task.total}"),
        TimeElapsedColumn(),
        console=console,
        transient=True,
    ) as progress:
        task = progress.add_task("Processing", total=len(entries))
        for entry in entries:
            summary.processed += 1
            try:
                _process_one(
                    entry,
                    source,
                    channel_dir,
                    overwrite,
                    summary,
                    cookies_from_browser=cookies,
                )
            except Exception as exc:
                # 兜底：任何未预期异常都不应中断整体流程
                summary.failed += 1
                raw_label = f"{entry.title or entry.id} [{entry.id}]"
                short = _short_exc(exc)
                summary.failures.append(f"{raw_label}: unexpected: {short}")
                console.print(
                    f"[red]{escape('[unexpected]')}[/] {escape(raw_label)}: {escape(short)}"
                )
            finally:
                progress.advance(task)

    _print_summary(summary)


if __name__ == "__main__":
    app()
