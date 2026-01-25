"""
🏆 Paul Tudor Jones 전략 백테스트
200일 이동평균선 추세추종 전략
"""

import pybithumb  # 빗썸 데이터로 백테스트 (코인원은 과거 데이터 제한)
import pandas as pd
import numpy as np
from datetime import datetime

# PTJ 설정
MA_PERIOD = 200
CONFIRMATION_MA = 50
STOP_LOSS_PCT = 0.07
TAKE_PROFIT_PCT = 0.15
TRAILING_STOP_PCT = 0.10
TRAILING_ACTIVATION_PCT = 0.08
COMMISSION = 0.001


def run_backtest():
    print("📊 데이터 조회 중...")
    df = pybithumb.get_ohlcv("BTC", interval="day")

    if df is None or len(df) < MA_PERIOD + 10:
        print("데이터 조회 실패")
        return None

    print(f"✅ {len(df)}일치 데이터 로드")

    # MA 계산
    df['ma_200'] = df['close'].rolling(window=MA_PERIOD).mean()
    df['ma_50'] = df['close'].rolling(window=CONFIRMATION_MA).mean()

    # 신호
    df['above_200ma'] = df['close'] > df['ma_200']
    df['ma_cross_up'] = (df['close'].shift(1) <= df['ma_200'].shift(1)) & (df['close'] > df['ma_200'])
    df['ma_cross_down'] = (df['close'].shift(1) >= df['ma_200'].shift(1)) & (df['close'] < df['ma_200'])
    df['strong_uptrend'] = (df['close'] > df['ma_50']) & (df['ma_50'] > df['ma_200'])

    # 백테스트
    initial_capital = 10000000
    capital = initial_capital
    position = 0
    entry_price = 0
    highest_price = 0

    trades = []
    yearly_stats = {}

    for i in range(MA_PERIOD, len(df)):
        row = df.iloc[i]
        date = df.index[i]
        price = row['close']
        year = date.year

        if position > 0:
            if price > highest_price:
                highest_price = price

            should_exit = False
            exit_reason = ""

            # 손절 7%
            if price <= entry_price * (1 - STOP_LOSS_PCT):
                should_exit = True
                exit_reason = "Stop Loss (7%)"

            # 트레일링 스탑 (8% 수익 이상시)
            if not should_exit and price > entry_price * (1 + TRAILING_ACTIVATION_PCT):
                if price <= highest_price * (1 - TRAILING_STOP_PCT):
                    should_exit = True
                    exit_reason = "Trailing Stop (10%)"

            # 200MA 하향 돌파
            if not should_exit and row['ma_cross_down']:
                should_exit = True
                exit_reason = "Below 200 MA"

            if should_exit:
                sell_value = position * price * (1 - COMMISSION)
                profit_pct = (price - entry_price) / entry_price * 100

                trades.append({
                    'entry_date': entry_date,
                    'exit_date': date,
                    'entry_price': entry_price,
                    'exit_price': price,
                    'profit_pct': profit_pct,
                    'reason': exit_reason
                })

                capital = sell_value
                position = 0
                entry_price = 0
                highest_price = 0

        else:
            # 매수 조건: 200MA 돌파 또는 강한 상승추세
            buy_signal = row['ma_cross_up'] or (row['strong_uptrend'] and row['above_200ma'] and df.iloc[i-1]['above_200ma'] == False)

            if buy_signal:
                position = capital * (1 - COMMISSION) / price
                entry_price = price
                highest_price = price
                entry_date = date
                capital = 0

        # 연도별 자산
        total_value = capital + position * price
        yearly_stats[year] = total_value

    # 마지막 포지션 청산
    if position > 0:
        final_price = df['close'].iloc[-1]
        sell_value = position * final_price * (1 - COMMISSION)
        profit_pct = (final_price - entry_price) / entry_price * 100

        trades.append({
            'entry_date': entry_date,
            'exit_date': df.index[-1],
            'entry_price': entry_price,
            'exit_price': final_price,
            'profit_pct': profit_pct,
            'reason': 'End of Data'
        })
        capital = sell_value

    # 결과 출력
    print("\n" + "=" * 60)
    print("📊 PTJ 전략 백테스트 결과")
    print("=" * 60)

    total_return = (capital / initial_capital - 1) * 100
    wins = [t for t in trades if t['profit_pct'] > 0]
    losses = [t for t in trades if t['profit_pct'] <= 0]

    print(f"초기 자본: {initial_capital:,.0f}원")
    print(f"최종 자본: {capital:,.0f}원")
    print(f"총 수익률: {total_return:+,.2f}%")
    print("-" * 60)
    print(f"총 거래: {len(trades)}회")
    print(f"승률: {len(wins)/len(trades)*100:.1f}%")
    print(f"평균 수익: {np.mean([t['profit_pct'] for t in wins]):+.2f}%")
    print(f"평균 손실: {np.mean([t['profit_pct'] for t in losses]):.2f}%")

    print("\n📋 거래 내역:")
    for i, t in enumerate(trades, 1):
        emoji = "✅" if t['profit_pct'] > 0 else "❌"
        print(f"{i:2}. {emoji} {t['entry_date'].strftime('%Y-%m-%d')} → {t['exit_date'].strftime('%Y-%m-%d')} | {t['profit_pct']:+7.2f}% | {t['reason']}")

    # 청산 사유별 통계
    print("\n📊 청산 사유별 통계:")
    reasons = {}
    for t in trades:
        r = t['reason']
        if r not in reasons:
            reasons[r] = {'count': 0, 'total': 0}
        reasons[r]['count'] += 1
        reasons[r]['total'] += t['profit_pct']

    for r, data in reasons.items():
        avg = data['total'] / data['count']
        print(f"  {r}: {data['count']}회, 평균 {avg:+.2f}%")

    return {
        'total_return': total_return,
        'final_capital': capital,
        'trades': trades,
        'num_trades': len(trades),
        'win_rate': len(wins) / len(trades) * 100
    }


if __name__ == "__main__":
    print("""
    ╔══════════════════════════════════════════╗
    ║  🏆 PTJ Strategy Backtest                ║
    ║  200 MA Trend Following                  ║
    ╚══════════════════════════════════════════╝
    """)

    results = run_backtest()
