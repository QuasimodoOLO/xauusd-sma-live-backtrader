import backtrader as bt
import datetime as dt
import MetaTrader5 as mt5
import pandas as pd

CONTRACT_SIZE = 100  # 1 standard lot of XAUUSD equals 100 ounces

# 1. Fetch MT5 data
def get_mt5_data(symbol="XAUUSD", timeframe=mt5.TIMEFRAME_D1,
                 start_date=dt.datetime(2015, 1, 1),
                 end_date=dt.datetime(2025, 1, 1)):
    """Fetch historical rates from MetaTrader 5"""
    if not mt5.initialize():
        raise SystemExit("MT5 initialization failed")

    try:
        rates = mt5.copy_rates_range(symbol, timeframe, start_date, end_date)
        if rates is None or len(rates) == 0:
            raise ValueError(f"Failed to retrieve data for {symbol}")

        df = pd.DataFrame(rates)
        df['datetime'] = pd.to_datetime(df['time'], unit='s')
        df.set_index('datetime', inplace=True)

        print(f"Data fetched: {len(df)} bars from {df.index[0]} to {df.index[-1]}")
        return df

    finally:
        mt5.shutdown()


# 2. MT5 data feed converter
class MT5DataFeed(bt.feeds.PandasData):
    """Convert MT5 DataFrame to Backtrader feed"""
    lines = ('openinterest',)

    params = dict(
        datetime=None,       # use index as datetime
        open='open',
        high='high',
        low='low',
        close='close',
        volume='tick_volume',
        openinterest=-1      # MT5 does not provide open interest
    )


# 3. Enhanced SMA Crossover Strategy
class EnhancedSmaCross(bt.Strategy):
    params = dict(
        fast=20,                # fast SMA period
        slow=50,                # slow SMA period
        risk_pct=0.02,          # risk 2% of portfolio per trade
        atr_period=14,          # ATR period
        stop_atr_mult=2.0,      # stop-loss multiple of ATR
        take_profit_mult=3.0    # take-profit multiple of ATR
    )

    def __init__(self):
        # indicators
        self.sma_fast = bt.ind.SMA(self.data.close, period=self.p.fast)
        self.sma_slow = bt.ind.SMA(self.data.close, period=self.p.slow)
        self.crossover = bt.ind.CrossOver(self.sma_fast, self.sma_slow)
        self.atr = bt.ind.ATR(self.data, period=self.p.atr_period)

        self.order = None
        self.stop_price = 0
        self.target_price = 0

    def log(self, txt, dt=None):
        """Log a message with timestamp"""
        dt = dt or self.datas[0].datetime.date(0)
        print(f'{dt.isoformat()}: {txt}')

    def notify_order(self, order):
        """Order status notifications"""
        if order.status in [order.Submitted, order.Accepted]:
            return

        if order.status == order.Completed:
            if order.isbuy():
                self.log(f'BUY EXECUTED, Price: {order.executed.price:.2f}, Size: {order.executed.size:.2f}, Comm: {order.executed.comm:.2f}')
            else:
                self.log(f'SELL EXECUTED, Price: {order.executed.price:.2f}, Size: {order.executed.size:.2f}, Comm: {order.executed.comm:.2f}')
        elif order.status in [order.Canceled, order.Margin, order.Rejected]:
            self.log('Order Canceled/Margin/Rejected')

        self.order = None

    def notify_trade(self, trade):
        """Trade profit/loss notifications"""
        if not trade.isclosed:
            return
        self.log(f'TRADE CLOSED, PnL: {trade.pnl:.2f}, Net PnL: {trade.pnlcomm:.2f}')

    def next(self):
        """Strategy logic for each new bar"""
        if self.order:
            return  # waiting for pending order

        price = self.data.close[0]
        portfolio_value = self.broker.getvalue()

        # Entry logic
        if not self.position:
            if self.crossover > 0:  # golden cross
                stop_dist = self.atr[0] * self.p.stop_atr_mult
                risk_amount = portfolio_value * self.p.risk_pct
                lot = risk_amount / (stop_dist * CONTRACT_SIZE)
                lot = max(0.01, min(lot, 10.0))

                self.order = self.buy(size=lot)
                self.stop_price = price - stop_dist
                self.target_price = price + stop_dist * self.p.take_profit_mult
                self.log(f'BUY SIGNAL, Size: {lot:.2f}, Stop: {self.stop_price:.2f}, Target: {self.target_price:.2f}')

        # Exit logic
        else:
            if self.crossover < 0:
                self.log('Death cross, closing position')
                self.order = self.close()
            elif price <= self.stop_price:
                self.log('Hit stop-loss, closing position')
                self.order = self.close()
            elif price >= self.target_price:
                self.log('Hit take-profit, closing position')
                self.order = self.close()


