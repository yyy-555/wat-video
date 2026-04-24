"""
WAT台本 + 生成画像 + TTS → ショート動画 (MP4) を組み立てる。
"""
from __future__ import annotations

import asyncio
import os
import textwrap
import threading

import numpy as np
from PIL import Image, ImageDraw, ImageFont
from moviepy.editor import (
    AudioFileClip, ColorClip, CompositeVideoClip,
    ImageClip, concatenate_videoclips,
)

from config import W, H, FPS, COLORS, FONT_BOLD, FONT_NORMAL, VOICES

# エンコード用に解像度を半分に落とす（速度優先）
ENC_W, ENC_H = W // 2, H // 2
ENC_FPS = 15

_BADGE_COLORS = {
    "W": COLORS["W"],
    "A": COLORS["A"],
    "T": COLORS["T"],
}


def _image_clip(img: Image.Image, duration: float) -> ImageClip:
    arr = np.array(img.convert("RGB").resize((W, H), Image.LANCZOS))
    return ImageClip(arr).set_duration(duration)


def _font(size: int, bold: bool = True) -> ImageFont.FreeTypeFont:
    path = FONT_BOLD if bold else FONT_NORMAL
    try:
        return ImageFont.truetype(path, size)
    except OSError:
        return ImageFont.load_default()


def _build_overlay(section_type: str, label: str, body: str,
                   idx: int, total: int) -> np.ndarray:
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

    bar_y = H - 72
    bar_h = 8
    mg    = 80
    full  = W - 2 * mg
    filled = int(full * (idx + 1) / total)
    draw.rounded_rectangle([mg, bar_y, mg + full, bar_y + bar_h], radius=4, fill=(60, 60, 80, 180))
    draw.rounded_rectangle([mg, bar_y, mg + filled, bar_y + bar_h], radius=4, fill=(*color, 220))

    return np.array(img)


def _tts_sync(text: str, voice: str, path: str, timeout: int = 30) -> bool:
    """TTSを生成。失敗/タイムアウト時はFalseを返す。"""
    result = {"ok": False, "err": None}

    async def _run():
        import edge_tts
        await edge_tts.Communicate(text, voice).save(path)
        result["ok"] = True

    def _thread():
        try:
            asyncio.run(_run())
        except Exception as e:
            result["err"] = e

    t = threading.Thread(target=_thread, daemon=True)
    t.start()
    t.join(timeout=timeout)
    return result["ok"]


def _silent_audio(duration: float, path: str) -> None:
    """無音MP3を生成する（TTS失敗時のフォールバック）。"""
    import struct, wave
    wav_path = path.replace(".mp3", ".wav")
    n_samples = int(44100 * duration)
    with wave.open(wav_path, "w") as wf:
        wf.setnchannels(1)
        wf.setsampwidth(2)
        wf.setframerate(44100)
        wf.writeframes(struct.pack("<" + "h" * n_samples, *([0] * n_samples)))
    os.replace(wav_path, path.replace(".mp3", ".wav"))
    # .wav のまま AudioFileClip に渡す（mp3不要）
    result_path = path.replace(".mp3", ".wav")
    return result_path


def assemble(
    script: dict,
    images: list[Image.Image],
    language: str,
    output_dir: str,
    video_id: str,
) -> str:
    os.makedirs(output_dir, exist_ok=True)
    voice    = VOICES.get(language, VOICES["en"])
    sections = script["sections"]
    total    = len(sections)

    tmp_dir = os.path.join(output_dir, "_tmp")
    os.makedirs(tmp_dir, exist_ok=True)

    clips = []
    try:
        for idx, (sec, img) in enumerate(zip(sections, images)):
            mp3_path = os.path.join(tmp_dir, f"s{idx}.mp3")
            tts_ok = _tts_sync(sec["text"], voice, mp3_path, timeout=30)

            if tts_ok and os.path.exists(mp3_path):
                audio_path = mp3_path
            else:
                # TTS失敗 → 無音3秒
                print(f"    TTS failed for section {idx}, using silent audio")
                wav_path = os.path.join(tmp_dir, f"s{idx}.wav")
                import struct, wave
                n = int(44100 * 3)
                with wave.open(wav_path, "w") as wf:
                    wf.setnchannels(1); wf.setsampwidth(2); wf.setframerate(44100)
                    wf.writeframes(struct.pack("<" + "h" * n, *([0] * n)))
                audio_path = wav_path

            audio    = AudioFileClip(audio_path)
            duration = audio.duration

            bg           = _image_clip(img, duration)
            dark         = ColorClip((W, H), color=(0, 0, 0)).set_opacity(0.45).set_duration(duration)
            overlay_arr  = _build_overlay(sec["type"], sec["label"], sec["text"], idx, total)
            overlay_clip = ImageClip(overlay_arr, ismask=False).set_duration(duration)

            section_clip = CompositeVideoClip([bg, dark, overlay_clip]).set_audio(audio)
            clips.append(section_clip)

        video    = concatenate_videoclips(clips, method="compose")
        # 半解像度・低FPSでエンコード（HF無料CPU向け）
        video    = video.resize((ENC_W, ENC_H))
        out_path = os.path.join(output_dir, f"{video_id}.mp4")
        video.write_videofile(
            out_path,
            fps=ENC_FPS,
            codec="libx264",
            audio_codec="aac",
            preset="ultrafast",
            logger=None,
        )
        video.close()

    finally:
        import shutil
        shutil.rmtree(tmp_dir, ignore_errors=True)
        for c in clips:
            try:
                c.close()
            except Exception:
                pass

    return out_path
