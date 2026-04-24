---
title: WAT Video Generator
emoji: 🎬
colorFrom: red
colorTo: blue
sdk: gradio
sdk_version: "6.13.0"
app_file: app.py
pinned: false
license: mit
---

# WAT Video Generator

WATフレームワークを使ったショート動画自動生成ツール。

**W** (Why/Hook) → **A** (Action) → **T** (Transformation)

## 機能
- 🔍 Google / YouTube / X / News からトレンドリサーチ
- 📝 Claude API でWAT台本を自動生成
- 🎨 HuggingFace FLUX.1-schnell で画像生成
- 🎬 TTS + 画像 → MP4 動画を自動組み立て
- 🌐 日本語 / English / Español 対応

## 必要なSecrets
| Secret名 | 説明 | 必須 |
|---|---|---|
| `ANTHROPIC_API_KEY` | Claude API | ✅ |
| `HF_API_KEY` | HuggingFace API | ✅ |
| `YOUTUBE_API_KEY` | YouTube Data API | 任意 |
| `TWITTER_BEARER_TOKEN` | X/Twitter API | 任意 |
| `NEWS_API_KEY` | NewsAPI | 任意 |