class FixedLotCommission(bt.CommInfoBase):
    """
    Charge fixed commission per lot :
      - $7 per lot, both on entry and exit
    """
    params = dict(
        lot=1.0,
        fee_per_lot=7.0,
        leverage=100,
        stocklike=False
    )

    def _getcommission(self, size, price, pseudoexec):
        return abs(size) * self.p.fee_per_lot


# 4. Custom trade analyzer
class TradeAnalyzer(bt.analyzers.Analyzer):
    def __init__(self):
        self.trades = []

    def notify_trade(self, trade):
        if trade.isclosed:
            self.trades.append({
                'pnl': trade.pnl,
                'pnlcomm': trade.pnlcomm,
                'size': trade.size,
                'price': trade.price,
                'value': trade.value
            })

    def get_analysis(self):
        if not self.trades:
            return {}
        pnls = [t['pnlcomm'] for t in self.trades]
        wins = [p for p in pnls if p > 0]
        losses = [p for p in pnls if p < 0]
        return {
            'total_trades': len(self.trades),
            'winning_trades': len(wins),
            'losing_trades': len(losses),
            'win_rate': len(wins)/len(self.trades) if self.trades else 0,
            'avg_win': sum(wins)/len(wins) if wins else 0,
            'avg_loss': sum(losses)/len(losses) if losses else 0,
            'total_pnl': sum(pnls),
            'max_win': max(pnls) if pnls else 0,
            'max_loss': min(pnls) if pnls else 0,
            'profit_factor': abs(sum(wins)/sum(losses)) if losses else float('inf')
        }

# 5. Main backtest runner
def run_backtest():
    print("="*50)
    print("XAUUSD SMA Crossover Strategy Backtest")
    print("="*50)

    # load data
    try:
        df = get_mt5_data()
    except Exception as e:
        print(f"Data fetch error: {e}")
        return

    cerebro = bt.Cerebro()

    # Simulate spread/slippage
    spread = 0.25  # $0.25
    approx_price = 2000
    spread_perc = spread / approx_price
    cerebro.broker.set_slippage_perc(perc=spread_perc/2,
                                     slip_open=True, slip_limit=True,
                                     slip_match=True, slip_out=True)

    cerebro.broker.addcommissioninfo(FixedLotCommission())

    data = MT5DataFeed(dataname=df)
    cerebro.adddata(data)
    cerebro.addstrategy(EnhancedSmaCross)
    cerebro.broker.setcash(10000.0)

    cerebro.addanalyzer(bt.analyzers.SharpeRatio, _name='sharpe')
    cerebro.addanalyzer(bt.analyzers.DrawDown, _name='drawdown')
    cerebro.addanalyzer(bt.analyzers.Returns, _name='returns')
    cerebro.addanalyzer(TradeAnalyzer, _name='trades')

    start_val = cerebro.broker.getvalue()
    print(f"Start Portfolio Value: ${start_val:.2f}")
    print("-"*50)

    results = cerebro.run()
    strat = results[0]

    final_val = cerebro.broker.getvalue()
    total_ret = (final_val - start_val)/start_val*100

    print("-"*50)
    print("Backtest Results:")
    print(f"Final Portfolio Value: ${final_val:.2f}")
    print(f"Total Return: {total_ret:.2f}%")

    # Sharpe
    try:
        sr = strat.analyzers.sharpe.get_analysis().get('sharperatio', 0)
        print(f"Sharpe Ratio: {sr:.3f}")
    except:
        print("Sharpe Ratio: N/A")

    dd = strat.analyzers.drawdown.get_analysis().get('max', {}).get('drawdown', 0)
    print(f"Max Drawdown: {dd:.2f}%")

    ta = strat.analyzers.trades.get_analysis()
    print(f"Total Trades: {ta.get('total_trades', 0)}")
    print(f"Win Rate: {ta.get('win_rate', 0):.2%}")
    print(f"Avg Win: ${ta.get('avg_win', 0):.2f}")
    print(f"Avg Loss: ${ta.get('avg_loss', 0):.2f}")
    print(f"Max Win: ${ta.get('max_win', 0):.2f}")
    print(f"Max Loss: ${ta.get('max_loss', 0):.2f}")
    pf = ta.get('profit_factor', 0)
    print(f"Profit Factor: {pf:.2f}")

    print("="*50)

    # plot
    try:
        print("Plotting...")
        cerebro.plot(style='candlestick', barup='green', bardown='red',
                     volup='lightgreen', voldown='lightcoral')
    except Exception as e:
        print(f"Plotting error: {e}")
        print("Is matplotlib installed?")

if __name__ == "__main__":
    run_backtest()
