# 또롱이 뉴스레터 프로젝트

## 프로젝트 개요
매일 오전 7시 AI/경제 뉴스를 자동 수집 → Claude API로 번역/요약 → 구독자 전체에게 이메일 발송하는 자동화 시스템.

## 저장소 정보
- GitHub: `https://github.com/sunyeong-park/ai-newsletter`
- 브랜치: `main`
- 실행 환경: GitHub Actions (Ubuntu)

## 파일 구조
```
ai-newsletter/
├── newsletter.py              # 핵심 코드 (뉴스수집 + Claude 요약 + 발송)
├── subscribers.txt            # 구독자 이메일 목록 (한 줄에 하나)
├── requirements.txt           # feedparser, anthropic
└── .github/workflows/
    └── daily.yml              # 매일 오전 7시 KST 자동 실행
```

## 환경변수 (GitHub Secrets)
```
ANTHROPIC_API_KEY     # Claude API 키 (sk-ant-...)
GMAIL_ADDRESS         # 발송용 Gmail 주소
GMAIL_APP_PASSWORD    # Gmail 앱 비밀번호 (16자리)
RECIPIENT_EMAIL       # 수신 fallback 이메일 (subscribers.txt 없을 때)
```

## 뉴스 소스
- 구글뉴스 AI (한국어 RSS)
- 구글뉴스 경제 (한국어 RSS)
- TechCrunch AI (영어 RSS) → Claude가 한국어로 번역
- Wired AI (영어 RSS) → Claude가 한국어로 번역

## 뉴스레터 섹션 구성
1. Editor's Note — 오늘 뉴스 전체 흐름 요약
2. 순모닝 브리핑 — 주요 뉴스 4~5개 불릿
3. Deep Dive — 심층 분석
4. Killer Chart — 데이터 막대 그래프 (Chart.js)
5. 오늘의 핵심 뉴스 3 — TOP 3
6. AI & 기술 섹션
7. 경제 & 금융 섹션
8. 이번 주 주요 일정

## 디자인 스펙 (현재)
- 배경: `#111` (헤더), `#FAFAF8` (본문)
- 포인트 색상: 골드 `#D4A847`
- 본문 폰트: Noto Sans KR
- 타이틀 폰트: Noto Serif KR
- 본문 글자 크기: 13.5px, 행간 1.75
- 최대 너비: 620px

## Claude API 설정
- 모델: `claude-sonnet-4-20250514`
- max_tokens: `8000`
- 응답 형식: JSON only (마크다운 코드블록 없이)

## 구독자 관리
- `subscribers.txt` 파일에 이메일 한 줄씩 입력
- `#` 으로 시작하는 줄은 주석 처리
- GitHub에서 직접 편집 가능

## 남은 작업 (TODO)
- [ ] 디자인 커스터마이즈
  - 폰트 종류 변경
  - 글자 크기 / 행간 조정
  - 섹션 타이틀 텍스트 변경
  - 포인트 색상 변경 (현재: 골드 #D4A847)

## 비용
- GitHub Actions: 무료
- Claude API: 월 $3~6 예상 (크레딧 잔액 $5.00)
- Gmail SMTP: 무료
