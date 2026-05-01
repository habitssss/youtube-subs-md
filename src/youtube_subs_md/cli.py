"""CLI 入口模块（占位）。

后续 commit 会替换为完整的命令行实现，目前仅保证
`uv run youtube-subs-md` 能正常解析入口点。
"""

from __future__ import annotations

import typer

app = typer.Typer(
    add_completion=False,
    help="Download recent YouTube channel English subtitles to Markdown.",
)


@app.command()
def main() -> None:
    """占位命令，实际功能将在后续 commit 实现。"""
    typer.echo("youtube-subs-md: not implemented yet (scaffold only)")


if __name__ == "__main__":
    app()
