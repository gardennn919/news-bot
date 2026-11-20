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
from difflib import SequenceMatcher
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
        lines += ["", e(shorten(n["summary"], SUMMARY_MAX))]
    lines += [
        "",
        f"{e(n['source'])} / {korean_time(n['published'])}",
    ]
    return "\n".join(lines)


SIMILAR_RATIO = 0.6     # 제목이 이만큼 비슷하면 같은 기사로 보고 한 번만 보냄 (0~1, 높을수록 엄격)
SIMILAR_HOURS = 24      # 최근 몇 시간 안에 보낸 기사와 비교할지
SAME_WORDS = 8          # 제목·본문에서 연속된 단어 이만큼이 똑같으면 같은 기사로 보고 거름


def load_sent():
    """보낸 기사 기록을 읽습니다. {"links": [...], "titles": [{"t": 제목, "at": 시각}, ...]}"""
    try:
        with open(SENT_FILE, encoding="utf-8") as f:
            data = json.load(f)
    except (FileNotFoundError, json.JSONDecodeError):
        data = {}
    if isinstance(data, list):          # 예전 형식(주소 목록)도 읽을 수 있게
        data = {"links": data}
    data.setdefault("links", [])
    data.setdefault("titles", [])
    data.setdefault("chunks", [])
    return data


def save_sent(data):
    limit = datetime.now(timezone.utc) - timedelta(hours=SIMILAR_HOURS)
    data["links"] = data["links"][-SENT_KEEP:]
    data["titles"] = [x for x in data["titles"]
                      if datetime.fromisoformat(x["at"]) >= limit]
    data["chunks"] = [x for x in data["chunks"]
                      if datetime.fromisoformat(x["at"]) >= limit]
    with open(SENT_FILE, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=0)


def normalize_title(title):
    """비교용 제목: [속보] 같은 말머리, 따옴표·문장부호·띄어쓰기를 지웁니다."""
    t = re.sub(r"\[[^\]]*\]|【[^】]*】|<[^>]*>", "", title)
    t = re.sub(r"[^0-9A-Za-z가-힣]", "", t)
    return t.lower()


def word_chunks(n):
    """제목과 본문 각각에서 연속된 SAME_WORDS개 단어 묶음들을 만듭니다."""
    chunks = set()
    for part, is_summary in ((n["title"], False), (n["summary"], True)):
        tokens = part.split()
        if is_summary and tokens and re.search(r"(\.\.\.|…)$", tokens[-1]):
            tokens = tokens[:-1]        # 요약 끝에 잘린 단어는 비교에서 뺌
        words = []
        for w in tokens:
            w = re.sub(r"^[^0-9A-Za-z가-힣]+|[^0-9A-Za-z가-힣]+$", "", w)  # 앞뒤 따옴표·문장부호 제거
            if w:
                words.append(w)
        for i in range(len(words) - SAME_WORDS + 1):
            chunks.add(" ".join(words[i:i + SAME_WORDS]))
    return chunks


def is_similar(a, b):
    """두 제목(정리된 것)이 같은 기사로 볼 만큼 비슷한지 확인합니다."""
    if not a or not b:
        return False
    if len(a) >= 10 and len(b) >= 10 and (a in b or b in a):
        return True
    return SequenceMatcher(None, a, b).ratio() >= SIMILAR_RATIO


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
    }
    if button_url:
        # 기사 미리보기(사진·제목·요약 카드)를 메시지에 붙입니다.
        payload["link_preview_options"] = json.dumps({
            "url": button_url,
            "prefer_large_media": True,   # 사진을 크게
            "show_above_text": False,     # 미리보기는 글 아래에
        })
    else:
        payload["disable_web_page_preview"] = "true"
    if button_text and button_url:
        # 메시지 아래에 누르면 기사로 이동하는 버튼을 붙입니다.
        payload["reply_markup"] = json.dumps({
            "inline_keyboard": [[{"text": button_text, "url": button_url}]]
        }, ensure_ascii=False)
    data = urllib.parse.urlencode(payload).encode()
    with urllib.request.urlopen(url, data=data, timeout=15) as resp:
        return json.loads(resp.read())


def main():
    data = load_sent()
    sent_set = set(data["links"])
    recent_titles = [x["t"] for x in data["titles"]]
    recent_chunks = {c for x in data["chunks"] for c in x["c"]}
    cutoff = datetime.now(timezone.utc) - timedelta(hours=MAX_AGE_HOURS)

    candidates = []
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
        candidates.append(n)

    sent_count = 0
    now = datetime.now(timezone.utc).isoformat()
    # 먼저 나온 기사부터 보내고, 비슷한 제목의 기사는 건너뜁니다.
    for n in sorted(candidates, key=lambda x: x["published"]):
        data["links"].append(n["original"])
        sent_set.add(n["original"])
        key = normalize_title(n["title"])
        if any(is_similar(key, t) for t in recent_titles):
            print(f"제외(비슷한 기사 이미 보냄): {n['source']} - {n['title']}")
            continue
        chunks = word_chunks(n)
        if chunks & recent_chunks:
            print(f"제외(연속 {SAME_WORDS}단어 일치): {n['source']} - {n['title']}")
            continue
        send_message(build_message(n), button_url=n["link"])  # 버튼 없이 사진 미리보기만
        recent_titles.append(key)
        data["titles"].append({"t": key, "at": now})
        recent_chunks |= chunks
        data["chunks"].append({"c": sorted(chunks), "at": now})
        sent_count += 1

    save_sent(data)
    print(f"{sent_count}건 전송" if sent_count else "새 기사 없음")


if __name__ == "__main__":
    main()
