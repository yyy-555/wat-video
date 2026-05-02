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
    subtitle_updates = []
    for i in range(MAX_SCENES):
        if i < len(sections):
            sec = sections[i]
            textbox_updates.append(gr.update(value=sec["text"],
                                             label=f"場面 {i+1}：{sec['label']}",
                                             visible=True))
            subtitle_updates.append(gr.update(value="",
                                              label=f"字幕 {i+1}（空欄＝字幕なし）",
                                              visible=True))
        else:
            textbox_updates.append(gr.update(value="", visible=False))
            subtitle_updates.append(gr.update(value="", visible=False))

    return [script] + textbox_updates + subtitle_updates + [gr.update(visible=True)]


def step2_gen_images(script: dict, t1: str, t2: str, t3: str, t4: str, t5: str,
                     style: str, progress=gr.Progress()):
    if script is None:
        raise gr.Error("先に「台本を生成」してください")

    edited = [t1, t2, t3, t4, t5]
    sections = script["sections"]
    for i, sec in enumerate(sections):
        if edited[i].strip():
            sec["text"] = edited[i].strip()

    video_id = str(uuid.uuid4())[:8]
    out_dir  = os.path.join(OUTPUT_DIR, video_id)
    os.makedirs(out_dir, exist_ok=True)

    from images.generator import generate as gen_image
    paths   = []
    prompts = []

    for i, sec in enumerate(sections):
        progress((i + 1) / len(sections),
                 desc=f"🎨 画像生成 {i+1}/{len(sections)} [{sec['type']}]...")
        img = gen_image(sec["image_prompt"], HF_API_KEY, style=style)
        p   = os.path.join(out_dir, f"img_{i}_{sec['type']}.png")
        img.save(p)
        paths.append(p)
        prompts.append(sec["image_prompt"])

    images_data = {"paths": paths, "prompts": prompts, "out_dir": out_dir}
    choices     = [f"場面 {i+1}" for i in range(len(sections))]

    return (images_data,
            gr.update(value=paths, visible=True),
            gr.update(choices=choices, value=choices[0], visible=True),
            prompts[0],
            gr.update(visible=True))


def on_scene_select(scene_label: str, images_data: dict):
    if not images_data or not scene_label:
        return gr.update(), gr.update()
    idx     = int(scene_label.replace("場面 ", "")) - 1
    paths   = images_data["paths"]
    prompts = images_data["prompts"]
    if idx >= len(paths):
        return gr.update(), gr.update()
    return paths[idx], prompts[idx]


def regen_one_image(scene_label: str, prompt: str, style: str, images_data: dict):
    if not images_data or not scene_label:
        raise gr.Error("先に画像を生成してください")
    idx  = int(scene_label.replace("場面 ", "")) - 1
    path = images_data["paths"][idx]
    from images.generator import generate as gen_image
    img = gen_image(prompt, HF_API_KEY, style=style)
    img.save(path)
    images_data["prompts"][idx] = prompt
    return images_data, images_data["paths"], path


def step3_make_video(script: dict, lang: str, images_data: dict,
                     sub1: str, sub2: str, sub3: str, sub4: str, sub5: str,
                     progress=gr.Progress()):
    if script is None or images_data is None:
        raise gr.Error("先に台本と画像を生成してください")

    sections  = script["sections"]
    paths     = images_data["paths"][:len(sections)]
    images    = [Image.open(p).convert("RGB") for p in paths]
    out_dir   = images_data["out_dir"]
    video_id  = os.path.basename(out_dir)
    subtitles = [sub1, sub2, sub3, sub4, sub5][:len(sections)]

    script_json_path = os.path.join(out_dir, "script.json")
    with open(script_json_path, "w", encoding="utf-8") as f:
        json.dump(script, f, ensure_ascii=False, indent=2)

    progress(0.8, desc="🎬 動画を組み立て中...")
    from video.assembler import assemble
    mp4_path = assemble(script, images, lang, out_dir, video_id, subtitles=subtitles)

    progress(1.0, desc="✅ 完了!")
    return _script_to_markdown(script), mp4_path, script_json_path


