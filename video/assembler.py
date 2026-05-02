"""
WAT台本 + 生成画像 + TTS → ショート動画 (MP4) を組み立てる。
moviepy を使わず ffmpeg を直接呼び出すことで HF 無料 CPU でも完走できる。
"""
from __future__ import annotations

import asyncio
import os
import struct
import subprocess
import textwrap
import threading
import wave

import numpy as np
from PIL import Image, ImageDraw, ImageFont

from config import W, H, COLORS, FONT_BOLD, FONT_NORMAL, VOICES

ENC_W, ENC_H = W // 2, H // 2
ENC_FPS = 15

_BADGE_COLORS = {
    "W": COLORS["W"],
    "A": COLORS["A"],
    "T": COLORS["T"],
}


def _font(size: int, bold: bool = True) -> ImageFont.FreeTypeFont:
    path = FONT_BOLD if bold else FONT_NORMAL
    try:
        return ImageFont.truetype(path, size)
    except OSError:
        return ImageFont.load_default()


def _build_overlay(section_type: str, label: str, body: str,
                   idx: int, total: int) -> Image.Image:
    img  = Image.new("RGBA", (W, H), (0, 0, 0, 0))
    draw = ImageDraw.Draw(img)
    color = _BADGE_COLORS.get(section_type, (180, 180, 180))

    font_badge = _font(48, bold=True)
    badge_text = f"  {label.upper()}  "
    bbox = draw.textbbox((0, 0), badge_text, font=font_badge)
    bw, bh = bbox[2] - bbox[0], bbox[3] - bbox[1]
    bx = (W - bw) // 2
    by = 160
    draw.rounded_rectangle(
        [bx - 20, by - 10, bx + bw + 20, by + bh + 10],
        radius=28, fill=(*color, 200),
    )
    draw.text((bx, by), badge_text, font=font_badge, fill=(255, 255, 255, 255))

    words  = len(body.split())
    fsize  = 68 if words <= 20 else 52
    wrap   = 18 if fsize == 68 else 24
    font_b = _font(fsize, bold=True)
    lines  = []
    for line in body.strip().splitlines():
        lines.extend(textwrap.wrap(line, wrap) or [""])

    line_h  = fsize + 20
    total_h = len(lines) * line_h
    start_y = (H - total_h) // 2 + 60

    for i, line in enumerate(lines):
        bb  = draw.textbbox((0, 0), line, font=font_b)
        tx  = (W - (bb[2] - bb[0])) // 2
        ty  = start_y + i * line_h
        draw.text((tx + 3, ty + 3), line, font=font_b, fill=(0, 0, 0, 200))
        clr = color if i == 0 else (255, 255, 255, 240)
        draw.text((tx, ty), line, font=font_b, fill=clr)

    bar_y  = H - 72
    bar_h  = 8
    mg     = 80
    full   = W - 2 * mg
    filled = int(full * (idx + 1) / total)
    draw.rounded_rectangle([mg, bar_y, mg + full, bar_y + bar_h],   radius=4, fill=(60, 60, 80, 180))
    draw.rounded_rectangle([mg, bar_y, mg + filled, bar_y + bar_h], radius=4, fill=(*color, 220))

    return img


def _wrap_by_pixel(draw, text: str, font, max_px: int) -> list[str]:
    """ピクセル幅ベースでテキストを折り返す。日本語・英語どちらにも対応。"""
    lines: list[str] = []
    cur = ""
    for unit in (text.split() or [""]):
        candidate = f"{cur} {unit}".strip() if cur else unit
        if draw.textbbox((0, 0), candidate, font=font)[2] <= max_px:
            cur = candidate
        else:
            if cur:
                lines.append(cur)
            if draw.textbbox((0, 0), unit, font=font)[2] > max_px:
                cur = ""
                for ch in unit:
                    tmp = cur + ch
                    if draw.textbbox((0, 0), tmp, font=font)[2] <= max_px:
                        cur = tmp
                    else:
                        if cur:
                            lines.append(cur)
                        cur = ch
            else:
                cur = unit
    if cur:
        lines.append(cur)
    return lines or [""]


