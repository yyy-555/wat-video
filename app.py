"""
WAT Video Generator — Gradio UI for HuggingFace Spaces
"""
import json
import os
import sys
import tempfile
import uuid

import gradio as gr
from PIL import Image

sys.path.insert(0, os.path.dirname(__file__))

from config import (
    GEMINI_API_KEY, HF_API_KEY,
    YOUTUBE_API_KEY, TWITTER_BEARER, NEWS_API_KEY,
    OUTPUT_DIR, SUPPORTED_LANGUAGES,
)

os.makedirs(OUTPUT_DIR, exist_ok=True)

LANG_NAMES  = {"ja": "🇯🇵 日本語", "en": "🇺🇸 English", "es": "🇪🇸 Español"}
COUNTRY_MAP = {"ja": "JP", "en": "US", "es": "ES"}


# ── Core pipeline functions ───────────────────────────────────────────────────

def run_research(query: str, lang: str, country: str, sources: list[str]) -> list[list]:
    if not query.strip():
        raise gr.Error("キーワードを入力してください")
    from research.trends import research
    results = research(
        query, language=lang, country=country, sources=sources,
        youtube_api_key=YOUTUBE_API_KEY,
        twitter_bearer=TWITTER_BEARER,
        news_api_key=NEWS_API_KEY,
    )
    return [[i + 1, r["topic"], r["score"], r["source"]] for i, r in enumerate(results[:15])]


def run_generate(topic: str, lang: str, progress=gr.Progress(track_tqdm=True)):
    if not topic.strip():
        raise gr.Error("トピックを入力してください")
    if not GEMINI_API_KEY:
        raise gr.Error("GEMINI_API_KEY が設定されていません")
    if not HF_API_KEY:
        raise gr.Error("HF_API_KEY が設定されていません")

    video_id = str(uuid.uuid4())[:8]
    out_dir  = os.path.join(OUTPUT_DIR, video_id)
    os.makedirs(out_dir, exist_ok=True)

    # ── 1. Script ──────────────────────────────────────────────────────────
    progress(0.05, desc="📝 台本を生成中...")
    from scripts.wat_writer import generate as gen_script
    script = gen_script(topic, lang)

    script_json_path = os.path.join(out_dir, "script.json")
    with open(script_json_path, "w", encoding="utf-8") as f:
        json.dump(script, f, ensure_ascii=False, indent=2)

    sections = script["sections"]
    script_md = _script_to_markdown(script)

    # ── 2. Images ──────────────────────────────────────────────────────────
    from images.generator import generate as gen_image
    images: list[Image.Image] = []
    img_paths: list[str] = []

    for i, sec in enumerate(sections):
        progress(0.1 + i * 0.1, desc=f"🎨 画像生成 {i+1}/{len(sections)} [{sec['type']}]...")
        img = gen_image(sec["image_prompt"], HF_API_KEY)
        p   = os.path.join(out_dir, f"img_{i}_{sec['type']}.png")
        img.save(p)
        images.append(img)
        img_paths.append(p)

    # ── 3. Video ───────────────────────────────────────────────────────────
    progress(0.75, desc="🎬 動画を組み立て中...")
    from video.assembler import assemble
    mp4_path = assemble(script, images, lang, out_dir, video_id)

    progress(1.0, desc="✅ 完了!")
    return script_md, img_paths, mp4_path, script_json_path


def run_auto(query: str, lang: str, country: str, sources: list[str],
             progress=gr.Progress(track_tqdm=True)):
    if not query.strip():
        raise gr.Error("キーワードを入力してください")

    progress(0.05, desc="🔍 トレンドをリサーチ中...")
    rows = run_research(query, lang, country, sources)

    if not rows:
        raise gr.Error("トレンドが見つかりませんでした。キーワードを変えてみてください。")

    top_topic = rows[0][1]
    progress(0.15, desc=f"🎯 トピック決定: {top_topic}")

    script_md, img_paths, mp4_path, json_path = run_generate(top_topic, lang, progress=progress)
    return top_topic, script_md, img_paths, mp4_path


# ── Helpers ───────────────────────────────────────────────────────────────────

def _script_to_markdown(script: dict) -> str:
    lines = [f"## 📋 {script.get('topic', '')}"]
    colors = {"W": "🔴", "A": "🔵", "T": "🟢"}
    for sec in script["sections"]:
        icon = colors.get(sec["type"], "⚪")
        lines.append(f"\n### {icon} {sec['label']}")
        lines.append(sec["text"])
    return "\n".join(lines)


def pick_topic_to_generate(evt: gr.SelectData, table_data, lang):
    try:
        row = evt.index[0]
        if hasattr(table_data, "iloc"):
            topic = str(table_data.iloc[row, 1])
        else:
            topic = table_data[row][1]
        return topic, lang
    except Exception:
        return gr.update(), gr.update()


