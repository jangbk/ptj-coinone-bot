"""
코인원 API 설정 파일
https://coinone.co.kr/developer/app 에서 API 키 발급
"""

# 코인원 API 키 설정
COINONE_ACCESS_TOKEN = "YOUR_ACCESS_TOKEN_HERE"
COINONE_SECRET_KEY = "YOUR_SECRET_KEY_HERE"

# 거래 설정
TICKER = "BTC"  # 거래할 코인 (BTC, ETH, XRP 등)
CURRENCY = "KRW"  # 결제 통화

# PTJ 전략 설정
MA_PERIOD = 200  # 이동평균 기간 (Paul Tudor Jones 기본값)
CONFIRMATION_MA = 50  # 확인용 단기 MA

# 리스크 관리 설정 (PTJ 스타일 - 빠른 손절)
STOP_LOSS_PCT = 0.07  # 손절 비율 (7%)
TAKE_PROFIT_PCT = 0.15  # 익절 비율 (15%) - 손익비 2:1 이상
TRAILING_STOP_PCT = 0.10  # 트레일링 스탑 비율 (10%)
TRAILING_ACTIVATION_PCT = 0.08  # 트레일링 스탑 활성화 (8% 수익시)

# 투자 비율 설정
INVEST_RATIO = 0.95  # 보유 원화의 95% 투자

# 봇 설정
CHECK_INTERVAL = 60 * 60  # 체크 간격 (초) - 1시간
CANDLE_INTERVAL = "day"  # 캔들 간격 (일봉)

# 로깅 설정
LOG_FILE = "ptj_trading_bot.log"

# 텔레그램 설정 (선택사항)
ENABLE_TELEGRAM = True
TELEGRAM_BOT_TOKEN = "YOUR_TELEGRAM_BOT_TOKEN"
TELEGRAM_CHAT_ID = "YOUR_CHAT_ID"
