"""
🏆 Paul Tudor Jones (PTJ) Trading Bot for Coinone
v2.1 - 운영 안정성 개선 (전략 변경 없음)

개선사항:
- 재진입 쿨다운 (무한 매매 방지)
- 포지션 동기화 검증
- API 재시도 로직
- 매시간 텔레그램 상태 알림

전략 (v1 유지):
- 200 MA 위면 진입
- 손절 7%
- 트레일링 스탑 10% (8% 수익시 활성화)
- 즉시 재진입 (청산 후 200 MA 위면)
"""

import hmac
import hashlib
import base64
import uuid
import time
import json
import os
import requests
import pandas as pd
import numpy as np
from datetime import datetime
from typing import Optional, Tuple, Dict
from functools import wraps
import logging
from dotenv import load_dotenv

load_dotenv()


# ============================================================================
# 설정
# ============================================================================
class Config:
    # 코인원 API
    COINONE_ACCESS_TOKEN = os.getenv("COINONE_ACCESS_TOKEN", "")
    COINONE_SECRET_KEY = os.getenv("COINONE_SECRET_KEY", "")

    # 거래 설정
    TICKER = "BTC"
    CURRENCY = "KRW"
    MIN_TRADE_AMOUNT = 10000

    # PTJ 전략 (v1 유지)
    MA_PERIOD = 200
    CONFIRMATION_MA = 50
    STOP_LOSS_PCT = 0.07
    TRAILING_STOP_PCT = 0.10
    TRAILING_ACTIVATION_PCT = 0.08

    # 재진입 설정
    ENABLE_REENTRY = True
    REENTRY_COOLDOWN = 60 * 60 * 4  # 4시간 쿨다운

    # 투자 비율
    INVEST_RATIO = 0.95

    # 봇 설정
    CHECK_INTERVAL = 60 * 60  # 1시간

    # API 설정
    API_TIMEOUT = 10
    API_MAX_RETRIES = 3
    API_RETRY_DELAY = 2

    # 텔레그램
    TELEGRAM_ENABLED = True
    TELEGRAM_TOKEN = os.getenv("TELEGRAM_TOKEN", "")
    TELEGRAM_CHAT_ID = os.getenv("TELEGRAM_CHAT_ID", "")

    # 매시간 상태 알림
    HOURLY_STATUS_ENABLED = True


# ============================================================================
# 로깅
# ============================================================================
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s [%(levelname)s] %(message)s',
    handlers=[
        logging.FileHandler('ptj_trading_bot.log', encoding='utf-8'),
        logging.StreamHandler()
    ]
)
logger = logging.getLogger(__name__)


# ============================================================================
# 유틸리티
# ============================================================================
def retry(max_attempts: int = 3, delay: float = 2):
    """API 재시도 데코레이터"""
    def decorator(func):
        @wraps(func)
        def wrapper(*args, **kwargs):
            last_exception = None
            for attempt in range(max_attempts):
                try:
                    return func(*args, **kwargs)
                except Exception as e:
                    last_exception = e
                    if attempt < max_attempts - 1:
                        wait_time = delay * (attempt + 1)
                        logger.warning(f"재시도 {attempt + 1}/{max_attempts}: {e}")
                        time.sleep(wait_time)
            raise last_exception
        return wrapper
    return decorator


def send_telegram(message: str) -> bool:
    """텔레그램 알림"""
    if not Config.TELEGRAM_ENABLED or not Config.TELEGRAM_TOKEN:
        return False

    try:
        url = f"https://api.telegram.org/bot{Config.TELEGRAM_TOKEN}/sendMessage"
        data = {
            "chat_id": Config.TELEGRAM_CHAT_ID,
            "text": message,
            "parse_mode": "HTML"
        }
        response = requests.post(url, data=data, timeout=10)
        if response.status_code == 200:
            logger.info("📱 텔레그램 전송 완료")
            return True
        return False
    except Exception as e:
        logger.error(f"텔레그램 오류: {e}")
        return False


