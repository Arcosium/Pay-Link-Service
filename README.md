# PayLink — AI 알뜰폰 요금제 추천 챗봇

> "3만원 이하로 데이터 무제한" 한 마디로 SKT·KT·LG U+ 와 알뜰폰 2,300여 개 요금제 중 적합한 3개를 추천하는 한국어 대화형 어시스턴트.

PayLink 는 자연어로 통신 요금제를 검색할 수 있는 챗봇입니다.
사용자가 한국어로 조건을 말하면 **Google Gemini 2.0 Flash** 가 의도와 파라미터를 추출하고,
Pandas 가 2,324 개의 요금제 데이터(`plans.csv`)에서 가격·데이터·약정·혜택 조건에 맞는
요금제 3개를 골라 카드 UI 로 보여줍니다.

- **백엔드**: FastAPI + Gemini 2.0 Flash (의도 추출)
- **프론트**: 단일 `index.html` (Tailwind CSS + Vanilla JS, Pretendard 한글 폰트)
- **데이터**: `plans.csv` — 2,324 row × 11 column (SKT/KT/LG + 알뜰폰)
- **배포**: systemd + Nginx 리버스 프록시

---

## 무엇을 할 수 있나

| 사용자 입력 | 추출되는 파라미터 |
|---|---|
| "3만원 이하로 데이터 무제한" | `price_limit=30000, data_gb=999` |
| "음성 통화 위주, 5천원대" | `price_limit=6000, voice_min=999` |
| "넷플릭스 같이 주는 거" | `benefit_keyword="넷플릭스"` |
| "5G 요금제 비교해줘" | `category="5G"` |
| "할인 빠진 정상가로 보여줘" | `exclude_discount=True` |

추출 → 필터 → 평점/가격순 정렬 → **상위 3개 카드** (월 요금, 데이터, 음성, 문자, 2년 평균 비용,
프로모션 혜택, 평점) 으로 응답합니다.

## 빠른 시작

### 1. 의존성

```bash
pip install fastapi uvicorn pandas google-generativeai python-dotenv
```

### 2. 환경변수 (`.env`)

```bash
GEMINI_API_KEY=AIza...        # Google AI Studio 에서 발급
CSV_PATH=./plans.csv          # 선택, 기본은 스크립트 폴더
APP_PORT=7861                 # 선택, 미설정시 7861~7898 자동 탐색
```

### 3. 실행

```bash
python PayLink_final.py
# [PayLink] Starting on port 7861
# 브라우저에서 http://localhost:7861 접속
```

### 4. systemd 등록

```bash
sudo cp paylink.service /etc/systemd/system/
sudo systemctl daemon-reload
sudo systemctl enable --now paylink
```

### 5. Nginx (선택)

```bash
sudo cp nginx_paylink_clean.conf /etc/nginx/conf.d/paylink.conf
sudo systemctl reload nginx
# → kakaopaylink.kro.kr 같은 도메인에서 접속
```

## 데이터 모델 (`plans.csv`)

| 컬럼 | 타입 | 설명 |
|---|---|---|
| `plan_id` | str | 고유 식별자 |
| `carrier` | str | 통신사 (SKT, KT, LG U+, 쉐이크모바일, KG모바일, …) |
| `plan_name` | str | 마케팅명 (예: "쉐이크 LTE 100GB + 네이버페이 5K") |
| `monthly_fee` | int | 월 요금 (원) |
| `data_gb` | float | 데이터 (999+ = 무제한) |
| `is_unlimited` | int | 1 = 무제한 |
| `voice_min` | int | 음성 분 (999+ = 무제한) |
| `sms_count` | int | 문자 (999+ = 무제한) |
| `qos_speed` | str | "무제한" / "5Mbps" / "400Kbps" |
| `category` | str | "LTE" / "5G" |
| `benefits` | str | 세미콜론 구분 (할인, 제휴 혜택, 평점) |

대표 row:
```
shakemodule_LTE,쉐이크모바일,"쉐이크 LTE 100GB + 네이버페이 5K",17000,100.0,0,
  999,999,무제한,LTE,"정상가 47,300원;할인 7개월;네이버페이 5,000원;평점 4.6"
```

## 디렉터리 구조

```
Pay-Link Service/
├── PayLink_final.py         # FastAPI 백엔드 (의도 추출 + 검색 필터)
├── index.html               # 챗 UI (Tailwind + Vanilla JS, 단일 파일)
├── plans.csv                # 2,324 요금제 데이터 (395KB)
├── paylink.service          # systemd 유닛
├── nginx_paylink.conf       # 풀 Nginx 설정 (process / log / proxy)
├── nginx_paylink_clean.conf # 최소 server 블록만
└── .gitignore
```

## API

### `POST /chat`

**Request:**
```json
{ "message": "3만원 이하로 데이터 무제한" }
```

**Response:**
```json
{
  "reply": "3만원 이하 데이터 무제한 요금제 3개 찾았어요!",
  "plans": [
    {
      "plan_id": "shakemodule_LTE",
      "carrier": "쉐이크모바일",
      "plan_name": "쉐이크 LTE 100GB + 네이버페이 5K",
      "monthly_fee": 17000,
      "data_gb": 100.0,
      "voice_min": 999,
      "sms_count": 999,
      "benefits": ["정상가 47,300원", "네이버페이 5,000원", "평점 4.6"],
      "two_year_avg": 23000
    },
    ...
  ]
}
```

CORS 는 모든 origin 허용 (`allow_origins=["*"]`).

## UI 미리보기

- **헤더**: "PayLink AI 상담사" (인디고 테마)
- **메시지 영역**: 사용자/봇 말풍선, 타이핑 애니메이션 (·· · 깜빡임)
- **요금제 카드**: 통신사 배지 / 월 요금 / 할인 인디케이터 (✨, ✅) / 데이터·음성·문자 3-col grid
- **2년 평균 비용**: 할인 종료 후 정상가까지 합산해 평균 (장기 부담 비교용)
- **혜택 펼치기**: 클릭으로 expand
- **인풋**: 둥근 텍스트 필드 + Enter 또는 send 버튼

## 운영 노트

- **포트 자동 탐색**: `APP_PORT` → `GRADIO_SERVER_PORT` → `PORT` 순으로 확인 후 비어있으면 7861~7898 스캔
- **데이터 로드**: `.env` 의 `CSV_PATH` → 스크립트 폴더 순서로 fallback
- **Nginx 설정**에는 WebSocket 헤더(`Upgrade`, `Connection: upgrade`)가 포함돼 있어
  추후 SSE/WS 기능 추가 시에도 그대로 사용 가능

---

## English Summary

Korean MVNO/telecom plan recommendation chatbot. Users describe their needs in
natural Korean ("under 30K won, unlimited data") and Gemini 2.0 Flash extracts
intent and parameters. Pandas filters 2,324 plans from major carriers (SKT, KT,
LG U+) and budget MVNOs (쉐이크, KG, SK7, etc.) and returns top 3 as
expandable cards with monthly fee, data quota, partner benefits, and 2-year
projected cost.

**Stack:** FastAPI · pandas · Google Gemini API · Tailwind CSS · Vanilla JS · Nginx

## License

Plan data is sourced from public Korean carrier websites; prices and benefits are
illustrative and subject to change. Do not use for commercial price quoting
without verifying current rates with carriers.
