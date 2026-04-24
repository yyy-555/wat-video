"""
HuggingFace InferenceClient (FLUX.1-schnell) で画像を生成する。
ポートレート (1080×1920) にリサイズして返す。
"""
from __future__ import annotations

import time

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


def generate(prompt: str, api_key: str, retries: int = 4) -> Image.Image:
    from huggingface_hub import InferenceClient

    client = InferenceClient(token=api_key)
    full_prompt = prompt + _STYLE

    for attempt in range(retries):
        try:
            img = client.text_to_image(
                full_prompt,
                model="black-forest-labs/FLUX.1-schnell",
                width=768,
                height=1360,
            )
            return _smart_crop_to_portrait(img)

        except Exception as e:
            err = str(e).lower()
            if "loading" in err or "503" in err:
                wait = 30
                print(f"    Model loading, wait {wait}s... (attempt {attempt+1})")
                time.sleep(wait)
                continue
            if attempt == retries - 1:
                raise RuntimeError(f"Image generation failed: {e}") from e
            time.sleep(10)

    raise RuntimeError("Image generation failed after all retries")
