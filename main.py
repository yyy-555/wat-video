#!/usr/bin/env python3
"""
WAT Video Generator
  research → script → images → video
"""
import os
import re
import sys
sys.path.insert(0, os.path.dirname(__file__))

import click
from rich.console import Console
from rich.panel import Panel
from rich.table import Table
from rich.progress import Progress, SpinnerColumn, TextColumn

from config import (
    ANTHROPIC_API_KEY, HF_API_KEY,
    YOUTUBE_API_KEY, TWITTER_BEARER, NEWS_API_KEY,
    OUTPUT_DIR, SUPPORTED_LANGUAGES,
)

console = Console()


# ── helpers ───────────────────────────────────────────────────────────────────

def _safe_id(text: str, max_len: int = 20) -> str:
    return re.sub(r"[^a-zA-Z0-9_\-ぁ-ん一-龯ァ-ン]", "_", text)[:max_len]


def _show_script(script: dict) -> None:
    for sec in script["sections"]:
        color = {"W": "red", "A": "blue", "T": "green"}.get(sec["type"], "white")
        console.print(Panel(
            sec["text"],
            title=f"[bold {color}]{sec['label']}[/]",
            border_style=color,
        ))


# ── research command ──────────────────────────────────────────────────────────

@click.group()
def cli():
    """WAT Short-Video Generator  ─  Research → Script → Images → Video"""


@cli.command()
@click.option("--query",   "-q", prompt="検索キーワード", help="Research keyword / topic")
@click.option("--lang",    "-l", default="ja", type=click.Choice(SUPPORTED_LANGUAGES))
@click.option("--country", "-c", default="JP", help="Country code (JP / US / ES)")
@click.option("--sources", "-s", default="google,youtube,twitter,news",
              help="Comma-separated: google,youtube,twitter,news")
def research(query, lang, country, sources):
    """Fetch trending topics from Google / YouTube / X / News."""
    from research.trends import research as do_research

    src_list = [s.strip() for s in sources.split(",")]
    console.print(f"\n[cyan]Researching:[/] {query}  |  sources: {', '.join(src_list)}\n")

    with Progress(SpinnerColumn(), TextColumn("{task.description}"), console=console) as prog:
        task = prog.add_task("[cyan]Fetching trends...", total=None)
        results = do_research(
            query, language=lang, country=country, sources=src_list,
            youtube_api_key=YOUTUBE_API_KEY,
            twitter_bearer=TWITTER_BEARER,
            news_api_key=NEWS_API_KEY,
        )
        prog.update(task, description="[green]Done")

    table = Table(title=f"Top Trends — {query}", show_lines=True)
    table.add_column("#",      style="dim",   width=4)
    table.add_column("Topic",  style="bold")
    table.add_column("Score",  justify="right")
    table.add_column("Source", style="cyan")

    for i, r in enumerate(results[:15], 1):
        table.add_row(str(i), r["topic"], str(r["score"]), r["source"])

    console.print(table)


# ── generate command ──────────────────────────────────────────────────────────

@cli.command()
@click.option("--topic", "-t", prompt="Topic", help="Video topic")
@click.option("--lang",  "-l", default="ja", type=click.Choice(SUPPORTED_LANGUAGES),
              prompt="Language [ja/en/es]")
@click.option("--no-video", is_flag=True, default=False,
              help="Skip video assembly (script + images only)")
def generate(topic, lang, no_video):
    """Generate WAT script → images → MP4 video."""

    if not ANTHROPIC_API_KEY:
        console.print("[red]ANTHROPIC_API_KEY not set.[/]")
        raise SystemExit(1)
    if not HF_API_KEY:
        console.print("[red]HF_API_KEY not set.[/]")
        raise SystemExit(1)

    video_id = _safe_id(topic)
    out_dir  = os.path.join(OUTPUT_DIR, f"{video_id}_{lang}")
    os.makedirs(out_dir, exist_ok=True)

    with Progress(SpinnerColumn(), TextColumn("{task.description}"), console=console) as prog:

        # ── 1. Script ──────────────────────────────────────────────────────
        t = prog.add_task("[cyan]Generating WAT script...", total=None)
        from scripts.wat_writer import generate as gen_script
        script = gen_script(topic, lang)
        prog.update(t, description="[green]WAT script done")

        # スクリプト保存
        import json
        with open(os.path.join(out_dir, "script.json"), "w", encoding="utf-8") as f:
            json.dump(script, f, ensure_ascii=False, indent=2)

        # ── 2. Images ──────────────────────────────────────────────────────
        from images.generator import generate as gen_image
        img_list = []
        for i, sec in enumerate(script["sections"]):
            ti = prog.add_task(
                f"[cyan]Image {i+1}/{len(script['sections'])} [{sec['type']}]...", total=None
            )
            img = gen_image(sec["image_prompt"], HF_API_KEY)
            img_path = os.path.join(out_dir, f"img_{i}_{sec['type']}.png")
            img.save(img_path)
            img_list.append(img)
            prog.update(ti, description=f"[green]Image {i+1} done → {os.path.basename(img_path)}")

        if no_video:
            prog.stop()
            console.print(Panel.fit(
                f"[green]Script + Images saved[/]\n{out_dir}",
                title="Done (no-video mode)", border_style="green",
            ))
            _show_script(script)
            return

        # ── 3. Video ───────────────────────────────────────────────────────
        tv = prog.add_task("[cyan]Assembling video...", total=None)
        from video.assembler import assemble
        mp4_path = assemble(script, img_list, lang, out_dir, video_id)
        prog.update(tv, description="[green]Video done!")

    console.print()
    _show_script(script)
    console.print(Panel.fit(
        f"[bold green]Video ready![/]\n[bold]File:[/] {mp4_path}",
        title="WAT Video", border_style="green",
    ))


# ── auto command ──────────────────────────────────────────────────────────────

@cli.command()
@click.option("--query",   "-q", prompt="検索キーワード", help="Research keyword")
@click.option("--lang",    "-l", default="ja", type=click.Choice(SUPPORTED_LANGUAGES),
              prompt="Language [ja/en/es]")
@click.option("--country", "-c", default="JP")
@click.option("--sources", "-s", default="google,youtube,twitter,news")
@click.option("--pick",    "-n", default=1, help="Use the Nth trending topic (default: 1st)")
def auto(query, lang, country, sources, pick):
    """Auto pipeline: research top trend → generate full video."""
    from research.trends import research as do_research

    src_list = [s.strip() for s in sources.split(",")]
    console.print(f"\n[cyan]Auto pipeline:[/] researching '{query}'...\n")

    results = do_research(
        query, language=lang, country=country, sources=src_list,
        youtube_api_key=YOUTUBE_API_KEY,
        twitter_bearer=TWITTER_BEARER,
        news_api_key=NEWS_API_KEY,
    )

    if not results:
        console.print("[red]No trending topics found. Try --query with a different keyword.[/]")
        raise SystemExit(1)

    chosen = results[min(pick - 1, len(results) - 1)]
    console.print(Panel.fit(
        f"[bold]Chosen topic:[/] {chosen['topic']}\n"
        f"[dim]Score {chosen['score']}  ·  Source: {chosen['source']}[/]",
        title="Top Trend", border_style="cyan",
    ))

    # generate コマンドを直接呼び出す
    from click.testing import CliRunner
    runner = CliRunner()
    result = runner.invoke(generate, [
        "--topic", chosen["topic"],
        "--lang", lang,
    ], catch_exceptions=False)
    console.print(result.output)


if __name__ == "__main__":
    cli()
