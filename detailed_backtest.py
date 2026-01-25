"""
PTJ (Paul Tudor Jones) 전략 - 연도별/사이클별 상세 분석
200일 이동평균선 추세추종 전략
"""

import pybithumb
import pandas as pd
import numpy as np
from datetime import datetime
import json

# PTJ 설정
MA_PERIOD = 200
CONFIRMATION_MA = 50
STOP_LOSS_PCT = 0.07
TRAILING_STOP_PCT = 0.10
TRAILING_ACTIVATION_PCT = 0.08
COMMISSION = 0.001


def run_detailed_backtest():
    print("📊 데이터 조회 중...")
    df = pybithumb.get_ohlcv("BTC", interval="day")

    if df is None:
        print("데이터 조회 실패")
        return None

    print(f"✅ {len(df)}일치 데이터 로드")
    print(f"   기간: {df.index[0].strftime('%Y-%m-%d')} ~ {df.index[-1].strftime('%Y-%m-%d')}")

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
    yearly_equity = {}

    # 연도별 시작 자본 추적
    year_start_capital = {df.index[MA_PERIOD].year: initial_capital}
    current_year = df.index[MA_PERIOD].year

    for i in range(MA_PERIOD, len(df)):
        row = df.iloc[i]
        date = df.index[i]
        price = row['close']
        year = date.year

        # 연도 변경 시 시작 자본 기록
        if year != current_year:
            total_value = capital + position * price
            year_start_capital[year] = total_value
            current_year = year

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
                    'entry_year': entry_date.year,
                    'exit_year': date.year,
                    'entry_price': entry_price,
                    'exit_price': price,
                    'profit_pct': profit_pct,
                    'reason': exit_reason,
                    'capital_after': sell_value
                })

                capital = sell_value
                position = 0
                entry_price = 0
                highest_price = 0

        else:
            # 매수 조건
            buy_signal = row['ma_cross_up'] or (row['strong_uptrend'] and row['above_200ma'] and not df.iloc[i-1]['above_200ma'])

            if buy_signal:
                position = capital * (1 - COMMISSION) / price
                entry_price = price
                highest_price = price
                entry_date = date
                capital = 0

        # 연도별 자산 기록
        total_value = capital + position * price
        yearly_equity[year] = total_value

    # 마지막 포지션 청산
    if position > 0:
        final_price = df['close'].iloc[-1]
        sell_value = position * final_price * (1 - COMMISSION)
        profit_pct = (final_price - entry_price) / entry_price * 100

        trades.append({
            'entry_date': entry_date,
            'exit_date': df.index[-1],
            'entry_year': entry_date.year,
            'exit_year': df.index[-1].year,
            'entry_price': entry_price,
            'exit_price': final_price,
            'profit_pct': profit_pct,
            'reason': 'End of Data',
            'capital_after': sell_value
        })
        capital = sell_value

    # 연도별 수익률 계산
    years = sorted(yearly_equity.keys())
    yearly_stats = []

    for i, year in enumerate(years):
        if year in year_start_capital:
            start_cap = year_start_capital[year]
        else:
            start_cap = yearly_stats[-1]['end_capital'] if yearly_stats else initial_capital

        end_cap = yearly_equity[year]
        year_return = (end_cap / start_cap - 1) * 100 if start_cap > 0 else 0

        year_trades = [t for t in trades if t['exit_year'] == year]
        year_wins = [t for t in year_trades if t['profit_pct'] > 0]

        yearly_stats.append({
            'year': year,
            'start_capital': start_cap,
            'end_capital': end_cap,
            'return_pct': year_return,
            'num_trades': len(year_trades),
            'wins': len(year_wins),
            'win_rate': len(year_wins) / len(year_trades) * 100 if year_trades else 0
        })

    # 사이클 분석 (비트코인 반감기 기준)
    cycles = [
        {'name': '1차 사이클 (2013-2016)', 'start': 2013, 'end': 2016, 'halving': '2012-11'},
        {'name': '2차 사이클 (2016-2020)', 'start': 2016, 'end': 2020, 'halving': '2016-07'},
        {'name': '3차 사이클 (2020-2024)', 'start': 2020, 'end': 2024, 'halving': '2020-05'},
        {'name': '4차 사이클 (2024-현재)', 'start': 2024, 'end': 2026, 'halving': '2024-04'},
    ]

    cycle_stats = []
    for cycle in cycles:
        cycle_trades = [t for t in trades if cycle['start'] <= t['exit_year'] <= cycle['end']]
        cycle_years = [y for y in yearly_stats if cycle['start'] <= y['year'] <= cycle['end']]

        if cycle_years:
            start_cap = cycle_years[0]['start_capital']
            end_cap = cycle_years[-1]['end_capital']
            total_return = (end_cap / start_cap - 1) * 100 if start_cap > 0 else 0
        else:
            total_return = 0
            start_cap = 0
            end_cap = 0

        cycle_wins = [t for t in cycle_trades if t['profit_pct'] > 0]

        cycle_stats.append({
            'name': cycle['name'],
            'halving': cycle['halving'],
            'start_capital': start_cap,
            'end_capital': end_cap,
            'total_return': total_return,
            'num_trades': len(cycle_trades),
            'wins': len(cycle_wins),
            'win_rate': len(cycle_wins) / len(cycle_trades) * 100 if cycle_trades else 0
        })

    # 결과 출력
    print("\n" + "="*70)
    print("📊 PTJ 전략 - 연도별 수익률")
    print("="*70)
    print(f"{'연도':<8} {'시작자본':>15} {'종료자본':>15} {'수익률':>10} {'거래':>6} {'승률':>8}")
    print("-"*70)

    for y in yearly_stats:
        print(f"{y['year']:<8} {y['start_capital']:>15,.0f} {y['end_capital']:>15,.0f} {y['return_pct']:>+9.1f}% {y['num_trades']:>6} {y['win_rate']:>7.1f}%")

    print("\n" + "="*70)
    print("📊 PTJ 전략 - 사이클별 수익률 (반감기 기준)")
    print("="*70)

    for c in cycle_stats:
        print(f"\n{c['name']}")
        print(f"  반감기: {c['halving']}")
        print(f"  총 수익률: {c['total_return']:+,.1f}%")
        print(f"  거래: {c['num_trades']}회, 승률: {c['win_rate']:.1f}%")

    # 개별 거래 내역
    print("\n" + "="*70)
    print("📋 전체 거래 내역")
    print("="*70)

    for i, t in enumerate(trades, 1):
        emoji = "✅" if t['profit_pct'] > 0 else "❌"
        print(f"{i:2}. {emoji} {t['entry_date'].strftime('%Y-%m-%d')} → {t['exit_date'].strftime('%Y-%m-%d')} | {t['profit_pct']:+7.2f}% | {t['reason']}")

    # 청산 사유별 통계
    print("\n" + "="*70)
    print("📊 청산 사유별 통계")
    print("="*70)

    reasons = {}
    for t in trades:
        r = t['reason']
        if r not in reasons:
            reasons[r] = {'count': 0, 'total': 0, 'wins': 0}
        reasons[r]['count'] += 1
        reasons[r]['total'] += t['profit_pct']
        if t['profit_pct'] > 0:
            reasons[r]['wins'] += 1

    for r, data in reasons.items():
        avg = data['total'] / data['count']
        print(f"  {r}: {data['count']}회, 평균 {avg:+.2f}%, 승률 {data['wins']/data['count']*100:.0f}%")

    # 총 결과
    total_return = (capital / initial_capital - 1) * 100
    wins = [t for t in trades if t['profit_pct'] > 0]
    losses = [t for t in trades if t['profit_pct'] <= 0]

    print("\n" + "="*70)
    print(f"💰 최종 결과")
    print("="*70)
    print(f"초기 자본: {initial_capital:,.0f}원")
    print(f"최종 자본: {capital:,.0f}원")
    print(f"총 수익률: {total_return:+,.2f}%")
    print(f"총 거래: {len(trades)}회")
    print(f"승률: {len(wins)/len(trades)*100:.1f}% ({len(wins)}승 {len(losses)}패)")
    print(f"평균 수익: {np.mean([t['profit_pct'] for t in wins]):+.2f}%")
    print(f"평균 손실: {np.mean([t['profit_pct'] for t in losses]):.2f}%")

    return {
        'yearly_stats': yearly_stats,
        'cycle_stats': cycle_stats,
        'trades': trades,
        'reasons': reasons,
        'total_return': total_return,
        'final_capital': capital,
        'num_trades': len(trades),
        'win_rate': len(wins) / len(trades) * 100,
        'avg_win': np.mean([t['profit_pct'] for t in wins]),
        'avg_loss': np.mean([t['profit_pct'] for t in losses])
    }


if __name__ == "__main__":
    print("""
    ╔══════════════════════════════════════════╗
    ║  🏆 PTJ Strategy Detailed Backtest       ║
    ║  200 MA Trend Following                  ║
    ╚══════════════════════════════════════════╝
    """)

    results = run_detailed_backtest()

    if results:
        # JSON으로 저장
        output = {
            'yearly_stats': results['yearly_stats'],
            'cycle_stats': results['cycle_stats'],
            'total_return': results['total_return'],
            'final_capital': results['final_capital'],
            'num_trades': results['num_trades'],
            'win_rate': results['win_rate'],
            'trades': [
                {
                    'entry_date': t['entry_date'].strftime('%Y-%m-%d'),
                    'exit_date': t['exit_date'].strftime('%Y-%m-%d'),
                    'profit_pct': t['profit_pct'],
                    'reason': t['reason']
                }
                for t in results['trades']
            ]
        }

        with open('ptj_backtest_results.json', 'w') as f:
            json.dump(output, f, indent=2, ensure_ascii=False)

        print("\n📁 결과가 ptj_backtest_results.json에 저장되었습니다.")
