"""
또롱이 뉴스레터 v2
- 신뢰 매체 RSS 직접 구독 + 전일 기사 필터 + 중복 제거
- 요일별 딥다이브 자동 전환 (월화: 사례분석 / 수목: 전략분석 / 금: SNS 말말말)
- 월~금만 발송 (주말 없음)
- 확정 디자인 적용 (고딕, 딥퍼플 헤더, 오렌지 one-liner, 아이보리 본문)
"""

import os
import json
import smtplib
import feedparser
import anthropic
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText
from datetime import datetime, timezone, timedelta
from pathlib import Path

# ─────────────────────────────────────────
# 설정
# ─────────────────────────────────────────
ANTHROPIC_API_KEY  = os.environ["ANTHROPIC_API_KEY"]
GMAIL_ADDRESS      = os.environ["GMAIL_ADDRESS"]
GMAIL_APP_PASSWORD = os.environ["GMAIL_APP_PASSWORD"]

KST       = timezone(timedelta(hours=9))
NOW_KST   = datetime.now(KST)
TODAY     = NOW_KST.strftime("%Y년 %m월 %d일")
DOW_NUM   = NOW_KST.weekday()   # 0=월 1=화 2=수 3=목 4=금 5=토 6=일
DOW_KR    = ["월", "화", "수", "목", "금", "토", "일"][DOW_NUM]
DOW_SHORT = ["(월)", "(화)", "(수)", "(목)", "(금)", "(토)", "(일)"][DOW_NUM]
YESTERDAY = (NOW_KST - timedelta(days=1)).date()

# 딥다이브 타입
if DOW_NUM in (0, 1):
    DIVE_TYPE  = "case"
elif DOW_NUM in (2, 3):
    DIVE_TYPE  = "strategy"
else:
    DIVE_TYPE  = "sns"

DIVE_LABEL = {
    "case":     "비즈니스 인사이트: 사례분석",
    "strategy": "비즈니스 인사이트: 전략분석",
    "sns":      "비즈니스 인사이트: 리더들의 SNS 말말말",
}[DIVE_TYPE]

DIVE_EYEBROW = {
    "case":     "Case Study",
    "strategy": "Strategy Analysis",
    "sns":      "Leaders' SNS",
}[DIVE_TYPE]

# ─────────────────────────────────────────
# RSS 소스
# ─────────────────────────────────────────
RSS_FEEDS = [
    {"name": "The Verge AI",       "url": "https://www.theverge.com/ai-artificial-intelligence/rss/index.xml",  "lang": "en", "category": "ai"},
    {"name": "TechCrunch AI",      "url": "https://techcrunch.com/category/artificial-intelligence/feed/",       "lang": "en", "category": "ai"},
    {"name": "VentureBeat AI",     "url": "https://venturebeat.com/category/ai/feed/",                           "lang": "en", "category": "ai"},
    {"name": "Reuters Tech",       "url": "https://feeds.reuters.com/reuters/technologyNews",                     "lang": "en", "category": "bigtech"},
    {"name": "연합뉴스 IT",        "url": "https://www.yna.co.kr/rss/it.xml",                                    "lang": "ko", "category": "bigtech"},
    {"name": "TechCrunch Startup", "url": "https://techcrunch.com/category/startups/feed/",                      "lang": "en", "category": "startup"},
    {"name": "연합뉴스 경제",      "url": "https://www.yna.co.kr/rss/economy.xml",                               "lang": "ko", "category": "economy"},
]

# ─────────────────────────────────────────
# 구독자 로드
# ─────────────────────────────────────────
def load_subscribers() -> list[str]:
    path = Path("subscribers.txt")
    if not path.exists():
        fallback = os.environ.get("RECIPIENT_EMAIL", "")
        return [fallback] if fallback else []
    emails = []
    for line in path.read_text(encoding="utf-8").splitlines():
        email = line.strip()
        if email and "@" in email and not email.startswith("#"):
            emails.append(email)
    return emails

# ─────────────────────────────────────────
# RSS 수집 (전일 기사 + 중복 제거)
# ─────────────────────────────────────────
def parse_entry_date(entry):
    for attr in ("published_parsed", "updated_parsed"):
        t = getattr(entry, attr, None)
        if t:
            try:
                return datetime(*t[:6], tzinfo=timezone.utc)
            except Exception:
                pass
    return None

