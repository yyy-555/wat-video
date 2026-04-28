"""
Groq API (llama-3.3-70b-versatile) を使ってWATフレームワークの台本を生成する。
各セクションに HuggingFace 向け英語画像プロンプトを含める。
"""
from __future__ import annotations

import json
import re

LANG_LABELS = {
    "ja": {"W": "なぜ？", "A": "方法", "T": "変化"},
    "en": {"W": "WHY",   "A": "ACTION", "T": "TRANSFORM"},
    "es": {"W": "POR QUÉ", "A": "ACCIÓN", "T": "CAMBIO"},
}

_LANG_NAMES = {"ja": "Japanese", "en": "English", "es": "Spanish"}

_SYSTEM = """\
You are a professional short-video scriptwriter using the WAT framework:
  W (Why/Hook)       — grab attention, state the core problem
  A (Action/Content) — concrete, actionable tips or steps
  T (Transformation) — show the result / call to action

Rules:
- Script text must be in the requested language.
- Match the requested text length per section as closely as possible.
- image_prompt must ALWAYS be in English, vertical (9:16), cinematic.
- image_prompt must depict ONE realistic, plausible scene directly related to the text.
- image_prompt must NEVER combine unrelated objects or locations (e.g. no "Tokyo Tower on Mt. Fuji").
- image_prompt should show real-world situations: people, food, nature, cities — each in their natural context.
- Return ONLY valid JSON. No markdown, no explanation outside the JSON.
"""


def _build_prompt(topic: str, language: str, duration_sec: int, num_scenes: int) -> str:
    labels    = LANG_LABELS.get(language, LANG_LABELS["en"])
    lang_name = _LANG_NAMES.get(language, language)

    num_a         = num_scenes - 2  # W と T を除いた A セクション数
    num_sections  = num_scenes
    sec_duration  = duration_sec / num_sections

    # 1セクションあたりの目安文字数/語数
    if language == "ja":
        text_hint = f"約{int(sec_duration * 6)}〜{int(sec_duration * 7)}文字"
    else:
        text_hint = f"about {int(sec_duration * 2)}–{int(sec_duration * 2.5)} words"

    # セクションのJSONテンプレートを動的生成
    parts = []
    parts.append(
        f'    {{\n'
        f'      "type": "W",\n'
        f'      "label": "{labels["W"]}",\n'
        f'      "text": "<hook in {lang_name}, {text_hint}>",\n'
        f'      "image_prompt": "<English image prompt, portrait 9:16, vivid>"\n'
        f'    }}'
    )
    for i in range(1, num_a + 1):
        parts.append(
            f'    {{\n'
            f'      "type": "A",\n'
            f'      "label": "{labels["A"]} {i}",\n'
            f'      "text": "<action tip {i} in {lang_name}, {text_hint}>",\n'
            f'      "image_prompt": "<English image prompt>"\n'
            f'    }}'
        )
    parts.append(
        f'    {{\n'
        f'      "type": "T",\n'
        f'      "label": "{labels["T"]}",\n'
        f'      "text": "<transformation/CTA in {lang_name}, {text_hint}>",\n'
        f'      "image_prompt": "<English image prompt>"\n'
        f'    }}'
    )

    sections_str = ",\n".join(parts)

    return (
        f"Topic    : {topic}\n"
        f"Language : {lang_name}\n"
        f"Target duration: {duration_sec} seconds "
        f"({num_sections} sections, {text_hint} per section)\n\n"
        f"Return exactly this JSON structure:\n"
        f'{{\n'
        f'  "topic": "{topic}",\n'
        f'  "sections": [\n'
        f"{sections_str}\n"
        f"  ]\n"
        f"}}"
    )


def generate(topic: str, language: str = "ja", duration_sec: int = 60,
             num_scenes: int = 5) -> dict:
    """WAT台本を生成して辞書で返す。"""
    from groq import Groq
    from config import GROQ_API_KEY

    client = Groq(api_key=GROQ_API_KEY)
    prompt = _build_prompt(topic, language, duration_sec, num_scenes)

    response = client.chat.completions.create(
        model="llama-3.3-70b-versatile",
        messages=[
            {"role": "system", "content": _SYSTEM},
            {"role": "user",   "content": prompt},
        ],
        temperature=0.7,
        max_tokens=4096,
    )

    raw = response.choices[0].message.content.strip()
    m   = re.search(r"\{[\s\S]+\}", raw)
    if not m:
        raise ValueError(f"No JSON found in Groq response:\n{raw}")
    return json.loads(m.group(0))