# ============================================================================
# 코인원 API
# ============================================================================
class CoinoneAPI:
    BASE_URL = "https://api.coinone.co.kr"

    def __init__(self, access_token: str, secret_key: str):
        self.access_token = access_token
        self.secret_key = secret_key.encode('utf-8')

    def _get_signature(self, payload: str) -> str:
        return hmac.new(self.secret_key, payload.encode('utf-8'), hashlib.sha512).hexdigest()

    @retry(max_attempts=Config.API_MAX_RETRIES, delay=Config.API_RETRY_DELAY)
    def _request(self, endpoint: str, params: Dict = None) -> Dict:
        if params is None:
            params = {}

        params['access_token'] = self.access_token
        params['nonce'] = str(uuid.uuid4())

        payload = base64.b64encode(json.dumps(params).encode('utf-8')).decode('utf-8')
        signature = self._get_signature(payload)

        headers = {
            'Content-Type': 'application/json',
            'X-COINONE-PAYLOAD': payload,
            'X-COINONE-SIGNATURE': signature
        }

        response = requests.post(
            f"{self.BASE_URL}{endpoint}",
            headers=headers,
            data=json.dumps(params),
            timeout=Config.API_TIMEOUT
        )

        result = response.json()
        if result.get('result') != 'success':
            raise Exception(f"API 오류: {result}")
        return result

    @retry(max_attempts=Config.API_MAX_RETRIES, delay=Config.API_RETRY_DELAY)
    def _public_request(self, endpoint: str, params: Dict = None) -> Dict:
        response = requests.get(f"{self.BASE_URL}{endpoint}", params=params, timeout=Config.API_TIMEOUT)
        return response.json()

    def get_balance(self) -> Dict:
        return self._request('/v2.1/account/balance/all')

    def get_ticker(self, currency: str = "BTC") -> Dict:
        return self._public_request(f"/public/v2/ticker_new/KRW/{currency}")

    def get_candles(self, currency: str = "BTC", interval: str = "1d", limit: int = 300) -> Optional[pd.DataFrame]:
        try:
            data = self._public_request(
                f"/public/v2/chart/KRW/{currency}",
                params={"interval": interval, "limit": limit}
            )

            if data.get('result') != 'success':
                return None

            candles = data.get('chart', [])
            if not candles:
                return None

            df = pd.DataFrame(candles)
            df['timestamp'] = pd.to_datetime(df['timestamp'], unit='ms')
            df.set_index('timestamp', inplace=True)
            df = df.astype({
                'open': float, 'high': float, 'low': float,
                'close': float, 'target_volume': float
            })
            df.rename(columns={'target_volume': 'volume'}, inplace=True)
            return df.sort_index()

        except Exception as e:
            logger.error(f"캔들 조회 오류: {e}")
            return None

    def buy_market_order(self, currency: str, amount: float) -> Dict:
        params = {
            'target_currency': currency,
            'quote_currency': 'KRW',
            'type': 'market',
            'side': 'buy',
            'amount': str(int(amount))
        }
        return self._request('/v2.1/order', params)

    def sell_market_order(self, currency: str, qty: float) -> Dict:
        params = {
            'target_currency': currency,
            'quote_currency': 'KRW',
            'type': 'market',
            'side': 'sell',
            'qty': str(qty)
        }
        return self._request('/v2.1/order', params)