def run_auto(query: str, lang: str, country: str, sources: list[str],
             duration_sec: int = 60, num_scenes: int = 5, style: str = "カートゥーン",
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
                 desc=f"🎨 画像生成 {i+1}/{len(sections)}...")
        img = gen_image(sec["image_prompt"], HF_API_KEY, style=style)
        p   = os.path.join(out_dir, f"img_{i}_{sec['type']}.png")
        img.save(p)
        images.append(img)
        img_paths.append(p)

    progress(0.75, desc="🎬 動画を組み立て中...")
    from video.assembler import assemble
    mp4_path = assemble(script, images, lang, out_dir, video_id)

    progress(1.0, desc="✅ 完了!")
    return top_topic, _script_to_markdown(script), img_paths, mp4_path


# ── History ───────────────────────────────────────────────────────────────────

def load_history() -> tuple[list, list]:
    rows = []
    items = []
    if not os.path.exists(OUTPUT_DIR):
        return [], []
    for video_id in sorted(os.listdir(OUTPUT_DIR), reverse=True):
        session_dir = os.path.join(OUTPUT_DIR, video_id)
        if not os.path.isdir(session_dir):
            continue
        mp4_files = [f for f in os.listdir(session_dir) if f.endswith(".mp4")]
        if not mp4_files:
            continue
        script_path = os.path.join(session_dir, "script.json")
        topic = "（不明）"
        if os.path.exists(script_path):
            try:
                with open(script_path, encoding="utf-8") as f:
                    topic = json.load(f).get("topic", "（不明）")
            except Exception:
                pass
        from datetime import datetime
        dt = datetime.fromtimestamp(os.path.getmtime(session_dir)).strftime("%Y-%m-%d %H:%M")
        rows.append([video_id, topic, dt])
        items.append({"video_id": video_id, "dir": session_dir, "mp4": mp4_files[0]})
    return rows, items


def show_history_item(evt: gr.SelectData, history_items: list) -> tuple:
    if not history_items or evt is None:
        return [], None, ""
    item = history_items[evt.index[0]]
    session_dir = item["dir"]
    img_paths = sorted(
        [os.path.join(session_dir, f) for f in os.listdir(session_dir)
         if f.startswith("img_") and f.endswith(".png")]
    )
    mp4_path = os.path.join(session_dir, item["mp4"])
    script_path = os.path.join(session_dir, "script.json")
    md = ""
    if os.path.exists(script_path):
        try:
            with open(script_path, encoding="utf-8") as f:
                md = _script_to_markdown(json.load(f))
        except Exception:
            pass
    return img_paths, mp4_path, md


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

