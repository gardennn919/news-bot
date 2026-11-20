"""
이광재 의원 뉴스 알림 텔레그램 봇
- 구글 뉴스 RSS에서 이광재 의원 관련 기사를 찾아 텔레그램으로 알려줍니다.
- 이미 보낸 기사는 sent.json에 기록해 다시 보내지 않습니다.
- 외부 패키지 없이 파이썬 기본 라이브러리만 사용합니다.

환경변수:
  TELEGRAM_TOKEN   : BotFather에서 받은 봇 토큰
  TELEGRAM_CHAT_ID : 알림을 받을 채팅방 ID
"""

import html
import json
import os
import urllib.parse
import urllib.request
import xml.etree.ElementTree as ET
from datetime import datetime, timedelta, timezone
from email.utils import parsedate_to_datetime

TOKEN = os.environ["TELEGRAM_TOKEN"]
CHAT_ID = os.environ["TELEGRAM_CHAT_ID"]

# 검색어: '이광재'가 들어가면서 의원 관련 단어가 함께 나오는 기사만
# (동명이인 기사를 줄이기 위함. 필요하면 단어를 더하거나 빼세요)
QUERIES = [
    '"이광재" (의원 OR 하남 OR 국회 OR 더불어민주당)',
]

MAX_AGE_HOURS = 12        # 이보다 오래된 기사는 보내지 않음 (첫 실행 때 옛날 기사 폭탄 방지)
SENT_FILE = "sent.json"   # 보낸 기사 기록
SENT_KEEP = 1000          # 기록은 최근 1000건만 보관
KST = timezone(timedelta(hours=9))


def load_sent():
    try:
        with open(SENT_FILE, encoding="utf-8") as f:
            return json.load(f)
    except (FileNotFoundError, json.JSONDecodeError):
        return []


def save_sent(sent):
    with open(SENT_FILE, "w", encoding="utf-8") as f:
        json.dump(sent[-SENT_KEEP:], f, ensure_ascii=False, indent=0)


def fetch_news(query):
    """구글 뉴스 RSS에서 기사 목록을 가져옵니다."""
    url = ("https://news.google.com/rss/search?q=" + urllib.parse.quote(query)
           + "&hl=ko&gl=KR&ceid=KR:ko")
    req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0"})
    with urllib.request.urlopen(req, timeout=15) as resp:
        root = ET.fromstring(resp.read())

    items = []
    for item in root.iter("item"):
        try:
            published = parsedate_to_datetime(item.findtext("pubDate", ""))
        except (TypeError, ValueError):
            continue
        items.append({
            "title": item.findtext("title", ""),
            "link": item.findtext("link", ""),
            "source": item.findtext("source", ""),
            "published": published,
        })
    return items


def send_message(text):
    url = f"https://api.telegram.org/bot{TOKEN}/sendMessage"
    data = urllib.parse.urlencode({
        "chat_id": CHAT_ID,
        "text": text,
        "parse_mode": "HTML",
        "disable_web_page_preview": "true",
    }).encode()
    with urllib.request.urlopen(url, data=data, timeout=15) as resp:
        return json.loads(resp.read())


def main():
    sent = load_sent()
    sent_set = set(sent)
    cutoff = datetime.now(timezone.utc) - timedelta(hours=MAX_AGE_HOURS)

    new_items = {}
    for q in QUERIES:
        for n in fetch_news(q):
            if n["published"] >= cutoff and n["link"] not in sent_set:
                new_items[n["link"]] = n

    if not new_items:
        print("새 기사 없음")
        return

    # 오래된 기사부터 순서대로 하나씩 알림
    for n in sorted(new_items.values(), key=lambda x: x["published"]):
        t = n["published"].astimezone(KST)
        text = (
            "📰 <b>이광재 의원 관련 새 기사</b>\n\n"
            f"<a href=\"{html.escape(n['link'])}\">{html.escape(n['title'])}</a>\n"
            f"{html.escape(n['source'])} · {t:%m/%d %H:%M}"
        )
        send_message(text)
        sent.append(n["link"])

    save_sent(sent)
    print(f"{len(new_items)}건 전송")


if __name__ == "__main__":
    main()
