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
# HTML 빌드 (네이버 메일 호환 — table 레이아웃 + bgcolor 속성)
# ─────────────────────────────────────────
_F = "font-family:'Noto Sans KR',sans-serif;"

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
        """섹션 제목 + eyebrow 태그 (table 2열)"""
        return (
            f'<table width="100%" cellpadding="0" cellspacing="0">'
            f'<tr>'
            f'<td style="{_F}font-size:17px;font-weight:700;color:#1A1040;'
            f'padding-bottom:14px;border-bottom:2px solid #D0CCC0;line-height:1.3;">'
            f'{title}</td>'
            f'<td align="right" valign="top" style="padding-bottom:14px;'
            f'border-bottom:2px solid #D0CCC0;white-space:nowrap;padding-left:12px;">'
            f'<span style="{_F}font-size:10px;text-transform:uppercase;color:#7B6FAA;'
            f'border:1px solid #B8B0D0;padding:2px 8px;">{eyebrow}</span>'
            f'</td>'
            f'</tr>'
            f'</table>'
            f'<table width="100%" cellpadding="0" cellspacing="0">'
            f'<tr><td height="20"></td></tr>'
            f'</table>'
        )

    def render_briefs(items):
        html = ""
        for i, b in enumerate(items):
            text = hl(b.get("text", ""), b.get("highlight"))
            pb = "0" if i == len(items) - 1 else "18px"
            html += (
                f'<table width="100%" cellpadding="0" cellspacing="0">'
                f'<tr>'
                f'<td width="18" valign="top" style="padding-top:5px;padding-bottom:{pb};'
                f'font-size:14px;color:#5B3FA0;line-height:1;">&#9679;</td>'
                f'<td valign="top" style="{_F}font-size:13.5px;line-height:1.85;'
                f'color:#2A2540;padding-bottom:{pb};">'
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

        # 레이블 + 제목
        html = (
            f'<table width="100%" cellpadding="0" cellspacing="0">'
            f'<tr><td style="padding-bottom:8px;">'
            f'<span style="{_F}font-size:10px;letter-spacing:1.5px;background-color:#EDE8F8;'
            f'color:#5B3FA0;padding:3px 10px;text-transform:uppercase;">{DIVE_EYEBROW}</span>'
            f'</td></tr>'
            f'<tr><td style="{_F}font-size:18px;font-weight:700;color:#1A1040;'
            f'line-height:1.35;padding-bottom:14px;">{subject}</td></tr>'
            f'</table>'
        )
        # 큰따옴표 + 인트로 (table 2열로 구현)
        html += (
            f'<table width="100%" cellpadding="0" cellspacing="0">'
            f'<tr>'
            f'<td width="24" valign="top" style="{_F}font-size:28px;color:#5B3FA0;'
            f'font-weight:700;line-height:1;padding-bottom:20px;">\u201C</td>'
            f'<td valign="top" style="{_F}font-size:13.5px;color:#4A4460;'
            f'line-height:1.85;padding-bottom:20px;">{intro}</td>'
            f'</tr>'
            f'</table>'
        )
        for i, b in enumerate(bullets):
            body = hl(b.get("body", ""), b.get("highlight"))
            pb = "0" if i == len(bullets) - 1 else "16px"
            html += (
                f'<table width="100%" cellpadding="0" cellspacing="0">'
                f'<tr>'
                f'<td width="18" valign="top" style="padding-top:5px;padding-bottom:{pb};'
                f'font-size:12px;color:#5B3FA0;line-height:1;">&#9632;</td>'
                f'<td valign="top" style="{_F}font-size:13.5px;line-height:1.85;'
                f'color:#2A2540;padding-bottom:{pb};">'
                f'<strong style="font-weight:700;color:#1A1040;">{b["head"]}</strong>'
                f' {body}'
                f'</td>'
                f'</tr>'
                f'</table>'
            )
        return html

    def render_bigtech(items):
        if not items:
            return f'<p style="margin:0;{_F}font-size:13px;color:#8A8780;">오늘 주요 지수 데이터가 없습니다.</p>'
        thead = (
            f'<tr>'
            f'<th align="left" style="{_F}font-size:10px;letter-spacing:1.5px;color:#9994A8;'
            f'text-transform:uppercase;font-weight:400;padding:0 0 10px;'
            f'border-bottom:1px solid #D0CCC0;">종목/지수</th>'
            f'<th align="right" style="{_F}font-size:10px;letter-spacing:1.5px;color:#9994A8;'
            f'text-transform:uppercase;font-weight:400;padding:0 0 10px;'
            f'border-bottom:1px solid #D0CCC0;">현재가</th>'
            f'<th align="right" style="{_F}font-size:10px;letter-spacing:1.5px;color:#9994A8;'
            f'text-transform:uppercase;font-weight:400;padding:0 0 10px;'
            f'border-bottom:1px solid #D0CCC0;">등락</th>'
            f'</tr>'
        )
        tbody = ""
        for i, item in enumerate(items):
            is_up = item.get("up", True)
            arrow = "▲" if is_up else "▼"
            c_chg = "#1A7A4A" if is_up else "#C0392B"
            bd    = "none" if i == len(items) - 1 else "1px solid #E8E5DC"
            tbody += (
                f'<tr>'
                f'<td style="{_F}padding:9px 0;border-bottom:{bd};color:#2A2540;" valign="middle">'
                f'<span style="font-weight:500;color:#1A1040;">{item["name"]}'
                f'&nbsp;<span style="font-size:11px;color:#9994A8;">{item.get("ticker","")}</span></span>'
                f'<br><span style="{_F}font-size:11.5px;color:#8A8098;">{item["reason"]}</span>'
                f'</td>'
                f'<td align="right" valign="middle" style="{_F}padding:9px 0;border-bottom:{bd};'
                f'font-weight:400;color:#4A4460;">{item.get("price","—")}</td>'
                f'<td align="right" valign="middle" style="padding:9px 0;border-bottom:{bd};">'
                f'<span style="{_F}color:{c_chg};font-weight:500;">{arrow}&nbsp;{item["change"]}</span>'
                f'</td>'
                f'</tr>'
            )
        return (
            f'<table width="100%" cellpadding="0" cellspacing="0" style="font-size:13px;">'
            f'<thead>{thead}</thead><tbody>{tbody}</tbody></table>'
        )

    def render_startups(items):
        html = ""
        for i, s in enumerate(items):
            is_last = i == len(items) - 1
            bd = "none" if is_last else "1px solid #E8E5DC"
            pb = "0" if is_last else "14px"
            html += (
                f'<table width="100%" cellpadding="0" cellspacing="0">'
                f'<tr>'
                f'<td style="padding-bottom:5px;border-bottom:{bd};padding-top:14px;" colspan="2">'
                f'<span style="{_F}font-size:14px;font-weight:700;color:#1A1040;">{s["name"]}</span>'
                f'&nbsp;&nbsp;'
                f'<span style="{_F}font-size:11px;background-color:#EDE8F8;color:#5B3FA0;padding:2px 8px;">'
                f'{s.get("amount","")}</span>'
                f'</td>'
                f'</tr>'
                f'<tr>'
                f'<td style="{_F}font-size:13px;color:#4A4460;line-height:1.8;'
                f'padding-bottom:{pb};border-bottom:{bd};">{s["summary"]}</td>'
                f'</tr>'
                f'</table>'
            )
        return html

    def render_tool(tool):
        if not tool:
            return ""
        return (
            f'<table width="100%" cellpadding="0" cellspacing="0">'
            f'<tr>'
            f'<td bgcolor="#EDEBFF" style="padding:20px 24px;border-left:4px solid #5B3FA0;">'
            f'<p style="margin:0 0 10px;">'
            f'<span style="{_F}font-size:16px;font-weight:700;color:#1A1040;">{tool["name"]}</span>'
            f'&nbsp;&nbsp;'
            f'<span style="{_F}font-size:11px;color:#7B6FAA;font-weight:300;">{tool.get("tagline","")}</span>'
            f'</p>'
            f'<p style="margin:0 0 8px;{_F}font-size:13.5px;color:#2A2540;line-height:1.85;">'
            f'<strong style="font-weight:600;color:#5B3FA0;">무엇인가</strong>&nbsp;{tool.get("what","")}</p>'
            f'<p style="margin:0 0 8px;{_F}font-size:13.5px;color:#2A2540;line-height:1.85;">'
            f'<strong style="font-weight:600;color:#5B3FA0;">왜 주목받나</strong>&nbsp;{tool.get("why","")}</p>'
            f'<a href="{tool.get("link","#")}" style="{_F}font-size:12px;color:#E8682A;'
            f'text-decoration:none;font-weight:500;">자세히 보기 →</a>'
            f'</td>'
            f'</tr>'
            f'</table>'
        )

    def render_schedule(items):
        html = ""
        for i, item in enumerate(items):
            is_last = i == len(items) - 1
            bd = "none" if is_last else "1px solid #E8E5DC"
            pb = "0" if is_last else "9px"
            star = '<span style="color:#5B3FA0;">★&nbsp;</span>' if item.get("key") else ""
            lbl_w = f"font-weight:700;color:#1A1040;" if item.get("key") else "color:#2A2540;"
            html += (
                f'<table width="100%" cellpadding="0" cellspacing="0">'
                f'<tr>'
                f'<td width="88" valign="top" style="{_F}color:#9994A8;font-weight:500;'
                f'font-size:12.5px;padding:9px 0 {pb};border-bottom:{bd};">{item["date"]}</td>'
                f'<td valign="top" style="{_F}font-size:13px;{lbl_w}'
                f'line-height:1.6;padding:9px 0 {pb};border-bottom:{bd};">'
                f'{star}{item["label"]}</td>'
                f'</tr>'
                f'</table>'
            )
        return html

    one_liner    = data.get("one_liner", "")
    briefs_html  = render_briefs(data.get("morning_briefs", []))
    dive_html    = render_dive(data.get("deep_dive", {}))
    bigtech_html = render_bigtech(data.get("bigtech", []))
    startup_html = render_startups(data.get("startups", []))
    tool_html    = render_tool(data.get("ai_tool"))
    sched_html   = render_schedule(data.get("schedule", []))

    # 섹션 구분선 행 (8px 딥퍼플 띠)
    SEP = '<tr><td height="8" bgcolor="#E0DDD4" style="font-size:0;line-height:0;">&nbsp;</td></tr>'

    return f"""<!DOCTYPE html>
<html lang="ko">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width,initial-scale=1.0">
<title>또롱이 뉴스레터 — {TODAY}</title>
<link href="https://fonts.googleapis.com/css2?family=Noto+Sans+KR:wght@300;400;500;700&display=swap" rel="stylesheet">
</head>
<body bgcolor="#ffffff" style="margin:0;padding:0;{_F}">
<table width="100%" bgcolor="#ffffff" cellpadding="0" cellspacing="0" border="0">
<tr><td align="center" style="padding:20px 0;">

<table width="620" cellpadding="0" cellspacing="0" border="0" style="border:1px solid #D8D5CB;">

<!-- 헤더 -->
<tr><td bgcolor="#1A1040" style="padding:28px 40px 45px;">
  <table width="100%" cellpadding="0" cellspacing="0">
    <tr>
      <td style="{_F}font-size:11px;letter-spacing:2px;color:#7B6FAA;text-transform:uppercase;">Daily Briefing · AI &amp; Economy</td>
      <td align="right" style="{_F}font-size:11px;color:#C4BAE8;font-weight:300;letter-spacing:0.5px;">{TODAY} {DOW_SHORT}</td>
    </tr>
  </table>
  <table cellpadding="0" cellspacing="0" style="margin-top:14px;margin-bottom:6px;">
    <tr>
      <td style="font-size:24px;line-height:1;">👓</td>
      <td style="{_F}padding-left:10px;font-size:26px;font-weight:700;color:#F0EDE4;letter-spacing:-0.5px;">또롱이 뉴스레터</td>
    </tr>
  </table>
  <p style="margin:2px 0 0;{_F}font-size:12px;color:#E8682A;font-weight:400;">AI · 기술 · 경제 핵심 뉴스</p>
</td></tr>

<!-- One-liner -->
<tr><td bgcolor="#E8682A" style="padding:18px 40px 20px;">
  <p style="margin:0 0 6px;{_F}font-size:10px;letter-spacing:2px;color:#FFD4B8;text-transform:uppercase;">Today's One-liner</p>
  <p style="margin:0;{_F}font-size:14.5px;color:#FFF8F5;line-height:1.75;font-weight:500;">{one_liner}</p>
</td></tr>

<!-- 또모닝 브리핑 (첫 섹션 — 구분선 없음) -->
<tr><td bgcolor="#F5F3EC" style="padding:43px 40px 32px;">
  {section_header("☀ 또모닝 브리핑", "Morning Brief")}
  {briefs_html}
</td></tr>

<!-- 딥다이브 -->
{SEP}
<tr><td bgcolor="#F8F6FF" style="padding:43px 40px 32px;">
  {section_header(DIVE_LABEL, "Deep Dive")}
  {dive_html}
</td></tr>

<!-- 빅테크 & 주요 지수 -->
{SEP}
<tr><td bgcolor="#F5F3EC" style="padding:43px 40px 32px;">
  {section_header("📊 빅테크 &amp; 주요 지수", "Markets")}
  {bigtech_html}
</td></tr>

<!-- AI 스타트업 -->
{SEP}
<tr><td bgcolor="#F5F3EC" style="padding:43px 40px 32px;">
  {section_header("🚀 AI 스타트업 레이더", "Startup Radar")}
  {startup_html}
</td></tr>

<!-- AI 툴 -->
{SEP}
<tr><td bgcolor="#F5F3EC" style="padding:43px 40px 32px;">
  {section_header("🛠 오늘의 AI 툴", "AI Tool")}
  {tool_html}
</td></tr>

<!-- 주요 일정 -->
{SEP}
<tr><td bgcolor="#F5F3EC" style="padding:43px 40px 32px;">
  {section_header("📅 이번 주 주요 일정", "Calendar")}
  {sched_html}
</td></tr>

<!-- Subscribe CTA -->
<tr><td bgcolor="#1A1040" style="padding:28px 40px;text-align:center;border-bottom:1px solid #0E0830;">
  <p style="margin:0 0 6px;{_F}font-size:16px;font-weight:700;color:#F0EDE4;">👓 또롱이 뉴스레터 구독하기</p>
  <p style="margin:0 0 18px;{_F}font-size:12.5px;color:#8A7FAA;line-height:1.7;font-weight:300;">매일 오전 7시, AI·기술·경제 핵심 뉴스를<br>깔끔하게 정리해서 보내드립니다.</p>
  <table width="100%" cellpadding="0" cellspacing="0">
    <tr>
      <td align="center">
        <table cellpadding="0" cellspacing="0">
          <tr>
            <td bgcolor="#E8682A" style="padding:12px 32px;">
              <a href="mailto:{GMAIL_ADDRESS}?subject=또롱이 뉴스레터 구독 신청&body=안녕하세요! 구독 신청합니다."
                 style="{_F}font-size:13px;font-weight:700;color:#ffffff;text-decoration:none;">구독 신청하기 →</a>
            </td>
          </tr>
        </table>
      </td>
    </tr>
  </table>
</td></tr>

<!-- 푸터 -->
<tr><td bgcolor="#1A1040" style="padding:22px 40px;text-align:center;">
  <p style="margin:0;{_F}font-size:11px;color:#5A5078;line-height:2;">또롱이 뉴스레터 · Powered by Claude AI<br>
  수신 거부:&nbsp;<a href="mailto:{GMAIL_ADDRESS}?subject=또롱이 뉴스레터 수신 거부"
    style="color:#7B6FAA;text-decoration:none;">여기로 메일 주세요</a></p>
</td></tr>

</table>
</td></tr>
</table>
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