def is_yesterday(entry) -> bool:
    dt = parse_entry_date(entry)
    if not dt:
        return True
    return dt.astimezone(KST).date() == YESTERDAY

def fetch_all_articles() -> list[dict]:
    seen: set[str] = set()
    articles: list[dict] = []
    for feed in RSS_FEEDS:
        try:
            parsed = feedparser.parse(feed["url"])
            count = 0
            for entry in parsed.entries:
                if count >= 6:
                    break
                if not is_yesterday(entry):
                    continue
                title = entry.get("title", "").strip()
                if not title:
                    continue
                key = title[:20].lower()
                if key in seen:
                    continue
                seen.add(key)
                articles.append({
                    "title":    title,
                    "link":     entry.get("link", ""),
                    "summary":  entry.get("summary", "")[:400],
                    "lang":     feed["lang"],
                    "source":   feed["name"],
                    "category": feed["category"],
                })
                count += 1
        except Exception as e:
            print(f"  [RSS 오류] {feed['name']}: {e}")
    print(f"  [수집] 총 {len(articles)}개 (전일 기사, 중복 제거)")
    return articles

# ─────────────────────────────────────────
# Claude 요약
# ─────────────────────────────────────────
def build_dive_prompt() -> str:
    if DIVE_TYPE == "case":
        return """[딥다이브: 사례분석]
수집된 기사에서 가장 흥미로운 해외 기업 사례를 하나 골라 스토리텔링으로 분석.
구성: ① 무슨 일이 있었나(팩트) ② 왜 흥미로운가 ③ 우리가 배울 점. 각 3~4줄."""
    elif DIVE_TYPE == "strategy":
        return """[딥다이브: 전략분석]
빅테크 또는 AI 스타트업의 핵심 비즈니스 전략 하나를 골라 분석.
구성: ① 이 회사가 지금 무엇을 하고 있나 ② 전략의 핵심 ③ 경쟁자 대비 포지셔닝. 수치 필수."""
    else:
        return """[딥다이브: 리더들의 SNS 말말말]
Sam Altman, Jensen Huang, Satya Nadella, Mark Zuckerberg, Elon Musk 등
AI/테크 리더들의 최근 X(트위터)/블로그 발언 중 이슈가 된 것 2~3개 선별.
각 발언: ① 누가 ② 무슨 말 (핵심 인용) ③ 왜 주목받았나. 각 3~4줄."""

def summarize_with_claude(articles: list[dict]) -> dict:
    client = anthropic.Anthropic(api_key=ANTHROPIC_API_KEY)

    articles_text = ""
    for i, a in enumerate(articles, 1):
        lang_note = "(영어→한국어 번역 필요)" if a["lang"] == "en" else ""
        articles_text += f"\n[{i}] [{a['source']}] [{a['category']}] {lang_note}\n제목: {a['title']}\n링크: {a['link']}\n내용: {a['summary']}\n---"

    prompt = f"""당신은 '또롱이 뉴스레터' 에디터입니다.
오늘: {TODAY} ({DOW_KR}요일)

{articles_text}

[규칙]
1. 영어 기사는 한국어로 번역 후 요약
2. 팩트 → 왜 중요한지 → 수치 순서로 구성, 수치 반드시 포함
3. {build_dive_prompt()}
4. one_liner: 오늘 뉴스를 관통하는 임팩트 있는 한 문장 (30자 이내)
5. bigtech: 뉴스 기반 주가 방향성 (실제 수치 없으면 상승/하락/보합으로 표기)
6. dive_subject: 반드시 한 줄로 끝낼 것 (20자 이내)

JSON만 응답 (마크다운 코드블록 없이):
{{
  "one_liner": "30자 이내 한 문장",
  "morning_briefs": [
    {{"bold": "키워드", "text": "팩트. 중요성. 수치.", "highlight": "강조 키워드 또는 null"}}
  ],
  "deep_dive": {{
    "subject": "한 줄 제목 (20자 이내)",
    "intro": "인트로 2~3줄",
    "bullets": [
      {{"head": "소제목", "body": "3~4줄 내용", "highlight": "강조 키워드 또는 null"}}
    ]
  }},
  "bigtech": [
    {{"name": "Nvidia", "ticker": "NVDA", "change": "+2.3%", "reason": "한 줄 이유", "up": true}}
  ],
  "startups": [
    {{"name": "회사명", "summary": "2줄 요약", "amount": "$100M · Series B", "link": "URL"}}
  ],
  "ai_tool": {{
    "name": "툴 이름",
    "tagline": "한 줄 설명",
    "what": "무엇인가 2줄",
    "why": "왜 주목받나 2줄",
    "link": "URL"
  }},
  "schedule": [
    {{"date": "3/17(화)", "label": "이벤트명", "key": true}}
  ]
}}"""

    message = client.messages.create(
        model="claude-sonnet-4-20250514",
        max_tokens=8000,
        messages=[{"role": "user", "content": prompt}]
    )
    raw = message.content[0].text.strip()
    if raw.startswith("```"):
        raw = raw.split("```")[1]
        if raw.startswith("json"):
            raw = raw[4:]
    return json.loads(raw.strip())

