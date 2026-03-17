"""
또롱이 뉴스레터
매일 아침 AI/경제 뉴스를 수집 → Claude 요약 → 구독자 전체 발송
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
# 설정 (GitHub Secrets에서 자동으로 불러옴)
# ─────────────────────────────────────────
ANTHROPIC_API_KEY  = os.environ["ANTHROPIC_API_KEY"]
GMAIL_ADDRESS      = os.environ["GMAIL_ADDRESS"]        # 발송용 Gmail 주소
GMAIL_APP_PASSWORD = os.environ["GMAIL_APP_PASSWORD"]   # Gmail 앱 비밀번호

# ─────────────────────────────────────────
# 뉴스 소스 RSS 목록
# ─────────────────────────────────────────
RSS_FEEDS = [
    {
        "name": "구글뉴스 AI",
        "url": "https://news.google.com/rss/search?q=인공지능+AI&hl=ko&gl=KR&ceid=KR:ko",
        "lang": "ko"
    },
    {
        "name": "구글뉴스 경제",
        "url": "https://news.google.com/rss/search?q=경제+주식+금융&hl=ko&gl=KR&ceid=KR:ko",
        "lang": "ko"
    },
    {
        "name": "TechCrunch AI",
        "url": "https://techcrunch.com/category/artificial-intelligence/feed/",
        "lang": "en"
    },
    {
        "name": "Wired AI",
        "url": "https://www.wired.com/feed/tag/ai/latest/rss",
        "lang": "en"
    },
]

KST   = timezone(timedelta(hours=9))
TODAY = datetime.now(KST).strftime("%Y년 %m월 %d일")
DOW   = ["월", "화", "수", "목", "금", "토", "일"][datetime.now(KST).weekday()]


# ─────────────────────────────────────────
# 구독자 목록 로드
# subscribers.txt — 한 줄에 이메일 하나
# # 으로 시작하는 줄은 주석 처리
# ─────────────────────────────────────────
def load_subscribers() -> list[str]:
    path = Path("subscribers.txt")
    if not path.exists():
        print("[경고] subscribers.txt 없음. RECIPIENT_EMAIL 환경변수로 대체.")
        fallback = os.environ.get("RECIPIENT_EMAIL", "")
        return [fallback] if fallback else []

    emails = []
    for line in path.read_text(encoding="utf-8").splitlines():
        email = line.strip()
        if email and "@" in email and not email.startswith("#"):
            emails.append(email)
    return emails


# ─────────────────────────────────────────
# RSS 수집
# ─────────────────────────────────────────
def fetch_articles(feed: dict, max_items: int = 5) -> list[dict]:
    try:
        parsed = feedparser.parse(feed["url"])
        articles = []
        for entry in parsed.entries[:max_items]:
            articles.append({
                "title":   entry.get("title", ""),
                "link":    entry.get("link", ""),
                "summary": entry.get("summary", "")[:300],
                "lang":    feed["lang"],
                "source":  feed["name"],
            })
        return articles
    except Exception as e:
        print(f"[RSS 오류] {feed['name']}: {e}")
        return []


# ─────────────────────────────────────────
# Claude 요약
# ─────────────────────────────────────────
def summarize_with_claude(articles: list[dict]) -> dict:
    client = anthropic.Anthropic(api_key=ANTHROPIC_API_KEY)

    articles_text = ""
    for i, a in enumerate(articles, 1):
        lang_note = "(영어 기사 - 한국어 번역 필요)" if a["lang"] == "en" else ""
        articles_text += f"""
[{i}] [{a['source']}] {lang_note}
제목: {a['title']}
링크: {a['link']}
내용: {a['summary']}
---"""

    prompt = f"""당신은 '또롱이 뉴스레터'의 AI·경제 전문 에디터입니다.
아래 뉴스 기사들을 읽고 오늘의 뉴스레터 콘텐츠를 작성해주세요.

오늘 날짜: {TODAY} ({DOW}요일)

[기사 목록]
{articles_text}

[작성 규칙]
1. 영어 기사는 반드시 한국어로 번역 후 요약
2. 각 기사는 2~3줄로 핵심만 요약, 중요 수치·키워드 강조
3. AI/기술 섹션과 경제/금융 섹션으로 구분
4. 오늘의 핵심 뉴스 TOP 3 선정 (가장 파급력 큰 뉴스 순)
5. morning_briefs: 간결한 불릿 포인트 4~5개 (순모닝 섹션용)
6. 이번 주 주요 일정 3~5개 (날짜·이벤트명·간단설명)
7. deep_dive_title: 오늘의 심층 분석 주제 제목
8. deep_dive_bullets: 심층 분석 내용 불릿 3~4개
9. editor_note: 오늘 뉴스의 흐름을 2~3줄로 요약한 에디터 한마디
10. killer_chart_title: 오늘 데이터로 만들 차트 제목
11. killer_chart_data: 차트에 쓸 레이블·수치·색상 배열 (최대 6개)