# ── UI ────────────────────────────────────────────────────────────────────────

CSS = """
.gradio-container { max-width: 900px !important; margin: auto; }
.wat-header { text-align: center; padding: 20px 0; }
footer { display: none !important; }
"""

with gr.Blocks(title="WAT Video Generator") as demo:

    gr.HTML("""
    <div class="wat-header">
      <h1>🎬 WAT Video Generator</h1>
      <p style="color:#888">Research → Script → Images → Short Video</p>
    </div>
    """)

    with gr.Tabs():

        # ── Tab 1: Research ────────────────────────────────────────────────
        with gr.Tab("🔍 リサーチ", id="research"):
            gr.Markdown("### トレンドトピックを調査")
            with gr.Row():
                r_query   = gr.Textbox(label="キーワード", placeholder="例: 料理, fitness, recetas...", scale=3)
                r_lang    = gr.Radio(choices=list(LANG_NAMES.keys()), value="ja",
                                     label="言語", type="value")
                r_country = gr.Dropdown(choices=["JP", "US", "ES", "GB", "FR"],
                                        value="JP", label="国")

            r_sources = gr.CheckboxGroup(
                choices=["google", "youtube", "twitter", "news"],
                value=["google", "youtube", "news"],
                label="リサーチソース",
            )
            r_btn = gr.Button("🔍 リサーチ開始", variant="primary")

            r_table = gr.DataFrame(
                headers=["#", "トピック", "スコア", "ソース"],
                datatype=["number", "str", "number", "str"],
                label="トレンドトピック",
                interactive=False,
            )
            gr.Markdown("💡 *行をクリックすると「動画生成」タブにトピックが入力されます*",
                        elem_classes=["hint"])

            # ── Tab 2: Generate (shared state) ──────────────────────────────
        with gr.Tab("🎬 動画生成", id="generate"):
            gr.Markdown("### WATフレームワークで動画を生成")
            with gr.Row():
                g_topic = gr.Textbox(label="トピック", placeholder="例: 5分で作れる朝食",
                                     scale=3)
                g_lang  = gr.Radio(choices=list(LANG_NAMES.keys()), value="ja",
                                   label="言語", type="value")

            g_btn = gr.Button("🎬 動画を生成", variant="primary", size="lg")

            with gr.Row():
                g_script = gr.Markdown(label="台本 (WAT)")
                g_gallery = gr.Gallery(label="生成画像", columns=3, height=300,
                                       object_fit="cover")

            g_video = gr.Video(label="🎬 完成動画", height=400)
            g_json  = gr.File(label="script.json ダウンロード", visible=False)

        # ── Tab 3: Auto ────────────────────────────────────────────────────
        with gr.Tab("🤖 全自動", id="auto"):
            gr.Markdown("### リサーチ → トップトレンド → 動画を全自動で生成")
            with gr.Row():
                a_query   = gr.Textbox(label="キーワード", placeholder="例: 健康, travel, cocina",
                                       scale=3)
                a_lang    = gr.Radio(choices=list(LANG_NAMES.keys()), value="ja",
                                     label="言語", type="value")
                a_country = gr.Dropdown(choices=["JP", "US", "ES", "GB", "FR"],
                                        value="JP", label="国")

            a_sources = gr.CheckboxGroup(
                choices=["google", "youtube", "twitter", "news"],
                value=["google", "youtube", "news"],
                label="リサーチソース",
            )
            a_btn = gr.Button("🤖 全自動実行", variant="primary", size="lg")

            a_topic   = gr.Textbox(label="選ばれたトピック", interactive=False)
            a_script  = gr.Markdown(label="台本")
            a_gallery = gr.Gallery(label="生成画像", columns=3, height=300, object_fit="cover")
            a_video   = gr.Video(label="🎬 完成動画", height=400)

    # ── Event bindings ─────────────────────────────────────────────────────

    r_btn.click(
        fn=run_research,
        inputs=[r_query, r_lang, r_country, r_sources],
        outputs=[r_table],
    )

    # リサーチ結果クリック → 動画生成タブに転送
    r_table.select(
        fn=pick_topic_to_generate,
        inputs=[r_table, r_lang],
        outputs=[g_topic, g_lang],
    )

    g_btn.click(
        fn=run_generate,
        inputs=[g_topic, g_lang],
        outputs=[g_script, g_gallery, g_video, g_json],
    )
    g_btn.click(fn=lambda: gr.update(visible=True), outputs=[g_json])

    a_btn.click(
        fn=run_auto,
        inputs=[a_query, a_lang, a_country, a_sources],
        outputs=[a_topic, a_script, a_gallery, a_video],
    )

if __name__ == "__main__":
    demo.launch(theme=gr.themes.Soft(primary_hue="red"), css=CSS)