# ─────────────────────────────────────────
# HTML 빌드 (확정 디자인)
# ─────────────────────────────────────────
CSS = """
* { margin:0; padding:0; box-sizing:border-box; }
body { background:#EDEBE4; font-family:'Noto Sans KR',sans-serif; -webkit-font-smoothing:antialiased; }
.wrap { max-width:620px; margin:0 auto; background:#F5F3EC; border:1px solid #D8D5CB; }
.header { background:#1A1040; padding:28px 40px 45px; }
.header-meta { display:flex; align-items:center; justify-content:space-between; font-size:11px; letter-spacing:2px; color:#7B6FAA; text-transform:uppercase; margin-bottom:14px; }
.header-meta-date { font-size:11px; color:#C4BAE8; font-weight:300; letter-spacing:0.5px; text-transform:none; }
.header-title { display:flex; align-items:center; gap:10px; margin-bottom:6px; }
.header-icon { font-size:24px; line-height:1; display:inline-block; }
.header-name { font-size:26px; font-weight:700; color:#F0EDE4; letter-spacing:-0.5px; }
.header-sub { font-size:12px; color:#E8682A; font-weight:400; margin-top:2px; }
.oneliner { background:#E8682A; padding:18px 40px 20px; }
.oneliner-label { font-size:10px; letter-spacing:2px; color:#FFD4B8; text-transform:uppercase; margin-bottom:6px; }
.oneliner-text { font-size:14.5px; color:#FFF8F5; line-height:1.75; font-weight:500; }
.section { padding:43px 40px 32px; border-bottom:1px solid #D0CCC0; background:#F5F3EC; position:relative; }
.section+.section { border-top:8px solid #E0DDD4; }
.section:last-of-type { border-bottom:none; }
.section.dive-bg { background:#F8F6FF; }
.section-eyebrow { display:inline-block; font-size:10px; letter-spacing:0; text-transform:uppercase; color:#7B6FAA; border:1px solid #B8B0D0; border-radius:3px; padding:2px 8px; position:absolute; top:37px; right:40px; }
.section-title { font-size:17px; font-weight:700; color:#1A1040; margin-bottom:20px; padding-bottom:14px; border-bottom:1.5px solid #D0CCC0; line-height:1.3; padding-right:110px; }
.brief-item { display:flex; gap:12px; margin-bottom:18px; }
.brief-item:last-child { margin-bottom:0; }
.brief-dot { flex-shrink:0; width:6px; height:6px; border-radius:50%; background:#5B3FA0; margin-top:7px; }
.brief-body { font-size:13.5px; line-height:1.85; color:#2A2540; }
.brief-body strong { font-weight:700; color:#1A1040; }
.hi-purple { color:#5B3FA0; font-weight:500; }
.hi-blue { color:#1A5FA0; font-weight:500; }
.dive-label { display:inline-block; font-size:10px; letter-spacing:1.5px; background:#EDE8F8; color:#5B3FA0; padding:3px 10px; border-radius:3px; text-transform:uppercase; margin-bottom:8px; }
.dive-subject { font-size:18px; font-weight:700; color:#1A1040; line-height:1.35; margin-bottom:14px; white-space:nowrap; overflow:hidden; text-overflow:ellipsis; }
.dive-intro { font-size:13.5px; color:#4A4460; line-height:1.85; margin-bottom:20px; padding-left:20px; position:relative; }
.dive-intro::before { content:'\201C'; position:absolute; left:0; top:-4px; font-size:28px; color:#5B3FA0; font-weight:700; line-height:1; }
.dive-bullet { display:flex; gap:12px; margin-bottom:16px; }
.dive-bullet:last-child { margin-bottom:0; }
.dive-sq { flex-shrink:0; width:6px; height:6px; background:#5B3FA0; margin-top:8px; border-radius:1px; }
.dive-text { font-size:13.5px; line-height:1.85; color:#2A2540; }
.dive-text strong { font-weight:700; color:#1A1040; }
.market-table { width:100%; border-collapse:collapse; font-size:13px; }
.market-table th { font-size:10px; letter-spacing:1.5px; color:#9994A8; text-transform:uppercase; font-weight:400; padding:0 0 10px; border-bottom:1px solid #D0CCC0; text-align:left; }
.market-table th:not(:first-child) { text-align:right; }
.market-table td { padding:9px 0; border-bottom:1px solid #E8E5DC; color:#2A2540; vertical-align:middle; }
.market-table tr:last-child td { border-bottom:none; }
.market-table td:not(:first-child) { text-align:right; }
.market-name { font-weight:500; color:#1A1040; }
.market-val { font-weight:400; color:#4A4460; }
.market-reason { font-size:11.5px; color:#8A8098; display:block; margin-top:2px; }
.up { color:#1A7A4A; font-weight:500; }
.down { color:#C0392B; font-weight:500; }
.startup-item { padding:14px 0; border-bottom:1px solid #E8E5DC; }
.startup-item:last-child { border-bottom:none; padding-bottom:0; }
.startup-head { display:flex; align-items:center; gap:8px; margin-bottom:5px; }
.startup-name { font-size:14px; font-weight:700; color:#1A1040; }
.startup-amount { display:inline-block; font-size:11px; background:#EDE8F8; color:#5B3FA0; padding:2px 8px; border-radius:3px; }
.startup-text { font-size:13px; color:#4A4460; line-height:1.8; }
.tool-card { background:#EDEBFF; border-radius:6px; padding:20px 24px; border-left:3px solid #5B3FA0; }
.tool-head { display:flex; align-items:baseline; gap:10px; margin-bottom:10px; }
.tool-name { font-size:16px; font-weight:700; color:#1A1040; }
.tool-tag { font-size:11px; color:#7B6FAA; font-weight:300; }
.tool-row { font-size:13.5px; color:#2A2540; line-height:1.85; margin-bottom:8px; }
.tool-row strong { font-weight:600; color:#5B3FA0; }
.tool-link { font-size:12px; color:#E8682A; text-decoration:none; font-weight:500; }
.sched-item { display:flex; gap:16px; padding:9px 0; border-bottom:1px solid #E8E5DC; font-size:13px; align-items:flex-start; }
.sched-item:last-child { border-bottom:none; padding-bottom:0; }
.sched-date { flex-shrink:0; width:88px; color:#9994A8; font-weight:500; font-size:12.5px; }
.sched-label { color:#2A2540; line-height:1.6; }
.sched-label.key { font-weight:700; color:#1A1040; }
.sched-star { color:#5B3FA0; margin-right:3px; }
.subscribe-cta { padding:28px 40px; background:#1A1040; text-align:center; border-bottom:1px solid #0E0830; }
.subscribe-cta-title { font-size:16px; font-weight:700; color:#F0EDE4; margin-bottom:6px; }
.subscribe-cta-desc { font-size:12.5px; color:#8A7FAA; margin-bottom:18px; line-height:1.7; font-weight:300; }
.subscribe-btn { display:inline-block; background:#E8682A; color:#fff; font-size:13px; font-weight:700; padding:12px 32px; border-radius:6px; text-decoration:none; }
.footer { background:#1A1040; padding:22px 40px; text-align:center; }
.footer p { font-size:11px; color:#5A5078; line-height:2; }
.footer a { color:#7B6FAA; text-decoration:none; }
"""

