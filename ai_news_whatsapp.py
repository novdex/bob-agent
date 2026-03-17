#!/usr/bin/env python3
"""
AI News WhatsApp Sender
Fetches top AI news and sends to WhatsApp via OpenClaw
"""

import os
import sys
import json
import requests
from datetime import datetime
from pathlib import Path

BRAVE_API_KEY = "BSABC7SXTILDt5BOqute8UBQ27xnBMG"
OPENCLAW_GATEWAY = "http://127.0.0.1:18789"
OPENCLAW_TOKEN = "61ed6750f4732c3ee83c352e3b8dca5a8acac1d6aed10e25"
WHATSAPP_TARGET = "+447946700361"

AI_TOPICS = [
    "artificial intelligence news today 2026",
    "LLM AI model release news",
    "AI agent autonomous news",
    "OpenAI Anthropic Google DeepMind news",
]

def search_news(query: str, count: int = 4) -> list:
    try:
        r = requests.get(
            "https://api.search.brave.com/res/v1/news/search",
            headers={
                "Accept": "application/json",
                "X-Subscription-Token": BRAVE_API_KEY
            },
            params={
                "q": query,
                "count": count,
                "freshness": "pd",
                "text_decorations": False,
                "search_lang": "en",
            },
            timeout=10
        )
        if r.status_code == 200:
            return r.json().get("results", [])
    except Exception as e:
        print(f"Search error: {e}")
    return []

def gather_news() -> list:
    seen_urls = set()
    all_news = []

    for topic in AI_TOPICS:
        for item in search_news(topic, 3):
            url = item.get("url", "")
            if url and url not in seen_urls:
                seen_urls.add(url)
                all_news.append({
                    "title": item.get("title", ""),
                    "description": item.get("description", ""),
                    "url": url,
                    "source": item.get("meta_url", {}).get("hostname", ""),
                    "age": item.get("age", ""),
                })

    return all_news[:8]

def format_whatsapp_message(news: list) -> str:
    now = datetime.now().strftime("%d %b %Y, %H:%M")
    msg = f"🤖 *AI NEWS DIGEST*\n_{now}_\n\n"

    for i, item in enumerate(news, 1):
        title = item["title"][:80]
        source = item["source"].replace("www.", "")
        age = f" • {item['age']}" if item.get("age") else ""
        desc = item["description"][:100] + "..." if len(item.get("description","")) > 100 else item.get("description","")
        url = item["url"]

        msg += f"*{i}. {title}*\n"
        if desc:
            msg += f"_{desc}_\n"
        msg += f"📰 {source}{age}\n"
        msg += f"🔗 {url}\n\n"

    msg += "─────────────────\n"
    msg += "_Next update in 2 hours_ ⏰"
    return msg

def send_whatsapp(message: str) -> bool:
    try:
        r = requests.post(
            f"{OPENCLAW_GATEWAY}/cli/outbound-send",
            headers={
                "Authorization": f"Bearer {OPENCLAW_TOKEN}",
                "Content-Type": "application/json"
            },
            json={
                "channel": "whatsapp",
                "to": WHATSAPP_TARGET,
                "message": message
            },
            timeout=15
        )
        print(f"WhatsApp send status: {r.status_code}")
        print(r.text[:200])
        return r.status_code == 200
    except Exception as e:
        print(f"WhatsApp error: {e}")
        return False

if __name__ == "__main__":
    print(f"[{datetime.now().strftime('%H:%M:%S')}] Fetching AI news...")
    news = gather_news()

    if not news:
        print("No news found")
        sys.exit(1)

    print(f"[{datetime.now().strftime('%H:%M:%S')}] Found {len(news)} stories, sending to WhatsApp...")
    msg = format_whatsapp_message(news)
    success = send_whatsapp(msg)

    if success:
        print("Done!")
    else:
        print("Failed to send")
        sys.exit(1)
