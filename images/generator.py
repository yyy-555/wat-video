"""
Pollinations.ai で画像を生成する。完全無料・APIキー不要。
ポートレート (1080×1920) にリサイズして返す。
"""
from __future__ import annotations

import io
import random
import time
import urllib.parse
import urllib.request

from PIL import Image

CANVAS_W, CANVAS_H = 1080, 1920

_STYLES: dict[str, str] = {
    "リアル": (
        ", ultra realistic, cinematic lighting, sharp focus, "
        "professional photography, vibrant colors, 9:16 vertical portrait"
    ),
    "カートゥーン": (
        ", cartoon style, bold outlines, vibrant flat colors, "
        "comic illustration, fun and energetic, 9:16 vertical portrait"
    ),
    "ポップアート": (
        ", pop art style, bold graphic colors, halftone dots, "
        "Andy Warhol inspired, striking contrast, 9:16 vertical portrait"
    ),
    "アニメ": (
        ", anime style, cel shading, vibrant colors, "
        "detailed illustration, Japanese animation, 9:16 vertical portrait"
    ),
}


def _smart_crop_to_portrait(img: Image.Image) -> Image.Image:
    iw, ih = img.size
    scale = max(CANVAS_W / iw, CANVAS_H / ih)
    nw, nh = int(iw * scale), int(ih * scale)
    img = img.resize((nw, nh), Image.LANCZOS)
    ox = (nw - CANVAS_W) // 2
    oy = (nh - CANVAS_H) // 2
    return img.crop((ox, oy, ox + CANVAS_W, oy + CANVAS_H))


def generate(prompt: str, api_key: str = "", style: str = "リアル",
             retries: int = 3) -> Image.Image:
    style_suffix = _STYLES.get(style, _STYLES["リアル"])
    full_prompt  = prompt + style_suffix
    encoded      = urllib.parse.quote(full_prompt)
    seed = random.randint(1, 99999)
    url  = (
        f"https://image.pollinations.ai/prompt/{encoded}"
        f"?width=768&height=1360&nologo=true&model=flux&seed={seed}"
    )

    for attempt in range(retries):
        try:
            req = urllib.request.Request(url, headers={"User-Agent": "wat-video/1.0"})
            with urllib.request.urlopen(req, timeout=120) as resp:
                img = Image.open(io.BytesIO(resp.read())).convert("RGB")
            return _smart_crop_to_portrait(img)
        except Exception as e:
            if attempt == retries - 1:
                raise RuntimeError(f"Image generation failed: {e}") from e
            print(f"    Image generation failed (attempt {attempt + 1}), retrying...")
            time.sleep(10)

    raise RuntimeError("Image generation failed after all retries")