def build_html(data: dict) -> str:

    def hl(text, keyword):
        if not keyword or not text:
            return text
        return text.replace(keyword, f'<span class="hi-purple">{keyword}</span>', 1)

    def render_briefs(items):
        html = ""
        for b in items:
            text = hl(b.get("text", ""), b.get("highlight"))
            html += (
                '<div class="brief-item">'
                '<div class="brief-dot"></div>'
                f'<div class="brief-body"><strong>{b["bold"]}</strong> — {text}</div>'
                '</div>'
            )
        return html

    def render_dive(dive):
        subject = dive.get("subject", "")
        intro   = dive.get("intro", "")
        bullets = dive.get("bullets", [])
        html = (
            f'<div class="dive-label">{DIVE_EYEBROW}</div>'
            f'<div class="dive-subject">{subject}</div>'
            f'<div class="dive-intro">{intro}</div>'
        )
        for b in bullets:
            body = hl(b.get("body", ""), b.get("highlight"))
            html += (
                '<div class="dive-bullet">'
                '<div class="dive-sq"></div>'
                f'<div class="dive-text"><strong>{b["head"]}</strong> {body}</div>'
                '</div>'
            )
        return html

    def render_bigtech(items):
        if not items:
            return '<p style="font-size:13px;color:#8A8780">오늘 주요 지수 데이터가 없습니다.</p>'
        rows = ""
        for item in items:
            is_up  = item.get("up", True)
            arrow  = "▲" if is_up else "▼"
            cls    = "up" if is_up else "down"
            rows += (
                f'<tr>'
                f'<td><span class="market-name">{item["name"]} <span style="font-size:11px;color:#9994A8">{item.get("ticker","")}</span></span>'
                f'<span class="market-reason">{item["reason"]}</span></td>'
                f'<td class="market-val">{item.get("price","—")}</td>'
                f'<td><span class="{cls}">{arrow} {item["change"]}</span></td>'
                f'</tr>'
            )
        return (
            '<table class="market-table"><thead><tr>'
            '<th>종목/지수</th><th>현재가</th><th>등락</th>'
            f'</tr></thead><tbody>{rows}</tbody></table>'
        )

    def render_startups(items):
        html = ""
        for s in items:
            html += (
                '<div class="startup-item">'
                '<div class="startup-head">'
                f'<span class="startup-name">{s["name"]}</span>'
                f'<span class="startup-amount">{s.get("amount","")}</span>'
                '</div>'
                f'<div class="startup-text">{s["summary"]}</div>'
                '</div>'
            )
        return html

    def render_tool(tool):
        if not tool:
            return ""
        return (
            '<div class="tool-card">'
            '<div class="tool-head">'
            f'<span class="tool-name">{tool["name"]}</span>'
            f'<span class="tool-tag">{tool.get("tagline","")}</span>'
            '</div>'
            f'<div class="tool-row"><strong>무엇인가</strong> {tool.get("what","")}</div>'
            f'<div class="tool-row"><strong>왜 주목받나</strong> {tool.get("why","")}</div>'
            f'<a href="{tool.get("link","#")}" class="tool-link">자세히 보기 →</a>'
            '</div>'
        )

    def render_schedule(items):
        html = ""
        for item in items:
            star = '<span class="sched-star">★</span>' if item.get("key") else ""
            key_cls = " key" if item.get("key") else ""
            html += (
                '<div class="sched-item">'
                f'<div class="sched-date">{item["date"]}</div>'
                f'<div class="sched-label{key_cls}">{star}{item["label"]}</div>'
                '</div>'
            )
        return html

    one_liner    = data.get("one_liner", "")
    briefs_html  = render_briefs(data.get("morning_briefs", []))
    dive_html    = render_dive(data.get("deep_dive", {}))
    bigtech_html = render_bigtech(data.get("bigtech", []))
    startup_html = render_startups(data.get("startups", []))
    tool_html    = render_tool(data.get("ai_tool"))
    sched_html   = render_schedule(data.get("schedule", []))

    return f"""<!DOCTYPE html>
<html lang="ko">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width,initial-scale=1.0">
<title>또롱이 뉴스레터 — {TODAY}</title>
<link href="https://fonts.googleapis.com/css2?family=Noto+Sans+KR:wght@300;400;500;700&display=swap" rel="stylesheet">
<style>{CSS}</style>
</head>
<body>
<div class="wrap">

<div class="header">
  <div class="header-meta">
    <span>Daily Briefing · AI &amp; Economy</span>
    <span class="header-meta-date">{TODAY} {DOW_SHORT}</span>
  </div>
  <div class="header-title">
    <span class="header-icon">👓</span>
    <span class="header-name">또롱이 뉴스레터</span>
  </div>
  <div class="header-sub">AI · 기술 · 경제 핵심 뉴스</div>
</div>

<div class="oneliner">
  <div class="oneliner-label">Today's One-liner</div>
  <div class="oneliner-text">{one_liner}</div>
</div>

<div class="section">
  <div class="section-eyebrow">Morning Brief</div>
  <div class="section-title">☀ 또모닝 브리핑</div>
  {briefs_html}
</div>

<div class="section dive-bg">
  <div class="section-eyebrow">Deep Dive</div>
  <div class="section-title">{DIVE_LABEL}</div>
  {dive_html}
</div>

<div class="section">
  <div class="section-eyebrow">Markets</div>
  <div class="section-title">📊 빅테크 &amp; 주요 지수</div>
  {bigtech_html}
</div>

<div class="section">
  <div class="section-eyebrow">Startup Radar</div>
  <div class="section-title">🚀 AI 스타트업 레이더</div>
  {startup_html}
</div>

<div class="section">
  <div class="section-eyebrow">AI Tool</div>
  <div class="section-title">🛠 오늘의 AI 툴</div>
  {tool_html}
</div>

<div class="section">
  <div class="section-eyebrow">Calendar</div>
  <div class="section-title">📅 이번 주 주요 일정</div>
  {sched_html}
</div>

<div class="subscribe-cta">
  <div class="subscribe-cta-title">👓 또롱이 뉴스레터 구독하기</div>
  <div class="subscribe-cta-desc">매일 오전 7시, AI·기술·경제 핵심 뉴스를<br>깔끔하게 정리해서 보내드립니다.</div>
  <a href="mailto:{GMAIL_ADDRESS}?subject=또롱이 뉴스레터 구독 신청&body=안녕하세요! 구독 신청합니다." class="subscribe-btn">구독 신청하기 →</a>
</div>

<div class="footer">
  <p>또롱이 뉴스레터 · Powered by Claude AI<br>
  수신 거부: <a href="mailto:{GMAIL_ADDRESS}?subject=또롱이 뉴스레터 수신 거부">여기로 메일 주세요</a></p>
</div>

</div>
</body>
</html>"""

