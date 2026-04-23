"""
HuggingFace Inference API (FLUX.1-schnell) で画像を生成する。
ポートレート (1080×1920) にリサイズして返す。
"""
from __future__ import annotations

import time
from io import BytesIO

import requests
from PIL import Image

HF_MODEL   = "black-forest-labs/FLUX.1-schnell"
HF_API_URL = f"https://api-inference.huggingface.co/models/{HF_MODEL}"

_STYLE = (
    ", ultra realistic, cinematic lighting, sharp focus, "
    "professional photography, vibrant colors, 9:16 vertical portrait"
)

# 出力キャンバスサイズ
CANVAS_W, CANVAS_H = 1080, 1920


def _smart_crop_to_portrait(img: Image.Image) -> Image.Image:
    """生成画像を 1080×1920 にセンタークロップ+リサイズ。"""
    iw, ih = img.size
    scale = max(CANVAS_W / iw, CANVAS_H / ih)
    nw, nh = int(iw * scale), int(ih * scale)
    img = img.resize((nw, nh), Image.LANCZOS)
    ox = (nw - CANVAS_W) // 2
    oy = (nh - CANVAS_H) // 2
    return img.crop((ox, oy, ox + CANVAS_W, oy + CANVAS_H))


def generate(prompt: str, api_key: str, retries: int = 4) -> Image.Image:
    """
    プロンプトから画像を生成して PIL Image (1080×1920) で返す。
    モデルロード中 (503) は自動リトライ。
    """
    headers = {"Authorization": f"Bearer {api_key}"}
    payload = {
        "inputs": prompt + _STYLE,
        "parameters": {
            "width": 768,
            "height": 1360,
            "num_inference_steps": 4,
            "guidance_scale": 0.0,
        },
    }

    for attempt in range(retries):
        try:
            resp = requests.post(HF_API_URL, headers=headers, json=payload, timeout=120)

            if resp.status_code == 503:
                wait = float(resp.json().get("estimated_time", 20))
                wait = min(wait, 40)
                print(f"    Model loading, wait {wait:.0f}s...")
                time.sleep(wait)
                continue

            if resp.status_code == 422:
                # パラメーター非対応の場合はデフォルトで再試行
                payload.pop("parameters", None)
                continue

            resp.raise_for_status()
            img = Image.open(BytesIO(resp.content)).convert("RGB")
            return _smart_crop_to_portrait(img)

        except requests.exceptions.Timeout:
            print(f"    Timeout (attempt {attempt + 1}/{retries})")
            if attempt == retries - 1:
                raise
            time.sleep(10)
        except Exception as e:
            if attempt == retries - 1:
                raise RuntimeError(f"Image generation failed: {e}") from e
            time.sleep(5)

    raise RuntimeError("Image generation failed after all retries")