아래 JSON 형식으로만 응답 (마크다운 코드블록 없이):
{{
  "morning_briefs": [
    {{"bold": "굵은 제목", "text": "나머지 설명", "highlight": "강조할 숫자나 키워드(없으면 null)"}}
  ],
  "deep_dive_title": "심층 분석 제목",
  "deep_dive_bullets": [
    {{"bold": "소제목", "text": "설명 2~3줄", "highlight": "강조 키워드(없으면 null)"}}
  ],
  "top3": [
    {{"rank": 1, "title": "제목", "summary": "2~3줄 요약", "link": "URL", "source": "출처"}},
    {{"rank": 2, "title": "제목", "summary": "2~3줄 요약", "link": "URL", "source": "출처"}},
    {{"rank": 3, "title": "제목", "summary": "2~3줄 요약", "link": "URL", "source": "출처"}}
  ],
  "ai_tech": [
    {{"title": "제목", "summary": "요약", "link": "URL", "source": "출처"}}
  ],
  "economy": [
    {{"title": "제목", "summary": "요약", "link": "URL", "source": "출처"}}
  ],
  "schedule": [
    {{"date": "3/17(화)", "label": "이벤트명", "key": true}},
    {{"date": "3/18(수)", "label": "이벤트명", "key": false}}
  ],
  "killer_chart_title": "차트 제목",
  "killer_chart_data": [
    {{"label": "항목명", "value": 8.2, "color": "#D4A847"}},
    {{"label": "항목명", "value": -2.1, "color": "#B0AEA6"}}
  ],
  "killer_chart_caption": "차트 아래 설명 2~3줄",
  "editor_note": "에디터 한마디 2~3줄"
}}"""

    message = client.messages.create(
        model="claude-sonnet-4-20250514",
        max_tokens=4000,
        messages=[{"role": "user", "content": prompt}]
    )

    raw = message.content[0].text.strip()
    return json.loads(raw)


# ─────────────────────────────────────────
# HTML 뉴스레터 생성 (또롱이 디자인)
# ─────────────────────────────────────────
def build_html(data: dict) -> str:

    def render_briefs(items):
        html = ""
        for b in items:
            hi = f'<span style="color:#C0392B;font-weight:500">{b["highlight"]}</span>' if b.get("highlight") else ""
            text = b["text"].replace(b.get("highlight") or "\x00", hi) if hi else b["text"]
            html += (
                '<div style="display:flex;gap:10px;margin-bottom:14px">'
                '<div style="flex-shrink:0;width:5px;height:5px;border-radius:50%;background:#D4A847;margin-top:8px"></div>'
                f'<div style="font-size:13.5px;line-height:1.75;color:#2A2825">'
                f'<strong style="font-weight:500">{b["bold"]}</strong> — {text}'
                '</div></div>'
            )
        return html

    def render_deep(items):
        html = ""
        for b in items:
            hi = f'<span style="color:#C0392B;font-weight:500">{b["highlight"]}</span>' if b.get("highlight") else ""
            text = b["text"].replace(b.get("highlight") or "\x00", hi) if hi else b["text"]
            html += (
                '<div style="display:flex;gap:10px;margin-bottom:14px">'
                '<div style="flex-shrink:0;width:5px;height:5px;border-radius:50%;background:#D4A847;margin-top:8px"></div>'
                f'<div style="font-size:13.5px;line-height:1.75;color:#2A2825">'
                f'<strong style="font-weight:500">{b["bold"]}</strong> {text}'
                '</div></div>'
            )
        return html

    def render_top3(items):
        medals = ["🥇", "🥈", "🥉"]
        html = ""
        for idx, item in enumerate(items):
            medal = medals[idx] if idx < 3 else "📌"
            sep = "" if idx == len(items) - 1 else "border-bottom:1px solid #ECEAE5;"
            html += (
                f'<div style="display:flex;gap:14px;margin-bottom:20px;padding-bottom:20px;{sep}">'
                f'<div style="font-size:22px;flex-shrink:0;padding-top:2px">{medal}</div>'
                f'<div>'
                f'<a href="{item["link"]}" style="display:block;font-size:14px;font-weight:700;color:#1A1916;text-decoration:none;line-height:1.5;margin-bottom:4px">{item["title"]}</a>'
                f'<span style="display:inline-block;font-size:10px;letter-spacing:1px;background:#ECEAE5;color:#8A8780;padding:2px 8px;border-radius:3px;text-transform:uppercase">{item["source"]}</span>'
                f'<p style="font-size:13px;color:#5A5754;line-height:1.7;margin-top:6px">{item["summary"]}</p>'
                f'</div></div>'
            )
        return html

    def render_articles(items):
        html = ""
        for idx, item in enumerate(items):
            sep = "" if idx == len(items) - 1 else "border-bottom:1px solid #ECEAE5;"
            html += (
                f'<div style="margin-bottom:18px;padding-bottom:18px;{sep}">'
                f'<a href="{item["link"]}" style="display:block;font-size:14px;font-weight:500;color:#1A1916;text-decoration:none;line-height:1.5;margin-bottom:4px">{item["title"]}</a>'
                f'<span style="display:inline-block;font-size:9px;letter-spacing:1px;background:#ECEAE5;color:#8A8780;padding:2px 8px;border-radius:3px;text-transform:uppercase">{item["source"]}</span>'
                f'<p style="font-size:12.5px;color:#6A6764;line-height:1.7;margin-top:5px">{item["summary"]}</p>'
                f'</div>'
            )
        return html

    def render_schedule(items):
        html = ""
        for idx, item in enumerate(items):
            sep = "" if idx == len(items) - 1 else "border-bottom:1px solid #ECEAE5;"
            star = '<span style="color:#D4A847;margin-right:3px">★</span>' if item.get("key") else ""
            bold = "font-weight:500" if item.get("key") else ""
            html += (
                f'<div style="display:flex;gap:12px;padding:8px 0;{sep}font-size:13px;align-items:flex-start">'
                f'<div style="flex-shrink:0;width:90px;font-weight:500;color:#8A8780">{item["date"]}</div>'
                f'<div style="color:#2A2825;line-height:1.6;{bold}">{star}{item["label"]}</div>'
                f'</div>'
            )
        return html

    def render_chart(title, chart_data, caption):
        labels_js = json.dumps([d["label"] for d in chart_data], ensure_ascii=False)
        values_js = json.dumps([d["value"] for d in chart_data])
        colors_js = json.dumps([d.get("color", "#B0AEA6") for d in chart_data])
        legend_html = "".join(
            f'<span style="display:inline-flex;align-items:center;gap:4px;font-size:11px;color:#8A8780;margin-right:10px">'
            f'<span style="width:10px;height:10px;border-radius:2px;background:{d.get("color","#B0AEA6")}"></span>'
            f'{d["label"]}</span>'
            for d in chart_data
        )
        return (
            f'<div style="background:#F7F5F0;border-radius:6px;padding:10px 12px 8px;margin-bottom:12px">'
            f'<div style="display:flex;align-items:center;gap:8px;margin-bottom:8px">'
            f'<span style="background:#E8B84B;color:#6B4800;font-size:10px;font-weight:500;padding:3px 8px;border-radius:4px;letter-spacing:1px;text-transform:uppercase">Killer Chart</span>'
            f'<span style="font-size:13px;font-weight:500;color:#1A1916">{title}</span></div>'
            f'<div style="flex-wrap:wrap;margin-bottom:6px">{legend_html}</div></div>'
            f'<div style="position:relative;width:100%;height:220px">'
            f'<canvas id="klChart"></canvas></div>'
            f'<script src="https://cdnjs.cloudflare.com/ajax/libs/Chart.js/4.4.1/chart.umd.js"></script>'
            f'<script>(function(){{'
            f'var l={labels_js};var v={values_js};var c={colors_js};'
            f'new Chart(document.getElementById("klChart"),{{'
            f'type:"bar",'
            f'data:{{labels:l,datasets:[{{data:v,backgroundColor:c,borderRadius:4,barThickness:38}}]}},'
            f'options:{{responsive:true,maintainAspectRatio:false,'
            f'plugins:{{legend:{{display:false}},tooltip:{{callbacks:{{label:function(x){{return(x.raw>0?"+":"")+x.raw+"%"}}}}}}}},'
            f'scales:{{x:{{grid:{{display:false}},border:{{display:false}},ticks:{{color:"#8A8780",font:{{size:11}}}}}},'
            f'y:{{grid:{{color:"rgba(0,0,0,0.06)"}},border:{{display:false}},ticks:{{color:"#8A8780",font:{{size:11}},callback:function(v){{return(v>0?"+":"")+v+"%"}}}}}}}},'
            f'animation:{{duration:0}}}},'
            f'plugins:[{{afterDatasetsDraw:function(ch){{'
            f'var ctx=ch.ctx;'
            f'ch.data.datasets[0].data.forEach(function(val,i){{'
            f'var m=ch.getDatasetMeta(0);var b=m.data[i];'
            f'var y=val>=0?b.y-5:b.y+13;'
            f'ctx.save();ctx.fillStyle="#2A2825";ctx.font="500 11px sans-serif";ctx.textAlign="center";'
            f'ctx.fillText((val>0?"+":"")+val+"%",b.x,y);ctx.restore();'
            f'}})}}}}]}});}})();</script>'
            f'<p style="font-size:12px;color:#6A6764;line-height:1.75;margin-top:12px;padding-top:10px;border-top:1px solid #ECEAE5">{caption}</p>'
        )

    briefs_html = render_briefs(data.get("morning_briefs", []))
    deep_html   = render_deep(data.get("deep_dive_bullets", []))
    top3_html   = render_top3(data.get("top3", []))
    ai_html     = render_articles(data.get("ai_tech", []))
    econ_html   = render_articles(data.get("economy", []))
    sched_html  = render_schedule(data.get("schedule", []))
    chart_html  = render_chart(
                      data.get("killer_chart_title", "오늘의 차트"),
                      data.get("killer_chart_data", []),
                      data.get("killer_chart_caption", "")
                  )
    editor_note = data.get("editor_note", "")
    dive_title  = data.get("deep_dive_title", "오늘의 심층 분석")
    github_repo = os.environ.get("GITHUB_REPOSITORY", "your/ai-newsletter")

    return f"""<!DOCTYPE html>