STYLE_CHOICES = ["リアル", "カートゥーン", "ポップアート", "アニメ",
                 "水彩画", "サイバーパンク", "ヴィンテージ"]

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
            g_style = gr.Radio(
                choices=STYLE_CHOICES,
                value="カートゥーン", label="🎨 画像スタイル",
            )

            g_script_btn = gr.Button("📝 ① 台本を生成", variant="secondary", size="lg")

            g_script_state = gr.State(value=None)
            g_scene_texts  = [
                gr.Textbox(label=f"場面 {i+1}", lines=3, visible=False, interactive=True)
                for i in range(MAX_SCENES)
            ]
            g_subtitle_texts = [
                gr.Textbox(label=f"字幕 {i+1}（空欄＝字幕なし）", lines=2,
                           visible=False, interactive=True,
                           placeholder="例: 朝食は大切です")
                for i in range(MAX_SCENES)
            ]
            g_img_btn = gr.Button("🎨 ② 画像を生成", variant="secondary", size="lg",
                                  visible=False)

            # 画像確認・再生成エリア
            g_images_data  = gr.State(value=None)
            g_gallery      = gr.Gallery(label="生成画像", columns=5, height=220,
                                        visible=False, object_fit="cover")
            g_scene_sel    = gr.Dropdown(label="再生成する場面を選択",
                                         choices=[], visible=False, interactive=True)
            g_edit_prompt  = gr.Textbox(
                label="プロンプト（英語で編集すると反映されやすい）",
                lines=3, interactive=True)
            g_edit_img     = gr.Image(label="選択中の画像", height=250, interactive=False)
            g_regen_btn    = gr.Button("🔄 この場面の画像を再生成", size="sm")

            g_video_btn = gr.Button("🎬 ③ 動画を作成", variant="primary", size="lg",
                                    visible=False)

            g_script_md = gr.Markdown()
            g_video     = gr.Video(label="🎬 完成動画", height=400)
            g_json      = gr.File(label="script.json ダウンロード", visible=False)

        # ── Tab 3: History ─────────────────────────────────────────────────
        with gr.Tab("📂 履歴", id="history"):
            gr.Markdown("### このセッションで生成した動画・画像の履歴")
            gr.Markdown("*注意: HuggingFace Spaces の再起動後は消えます*")
            h_load_btn = gr.Button("🔄 履歴を読み込む", variant="secondary")
            h_table = gr.DataFrame(
                headers=["動画ID", "トピック", "作成日時"],
                datatype=["str", "str", "str"],
                label="生成履歴",
                interactive=False,
            )
            gr.Markdown("💡 *行をクリックすると詳細が表示されます*")
            h_items_state = gr.State(value=[])
            h_gallery  = gr.Gallery(label="生成画像", columns=5, height=220,
                                    object_fit="cover")
            h_video    = gr.Video(label="🎬 完成動画", height=400)
            h_script   = gr.Markdown()

        # ── Tab 4: Auto ────────────────────────────────────────────────────
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
            a_style = gr.Radio(
                choices=STYLE_CHOICES,
                value="カートゥーン", label="🎨 画像スタイル",
            )
            a_btn     = gr.Button("🤖 全自動実行", variant="primary", size="lg")
            a_topic   = gr.Textbox(label="選ばれたトピック", interactive=False)
            a_script  = gr.Markdown()
            a_gallery = gr.Gallery(label="生成画像", columns=3, height=300, object_fit="cover")
            a_video   = gr.Video(label="🎬 完成動画", height=400)

    # ── Event bindings ─────────────────────────────────────────────────────

    r_btn.click(fn=run_research,
                inputs=[r_query, r_lang, r_country, r_sources],
                outputs=[r_table])
    r_table.select(fn=pick_topic_to_generate,
                   inputs=[r_table, r_lang],
                   outputs=[g_topic, g_lang])

    # ① 台本生成
    g_script_btn.click(
        fn=step1_gen_script,
        inputs=[g_topic, g_lang, g_duration, g_scenes],
        outputs=[g_script_state] + g_scene_texts + g_subtitle_texts + [g_img_btn],
    )

    # ② 画像生成 → (images_data, gallery, scene_sel, edit_prompt, video_btn)
    g_img_btn.click(
        fn=step2_gen_images,
        inputs=[g_script_state] + g_scene_texts + [g_style],
        outputs=[g_images_data, g_gallery, g_scene_sel, g_edit_prompt, g_video_btn],
    )

    # 場面選択 → 画像・プロンプト更新
    g_scene_sel.change(
        fn=on_scene_select,
        inputs=[g_scene_sel, g_images_data],
        outputs=[g_edit_img, g_edit_prompt],
    )

    # 再生成 → (images_data, gallery, edit_img)
    g_regen_btn.click(
        fn=regen_one_image,
        inputs=[g_scene_sel, g_edit_prompt, g_style, g_images_data],
        outputs=[g_images_data, g_gallery, g_edit_img],
    )

    # ③ 動画作成
    g_video_btn.click(
        fn=step3_make_video,
        inputs=[g_script_state, g_lang, g_images_data] + g_subtitle_texts,
        outputs=[g_script_md, g_video, g_json],
    )
    g_video_btn.click(fn=lambda: gr.update(visible=True), outputs=[g_json])

    # 履歴
    def _load_history_ui():
        rows, items = load_history()
        return rows, items

    h_load_btn.click(fn=_load_history_ui, outputs=[h_table, h_items_state])
    h_table.select(fn=show_history_item,
                   inputs=[h_items_state],
                   outputs=[h_gallery, h_video, h_script])

    # 全自動
    a_btn.click(
        fn=run_auto,
        inputs=[a_query, a_lang, a_country, a_sources, a_duration, a_scenes, a_style],
        outputs=[a_topic, a_script, a_gallery, a_video],
    )

if __name__ == "__main__":
    demo.launch(theme=gr.themes.Soft(primary_hue="red"), css=CSS)
