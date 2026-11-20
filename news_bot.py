"""
이광재 의원 뉴스 알림 텔레그램 봇 (네이버 뉴스 검색 - NAVER API HUB)
- 네이버 검색 API로 이광재 의원 관련 최신 기사를 찾아 텔레그램으로 알려줍니다.
- '언론사 분류 기준'(더불어민주당 공보국 등록사·네이버 뉴스제휴 기준)에서
  지방지를 뺀 언론사의 기사만 보냅니다.
- 이미 보낸 기사는 sent.json에 기록해 다시 보내지 않습니다.
- 외부 패키지 없이 파이썬 기본 라이브러리만 사용합니다.

환경변수:
  TELEGRAM_TOKEN      : BotFather에서 받은 봇 토큰
  TELEGRAM_CHAT_ID    : 알림을 받을 채팅방(채널) ID
  NAVER_CLIENT_ID     : 네이버 클라우드 NAVER API HUB 애플리케이션 Client ID
  NAVER_CLIENT_SECRET : 네이버 클라우드 NAVER API HUB 애플리케이션 Client Secret
"""

import html
import json
import os
import re
import urllib.parse
import urllib.request
from datetime import datetime, timedelta, timezone
from email.utils import parsedate_to_datetime

TOKEN = os.environ["TELEGRAM_TOKEN"]
CHAT_ID = os.environ["TELEGRAM_CHAT_ID"]
NAVER_ID = os.environ["NAVER_CLIENT_ID"]
NAVER_SECRET = os.environ["NAVER_CLIENT_SECRET"]

# 네이버에서 검색할 단어
SEARCH_WORD = "이광재"

# 동명이인 기사를 줄이기 위해, 제목이나 요약에 아래 단어 중 하나가 함께 있어야 보냅니다.
# (하남 관련 기사는 모두 포함되도록 '하남'을 넣어 두었습니다)
MUST_INCLUDE_ONE_OF = ["의원", "하남", "국회", "민주당"]

# ─────────────────────────────────────────────────────────────
# 받을 언론사 목록 (언론사 분류 기준에서 '지방지'를 뺀 나머지)
# 형식: "분류": [("언론사 이름", "인터넷 주소"), ...]
# 기사 원문 주소로 언론사를 구분합니다.
# 언론사를 더하거나 빼려면 이 목록에 줄을 추가하거나 지우세요.
# ─────────────────────────────────────────────────────────────
ALLOWED_OUTLETS = {
    "지상파 방송": [
        ("KBS", "kbs.co.kr"),
        ("MBC", "imbc.com"),
        ("SBS", "sbs.co.kr"),
    ],
    "보도·종편 채널": [
        ("YTN", "ytn.co.kr"),
        ("연합뉴스TV", "yonhapnewstv.co.kr"),
        ("MBN", "mbn.co.kr"),
        ("JTBC", "jtbc.co.kr"),
        ("채널A", "ichannela.com"),
        ("TV조선", "tvchosun.com"),
    ],
    "방송": [
        ("OBS", "obsnews.co.kr"),
        ("BBS", "bbsi.co.kr"),
        ("CBS", "cbs.co.kr"),
        ("EBS", "ebs.co.kr"),
        ("한국경제TV", "wowtv.co.kr"),
        ("아리랑TV", "arirang.com"),
        ("KTV", "ktv.go.kr"),
        ("KBC", "ikbc.co.kr"),
        ("KNN", "knn.co.kr"),
        ("TJB", "tjb.co.kr"),
    ],
    "중앙지": [
        ("경향신문", "khan.co.kr"),
        ("국민일보", "kmib.co.kr"),
        ("내일신문", "naeil.com"),
        ("동아일보", "donga.com"),
        ("문화일보", "munhwa.com"),
        ("서울신문", "seoul.co.kr"),
        ("세계일보", "segye.com"),
        ("조선일보", "chosun.com"),
        ("중앙일보", "joongang.co.kr"),
        ("한겨레", "hani.co.kr"),
        ("한국일보", "hankookilbo.com"),
    ],
    "일간지": [
        ("아시아투데이", "asiatoday.co.kr"),
        ("전자신문", "etnews.com"),
        ("신아일보", "shinailbo.co.kr"),
        ("메트로신문", "metroseoul.co.kr"),
    ],
    "경제지": [
        ("매일경제", "mk.co.kr"),
        ("머니투데이", "mt.co.kr"),
        ("서울경제", "sedaily.com"),
        ("아시아경제", "asiae.co.kr"),
        ("아주경제", "ajunews.com"),
        ("이데일리", "edaily.co.kr"),
        ("이투데이", "etoday.co.kr"),
        ("파이낸셜뉴스", "fnnews.com"),
        ("한국경제", "hankyung.com"),
        ("헤럴드경제", "heraldcorp.com"),
    ],
    "통신사": [
        ("뉴스1", "news1.kr"),
        ("뉴시스", "newsis.com"),
        ("연합뉴스", "yna.co.kr"),
    ],
    "인터넷 매체": [
        ("노컷뉴스", "nocutnews.co.kr"),
        ("뉴스타파", "newstapa.org"),
        ("뉴스핌", "newspim.com"),
        ("미디어오늘", "mediatoday.co.kr"),
        ("민중의소리", "vop.co.kr"),
        ("뷰스앤뉴스", "viewsnnews.com"),
        ("아이뉴스24", "inews24.com"),
        ("오마이뉴스", "ohmynews.com"),
        ("조세일보", "joseilbo.com"),
        ("쿠키뉴스", "kukinews.com"),
        ("폴리뉴스", "polinews.co.kr"),
        ("프레시안", "pressian.com"),
        ("CNB뉴스", "cnbnews.com"),
    ],
}

