"""
Pollinations.ai で画像を生成する。完全無料・APIキー不要。
ポートレート (1080×1920) にリサイズして返す。
"""
from __future__ import annotations

import time
import urllib.parse
import urllib.request
import io

from PIL import Image

_STYLE = (
    ", ultra realistic, cinematic lighting, sharp focus, "
    "professional photography, vibrant colors, 9:16 vertical portrait"
)

CANVAS_W, CANVAS_H = 1080, 1920


def _smart_crop_to_portrait(img: Image.Image) -> Image.Image:
    iw, ih = img.size
    scale = max(CANVAS_W / iw, CANVAS_H / ih)
    nw, nh = int(iw * scale), int(ih * scale)
    img = img.resize((nw, nh), Image.LANCZOS)
    ox = (nw - CANVAS_W) // 2
    oy = (nh - CANVAS_H) // 2
    return img.crop((ox, oy, ox + CANVAS_W, oy + CANVAS_H))


def generate(prompt: str, api_key: str = "", retries: int = 3) -> Image.Image:
    full_prompt  = prompt + _STYLE
    encoded      = urllib.parse.quote(full_prompt)
    url = (
        f"https://image.pollinations.ai/prompt/{encoded}"
        f"?width=768&height=1360&nologo=true&model=flux"
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
