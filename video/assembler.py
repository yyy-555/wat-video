"""
WAT台本 + 生成画像 + TTS → ショート動画 (MP4) を組み立てる。
"""
from __future__ import annotations

import asyncio
import os
import textwrap

import numpy as np
from PIL import Image, ImageDraw, ImageFont
from moviepy.editor import (
    AudioFileClip, ColorClip, CompositeVideoClip,
    ImageClip, VideoClip, concatenate_videoclips,
)

from config import W, H, FPS, COLORS, FONT_BOLD, FONT_NORMAL, VOICES

# WAT ラベルの背景色
_BADGE_COLORS = {
    "W": COLORS["W"],
    "A": COLORS["A"],
    "T": COLORS["T"],
}


# ── Ken Burns ────────────────────────────────────────────────────────────────

def _ken_burns_clip(img: Image.Image, duration: float) -> VideoClip:
    base = np.array(img.convert("RGB"))
    bh, bw = base.shape[:2]

    def make_frame(t):
        zoom = 1.0 + 0.05 * (t / duration)
        fw = int(W / zoom)
        fh = int(H / zoom)
        ox = (bw - fw) // 2
        oy = (bh - fh) // 2
        cropped = base[oy:oy + fh, ox:ox + fw]
        return np.array(Image.fromarray(cropped).resize((W, H), Image.LANCZOS))

    return VideoClip(make_frame, duration=duration)


# ── Font helper ───────────────────────────────────────────────────────────────

def _font(size: int, bold: bool = True) -> ImageFont.FreeTypeFont:
    path = FONT_BOLD if bold else FONT_NORMAL
    try:
        return ImageFont.truetype(path, size)
    except OSError:
        return ImageFont.load_default()


# ── Text overlay ──────────────────────────────────────────────────────────────

def _build_overlay(section_type: str, label: str, body: str,
                   idx: int, total: int) -> np.ndarray:
    img  = Image.new("RGBA", (W, H), (0, 0, 0, 0))
    draw = ImageDraw.Draw(img)
    color = _BADGE_COLORS.get(section_type, (180, 180, 180))

    # バッジ
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

    # 本文
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
        # 影
        draw.text((tx + 3, ty + 3), line, font=font_b, fill=(0, 0, 0, 200))
        clr = color if i == 0 else (255, 255, 255, 240)
        draw.text((tx, ty), line, font=font_b, fill=clr)

    # プログレスバー
    bar_y = H - 72
    bar_h = 8
    mg    = 80
    full  = W - 2 * mg
    filled = int(full * (idx + 1) / total)
    draw.rounded_rectangle([mg, bar_y, mg + full, bar_y + bar_h], radius=4, fill=(60, 60, 80, 180))
    draw.rounded_rectangle([mg, bar_y, mg + filled, bar_y + bar_h], radius=4, fill=(*color, 220))

    return np.array(img)


# ── TTS ───────────────────────────────────────────────────────────────────────

def _tts_sync(text: str, voice: str, path: str) -> None:
    import edge_tts
    asyncio.run(edge_tts.Communicate(text, voice).save(path))


# ── Main entry ────────────────────────────────────────────────────────────────

def assemble(
    script: dict,
    images: list[Image.Image],
    language: str,
    output_dir: str,
    video_id: str,
) -> str:
    """
    script  : wat_writer.generate() の戻り値
    images  : 各セクションの PIL Image (script["sections"] と同順)
    language: "ja" | "en" | "es"
    Returns : 出力 MP4 パス
    """
    os.makedirs(output_dir, exist_ok=True)
    voice    = VOICES.get(language, VOICES["en"])
    sections = script["sections"]
    total    = len(sections)

    tmp_dir = os.path.join(output_dir, "_tmp")
    os.makedirs(tmp_dir, exist_ok=True)

    clips = []
    try:
        for idx, (sec, img) in enumerate(zip(sections, images)):
            # TTS
            mp3_path = os.path.join(tmp_dir, f"s{idx}.mp3")
            _tts_sync(sec["text"], voice, mp3_path)
            audio = AudioFileClip(mp3_path)
            duration = audio.duration

            # 背景 (Ken Burns)
            bg = _ken_burns_clip(img, duration)

            # 暗幕
            dark = ColorClip((W, H), color=(0, 0, 0)).set_opacity(0.45).set_duration(duration)

            # テキストオーバーレイ
            overlay_arr  = _build_overlay(sec["type"], sec["label"], sec["text"], idx, total)
            overlay_clip = ImageClip(overlay_arr, ismask=False).set_duration(duration)

            section_clip = (
                CompositeVideoClip([bg, dark, overlay_clip])
                .set_audio(audio)
            )
            clips.append(section_clip)

        video    = concatenate_videoclips(clips, method="compose")
        out_path = os.path.join(output_dir, f"{video_id}.mp4")
        video.write_videofile(
            out_path, fps=FPS, codec="libx264", audio_codec="aac", logger=None,
        )
        video.close()

    finally:
        import shutil
        shutil.rmtree(tmp_dir, ignore_errors=True)
        for c in clips:
            c.close()

    return out_path