MAX_AGE_HOURS = 12        # 이보다 오래된 기사는 보내지 않음
SENT_FILE = "sent.json"   # 보낸 기사 기록
SENT_KEEP = 2000          # 기록은 최근 2000건만 보관
KST = timezone(timedelta(hours=9))


def find_outlet(url):
    """기사 주소를 보고 받을 언론사이면 (이름, 분류)를, 아니면 None을 돌려줍니다."""
    host = urllib.parse.urlparse(url).netloc.lower().split(":")[0]
    for category, outlets in ALLOWED_OUTLETS.items():
        for name, domain in outlets:
            if host == domain or host.endswith("." + domain):
                return name, category
    return None


def clean(text):
    """네이버 결과의 <b> 태그와 &quot; 같은 기호를 정리합니다."""
    return html.unescape(re.sub(r"<[^>]+>", "", text or "")).strip()


WEEKDAYS = ["월", "화", "수", "목", "금", "토", "일"]
SUMMARY_MAX = 110   # 요약은 이 글자 수까지만 보여줌


def korean_time(dt):
    """예: 11월 20일(금) 오전 9:15"""
    t = dt.astimezone(KST)
    ampm = "오전" if t.hour < 12 else "오후"
    hour = t.hour % 12 or 12
    return f"{t.month}월 {t.day}일({WEEKDAYS[t.weekday()]}) {ampm} {hour}:{t.minute:02d}"


def shorten(text, limit):
    return text if len(text) <= limit else text[:limit].rstrip() + "…"


def build_message(n):
    """텔레그램에 보낼 메시지 모양을 만듭니다."""
    e = html.escape
    lines = [
        "🔔 <b>이광재 의원 새 뉴스</b>",
        "",
        f"<b>{e(n['title'])}</b>",
    ]
    if n["summary"]:
        lines += ["", f"<blockquote>{e(shorten(n['summary'], SUMMARY_MAX))}</blockquote>"]
    lines += [
        "",
        f"🗞 {e(n['source'])}",
        f"🕘 {korean_time(n['published'])}",
    ]
    return "\n".join(lines)


def load_sent():
    try:
        with open(SENT_FILE, encoding="utf-8") as f:
            return json.load(f)
    except (FileNotFoundError, json.JSONDecodeError):
        return []


def save_sent(sent):
    with open(SENT_FILE, "w", encoding="utf-8") as f:
        json.dump(sent[-SENT_KEEP:], f, ensure_ascii=False, indent=0)


def fetch_naver_news(word):
    """네이버 뉴스 검색 API(NAVER API HUB)로 최신순 기사 100건을 가져옵니다."""
    url = ("https://naverapihub.apigw.ntruss.com/search/v1/news?"
           + urllib.parse.urlencode({"query": word, "display": 100, "start": 1,
                                     "sort": "date", "format": "json"}))
    req = urllib.request.Request(url, headers={
        "X-NCP-APIGW-API-KEY-ID": NAVER_ID,
        "X-NCP-APIGW-API-KEY": NAVER_SECRET,
    })
    with urllib.request.urlopen(req, timeout=15) as resp:
        data = json.loads(resp.read())

    items = []
    for it in data.get("items", []):
        try:
            published = parsedate_to_datetime(it.get("pubDate", ""))
        except (TypeError, ValueError):
            continue
        original = it.get("originallink") or it.get("link", "")
        items.append({
            "title": clean(it.get("title")),
            "summary": clean(it.get("description")),
            "original": original,                  # 언론사 원문 주소
            "link": it.get("link") or original,    # 네이버 뉴스 주소(있으면)
            "published": published,
        })
    return items


def send_message(text, button_text=None, button_url=None):
    url = f"https://api.telegram.org/bot{TOKEN}/sendMessage"
    payload = {
        "chat_id": CHAT_ID,
        "text": text,
        "parse_mode": "HTML",
        "disable_web_page_preview": "true",
    }
    if button_text and button_url:
        # 메시지 아래에 누르면 기사로 이동하는 버튼을 붙입니다.
        payload["reply_markup"] = json.dumps({
            "inline_keyboard": [[{"text": button_text, "url": button_url}]]
        }, ensure_ascii=False)
    data = urllib.parse.urlencode(payload).encode()
    with urllib.request.urlopen(url, data=data, timeout=15) as resp:
        return json.loads(resp.read())


def main():
    sent = load_sent()
    sent_set = set(sent)
    cutoff = datetime.now(timezone.utc) - timedelta(hours=MAX_AGE_HOURS)

    new_items = []
    for n in fetch_naver_news(SEARCH_WORD):
        if n["published"] < cutoff or n["original"] in sent_set:
            continue
        text = n["title"] + " " + n["summary"]
        if SEARCH_WORD not in text or not any(w in text for w in MUST_INCLUDE_ONE_OF):
            continue
        found = find_outlet(n["original"])
        if found is None:
            print(f"제외(목록에 없는 언론사): {n['original']} - {n['title']}")
            continue
        n["source"], n["category"] = found
        new_items.append(n)
        sent_set.add(n["original"])

    if not new_items:
        print("새 기사 없음")
        return

    for n in sorted(new_items, key=lambda x: x["published"]):
        send_message(build_message(n), "📖 기사 전문 보기", n["link"])
        sent.append(n["original"])

    save_sent(sent)
    print(f"{len(new_items)}건 전송")


if __name__ == "__main__":
    main()
