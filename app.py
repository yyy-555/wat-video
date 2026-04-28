"""
WAT Video Generator — Gradio UI for HuggingFace Spaces
"""
import json
import os
import sys
import uuid

import gradio as gr
from PIL import Image

sys.path.insert(0, os.path.dirname(__file__))

from config import (
    GROQ_API_KEY, HF_API_KEY,
    YOUTUBE_API_KEY, TWITTER_BEARER, NEWS_API_KEY,
    OUTPUT_DIR, SUPPORTED_LANGUAGES,
)

os.makedirs(OUTPUT_DIR, exist_ok=True)

LANG_NAMES  = {"ja": "🇯🇵 日本語", "en": "🇺🇸 English", "es": "🇪🇸 Español"}
COUNTRY_MAP = {"ja": "JP", "en": "US", "es": "ES"}
MAX_SCENES  = 5


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


def step1_gen_script(topic: str, lang: str, duration_sec: int, num_scenes: int,
                     progress=gr.Progress()):
    """台本だけ生成して編集用テキストボックスに展開する。"""
    if not topic.strip():
        raise gr.Error("トピックを入力してください")
    if not GROQ_API_KEY:
        raise gr.Error("GROQ_API_KEY が設定されていません")

    progress(0.2, desc="📝 台本を生成中...")
    from scripts.wat_writer import generate as gen_script
    script = gen_script(topic, lang, duration_sec=int(duration_sec),
                        num_scenes=int(num_scenes))
    progress(1.0, desc="✅ 台本完成！自由に編集してください")

    sections = script["sections"]
    textbox_updates = []
    for i in range(MAX_SCENES):
        if i < len(sections):
            sec = sections[i]
            textbox_updates.append(gr.update(
                value=sec["text"],
                label=f"場面 {i + 1}：{sec['label']}",
                visible=True,
            ))
        else:
            textbox_updates.append(gr.update(value="", label=f"場面 {i + 1}", visible=False))

    return [script] + textbox_updates + [gr.update(visible=True)]


def step2_make_video(script: dict, t1: str, t2: str, t3: str, t4: str, t5: str,
                     lang: str, progress=gr.Progress(track_tqdm=True)):
    """編集済みテキストで画像生成 → 動画組み立てを行う。"""
    if script is None:
        raise gr.Error("先に「台本を生成」してください")
    if not HF_API_KEY:
        raise gr.Error("HF_API_KEY が設定されていません")

    edited_texts = [t1, t2, t3, t4, t5]
    sections     = script["sections"]

    for i, sec in enumerate(sections):
        if edited_texts[i].strip():
            sec["text"] = edited_texts[i].strip()

    video_id = str(uuid.uuid4())[:8]
    out_dir  = os.path.join(OUTPUT_DIR, video_id)
    os.makedirs(out_dir, exist_ok=True)

    script_json_path = os.path.join(out_dir, "script.json")
    with open(script_json_path, "w", encoding="utf-8") as f:
        json.dump(script, f, ensure_ascii=False, indent=2)

    from images.generator import generate as gen_image
    images: list[Image.Image] = []
    img_paths: list[str]      = []

    for i, sec in enumerate(sections):
        progress(0.1 + i * (0.6 / len(sections)),
                 desc=f"🎨 画像生成 {i + 1}/{len(sections)} [{sec['type']}]...")
        img = gen_image(sec["image_prompt"], HF_API_KEY)
        p   = os.path.join(out_dir, f"img_{i}_{sec['type']}.png")
        img.save(p)
        images.append(img)
        img_paths.append(p)

    progress(0.75, desc="🎬 動画を組み立て中...")
    from video.assembler import assemble
    mp4_path  = assemble(script, images, lang, out_dir, video_id)
    script_md = _script_to_markdown(script)

    progress(1.0, desc="✅ 完了!")
    return script_md, img_paths, mp4_path, script_json_path


def run_auto(query: str, lang: str, country: str, sources: list[str],
             duration_sec: int = 60, num_scenes: int = 5,
             progress=gr.Progress(track_tqdm=True)):
    if not query.strip():
        raise gr.Error("キーワードを入力してください")

    progress(0.05, desc="🔍 トレンドをリサーチ中...")
    rows = run_research(query, lang, country, sources)
    if not rows:
        raise gr.Error("トレンドが見つかりませんでした。キーワードを変えてみてください。")

    top_topic = rows[0][1]
    progress(0.15, desc=f"🎯 トピック決定: {top_topic}")

    from scripts.wat_writer import generate as gen_script
    progress(0.2, desc="📝 台本を生成中...")
    script   = gen_script(top_topic, lang, duration_sec=int(duration_sec),
                          num_scenes=int(num_scenes))
    sections = script["sections"]

    video_id = str(uuid.uuid4())[:8]
    out_dir  = os.path.join(OUTPUT_DIR, video_id)
    os.makedirs(out_dir, exist_ok=True)

    from images.generator import generate as gen_image
    images: list[Image.Image] = []
    img_paths: list[str]      = []
    for i, sec in enumerate(sections):
        progress(0.3 + i * (0.4 / len(sections)),
                 desc=f"🎨 画像生成 {i + 1}/{len(sections)}...")
        img = gen_image(sec["image_prompt"], HF_API_KEY)
        p   = os.path.join(out_dir, f"img_{i}_{sec['type']}.png")
        img.save(p)
        images.append(img)
        img_paths.append(p)

    progress(0.75, desc="🎬 動画を組み立て中...")
    from video.assembler import assemble
    mp4_path = assemble(script, images, lang, out_dir, video_id)

    progress(1.0, desc="✅ 完了!")
    return top_topic, _script_to_markdown(script), img_paths, mp4_path