<html lang="ko">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width,initial-scale=1.0">
<title>또롱이 뉴스레터 — {TODAY}</title>
<style>
@import url('https://fonts.googleapis.com/css2?family=Noto+Serif+KR:wght@400;700&family=Noto+Sans+KR:wght@300;400;500;700&display=swap');
*{{margin:0;padding:0;box-sizing:border-box}}
body{{background:#F5F3EE;font-family:'Noto Sans KR',sans-serif;color:#2A2825}}
.wrap{{max-width:620px;margin:0 auto;background:#FAFAF8}}
</style>
</head>
<body>
<div class="wrap">

<div style="background:#111;padding:32px 36px 26px">
  <div style="font-size:10px;letter-spacing:3px;text-transform:uppercase;color:#555;margin-bottom:8px">Daily Briefing · AI &amp; Economy</div>
  <div style="width:28px;height:3px;background:#D4A847;margin-bottom:12px"></div>
  <div style="font-family:'Noto Serif KR',serif;font-size:28px;font-weight:700;color:#F5F5F0;line-height:1.2;margin-bottom:6px">또롱이 뉴스레터</div>
  <div style="font-size:12px;color:#666;font-weight:300">{TODAY} ({DOW}요일) · AI·기술·경제 핵심 뉴스</div>
</div>

<div style="background:#1E1C1A;padding:18px 36px;border-left:3px solid #D4A847">
  <div style="font-size:10px;letter-spacing:2px;color:#D4A847;text-transform:uppercase;margin-bottom:6px">Editor's Note</div>
  <p style="font-size:13px;color:#B8B5AF;line-height:1.8;font-weight:300">{editor_note}</p>
</div>

<div style="padding:28px 36px;border-bottom:1px solid #ECEAE5">
  <div style="font-size:10px;letter-spacing:2.5px;text-transform:uppercase;color:#8A8780;margin-bottom:4px">Morning Brief</div>
  <div style="font-family:'Noto Serif KR',serif;font-size:18px;font-weight:700;color:#1A1916;margin-bottom:18px;padding-bottom:12px;border-bottom:1px solid #ECEAE5">☀ 순모닝! 우리가 잠든 사이 무슨 일들이?</div>
  {briefs_html}
</div>

<div style="padding:28px 36px;border-bottom:1px solid #ECEAE5">
  <div style="font-size:10px;letter-spacing:2.5px;text-transform:uppercase;color:#8A8780;margin-bottom:4px">Deep Dive</div>
  <div style="font-family:'Noto Serif KR',serif;font-size:18px;font-weight:700;color:#1A1916;margin-bottom:18px;padding-bottom:12px;border-bottom:1px solid #ECEAE5">{dive_title}</div>
  {deep_html}
</div>

<div style="padding:28px 36px;border-bottom:1px solid #ECEAE5">
  {chart_html}
</div>

<div style="padding:28px 36px;border-bottom:1px solid #ECEAE5">
  <div style="font-size:10px;letter-spacing:2.5px;text-transform:uppercase;color:#8A8780;margin-bottom:4px">Top Stories</div>
  <div style="font-family:'Noto Serif KR',serif;font-size:18px;font-weight:700;color:#1A1916;margin-bottom:18px;padding-bottom:12px;border-bottom:1px solid #ECEAE5">오늘의 핵심 뉴스 3</div>
  {top3_html}
</div>

<div style="padding:28px 36px;border-bottom:1px solid #ECEAE5">
  <div style="font-size:10px;letter-spacing:2.5px;text-transform:uppercase;color:#8A8780;margin-bottom:4px">Technology</div>
  <div style="font-family:'Noto Serif KR',serif;font-size:18px;font-weight:700;color:#1A1916;margin-bottom:18px;padding-bottom:12px;border-bottom:1px solid #ECEAE5">🤖 AI &amp; 기술</div>
  {ai_html}
</div>

<div style="padding:28px 36px;border-bottom:1px solid #ECEAE5">
  <div style="font-size:10px;letter-spacing:2.5px;text-transform:uppercase;color:#8A8780;margin-bottom:4px">Economy</div>
  <div style="font-family:'Noto Serif KR',serif;font-size:18px;font-weight:700;color:#1A1916;margin-bottom:18px;padding-bottom:12px;border-bottom:1px solid #ECEAE5">📈 경제 &amp; 금융</div>
  {econ_html}
</div>

<div style="padding:28px 36px;border-bottom:1px solid #ECEAE5">
  <div style="font-size:10px;letter-spacing:2.5px;text-transform:uppercase;color:#8A8780;margin-bottom:4px">Calendar</div>
  <div style="font-family:'Noto Serif KR',serif;font-size:18px;font-weight:700;color:#1A1916;margin-bottom:18px;padding-bottom:12px;border-bottom:1px solid #ECEAE5">📅 이번 주 주요 일정</div>
  {sched_html}
</div>

<div style="background:#111;padding:24px 36px;text-align:center">
  <p style="font-size:11px;color:#555;line-height:2.0">
    또롱이 뉴스레터 · Powered by Claude AI<br>
    구독 신청은 <a href="mailto:{GMAIL_ADDRESS}?subject=또롱이 뉴스레터 구독 신청&body=안녕하세요! 구독 신청합니다." style="color:#888;text-decoration:none">이메일로 신청</a>
    &nbsp;·&nbsp;
    수신 거부는 <a href="mailto:{GMAIL_ADDRESS}?subject=또롱이 뉴스레터 수신 거부" style="color:#888;text-decoration:none">여기</a>
  </p>
</div>

</div>
</body>
</html>"""


# ─────────────────────────────────────────
# 이메일 발송 (구독자 전체)
# ─────────────────────────────────────────
def send_to_all(html_content: str, subscribers: list[str]):
    subject = f"📰 또롱이 뉴스레터 — {TODAY} ({DOW}요일)"

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
                print(f"  [✓] 발송 완료 → {email}")
            except Exception as e:
                print(f"  [✗] 발송 실패 → {email}: {e}")


# ─────────────────────────────────────────
# 메인
# ─────────────────────────────────────────
def main():
    print(f"[시작] {TODAY} 또롱이 뉴스레터 생성 중...")

    subscribers = load_subscribers()
    if not subscribers:
        print("[오류] 구독자가 없습니다. subscribers.txt를 확인하세요.")
        return
    print(f"[구독자] {len(subscribers)}명: {', '.join(subscribers)}")

    all_articles = []
    for feed in RSS_FEEDS:
        articles = fetch_articles(feed, max_items=5)
        all_articles.extend(articles)
        print(f"  [{feed['name']}] {len(articles)}개 수집")

    if not all_articles:
        print("[오류] 수집된 기사가 없습니다.")
        return
    print(f"[수집 완료] 총 {len(all_articles)}개 기사")

    print("[Claude] 요약 및 번역 중...")
    data = summarize_with_claude(all_articles)

    html = build_html(data)

    print(f"[발송] {len(subscribers)}명에게 발송 중...")
    send_to_all(html, subscribers)
    print("[완료] 또롱이 뉴스레터 발송 완료!")


if __name__ == "__main__":
    main()
