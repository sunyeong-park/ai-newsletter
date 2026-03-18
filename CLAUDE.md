# 또롱이 뉴스레터 프로젝트

## 개요
매일 오전 7시(KST) AI/경제 뉴스 자동 수집 → Claude API 요약 → 구독자 전체 이메일 발송
월~금만 발송, 주말 없음.

## 저장소
- GitHub: https://github.com/sunyeong-park/ai-newsletter
- 브랜치: main
- 실행: GitHub Actions (Ubuntu)

## 파일 구조
```
ai-newsletter/
├── newsletter.py        # 핵심 코드 (v2 완성본)
├── subscribers.txt      # 구독자 이메일 목록 (한 줄에 하나)
├── requirements.txt     # feedparser, anthropic
├── CLAUDE.md            # 이 파일
└── .github/workflows/
    └── daily.yml        # 매일 오전 7시 KST 자동 실행
```

## 환경변수 (GitHub Secrets)
- ANTHROPIC_API_KEY   : Claude API 키 (sk-ant-...)
- GMAIL_ADDRESS       : 발송용 Gmail 주소
- GMAIL_APP_PASSWORD  : Gmail 앱 비밀번호 (16자리)
- RECIPIENT_EMAIL     : fallback 수신 이메일 (subscribers.txt 없을 때)

## 뉴스 소스 (RSS)
- The Verge AI, TechCrunch AI, VentureBeat AI  (영어 → 번역)
- Reuters Tech, 연합뉴스 IT/경제               (신뢰 매체)
- TechCrunch Startups                          (스타트업/투자)
필터: 전일 기사만 / 중복 제거 (제목 앞 20자 기준)

## 섹션 구성
1. Today's One-liner   — 오늘 뉴스 한 문장
2. ☀ 또모닝 브리핑     — 전일 핵심 4~5개 불릿
3. 딥다이브            — 요일별 자동 전환
   - 월/화: 비즈니스 인사이트: 사례분석
   - 수/목: 비즈니스 인사이트: 전략분석
   - 금:   비즈니스 인사이트: 리더들의 SNS 말말말
4. 📊 빅테크 & 주요 지수
5. 🚀 AI 스타트업 레이더
6. 🛠 오늘의 AI 툴
7. 📅 이번 주 주요 일정
8. 구독 신청 CTA

## 확정 디자인 스펙
- 폰트: Noto Sans KR 고딕 전용 (명조 없음)
- 헤더: #1A1040 (딥퍼플), padding 28px 40px 45px
- 날짜: Daily Briefing 같은 줄 오른쪽, #C4BAE8 (연보라)
- One-liner: #E8682A (오렌지 배경), 흰색 텍스트
- 본문 배경: #F5F3EC (아이보리)
- 딥다이브 배경: #F8F6FF (연보라)
- 포인트 컬러: 보라 #5B3FA0 / 파랑 #1A5FA0 / 오렌지 #E8682A
- 섹션 padding-top: 43px
- 섹션 구분: 8px solid #E0DDD4
- eyebrow 태그: 우측 상단 절대위치, 테두리 박스, 자간 없음
- 딥다이브 인트로: 보라 큰따옴표 + 들여쓰기

## Claude API 설정
- 모델: claude-sonnet-4-20250514
- max_tokens: 8000
- 응답: JSON only

## 구독자 관리
- subscribers.txt에 이메일 한 줄씩
- # 주석 처리 가능
- GitHub에서 직접 편집

## TODO (다음 작업)
- [ ] daily.yml 주말 제외 cron 설정 확인
- [ ] GitHub에 최신 newsletter.py 업로드
- [ ] 테스트 실행 후 메일 확인