# ── Helpers ───────────────────────────────────────────────────────────────────

def _script_to_markdown(script: dict) -> str:
    lines  = [f"## 📋 {script.get('topic', '')}"]
    colors = {"W": "🔴", "A": "🔵", "T": "🟢"}
    for sec in script["sections"]:
        icon = colors.get(sec["type"], "⚪")
        lines.append(f"\n### {icon} {sec['label']}")
        lines.append(sec["text"])
    return "\n".join(lines)


def pick_topic_to_generate(evt: gr.SelectData, table_data, lang):
    try:
        row   = evt.index[0]
        topic = (str(table_data.iloc[row, 1]) if hasattr(table_data, "iloc")
                 else table_data[row][1])
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
                r_query   = gr.Textbox(label="キーワード",
                                       placeholder="例: 料理, fitness, recetas...", scale=3)
                r_lang    = gr.Radio(choices=list(LANG_NAMES.keys()), value="ja",
                                     label="言語", type="value")
                r_country = gr.Dropdown(choices=["JP", "US", "ES", "GB", "FR"],
                                        value="JP", label="国")
            r_sources = gr.CheckboxGroup(
                choices=["google", "youtube", "twitter", "news"],
                value=["google", "youtube", "news"],
                label="リサーチソース",
            )
            r_btn   = gr.Button("🔍 リサーチ開始", variant="primary")
            r_table = gr.DataFrame(
                headers=["#", "トピック", "スコア", "ソース"],
                datatype=["number", "str", "number", "str"],
                label="トレンドトピック",
                interactive=False,
            )
            gr.Markdown("💡 *行をクリックすると「動画生成」タブにトピックが入力されます*")

        # ── Tab 2: Generate ────────────────────────────────────────────────
        with gr.Tab("🎬 動画生成", id="generate"):
            gr.Markdown("### WATフレームワークで動画を生成")

            with gr.Row():
                g_topic = gr.Textbox(label="トピック", placeholder="例: 5分で作れる朝食",
                                     scale=3)
                g_lang  = gr.Radio(choices=list(LANG_NAMES.keys()), value="ja",
                                   label="言語", type="value")
            with gr.Row():
                g_duration = gr.Slider(minimum=20, maximum=60, step=10, value=60,
                                       label="動画の長さ（秒）", scale=2)
                g_scenes   = gr.Radio(choices=[3, 4, 5], value=5, label="場面数", scale=1)

            g_script_btn = gr.Button("📝 ① 台本を生成", variant="secondary", size="lg")

            # 台本編集エリア（生成後に表示）
            g_script_state = gr.State(value=None)
            g_scene_texts  = [
                gr.Textbox(label=f"場面 {i + 1}", lines=4, visible=False, interactive=True)
                for i in range(MAX_SCENES)
            ]

            g_make_btn = gr.Button("🎬 ② 動画を作成", variant="primary", size="lg",
                                   visible=False)

            with gr.Row():
                g_script_md = gr.Markdown(label="台本 (WAT)")
                g_gallery   = gr.Gallery(label="生成画像", columns=3, height=300,
                                         object_fit="cover")
            g_video = gr.Video(label="🎬 完成動画", height=400)
            g_json  = gr.File(label="script.json ダウンロード", visible=False)

        # ── Tab 3: Auto ────────────────────────────────────────────────────
        with gr.Tab("🤖 全自動", id="auto"):
            gr.Markdown("### リサーチ → トップトレンド → 動画を全自動で生成")
            with gr.Row():
                a_query   = gr.Textbox(label="キーワード",
                                       placeholder="例: 健康, travel, cocina", scale=3)
                a_lang    = gr.Radio(choices=list(LANG_NAMES.keys()), value="ja",
                                     label="言語", type="value")
                a_country = gr.Dropdown(choices=["JP", "US", "ES", "GB", "FR"],
                                        value="JP", label="国")
            a_sources = gr.CheckboxGroup(
                choices=["google", "youtube", "twitter", "news"],
                value=["google", "youtube", "news"],
                label="リサーチソース",
            )
            with gr.Row():
                a_duration = gr.Slider(minimum=20, maximum=60, step=10, value=60,
                                       label="動画の長さ（秒）", scale=2)
                a_scenes   = gr.Radio(choices=[3, 4, 5], value=5, label="場面数", scale=1)
            a_btn     = gr.Button("🤖 全自動実行", variant="primary", size="lg")
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
    r_table.select(
        fn=pick_topic_to_generate,
        inputs=[r_table, r_lang],
        outputs=[g_topic, g_lang],
    )

    # ① 台本生成
    g_script_btn.click(
        fn=step1_gen_script,
        inputs=[g_topic, g_lang, g_duration, g_scenes],
        outputs=[g_script_state] + g_scene_texts + [g_make_btn],
    )

    # ② 動画作成
    g_make_btn.click(
        fn=step2_make_video,
        inputs=[g_script_state] + g_scene_texts + [g_lang],
        outputs=[g_script_md, g_gallery, g_video, g_json],
    )
    g_make_btn.click(fn=lambda: gr.update(visible=True), outputs=[g_json])

    a_btn.click(
        fn=run_auto,
        inputs=[a_query, a_lang, a_country, a_sources, a_duration, a_scenes],
        outputs=[a_topic, a_script, a_gallery, a_video],
    )

if __name__ == "__main__":
    demo.launch(theme=gr.themes.Soft(primary_hue="red"), css=CSS)