# ============================================================================
# 포지션 관리
# ============================================================================
class PositionManager:
    STATE_FILE = "ptj_position_state.json"

    def __init__(self):
        self.entry_price: Optional[float] = None
        self.highest_price: Optional[float] = None
        self.in_position: bool = False
        self.entry_time: Optional[str] = None
        self.last_exit_time: Optional[float] = None
        self.last_exit_reason: Optional[str] = None
        self.load_state()

    def load_state(self):
        if os.path.exists(self.STATE_FILE):
            try:
                with open(self.STATE_FILE, 'r') as f:
                    state = json.load(f)
                    self.entry_price = state.get('entry_price')
                    self.highest_price = state.get('highest_price')
                    self.in_position = state.get('in_position', False)
                    self.entry_time = state.get('entry_time')
                    self.last_exit_time = state.get('last_exit_time')
                    self.last_exit_reason = state.get('last_exit_reason')
                    logger.info(f"📂 포지션 상태 로드 완료")
            except Exception as e:
                logger.error(f"상태 로드 실패: {e}")

    def save_state(self):
        state = {
            'entry_price': self.entry_price,
            'highest_price': self.highest_price,
            'in_position': self.in_position,
            'entry_time': self.entry_time,
            'last_exit_time': self.last_exit_time,
            'last_exit_reason': self.last_exit_reason
        }
        try:
            with open(self.STATE_FILE, 'w') as f:
                json.dump(state, f, indent=2)
        except Exception as e:
            logger.error(f"상태 저장 실패: {e}")

    def enter_position(self, price: float):
        self.entry_price = price
        self.highest_price = price
        self.in_position = True
        self.entry_time = datetime.now().isoformat()
        self.save_state()

    def update_highest(self, price: float) -> bool:
        if self.in_position and price > (self.highest_price or 0):
            self.highest_price = price
            self.save_state()
            return True
        return False

    def exit_position(self, reason: str = ""):
        self.entry_price = None
        self.highest_price = None
        self.in_position = False
        self.entry_time = None
        self.last_exit_time = time.time()
        self.last_exit_reason = reason
        self.save_state()

    def can_reenter(self) -> Tuple[bool, str]:
        """재진입 가능 여부 (쿨다운 체크)"""
        if not Config.ENABLE_REENTRY:
            return False, "재진입 비활성화"

        if self.last_exit_time is None:
            return True, ""

        elapsed = time.time() - self.last_exit_time
        remaining = Config.REENTRY_COOLDOWN - elapsed

        if remaining > 0:
            minutes = int(remaining / 60)
            return False, f"쿨다운 {minutes}분 남음"

        return True, ""

    def get_stop_loss_price(self) -> Optional[float]:
        if self.entry_price:
            return self.entry_price * (1 - Config.STOP_LOSS_PCT)
        return None

    def get_trailing_stop_price(self) -> Optional[float]:
        if self.highest_price:
            return self.highest_price * (1 - Config.TRAILING_STOP_PCT)
        return None

    def is_trailing_active(self, current_price: float) -> bool:
        if self.entry_price:
            return current_price > self.entry_price * (1 + Config.TRAILING_ACTIVATION_PCT)
        return False


