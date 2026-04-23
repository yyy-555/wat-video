"""
Multi-source trend research:
  Google Trends / YouTube / X (Twitter) / News RSS
"""
from __future__ import annotations

import time
import xml.etree.ElementTree as ET
from urllib.parse import quote_plus

import requests


# ── Google Trends ─────────────────────────────────────────────────────────────

def _google_trends(query: str, country: str, language: str) -> list[dict]:
    try:
        from pytrends.request import TrendReq
        hl = {"ja": "ja-JP", "en": "en-US", "es": "es-ES"}.get(language, "en-US")
        tz = {"JP": 540, "US": -300, "ES": 60}.get(country, 0)
        pt = TrendReq(hl=hl, tz=tz, timeout=(10, 25))
        pt.build_payload([query], timeframe="now 7-d", geo=country)
        related = pt.related_queries()
        out = []
        if query in related and related[query]["top"] is not None:
            for _, row in related[query]["top"].head(10).iterrows():
                out.append({"topic": row["query"], "score": int(row["value"]), "source": "google"})
        return out
    except Exception as e:
        print(f"  [Google Trends] {e}")
        return []


def _google_trending_searches(country: str) -> list[dict]:
    try:
        from pytrends.request import TrendReq
        code = {"JP": "japan", "US": "united_states", "ES": "spain"}.get(country, "united_states")
        pt = TrendReq(hl="en-US", tz=0)
        df = pt.trending_searches(pn=code)
        return [{"topic": t, "score": 100 - i, "source": "google_trending"}
                for i, t in enumerate(df[0].tolist()[:10])]
    except Exception as e:
        print(f"  [Google Trending] {e}")
        return []


# ── YouTube Trending ──────────────────────────────────────────────────────────

def _youtube_trending(query: str, api_key: str, language: str, country: str) -> list[dict]:
    if not api_key:
        return _youtube_search_fallback(query, language)
    try:
        resp = requests.get(
            "https://www.googleapis.com/youtube/v3/videos",
            params={
                "part": "snippet",
                "chart": "mostPopular",
                "regionCode": country,
                "relevanceLanguage": language,
                "maxResults": 10,
                "key": api_key,
            },
            timeout=10,
        )
        resp.raise_for_status()
        items = resp.json().get("items", [])
        return [{"topic": it["snippet"]["title"], "score": 90 - i, "source": "youtube"}
                for i, it in enumerate(items)]
    except Exception as e:
        print(f"  [YouTube API] {e}")
        return _youtube_search_fallback(query, language)


def _youtube_search_fallback(query: str, language: str) -> list[dict]:
    """YouTube RSS検索（APIキー不要）"""
    try:
        from urllib.parse import quote_plus
        url = f"https://www.youtube.com/feeds/videos.xml?search={quote_plus(query)}"
        resp = requests.get(url, timeout=10, headers={"User-Agent": "Mozilla/5.0"})
        if resp.status_code != 200:
            return []
        root = ET.fromstring(resp.content)
        ns = {"atom": "http://www.w3.org/2005/Atom"}
        entries = root.findall("atom:entry", ns)
        return [{"topic": e.findtext("atom:title", "", ns), "score": 80 - i, "source": "youtube"}
                for i, e in enumerate(entries[:10]) if e.findtext("atom:title", "", ns)]
    except Exception as e:
        print(f"  [YouTube Fallback] {e}")
        return []


# ── X / Twitter ───────────────────────────────────────────────────────────────

def _twitter_trends(bearer_token: str, country: str) -> list[dict]:
    if not bearer_token:
        return []
    # WOEID map for Twitter trends endpoint (v1.1 still needed for trends)
    woeid_map = {"JP": 23424856, "US": 23424977, "ES": 23424950}
    woeid = woeid_map.get(country, 1)
    try:
        resp = requests.get(
            f"https://api.twitter.com/1.1/trends/place.json?id={woeid}",
            headers={"Authorization": f"Bearer {bearer_token}"},
            timeout=10,
        )
        resp.raise_for_status()
        trends = resp.json()[0].get("trends", [])
        return [{"topic": t["name"].lstrip("#"), "score": 70 - i, "source": "twitter"}
                for i, t in enumerate(trends[:10])]
    except Exception as e:
        print(f"  [X/Twitter] {e}")
        return []


# ── News RSS ──────────────────────────────────────────────────────────────────

def _news_rss(query: str, language: str, country: str) -> list[dict]:
    """Google News RSS（APIキー不要）"""
    hl_map  = {"ja": "ja", "en": "en", "es": "es"}
    gl_map  = {"JP": "JP", "US": "US", "ES": "ES"}
    ceid_map = {"ja": "JP:ja", "en": "US:en", "es": "ES:es"}

    hl   = hl_map.get(language, "en")
    gl   = gl_map.get(country, "US")
    ceid = ceid_map.get(language, "US:en")
    url  = f"https://news.google.com/rss/search?q={quote_plus(query)}&hl={hl}&gl={gl}&ceid={ceid}"

    try:
        resp = requests.get(url, timeout=10, headers={"User-Agent": "Mozilla/5.0"})
        resp.raise_for_status()
        root  = ET.fromstring(resp.content)
        items = root.findall("./channel/item")
        out   = []
        for i, item in enumerate(items[:10]):
            title = item.findtext("title", "")
            if title:
                out.append({"topic": title, "score": 60 - i, "source": "news"})
        return out
    except Exception as e:
        print(f"  [News RSS] {e}")
        return []


def _newsapi(query: str, api_key: str, language: str) -> list[dict]:
    if not api_key:
        return []
    try:
        resp = requests.get(
            "https://newsapi.org/v2/everything",
            params={"q": query, "language": language, "sortBy": "popularity",
                    "pageSize": 10, "apiKey": api_key},
            timeout=10,
        )
        resp.raise_for_status()
        articles = resp.json().get("articles", [])
        return [{"topic": a["title"], "score": 65 - i, "source": "newsapi"}
                for i, a in enumerate(articles)]
    except Exception as e:
        print(f"  [NewsAPI] {e}")
        return []


# ── Aggregator ────────────────────────────────────────────────────────────────

def research(
    query: str,
    language: str = "ja",
    country: str = "JP",
    sources: list[str] | None = None,
    youtube_api_key: str = "",
    twitter_bearer: str = "",
    news_api_key: str = "",
) -> list[dict]:
    """
    複数ソースからトレンドを集約し、スコア降順で返す。
    sources: ["google", "youtube", "twitter", "news"]  (None = 全て)
    """
    if sources is None:
        sources = ["google", "youtube", "twitter", "news"]

    all_results: list[dict] = []

    if "google" in sources:
        print("  Fetching Google Trends...")
        all_results += _google_trends(query, country, language)
        all_results += _google_trending_searches(country)
        time.sleep(1)

    if "youtube" in sources:
        print("  Fetching YouTube trends...")
        all_results += _youtube_trending(query, youtube_api_key, language, country)

    if "twitter" in sources:
        print("  Fetching X/Twitter trends...")
        all_results += _twitter_trends(twitter_bearer, country)

    if "news" in sources:
        print("  Fetching news...")
        all_results += _newsapi(query, news_api_key, language) or _news_rss(query, language, country)

    # 重複排除（同一トピック名は最高スコアを保持）
    seen: dict[str, dict] = {}
    for r in all_results:
        key = r["topic"].lower().strip()
        if key not in seen or r["score"] > seen[key]["score"]:
            seen[key] = r

    return sorted(seen.values(), key=lambda x: x["score"], reverse=True)