def _build_subtitle(text: str) -> Image.Image:
    """字幕オーバーレイを生成する。画面内に必ず収まるよう調整。"""
    img  = Image.new("RGBA", (ENC_W, ENC_H), (0, 0, 0, 0))
    draw = ImageDraw.Draw(img)

    SIDE_PAD = 32   # 左右の余白（px）
    BTM_PAD  = 60   # 下からの余白（px）
    max_w    = ENC_W - 2 * SIDE_PAD

    # フォントサイズを大→小で試して3行以内に収まる最大サイズを選ぶ
    font = None
    lines: list[str] = []
    for size in [34, 28, 22, 18]:
        f = _font(size, bold=False)
        wrapped = _wrap_by_pixel(draw, text.strip(), f, max_w)
        if len(wrapped) <= 3:
            font, lines = f, wrapped
            font_size = size
            break
    if font is None:
        font_size = 18
        font = _font(font_size, bold=False)
        lines = _wrap_by_pixel(draw, text.strip(), font, max_w)[:3]

    line_h  = font_size + 14
    total_h = len(lines) * line_h
    start_y = max(ENC_H - total_h - BTM_PAD, 10)

    for i, line in enumerate(lines):
        bb = draw.textbbox((0, 0), line, font=font)
        tw = bb[2] - bb[0]
        tx = max(SIDE_PAD, (ENC_W - tw) // 2)
        ty = start_y + i * line_h
        rx2 = min(tx + tw + 10, ENC_W - SIDE_PAD)
        draw.rounded_rectangle(
            [tx - 10, ty - 4, rx2, ty + line_h - 4],
            radius=6, fill=(0, 0, 0, 180),
        )
        for dx, dy in [(-1, -1), (1, -1), (-1, 1), (1, 1)]:
            draw.text((tx + dx, ty + dy), line, font=font, fill=(0, 0, 0, 255))
        draw.text((tx, ty), line, font=font, fill=(255, 255, 255, 255))

    return img


def _make_frame(img: Image.Image, sec: dict, idx: int, total: int,
                subtitle: str = "") -> Image.Image:
    """背景画像 + 暗幕 + オーバーレイ + 字幕を PIL で合成して1枚のRGB画像にする。"""
    bg      = img.convert("RGB").resize((ENC_W, ENC_H), Image.LANCZOS)
    dark    = Image.new("RGBA", (ENC_W, ENC_H), (0, 0, 0, int(0.45 * 255)))
    overlay = _build_overlay(sec["type"], sec["label"], sec["text"], idx, total)
    overlay = overlay.resize((ENC_W, ENC_H), Image.LANCZOS)

    result = Image.alpha_composite(bg.convert("RGBA"), dark)
    result = Image.alpha_composite(result, overlay)

    sub_text = (subtitle or "").strip()
    if sub_text:
        result = Image.alpha_composite(result, _build_subtitle(sub_text))

    return result.convert("RGB")


def _tts_sync(text: str, voice: str, path: str, timeout: int = 10) -> bool:
    """edge-tts でTTS生成。timeout秒以内に失敗したらFalseを返す。"""
    result = {"ok": False}

    async def _run():
        import edge_tts
        await edge_tts.Communicate(text, voice).save(path)
        result["ok"] = True

    def _thread():
        try:
            asyncio.run(_run())
        except Exception:
            pass

    t = threading.Thread(target=_thread, daemon=True)
    t.start()
    t.join(timeout=timeout)
    return result["ok"]


def _silent_wav(duration: float, path: str) -> None:
    """指定秒数の無音WAVを生成する。"""
    n = int(44100 * duration)
    with wave.open(path, "w") as wf:
        wf.setnchannels(1)
        wf.setsampwidth(2)
        wf.setframerate(44100)
        wf.writeframes(struct.pack("<" + "h" * n, *([0] * n)))


def _ffmpeg(*args: str, timeout: int = 120) -> None:
    """ffmpeg を呼び出す。失敗したら RuntimeError を上げる。"""
    r = subprocess.run(
        ["ffmpeg", "-y", *args],
        capture_output=True,
        timeout=timeout,
    )
    if r.returncode != 0:
        raise RuntimeError(r.stderr.decode(errors="replace")[-600:])


def assemble(
    script: dict,
    images: list[Image.Image],
    language: str,
    output_dir: str,
    video_id: str,
    subtitles: list[str] = None,
    voice: str = None,
) -> str:
    os.makedirs(output_dir, exist_ok=True)
    voice    = voice or VOICES.get(language, VOICES["en"])
    sections = script["sections"]
    raw_subs = subtitles or []
    subs     = [(s or "") for s in raw_subs] + [""] * (len(sections) - len(raw_subs))

    tmp_dir = os.path.join(output_dir, "_tmp")
    os.makedirs(tmp_dir, exist_ok=True)

    clip_paths: list[str] = []
    try:
        for idx, (sec, img) in enumerate(zip(sections, images)):
            # ── TTS ──────────────────────────────────────────────────────────
            mp3_path = os.path.join(tmp_dir, f"s{idx}.mp3")
            tts_ok   = _tts_sync(sec["text"], voice, mp3_path, timeout=25)
            if tts_ok and os.path.exists(mp3_path):
                audio_path = mp3_path
            else:
                print(f"    TTS failed for section {idx}, using silent audio")
                wav_path = os.path.join(tmp_dir, f"s{idx}.wav")
                _silent_wav(3.0, wav_path)
                audio_path = wav_path

            # ── フレーム合成（PIL） ──────────────────────────────────────────
            subtitle   = subs[idx] if idx < len(subs) else ""
            frame      = _make_frame(img, sec, idx, len(sections), subtitle=subtitle)
            frame_path = os.path.join(tmp_dir, f"s{idx}.png")
            frame.save(frame_path)

            # ── ffmpeg で静止画 + 音声 → 動画クリップ ──────────────────────
            clip_path = os.path.join(tmp_dir, f"s{idx}.mp4")
            _ffmpeg(
                "-loop", "1", "-framerate", str(ENC_FPS), "-i", frame_path,
                "-i", audio_path,
                "-c:v", "libx264", "-preset", "ultrafast", "-crf", "28",
                "-c:a", "aac", "-b:a", "96k",
                "-shortest",
                clip_path,
                timeout=60,
            )
            clip_paths.append(clip_path)

        # ── 全クリップを結合 ──────────────────────────────────────────────────
        concat_file = os.path.join(tmp_dir, "concat.txt")
        with open(concat_file, "w") as f:
            for p in clip_paths:
                f.write(f"file '{p}'\n")

        out_path = os.path.join(output_dir, f"{video_id}.mp4")
        _ffmpeg(
            "-f", "concat", "-safe", "0", "-i", concat_file,
            "-c", "copy",
            out_path,
            timeout=120,
        )

    finally:
        import shutil
        shutil.rmtree(tmp_dir, ignore_errors=True)

    return out_path
