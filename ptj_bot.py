"""
🏆 Paul Tudor Jones (PTJ) Trading Bot for Coinone
전설적인 헤지펀드 매니저 Paul Tudor Jones의 추세추종 전략

핵심 원칙:
1. "The most important rule is to play great defense" - 방어가 최우선
2. 200일 이동평균선으로 대세 판단
3. 빠른 손절, 수익은 길게 (손익비 2:1 이상)
4. "Losers average losers" - 물타기 금지
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
from typing import Optional, Tuple, Dict, Any
import logging
from dotenv import load_dotenv

# .env 파일 로드
load_dotenv()

# ============================================================================
# 설정
# ============================================================================
class Config:
    # 코인원 API 키 (.env에서 로드)
    COINONE_ACCESS_TOKEN = os.getenv("COINONE_ACCESS_TOKEN", "")
    COINONE_SECRET_KEY = os.getenv("COINONE_SECRET_KEY", "")

    # 거래 설정
    TICKER = "BTC"
    CURRENCY = "KRW"

    # PTJ 전략 설정
    MA_PERIOD = 200  # 메인 이동평균
    CONFIRMATION_MA = 50  # 확인용 단기 MA

    # 리스크 관리 (PTJ 스타일)
    STOP_LOSS_PCT = 0.07  # 손절 7%
    TAKE_PROFIT_PCT = 0.15  # 익절 15%
    TRAILING_STOP_PCT = 0.10  # 트레일링 10%
    TRAILING_ACTIVATION_PCT = 0.08  # 8% 수익시 트레일링 활성화

    # 투자 비율
    INVEST_RATIO = 0.95

    # 봇 설정
    CHECK_INTERVAL = 60 * 60  # 1시간

    # 텔레그램
    TELEGRAM_ENABLED = True
    TELEGRAM_TOKEN = os.getenv("TELEGRAM_TOKEN", "")
    TELEGRAM_CHAT_ID = os.getenv("TELEGRAM_CHAT_ID", "")


# 로깅 설정
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s [%(levelname)s] %(message)s',
    handlers=[
        logging.FileHandler('ptj_trading_bot.log', encoding='utf-8'),
        logging.StreamHandler()
    ]
)
logger = logging.getLogger(__name__)


def send_telegram(message: str):
    """텔레그램 알림 전송"""
    if not Config.TELEGRAM_ENABLED or not Config.TELEGRAM_TOKEN:
        return

    try:
        url = f"https://api.telegram.org/bot{Config.TELEGRAM_TOKEN}/sendMessage"
        data = {
            "chat_id": Config.TELEGRAM_CHAT_ID,
            "text": message,
            "parse_mode": "HTML"
        }
        requests.post(url, data=data, timeout=10)
        logger.info("📱 텔레그램 알림 전송 완료")
    except Exception as e:
        logger.error(f"텔레그램 오류: {e}")


class CoinoneAPI:
    """코인원 API 클래스"""

    BASE_URL = "https://api.coinone.co.kr"

    def __init__(self, access_token: str, secret_key: str):
        self.access_token = access_token
        self.secret_key = secret_key.encode('utf-8')

    def _get_signature(self, payload: str) -> str:
        """API 서명 생성"""
        signature = hmac.new(
            self.secret_key,
            payload.encode('utf-8'),
            hashlib.sha512
        )
        return signature.hexdigest()

    def _request(self, endpoint: str, params: Dict = None) -> Dict:
        """Private API 요청"""
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
            timeout=10
        )

        return response.json()

    def get_balance(self) -> Dict:
        """잔고 조회"""
        return self._request('/v2.1/account/balance/all')

    def get_ticker(self, currency: str = "BTC") -> Dict:
        """현재가 조회"""
        response = requests.get(
            f"{self.BASE_URL}/public/v2/ticker_new/KRW/{currency}",
            timeout=10
        )
        return response.json()

    def get_candles(self, currency: str = "BTC", interval: str = "1d", limit: int = 300) -> pd.DataFrame:
        """캔들 데이터 조회"""
        # interval: 1m, 3m, 5m, 15m, 30m, 1h, 4h, 6h, 1d
        response = requests.get(
            f"{self.BASE_URL}/public/v2/chart/KRW/{currency}",
            params={"interval": interval, "limit": limit},
            timeout=10
        )

        data = response.json()
        if data.get('result') != 'success':
            return None

        candles = data.get('chart', [])
        if not candles:
            return None

        df = pd.DataFrame(candles)
        df['timestamp'] = pd.to_datetime(df['timestamp'], unit='ms')
        df.set_index('timestamp', inplace=True)
        df = df.astype({
            'open': float,
            'high': float,
            'low': float,
            'close': float,
            'target_volume': float
        })
        df.rename(columns={'target_volume': 'volume'}, inplace=True)

        return df.sort_index()

    def buy_market_order(self, currency: str, amount: float) -> Dict:
        """시장가 매수"""
        params = {
            'target_currency': currency,
            'quote_currency': 'KRW',
            'type': 'market',
            'side': 'buy',
            'amount': str(amount)  # KRW 금액
        }
        return self._request('/v2.1/order', params)

    def sell_market_order(self, currency: str, qty: float) -> Dict:
        """시장가 매도"""
        params = {
            'target_currency': currency,
            'quote_currency': 'KRW',
            'type': 'market',
            'side': 'sell',
            'qty': str(qty)  # 코인 수량
        }
        return self._request('/v2.1/order', params)


class PositionManager:
    """포지션 상태 관리"""

    STATE_FILE = "ptj_position_state.json"

    def __init__(self):
        self.entry_price: Optional[float] = None
        self.highest_price: Optional[float] = None
        self.in_position: bool = False
        self.entry_time: Optional[str] = None
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
                    logger.info(f"📂 포지션 상태 로드: {state}")
            except Exception as e:
                logger.error(f"상태 로드 실패: {e}")

    def save_state(self):
        state = {
            'entry_price': self.entry_price,
            'highest_price': self.highest_price,
            'in_position': self.in_position,
            'entry_time': self.entry_time
        }
        with open(self.STATE_FILE, 'w') as f:
            json.dump(state, f, indent=2)

    def enter_position(self, price: float):
        self.entry_price = price
        self.highest_price = price
        self.in_position = True
        self.entry_time = datetime.now().isoformat()
        self.save_state()

    def update_highest(self, price: float):
        if self.in_position and price > self.highest_price:
            self.highest_price = price
            self.save_state()

    def exit_position(self):
        self.entry_price = None
        self.highest_price = None
        self.in_position = False
        self.entry_time = None
        self.save_state()

    def get_stop_loss_price(self) -> Optional[float]:
        if self.entry_price:
            return self.entry_price * (1 - Config.STOP_LOSS_PCT)
        return None

    def get_take_profit_price(self) -> Optional[float]:
        if self.entry_price:
            return self.entry_price * (1 + Config.TAKE_PROFIT_PCT)
        return None

    def get_trailing_stop_price(self) -> Optional[float]:
        if self.highest_price:
            return self.highest_price * (1 - Config.TRAILING_STOP_PCT)
        return None

    def is_trailing_active(self, current_price: float) -> bool:
        if self.entry_price:
            return current_price > self.entry_price * (1 + Config.TRAILING_ACTIVATION_PCT)
        return False


class PTJBot:
    """Paul Tudor Jones 추세추종 봇"""

    def __init__(self):
        self.api = CoinoneAPI(Config.COINONE_ACCESS_TOKEN, Config.COINONE_SECRET_KEY)
        self.position = PositionManager()
        self.trade_count = 0
        self.win_count = 0
        self.start_time = datetime.now()
        logger.info("🏆 PTJ Trading Bot 초기화 완료")

    def get_ohlcv(self) -> Optional[pd.DataFrame]:
        """OHLCV 데이터 조회"""
        try:
            df = self.api.get_candles(Config.TICKER, interval="1d", limit=300)
            if df is None or len(df) < Config.MA_PERIOD:
                logger.error(f"충분한 데이터가 없습니다. 필요: {Config.MA_PERIOD}")
                return None
            return df
        except Exception as e:
            logger.error(f"OHLCV 조회 실패: {e}")
            return None

    def calculate_signals(self, df: pd.DataFrame) -> Dict:
        """PTJ 신호 계산"""
        # 이동평균 계산
        df['ma_200'] = df['close'].rolling(window=Config.MA_PERIOD).mean()
        df['ma_50'] = df['close'].rolling(window=Config.CONFIRMATION_MA).mean()

        current_price = df['close'].iloc[-1]
        ma_200 = df['ma_200'].iloc[-1]
        ma_50 = df['ma_50'].iloc[-1]

        prev_price = df['close'].iloc[-2]
        prev_ma_200 = df['ma_200'].iloc[-2]

        # PTJ 추세 판단
        above_200ma = current_price > ma_200
        ma_50_above_200 = ma_50 > ma_200

        # 매수 신호: 가격이 200MA 위로 돌파 + 50MA가 200MA 위
        buy_signal = (prev_price <= prev_ma_200) and (current_price > ma_200) and ma_50_above_200

        # 강한 상승 추세: 가격 > 50MA > 200MA
        strong_uptrend = current_price > ma_50 > ma_200

        # 매도 신호: 가격이 200MA 아래로 하락
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
        """잔고 조회"""
        try:
            result = self.api.get_balance()
            if result.get('result') != 'success':
                return 0, 0

            # balances는 리스트 형태로 반환됨
            balances_list = result.get('balances', [])
            balances = {b['currency'].upper(): b for b in balances_list}
            
            krw = float(balances.get('KRW', {}).get('available', 0))
            coin = float(balances.get(Config.TICKER.upper(), {}).get('available', 0))
            return krw, coin
        except Exception as e:
            logger.error(f"잔고 조회 실패: {e}")
            return 0, 0

    def get_current_price(self) -> Optional[float]:
        """현재가 조회"""
        try:
            result = self.api.get_ticker(Config.TICKER)
            if result.get('result') != 'success':
                return None
            return float(result.get('tickers', [{}])[0].get('last', 0))
        except Exception as e:
            logger.error(f"현재가 조회 실패: {e}")
            return None

    def buy(self, reason: str) -> bool:
        """매수 실행"""
        try:
            krw_balance, _ = self.get_balance()
            if krw_balance < 10000:
                logger.warning(f"원화 잔고 부족: {krw_balance:,.0f}원")
                return False

            invest_amount = krw_balance * Config.INVEST_RATIO
            current_price = self.get_current_price()

            if current_price is None:
                return False

            result = self.api.buy_market_order(Config.TICKER, invest_amount)

            if result.get('result') == 'success':
                self.position.enter_position(current_price)
                msg = f"🟢 <b>매수 완료</b> [{reason}]\n가격: {current_price:,.0f}원\n금액: {invest_amount:,.0f}원"
                logger.info(msg.replace('<b>', '').replace('</b>', ''))
                send_telegram(msg)
                return True
            else:
                logger.error(f"매수 실패: {result}")
                return False

        except Exception as e:
            logger.error(f"매수 오류: {e}")
            return False

    def sell(self, reason: str) -> bool:
        """매도 실행"""
        try:
            _, coin_balance = self.get_balance()
            current_price = self.get_current_price()

            if coin_balance <= 0 or current_price is None:
                logger.warning("매도할 코인이 없습니다")
                return False

            result = self.api.sell_market_order(Config.TICKER, coin_balance)

            if result.get('result') == 'success':
                entry_price = self.position.entry_price
                profit_pct = ((current_price - entry_price) / entry_price * 100) if entry_price else 0

                self.trade_count += 1
                if profit_pct > 0:
                    self.win_count += 1

                emoji = "✅" if profit_pct > 0 else "❌"
                msg = f"🔴 <b>매도 완료</b> [{reason}]\n가격: {current_price:,.0f}원\n수익률: {emoji} {profit_pct:+.2f}%"
                logger.info(msg.replace('<b>', '').replace('</b>', ''))
                send_telegram(msg)

                self.position.exit_position()
                return True
            else:
                logger.error(f"매도 실패: {result}")
                return False

        except Exception as e:
            logger.error(f"매도 오류: {e}")
            return False

    def check_exit_conditions(self, current_price: float, signals: Dict) -> Tuple[bool, str]:
        """청산 조건 확인 (PTJ 스타일)"""
        if not self.position.in_position:
            return False, ""

        self.position.update_highest(current_price)

        # 1. 손절 (7%)
        stop_loss_price = self.position.get_stop_loss_price()
        if stop_loss_price and current_price <= stop_loss_price:
            return True, "Stop Loss (7%)"

        # 2. 익절 (15%)
        take_profit_price = self.position.get_take_profit_price()
        if take_profit_price and current_price >= take_profit_price:
            # 익절 도달 후에는 트레일링 스탑으로 전환
            pass

        # 3. 트레일링 스탑 (8% 수익 이상시 활성화)
        if self.position.is_trailing_active(current_price):
            trailing_stop_price = self.position.get_trailing_stop_price()
            if trailing_stop_price and current_price <= trailing_stop_price:
                return True, "Trailing Stop (10%)"

        # 4. 200MA 하향 돌파
        if signals['sell_signal']:
            return True, "Below 200 MA"

        return False, ""

    def get_status_message(self, signals: Dict) -> str:
        """상태 메시지 생성"""
        krw_balance, coin_balance = self.get_balance()
        current_price = signals['current_price']
        total_value = krw_balance + coin_balance * current_price

        trend = "🟢 BULL" if signals['above_200ma'] else "🔴 BEAR"
        strength = "💪 Strong" if signals['strong_uptrend'] else ""

        if self.position.in_position and self.position.entry_price:
            pnl = (current_price - self.position.entry_price) / self.position.entry_price * 100
            pnl_emoji = "📈" if pnl > 0 else "📉"
            position_status = f"LONG ({pnl_emoji} {pnl:+.2f}%)"
            stop_loss = self.position.get_stop_loss_price()
            stop_info = f"손절: {stop_loss:,.0f}원 (-7%)"
        else:
            position_status = "CASH (대기)"
            stop_info = "-"

        return f"""