# ============================================================================
# PTJ 봇
# ============================================================================
class PTJBot:
    """PTJ Trading Bot v2.1"""

    def __init__(self):
        self.api = CoinoneAPI(Config.COINONE_ACCESS_TOKEN, Config.COINONE_SECRET_KEY)
        self.position = PositionManager()
        self.trade_count = 0
        self.win_count = 0
        self.start_time = datetime.now()
        logger.info("🏆 PTJ Trading Bot v2.1 초기화 완료")

    def get_ohlcv(self) -> Optional[pd.DataFrame]:
        try:
            df = self.api.get_candles(Config.TICKER, interval="1d", limit=300)
            if df is None or len(df) < Config.MA_PERIOD:
                logger.error(f"데이터 부족: {len(df) if df is not None else 0}")
                return None
            return df
        except Exception as e:
            logger.error(f"OHLCV 조회 실패: {e}")
            return None

    def calculate_signals(self, df: pd.DataFrame) -> Dict:
        df['ma_200'] = df['close'].rolling(window=Config.MA_PERIOD).mean()
        df['ma_50'] = df['close'].rolling(window=Config.CONFIRMATION_MA).mean()

        current_price = df['close'].iloc[-1]
        ma_200 = df['ma_200'].iloc[-1]
        ma_50 = df['ma_50'].iloc[-1]

        prev_price = df['close'].iloc[-2]
        prev_ma_200 = df['ma_200'].iloc[-2]

        above_200ma = current_price > ma_200
        strong_uptrend = current_price > ma_50 > ma_200
        buy_signal = (prev_price <= prev_ma_200) and (current_price > ma_200)
        sell_signal = (prev_price >= prev_ma_200) and (current_price < ma_200)

        return {
            'current_price': current_price,
            'ma_200': ma_200,
            'ma_50': ma_50,
            'above_200ma': above_200ma,
            'strong_uptrend': strong_uptrend,
            'buy_signal': buy_signal,
            'sell_signal': sell_signal,
            'trend': 'BULL' if above_200ma else 'BEAR'
        }

    def get_balance(self) -> Tuple[float, float]:
        try:
            result = self.api.get_balance()
            balances_list = result.get('balances', [])
            balances = {b['currency'].upper(): b for b in balances_list}
            krw = float(balances.get('KRW', {}).get('available', 0))
            coin = float(balances.get(Config.TICKER.upper(), {}).get('available', 0))
            return krw, coin
        except Exception as e:
            logger.error(f"잔고 조회 실패: {e}")
            return 0, 0

    def get_current_price(self) -> Optional[float]:
        try:
            result = self.api.get_ticker(Config.TICKER)
            if result.get('result') != 'success':
                return None
            tickers = result.get('tickers', [])
            if not tickers:
                return None
            return float(tickers[0].get('last', 0))
        except Exception as e:
            logger.error(f"현재가 조회 실패: {e}")
            return None

    def verify_position_sync(self, coin_balance: float, current_price: float) -> bool:
        """포지션 동기화 검증"""
        has_actual_position = coin_balance * current_price > Config.MIN_TRADE_AMOUNT

        if has_actual_position and not self.position.in_position:
            logger.warning("⚠️ 포지션 불일치: 실제 보유 중이나 기록 없음")
            send_telegram(f"⚠️ <b>포지션 불일치</b>\n실제: {coin_balance:.8f} BTC\n기록: 없음")
            self.position.enter_position(current_price)
            return False

        elif not has_actual_position and self.position.in_position:
            logger.warning("⚠️ 포지션 불일치: 기록에는 있으나 실제 없음")
            send_telegram(f"⚠️ <b>포지션 불일치</b>\n실제: 없음\n기록 초기화")
            self.position.exit_position("상태 불일치")
            return False

        return True

    def buy(self, reason: str) -> bool:
        try:
            krw_balance, _ = self.get_balance()

            if krw_balance < Config.MIN_TRADE_AMOUNT:
                logger.warning(f"잔고 부족: {krw_balance:,.0f}원")
                return False

            invest_amount = krw_balance * Config.INVEST_RATIO
            current_price = self.get_current_price()

            if current_price is None:
                return False

            logger.info(f"🟢 매수 시도: {invest_amount:,.0f}원")
            self.api.buy_market_order(Config.TICKER, invest_amount)

            time.sleep(2)
            _, new_coin = self.get_balance()

            if new_coin > 0:
                self.position.enter_position(current_price)
                msg = f"🟢 <b>매수 완료</b>\n사유: {reason}\n가격: {current_price:,.0f}원\n금액: {invest_amount:,.0f}원"
                logger.info(f"매수 완료: {reason}")
                send_telegram(msg)
                return True
            else:
                logger.error("매수 후 잔고 미반영")
                return False

        except Exception as e:
            logger.error(f"매수 오류: {e}")
            return False

    def sell(self, reason: str) -> Tuple[bool, float]:
        try:
            _, coin_balance = self.get_balance()
            current_price = self.get_current_price()

            if coin_balance <= 0 or current_price is None:
                return False, 0

            logger.info(f"🔴 매도 시도: {coin_balance:.8f} BTC")
            self.api.sell_market_order(Config.TICKER, coin_balance)

            time.sleep(2)
            _, remaining = self.get_balance()

            if remaining * current_price < Config.MIN_TRADE_AMOUNT:
                entry_price = self.position.entry_price
                profit_pct = ((current_price - entry_price) / entry_price * 100) if entry_price else 0

                self.trade_count += 1
                if profit_pct > 0:
                    self.win_count += 1

                emoji = "✅" if profit_pct > 0 else "❌"
                msg = f"🔴 <b>매도 완료</b>\n사유: {reason}\n가격: {current_price:,.0f}원\n수익률: {emoji} {profit_pct:+.2f}%"
                logger.info(f"매도 완료: {reason} ({profit_pct:+.2f}%)")
                send_telegram(msg)

                self.position.exit_position(reason)
                return True, profit_pct
            else:
                logger.error("매도 후 잔고 미반영")
                return False, 0

        except Exception as e:
            logger.error(f"매도 오류: {e}")
            return False, 0

    def check_exit_conditions(self, current_price: float, signals: Dict) -> Tuple[bool, str, bool]:
        """청산 조건 (should_exit, reason, allow_reentry)"""
        if not self.position.in_position:
            return False, "", False

        self.position.update_highest(current_price)

        # 손절 7%
        stop_loss_price = self.position.get_stop_loss_price()
        if stop_loss_price and current_price <= stop_loss_price:
            return True, "Stop Loss (7%)", True

        # 트레일링 스탑 10%
        if self.position.is_trailing_active(current_price):
            trailing_stop_price = self.position.get_trailing_stop_price()
            if trailing_stop_price and current_price <= trailing_stop_price:
                return True, "Trailing Stop (10%)", True

        # 200MA 하향 돌파
        if signals['sell_signal']:
            return True, "Below 200 MA", False

        return False, "", False

    def get_status_message(self, signals: Dict) -> str:
        krw_balance, coin_balance = self.get_balance()
        current_price = signals['current_price']
        total_value = krw_balance + coin_balance * current_price

        trend = "🟢 BULL" if signals['above_200ma'] else "🔴 BEAR"

        if self.position.in_position and self.position.entry_price:
            pnl = (current_price - self.position.entry_price) / self.position.entry_price * 100
            pnl_emoji = "📈" if pnl > 0 else "📉"
            position_status = f"LONG ({pnl_emoji} {pnl:+.2f}%)"
            stop_info = f"손절: {self.position.get_stop_loss_price():,.0f}원"
        else:
            position_status = "CASH (대기)"
            stop_info = "-"

        return f"""
<b>🏆 PTJ Bot v2.1 상태</b>
━━━━━━━━━━━━━━━
📊 <b>시장</b>
  가격: {current_price:,.0f}원
  200 MA: {signals['ma_200']:,.0f}
  추세: {trend}
━━━━━━━━━━━━━━━
💼 <b>포지션</b>: {position_status}
  {stop_info}
━━━━━━━━━━━━━━━
💰 <b>잔고</b>
  KRW: {krw_balance:,.0f}원
  BTC: {coin_balance:.8f}
  총: {total_value:,.0f}원
"""

    def run_once(self, send_hourly_status: bool = True):
        logger.info("=" * 60)
        logger.info(f"📊 PTJ v2.1 분석 | {datetime.now().strftime('%H:%M:%S')}")

        df = self.get_ohlcv()
        if df is None:
            return

        signals = self.calculate_signals(df)
        current_price = signals['current_price']

        logger.info(f"현재가: {current_price:,.0f}원")
        logger.info(f"200 MA: {signals['ma_200']:,.0f}")
        logger.info(f"추세: {'🟢 BULL' if signals['above_200ma'] else '🔴 BEAR'}")

        krw_balance, coin_balance = self.get_balance()

        if not self.verify_position_sync(coin_balance, current_price):
            return

        logger.info(f"💰 잔고: {krw_balance:,.0f}원 / {coin_balance:.8f} BTC")

        # 포지션 있을 때
        if self.position.in_position:
            should_exit, reason, allow_reentry = self.check_exit_conditions(current_price, signals)

            if should_exit:
                logger.info(f"🔴 청산: {reason}")
                success, profit_pct = self.sell(reason)

                # 재진입 로직
                if success and allow_reentry:
                    can_reenter, cooldown_reason = self.position.can_reenter()

                    if can_reenter and signals['above_200ma']:
                        time.sleep(2)
                        krw_balance, _ = self.get_balance()

                        if krw_balance > Config.MIN_TRADE_AMOUNT:
                            logger.info("🔄 재진입 조건 충족")
                            if self.buy("Reentry (Above 200 MA)"):
                                send_telegram("🔄 <b>재진입 완료</b>\n200 MA 위 유지 중")
                    elif not can_reenter:
                        logger.info(f"재진입 대기: {cooldown_reason}")
                    else:
                        logger.info("재진입 불가: 200 MA 아래")
            else:
                if self.position.entry_price:
                    pnl = (current_price - self.position.entry_price) / self.position.entry_price * 100
                    trailing = "활성" if self.position.is_trailing_active(current_price) else "대기"
                    logger.info(f"손익: {pnl:+.2f}% | 트레일링: {trailing}")

        # 포지션 없을 때
        else:
            can_reenter, cooldown_reason = self.position.can_reenter()

            if signals['above_200ma']:
                if can_reenter:
                    reason = "200 MA Breakout" if signals['buy_signal'] else "Above 200 MA"
                    logger.info(f"🟢 매수 신호: {reason}")
                    self.buy(reason)
                else:
                    logger.info(f"대기: {cooldown_reason}")
            else:
                logger.info("대기: 200 MA 아래")

        # 매시간 상태 알림
        if send_hourly_status and Config.HOURLY_STATUS_ENABLED:
            send_telegram(self.get_status_message(signals))
            logger.info("📱 매시간 상태 전송")

    def run(self):
        logger.info("🏆 PTJ Trading Bot v2.1 시작")
        logger.info(f"전략: 200 MA + 즉시 재진입")
        logger.info(f"손절: {Config.STOP_LOSS_PCT*100}% | 트레일링: {Config.TRAILING_STOP_PCT*100}%")
        logger.info(f"재진입 쿨다운: {Config.REENTRY_COOLDOWN//3600}시간")

        start_msg = f"""
<b>🏆 PTJ Bot v2.1 시작</b>
━━━━━━━━━━━━━━━
전략: 200 MA 추세추종
손절: {Config.STOP_LOSS_PCT*100}%
트레일링: {Config.TRAILING_STOP_PCT*100}%
━━━━━━━━━━━━━━━
<b>v2.1 개선사항</b>
✅ 재진입 쿨다운 (4시간)
✅ 포지션 동기화 검증
✅ API 재시도 로직
✅ 매시간 상태 알림
━━━━━━━━━━━━━━━
"Play great defense"
- Paul Tudor Jones
"""
        send_telegram(start_msg)

        self.run_once(send_hourly_status=True)

        while True:
            try:
                time.sleep(Config.CHECK_INTERVAL)
                self.run_once(send_hourly_status=True)

            except KeyboardInterrupt:
                logger.info("봇 종료")
                send_telegram("⚠️ PTJ Bot 종료됨")
                break
            except Exception as e:
                logger.error(f"오류: {e}")
                send_telegram(f"⚠️ 오류: {e}")
                time.sleep(60)


def main():
    print("""
    ╔══════════════════════════════════════════════════════════════╗
    ║  🏆 PTJ Trading Bot v2.1                                     ║
    ║  운영 안정성 개선 (전략 변경 없음)                           ║
    ╠══════════════════════════════════════════════════════════════╣
    ║  ✅ 재진입 쿨다운 (4시간)                                    ║
    ║  ✅ 포지션 동기화 검증                                       ║
    ║  ✅ API 재시도 로직                                          ║
    ║  ✅ 매시간 상태 알림                                         ║
    ╚══════════════════════════════════════════════════════════════╝
    """)

    if not Config.COINONE_ACCESS_TOKEN:
        print("⚠️  .env 파일에서 API 키를 설정해주세요!")
        return

    bot = PTJBot()
    bot.run()


if __name__ == "__main__":
    main()
