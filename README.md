# PTJ 200MA 자동매매 봇 (코인원)

Paul Tudor Jones 스타일의 200일 이동평균선 기반 비트코인 자동매매 봇

> "Play great defense, not great offense" - Paul Tudor Jones

## 전략

- **메인 지표**: 200일 이동평균선
- **매수**: 가격 > 200 MA 돌파
- **손절**: 7% (빠른 손절)
- **트레일링 스탑**: 10% (8% 수익시 활성화)

## 백테스트 결과 (2015-2025)

- 총 수익률: +822%
- 승률: 31.2% (32회 거래)
- 평균 손실: -2.9% (자본 보존 강점)

### 사이클별 수익률

| 사이클 | 기간 | 수익률 |
|--------|------|--------|
| 1차 | 2013-2016 | +63% |
| 2차 | 2016-2020 | +98% |
| 3차 | 2020-2024 | +185% |
| 4차 | 2024-현재 | +80% |

## 설치

```bash
pip install -r requirements.txt
cp .env.example .env
# .env 파일에 API 키 입력
```

## 실행

```bash
python ptj_bot.py
```

## 환경변수

| 변수 | 설명 |
|------|------|
| COINONE_ACCESS_TOKEN | 코인원 API Access Token |
| COINONE_SECRET_KEY | 코인원 API Secret Key |
| TELEGRAM_TOKEN | 텔레그램 봇 토큰 |
| TELEGRAM_CHAT_ID | 텔레그램 채팅 ID |

## Seykota vs PTJ 비교

| 항목 | Seykota | PTJ |
|------|---------|-----|
| 스타일 | 공격적 | 보수적 |
| 지표 | EMA 15/150 | 200 MA |
| 손절 | 10% | 7% |
| MDD | 높음 | 낮음 |
| 자본 보존 | 보통 | 강함 |
