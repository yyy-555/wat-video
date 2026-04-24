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

_SYSTEM = """\
You are a professional short-video scriptwriter using the WAT framework:
  W (Why/Hook)       — grab attention in 1–2 sentences, state the core problem
  A (Action/Content) — 3 concrete, actionable tips or steps
  T (Transformation) — show the result / call to action in 1–2 sentences

Rules:
- Script text must be in the requested language.
- image_prompt must ALWAYS be in English, photorealistic, vertical (9:16), cinematic.
- Return ONLY valid JSON. No markdown, no explanation outside the JSON.
"""

_TEMPLATE = """\
Topic    : {topic}
Language : {language}

Return exactly this JSON structure:
{{
  "topic": "{topic}",
  "sections": [
    {{
      "type": "W",
      "label": "{w_label}",
      "text": "<hook script in {language}>",
      "image_prompt": "<English image prompt, portrait 9:16, vivid>"
    }},
    {{
      "type": "A",
      "label": "{a_label} 1",
      "text": "<action tip 1 in {language}>",
      "image_prompt": "<English image prompt>"
    }},
    {{
      "type": "A",
      "label": "{a_label} 2",
      "text": "<action tip 2 in {language}>",
      "image_prompt": "<English image prompt>"
    }},
    {{
      "type": "A",
      "label": "{a_label} 3",
      "text": "<action tip 3 in {language}>",
      "image_prompt": "<English image prompt>"
    }},
    {{
      "type": "T",
      "label": "{t_label}",
      "text": "<transformation/CTA in {language}>",
      "image_prompt": "<English image prompt>"
    }}
  ]
}}
"""

_LANG_NAMES = {"ja": "Japanese", "en": "English", "es": "Spanish"}


def generate(topic: str, language: str = "ja") -> dict:
    """WAT台本を生成して辞書で返す。"""
    from groq import Groq
    from config import GROQ_API_KEY

    client = Groq(api_key=GROQ_API_KEY)

    labels = LANG_LABELS.get(language, LANG_LABELS["en"])
    lang_name = _LANG_NAMES.get(language, language)

    prompt = _TEMPLATE.format(
        topic=topic,
        language=lang_name,
        w_label=labels["W"],
        a_label=labels["A"],
        t_label=labels["T"],
    )

    response = client.chat.completions.create(
        model="llama-3.3-70b-versatile",
        messages=[
            {"role": "system", "content": _SYSTEM},
            {"role": "user",   "content": prompt},
        ],
        temperature=0.7,
        max_tokens=2048,
    )

    raw = response.choices[0].message.content.strip()

    m = re.search(r"\{[\s\S]+\}", raw)
    if not m:
        raise ValueError(f"No JSON found in Groq response:\n{raw}")
    return json.loads(m.group(0))