# ─────────────────────────────────────────
# 발송
# ─────────────────────────────────────────
def send_to_all(html_content: str, subscribers: list[str]):
    subject = f"📰 또롱이 뉴스레터 — {TODAY} {DOW_SHORT}"
    with smtplib.SMTP_SSL("smtp.gmail.com", 465) as server:
        server.login(GMAIL_ADDRESS, GMAIL_APP_PASSWORD)
        for email in subscribers:
            try:
                msg = MIMEMultipart("alternative")
                msg["Subject"] = subject
                msg["From"]    = f"또롱이 뉴스레터 <{GMAIL_ADDRESS}>"
                msg["To"]      = email
                msg.attach(MIMEText(html_content, "html", "utf-8"))
                server.sendmail(GMAIL_ADDRESS, email, msg.as_string())
                print(f"  [✓] {email}")
            except Exception as e:
                print(f"  [✗] {email}: {e}")

# ─────────────────────────────────────────
# 메인
# ─────────────────────────────────────────
def main():
    print(f"[시작] {TODAY} ({DOW_KR}요일) — {DIVE_LABEL}")

    if DOW_NUM >= 5:
        print("[중단] 주말 발송 없음.")
        return

    subscribers = load_subscribers()
    if not subscribers:
        print("[오류] 구독자 없음.")
        return
    print(f"[구독자] {len(subscribers)}명")

    articles = fetch_all_articles()
    if not articles:
        print("[오류] 수집된 기사 없음.")
        return

    print("[Claude] 요약 중...")
    data = summarize_with_claude(articles)

    html = build_html(data)

    print(f"[발송] {len(subscribers)}명...")
    send_to_all(html, subscribers)
    print("[완료] 또롱이 뉴스레터 발송!")

if __name__ == "__main__":
    main()
