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
# HTML 빌드 (인라인 스타일 — 이메일 클라이언트 호환)
# ─────────────────────────────────────────
_F = "font-family:'Noto Sans KR',sans-serif;"  # 폰트 축약

def build_html(data: dict) -> str:

    def hl(text, keyword):
        if not keyword or not text:
            return text
        return text.replace(
            keyword,
            f'<span style="color:#5B3FA0;font-weight:500;">{keyword}</span>',
            1,
        )

    def section_header(title, eyebrow):
        """섹션 제목 + eyebrow 태그를 table로 나란히 배치"""
        return (
            f'<table style="width:100%;border-collapse:collapse;margin-bottom:20px;">'
            f'<tr>'
            f'<td style="{_F}font-size:17px;font-weight:700;color:#1A1040;'
            f'padding-bottom:14px;border-bottom:1.5px solid #D0CCC0;line-height:1.3;">'
            f'{title}</td>'
            f'<td style="text-align:right;vertical-align:top;padding-bottom:14px;'
            f'border-bottom:1.5px solid #D0CCC0;white-space:nowrap;padding-left:12px;">'
            f'<span style="{_F}display:inline-block;font-size:10px;letter-spacing:0;'
            f'text-transform:uppercase;color:#7B6FAA;border:1px solid #B8B0D0;'
            f'border-radius:3px;padding:2px 8px;">{eyebrow}</span>'
            f'</td>'
            f'</tr>'
            f'</table>'
        )

    def render_briefs(items):
        html = ""
        for i, b in enumerate(items):
            text = hl(b.get("text", ""), b.get("highlight"))
            mb = "0" if i == len(items) - 1 else "18px"
            html += (
                f'<table style="width:100%;border-collapse:collapse;margin-bottom:{mb};">'
                f'<tr>'
                f'<td style="width:6px;vertical-align:top;padding-top:7px;padding-right:12px;">'
                f'<div style="width:6px;height:6px;border-radius:50%;background:#5B3FA0;"></div>'
                f'</td>'
                f'<td style="{_F}font-size:13.5px;line-height:1.85;color:#2A2540;">'
                f'<strong style="font-weight:700;color:#1A1040;">{b["bold"]}</strong>'
                f' — {text}'
                f'</td>'
                f'</tr>'
                f'</table>'
            )
        return html

    def render_dive(dive):
        subject = dive.get("subject", "")
        intro   = dive.get("intro", "")
        bullets = dive.get("bullets", [])

        html = (
            f'<div style="{_F}display:inline-block;font-size:10px;letter-spacing:1.5px;'
            f'background:#EDE8F8;color:#5B3FA0;padding:3px 10px;border-radius:3px;'
            f'text-transform:uppercase;margin-bottom:8px;">{DIVE_EYEBROW}</div>'
            f'<div style="{_F}font-size:18px;font-weight:700;color:#1A1040;line-height:1.35;'
            f'margin-bottom:14px;overflow:hidden;text-overflow:ellipsis;">{subject}</div>'
        )
        # ::before 큰따옴표를 실제 td 셀로 구현
        html += (
            f'<table style="width:100%;border-collapse:collapse;margin-bottom:20px;">'
            f'<tr>'
            f'<td style="{_F}width:20px;vertical-align:top;font-size:28px;color:#5B3FA0;'
            f'font-weight:700;line-height:1;padding-right:4px;">\u201C</td>'
            f'<td style="{_F}font-size:13.5px;color:#4A4460;line-height:1.85;">{intro}</td>'
            f'</tr>'
            f'</table>'
        )
        for i, b in enumerate(bullets):
            body = hl(b.get("body", ""), b.get("highlight"))
            mb = "0" if i == len(bullets) - 1 else "16px"
            html += (
                f'<table style="width:100%;border-collapse:collapse;margin-bottom:{mb};">'
                f'<tr>'
                f'<td style="width:6px;vertical-align:top;padding-top:8px;padding-right:12px;">'
                f'<div style="width:6px;height:6px;background:#5B3FA0;border-radius:1px;"></div>'
                f'</td>'
                f'<td style="{_F}font-size:13.5px;line-height:1.85;color:#2A2540;">'
                f'<strong style="font-weight:700;color:#1A1040;">{b["head"]}</strong>'
                f' {body}'
                f'</td>'
                f'</tr>'
                f'</table>'
            )
        return html

    def render_bigtech(items):
        if not items:
            return f'<p style="{_F}font-size:13px;color:#8A8780;">오늘 주요 지수 데이터가 없습니다.</p>'
        thead = (
            f'<tr>'
            f'<th style="{_F}font-size:10px;letter-spacing:1.5px;color:#9994A8;'
            f'text-transform:uppercase;font-weight:400;padding:0 0 10px;'
            f'border-bottom:1px solid #D0CCC0;text-align:left;">종목/지수</th>'
            f'<th style="{_F}font-size:10px;letter-spacing:1.5px;color:#9994A8;'
            f'text-transform:uppercase;font-weight:400;padding:0 0 10px;'
            f'border-bottom:1px solid #D0CCC0;text-align:right;">현재가</th>'
            f'<th style="{_F}font-size:10px;letter-spacing:1.5px;color:#9994A8;'
            f'text-transform:uppercase;font-weight:400;padding:0 0 10px;'
            f'border-bottom:1px solid #D0CCC0;text-align:right;">등락</th>'
            f'</tr>'
        )
        tbody = ""
        for i, item in enumerate(items):
            is_up  = item.get("up", True)
            arrow  = "▲" if is_up else "▼"
            c_chg  = "#1A7A4A" if is_up else "#C0392B"
            bd     = "none" if i == len(items) - 1 else "1px solid #E8E5DC"
            td_base = f"padding:9px 0;border-bottom:{bd};vertical-align:middle;"
            tbody += (
                f'<tr>'
                f'<td style="{_F}{td_base}color:#2A2540;">'
                f'<span style="font-weight:500;color:#1A1040;">{item["name"]}'
                f' <span style="font-size:11px;color:#9994A8;">{item.get("ticker","")}</span></span>'
                f'<span style="{_F}font-size:11.5px;color:#8A8098;display:block;margin-top:2px;">'
                f'{item["reason"]}</span>'
                f'</td>'
                f'<td style="{_F}{td_base}font-weight:400;color:#4A4460;text-align:right;">'
                f'{item.get("price","—")}</td>'
                f'<td style="{td_base}text-align:right;">'
                f'<span style="{_F}color:{c_chg};font-weight:500;">{arrow} {item["change"]}</span>'
                f'</td>'
                f'</tr>'
            )
        return (
            f'<table style="width:100%;border-collapse:collapse;font-size:13px;">'
            f'<thead>{thead}</thead><tbody>{tbody}</tbody></table>'
        )

    def render_startups(items):
        html = ""
        for i, s in enumerate(items):
            is_last = i == len(items) - 1
            bd = "none" if is_last else "1px solid #E8E5DC"
            pb = "0" if is_last else "14px"
            html += (
                f'<div style="padding:14px 0 {pb};border-bottom:{bd};">'
                f'<table style="width:100%;border-collapse:collapse;margin-bottom:5px;">'
                f'<tr>'
                f'<td style="vertical-align:middle;">'
                f'<span style="{_F}font-size:14px;font-weight:700;color:#1A1040;">{s["name"]}</span>'
                f'</td>'
                f'<td style="text-align:right;vertical-align:middle;">'
                f'<span style="{_F}display:inline-block;font-size:11px;background:#EDE8F8;'
                f'color:#5B3FA0;padding:2px 8px;border-radius:3px;">{s.get("amount","")}</span>'
                f'</td>'
                f'</tr>'
                f'</table>'
                f'<div style="{_F}font-size:13px;color:#4A4460;line-height:1.8;">{s["summary"]}</div>'
                f'</div>'
            )
        return html

    def render_tool(tool):
        if not tool:
            return ""
        return (
            f'<div style="background:#EDEBFF;border-radius:6px;padding:20px 24px;'
            f'border-left:3px solid #5B3FA0;">'
            f'<div style="margin-bottom:10px;">'
            f'<span style="{_F}font-size:16px;font-weight:700;color:#1A1040;">{tool["name"]}</span>'
            f'&nbsp;&nbsp;'
            f'<span style="{_F}font-size:11px;color:#7B6FAA;font-weight:300;">{tool.get("tagline","")}</span>'
            f'</div>'
            f'<div style="{_F}font-size:13.5px;color:#2A2540;line-height:1.85;margin-bottom:8px;">'
            f'<strong style="font-weight:600;color:#5B3FA0;">무엇인가</strong> {tool.get("what","")}</div>'
            f'<div style="{_F}font-size:13.5px;color:#2A2540;line-height:1.85;margin-bottom:8px;">'
            f'<strong style="font-weight:600;color:#5B3FA0;">왜 주목받나</strong> {tool.get("why","")}</div>'
            f'<a href="{tool.get("link","#")}" style="{_F}font-size:12px;color:#E8682A;'
            f'text-decoration:none;font-weight:500;">자세히 보기 →</a>'
            f'</div>'
        )

    def render_schedule(items):
        html = ""
        for i, item in enumerate(items):
            is_last = i == len(items) - 1
            bd = "none" if is_last else "1px solid #E8E5DC"
            pb = "0" if is_last else "9px"
            star = f'<span style="color:#5B3FA0;margin-right:3px;">★</span>' if item.get("key") else ""
            lbl_style = (
                f"{_F}color:#1A1040;font-weight:700;line-height:1.6;"
                if item.get("key")
                else f"{_F}color:#2A2540;line-height:1.6;"
            )
            html += (
                f'<div style="padding:9px 0 {pb};border-bottom:{bd};">'
                f'<table style="width:100%;border-collapse:collapse;">'
                f'<tr>'
                f'<td style="{_F}width:88px;color:#9994A8;font-weight:500;font-size:12.5px;'
                f'vertical-align:top;">{item["date"]}</td>'
                f'<td style="{lbl_style}">{star}{item["label"]}</td>'
                f'</tr>'
                f'</table>'
                f'</div>'
            )
        return html

    one_liner    = data.get("one_liner", "")
    briefs_html  = render_briefs(data.get("morning_briefs", []))
    dive_html    = render_dive(data.get("deep_dive", {}))
    bigtech_html = render_bigtech(data.get("bigtech", []))
    startup_html = render_startups(data.get("startups", []))
    tool_html    = render_tool(data.get("ai_tool"))
    sched_html   = render_schedule(data.get("schedule", []))

    _S  = f"padding:43px 40px 32px;background:#F5F3EC;border-top:8px solid #E0DDD4;"
    _S0 = f"padding:43px 40px 32px;background:#F5F3EC;"           # 첫 섹션 (border-top 없음)
    _SD = f"padding:43px 40px 32px;background:#F8F6FF;border-top:8px solid #E0DDD4;"  # 딥다이브

    return f"""<!DOCTYPE html>
<html lang="ko">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width,initial-scale=1.0">
<title>또롱이 뉴스레터 — {TODAY}</title>
<link href="https://fonts.googleapis.com/css2?family=Noto+Sans+KR:wght@300;400;500;700&display=swap" rel="stylesheet">
</head>
<body style="margin:0;padding:0;background:#EDEBE4;{_F}-webkit-font-smoothing:antialiased;">
<div style="max-width:620px;margin:0 auto;background:#F5F3EC;border:1px solid #D8D5CB;">

<!-- Header -->
<div style="background:#1A1040;padding:28px 40px 45px;">
  <table style="width:100%;border-collapse:collapse;margin-bottom:14px;">
    <tr>
      <td style="{_F}font-size:11px;letter-spacing:2px;color:#7B6FAA;text-transform:uppercase;">Daily Briefing · AI &amp; Economy</td>
      <td style="{_F}text-align:right;font-size:11px;color:#C4BAE8;font-weight:300;letter-spacing:0.5px;">{TODAY} {DOW_SHORT}</td>
    </tr>
  </table>
  <div style="margin-bottom:6px;">
    <span style="font-size:24px;line-height:1;display:inline-block;">👓</span>
    <span style="{_F}font-size:26px;font-weight:700;color:#F0EDE4;letter-spacing:-0.5px;vertical-align:middle;margin-left:10px;">또롱이 뉴스레터</span>
  </div>
  <div style="{_F}font-size:12px;color:#E8682A;font-weight:400;margin-top:2px;">AI · 기술 · 경제 핵심 뉴스</div>
</div>

<!-- One-liner -->
<div style="background:#E8682A;padding:18px 40px 20px;">
  <div style="{_F}font-size:10px;letter-spacing:2px;color:#FFD4B8;text-transform:uppercase;margin-bottom:6px;">Today's One-liner</div>
  <div style="{_F}font-size:14.5px;color:#FFF8F5;line-height:1.75;font-weight:500;">{one_liner}</div>
</div>

<!-- Morning Briefing -->
<div style="{_S0}">
  {section_header("☀ 또모닝 브리핑", "Morning Brief")}
  {briefs_html}
</div>

<!-- Deep Dive -->
<div style="{_SD}">
  {section_header(DIVE_LABEL, "Deep Dive")}
  {dive_html}
</div>

<!-- BigTech & 주요 지수 -->
<div style="{_S}">
  {section_header("📊 빅테크 &amp; 주요 지수", "Markets")}
  {bigtech_html}
</div>

<!-- AI 스타트업 -->
<div style="{_S}">
  {section_header("🚀 AI 스타트업 레이더", "Startup Radar")}
  {startup_html}
</div>

<!-- AI 툴 -->
<div style="{_S}">
  {section_header("🛠 오늘의 AI 툴", "AI Tool")}
  {tool_html}
</div>

<!-- 주요 일정 -->
<div style="{_S}">
  {section_header("📅 이번 주 주요 일정", "Calendar")}
  {sched_html}
</div>

<!-- Subscribe CTA -->
<div style="padding:28px 40px;background:#1A1040;text-align:center;border-bottom:1px solid #0E0830;">
  <div style="{_F}font-size:16px;font-weight:700;color:#F0EDE4;margin-bottom:6px;">👓 또롱이 뉴스레터 구독하기</div>
  <div style="{_F}font-size:12.5px;color:#8A7FAA;margin-bottom:18px;line-height:1.7;font-weight:300;">매일 오전 7시, AI·기술·경제 핵심 뉴스를<br>깔끔하게 정리해서 보내드립니다.</div>
  <a href="mailto:{GMAIL_ADDRESS}?subject=또롱이 뉴스레터 구독 신청&body=안녕하세요! 구독 신청합니다."
     style="{_F}display:inline-block;background:#E8682A;color:#fff;font-size:13px;font-weight:700;padding:12px 32px;border-radius:6px;text-decoration:none;">구독 신청하기 →</a>
</div>

<!-- Footer -->
<div style="background:#1A1040;padding:22px 40px;text-align:center;">
  <p style="{_F}font-size:11px;color:#5A5078;line-height:2;">또롱이 뉴스레터 · Powered by Claude AI<br>
  수신 거부: <a href="mailto:{GMAIL_ADDRESS}?subject=또롱이 뉴스레터 수신 거부"
               style="color:#7B6FAA;text-decoration:none;">여기로 메일 주세요</a></p>
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