<b>🏆 PTJ Bot 상태</b>
━━━━━━━━━━━━━━━
📊 <b>시장</b>
  가격: {current_price:,.0f}원
  200 MA: {signals['ma_200']:,.0f}
  50 MA: {signals['ma_50']:,.0f}
  추세: {trend} {strength}
━━━━━━━━━━━━━━━
💼 <b>포지션</b>: {position_status}
  {stop_info}
━━━━━━━━━━━━━━━
💰 <b>잔고</b>
  KRW: {krw_balance:,.0f}원
  {Config.TICKER}: {coin_balance:.8f}
  총: {total_value:,.0f}원
"""

    def run_once(self):
        """매매 로직 1회 실행"""
        logger.info("=" * 50)
        logger.info("📊 PTJ 시장 분석")

        df = self.get_ohlcv()
        if df is None:
            return

        signals = self.calculate_signals(df)
        current_price = signals['current_price']

        logger.info(f"현재가: {current_price:,.0f}원")
        logger.info(f"200 MA: {signals['ma_200']:,.0f}")
        logger.info(f"50 MA: {signals['ma_50']:,.0f}")
        logger.info(f"추세: {'🟢 BULL' if signals['above_200ma'] else '🔴 BEAR'}")

        krw_balance, coin_balance = self.get_balance()
        has_position = coin_balance * current_price > 10000

        if has_position and not self.position.in_position:
            logger.info("기존 포지션 발견, 상태 복구")
            self.position.enter_position(current_price)
        elif not has_position and self.position.in_position:
            logger.info("포지션 없음, 상태 초기화")
            self.position.exit_position()

        logger.info(f"💰 잔고: {krw_balance:,.0f}원 / {coin_balance:.8f} {Config.TICKER}")

        if self.position.in_position:
            should_exit, reason = self.check_exit_conditions(current_price, signals)
            if should_exit:
                logger.info(f"🔴 청산 신호: {reason}")
                self.sell(reason)
            else:
                if self.position.entry_price:
                    pnl = (current_price - self.position.entry_price) / self.position.entry_price * 100
                    logger.info(f"손익: {pnl:+.2f}% | 손절가: {self.position.get_stop_loss_price():,.0f}원")
        else:
            if signals['buy_signal'] or (signals['strong_uptrend'] and signals['above_200ma']):
                reason = "200 MA Breakout" if signals['buy_signal'] else "Strong Uptrend"
                logger.info(f"🟢 매수 신호: {reason}")
                self.buy(reason)
            else:
                logger.info("대기 중... (200 MA 위 돌파 대기)")

    def run(self):
        """메인 루프"""
        logger.info("🏆 PTJ Trading Bot 시작")
        logger.info(f"전략: 200 MA 추세추종")
        logger.info(f"손절: {Config.STOP_LOSS_PCT*100}%, 트레일링: {Config.TRAILING_STOP_PCT*100}%")

        start_msg = f"""
<b>🏆 PTJ Bot 시작</b>
━━━━━━━━━━━━━━━
전략: 200 MA 추세추종
손절: {Config.STOP_LOSS_PCT*100}%
트레일링: {Config.TRAILING_STOP_PCT*100}%
━━━━━━━━━━━━━━━
"Play great defense"
- Paul Tudor Jones
"""
        send_telegram(start_msg)

        self.run_once()

        while True:
            try:
                time.sleep(Config.CHECK_INTERVAL)
                self.run_once()

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
    ╔══════════════════════════════════════════╗
    ║  🏆 Paul Tudor Jones Trading Bot         ║
    ║  "Play great defense, not offense"       ║
    ╚══════════════════════════════════════════╝
    """)

    if not Config.COINONE_ACCESS_TOKEN:
        print("⚠️  .env 파일에서 API 키를 설정해주세요!")
        print("   코인원 API 발급: https://coinone.co.kr/developer/app")
        return

    bot = PTJBot()
    bot.run()


if __name__ == "__main__":
    main()
