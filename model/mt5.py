from __future__ import annotations

import argparse
import datetime as dt
import math
import sys
import pathlib
import time
import threading
from collections import deque

import backtrader as bt
import MetaTrader5 as mt5

# ──────────────────────────────────── CONFIG ────────────────────────────────────
DEFAULT_SYMBOL = "XAUUSD"
TERMINAL_PATH = pathlib.Path(r"C:\Program Files\MetaTrader 5\terminal64.exe")

# ────────────────────────────────────────────────────────────────────────────────

def init_mt5(login: int, password: str, server: str, path: pathlib.Path = TERMINAL_PATH):
    """Initialize connection to MT5 terminal"""
    if not mt5.initialize(path=str(path), login=login, password=password, server=server):
        print("MT5 initialization failed:", mt5.last_error())
        sys.exit(1)
    account = mt5.account_info()
    print(f"Connected successfully, account: {account.login}")


def shutdown_mt5():
    """Shutdown MT5 connection"""
    mt5.shutdown()


# ─────────────────────────── MT5 Live Data Feed ─────────────────────────────
class MT5LiveDataFeed(bt.feeds.DataBase):
    """Live data feed from MT5 - supports tick and minute bars"""

    params = (
        ('symbol', DEFAULT_SYMBOL),
        ('timeframe', mt5.TIMEFRAME_M1),  # default 1-minute bars
        ('historical_days', 15),          # days of history to preload
        ('tick_mode', False),             # True = tick mode, False = bar mode
        ('update_interval', 1.0),         # update interval in seconds
    )

    def __init__(self):
        super().__init__()
        # Data buffer
        self._data_queue = deque(maxlen=10000)
        self._last_tick_time = 0
        self._last_bar_time = 0
        # Thread control
        self._thread = None
        self._stop_event = threading.Event()
        self._data_ready = threading.Event()
        # Load historical data
        self._init_historical_data()
        print(f"📡 MT5 live data feed initialized: {self.p.symbol}")
        mode = 'Tick' if self.p.tick_mode else 'Bar'
        print(f"   Mode: {mode}, Timeframe: {self._timeframe_to_str(self.p.timeframe)}")

    def _timeframe_to_str(self, tf):
        """Convert timeframe constant to string"""
        mapping = {
            mt5.TIMEFRAME_M1: "1min",
            mt5.TIMEFRAME_M5: "5min",
            mt5.TIMEFRAME_M15: "15min",
            mt5.TIMEFRAME_M30: "30min",
            mt5.TIMEFRAME_H1: "1h",
            mt5.TIMEFRAME_H4: "4h",
            mt5.TIMEFRAME_D1: "1d"
        }
        return mapping.get(tf, f"Unknown({tf})")

    def _init_historical_data(self):
        """Load historical bars into buffer"""
        if self.p.historical_days <= 0:
            print("⚠️ historical_days <= 0, skipping history load")
            return
        now = dt.datetime.now()
        start = now - dt.timedelta(days=self.p.historical_days)
        rates = mt5.copy_rates_range(self.p.symbol, self.p.timeframe, start, now)
        if rates is None or len(rates) == 0:
            print(f"Failed to load historical data for {self.p.symbol}")
            return
        for rate in rates:
            self._data_queue.append({
                'datetime': dt.datetime.fromtimestamp(rate['time']),
                'open': rate['open'], 'high': rate['high'],
                'low': rate['low'], 'close': rate['close'],
                'volume': rate['tick_volume'], 'openinterest': 0
            })
        print(f"📊 Loaded {len(rates)} historical bars")

    def start(self):
        """Start the live data thread"""
        if not self._thread or not self._thread.is_alive():
            self._stop_event.clear()
            self._thread = threading.Thread(target=self._data_thread, daemon=True)
            self._thread.start()
            print("🚀 Live data feed started")

    def stop(self):
        """Stop the live data thread"""
        if self._thread and self._thread.is_alive():
            self._stop_event.set()
            self._thread.join(timeout=5)
            print("⏹️ Live data feed stopped")

    def _data_thread(self):
        """Thread fetching live data"""
        print(f"📡 Data thread running - {self.p.symbol}")
        while not self._stop_event.is_set():
            if self.p.tick_mode:
                self._fetch_tick_data()
            else:
                self._fetch_bar_data()
            time.sleep(self.p.update_interval)
        print("📡 Data thread exiting")

    def _fetch_tick_data(self):
        """Fetch latest tick and append to buffer"""
        tick = mt5.symbol_info_tick(self.p.symbol)
        if not tick or tick.time <= self._last_tick_time:
            return
        self._last_tick_time = tick.time
        self._data_queue.append({
            'datetime': dt.datetime.fromtimestamp(tick.time),
            'open': tick.bid, 'high': tick.bid,
            'low': tick.bid, 'close': tick.bid,
            'volume': 1, 'openinterest': 0
        })
        self._data_ready.set()

    def _fetch_bar_data(self):
        """Fetch latest 2 bars and keep the newest"""
        rates = mt5.copy_rates_from_pos(self.p.symbol, self.p.timeframe, 0, 2)
        if not rates or len(rates) < 1:
            return
        latest = rates[-1]
        if latest['time'] <= self._last_bar_time:
            return
        self._last_bar_time = latest['time']
        self._data_queue.append({
            'datetime': dt.datetime.fromtimestamp(latest['time']),
            'open': latest['open'], 'high': latest['high'],
            'low': latest['low'], 'close': latest['close'],
            'volume': latest['tick_volume'], 'openinterest': 0
        })
        self._data_ready.set()
        dt0 = dt.datetime.fromtimestamp(latest['time'])
        print(f"📊 New bar: {dt0} O={latest['open']:.2f} H={latest['high']:.2f} L={latest['low']:.2f} C={latest['close']:.2f}")

    def _load(self):
        """Load next data point for Backtrader"""
        if self._data_queue:
            bar = self._data_queue.popleft()
            self.lines.datetime[0] = bt.date2num(bar['datetime'])
            self.lines.open[0] = bar['open']
            self.lines.high[0] = bar['high']
            self.lines.low[0] = bar['low']
            self.lines.close[0] = bar['close']
            self.lines.volume[0] = bar['volume']
            self.lines.openinterest[0] = bar['openinterest']
            return True
        if self._data_ready.wait(timeout=1.0):
            self._data_ready.clear()
            return self._load()
        return None

    def islive(self):
        """Indicate this is a live feed"""
        return True


# ─────────────────────────── Real-Time Trading Strategy ──────────────────────────
class LiveTradingStrategy(bt.Strategy):
    params = dict(
        fast=20, slow=50, risk_pct=0.02, atr_period=14,
        stop_atr_mult=2.0, take_profit_mult=3.0,
        symbol=DEFAULT_SYMBOL, lot_min=0.01, lot_max=10.0,
        max_positions=1
    )

    def __init__(self):
        self.sma_fast = bt.ind.SMA(self.data.close, period=self.p.fast)
        self.sma_slow = bt.ind.SMA(self.data.close, period=self.p.slow)
        self.crossover = bt.ind.CrossOver(self.sma_fast, self.sma_slow)
        self.atr = bt.ind.ATR(self.data, period=self.p.atr_period)
        self.position_count = 0
        self.last_signal_minute = None

    def log(self, msg):
        dtstr = self.data.datetime.datetime(0).strftime("%Y-%m-%d %H:%M:%S")
        print(f"[{dtstr}] {msg}")

    def next(self):
        now = self.data.datetime.datetime(0)
        price = self.data.close[0]
        minute = now.replace(second=0, microsecond=0)
        if minute == self.last_signal_minute:
            return
        # wait for indicators
        if len(self.sma_slow) < self.p.slow:
            return
        # get account balance
        info = mt5.account_info()
        if not info:
            self.log("Cannot fetch account info")
            return
        balance = info.balance
        # signal: golden cross open long
        if self.crossover > 0 and self.position_count < self.p.max_positions:
            self._open_long(price, balance, now)
            self.last_signal_minute = minute
        # signal: death cross close all
        elif self.crossover < 0:
            self._close_all("DeathCross")
            self.last_signal_minute = minute

    def _open_long(self, price, balance, now):
        if not math.isfinite(self.atr[0]) or self.atr[0] <= 0:
            return
        try:
            stop_dist = self.atr[0] * self.p.stop_atr_mult
            risk_amt = balance * self.p.risk_pct
            sym_info = mt5.symbol_info(self.p.symbol)
            if not sym_info:
                raise RuntimeError("No symbol info")
            order_type = mt5.ORDER_TYPE_BUY
            tick = mt5.symbol_info_tick(self.p.symbol)
            if not tick:
                return
            exec_price = tick.ask
            margin_per_lot = mt5.order_calc_margin(order_type, self.p.symbol, 1.0, exec_price)
            lot = risk_amt / (stop_dist * sym_info.trade_contract_size)
            if margin_per_lot > 0:
                free = mt5.account_info().margin_free
                lot = min(lot, free / margin_per_lot)
            step, vmin, vmax = sym_info.volume_step, sym_info.volume_min, sym_info.volume_max
            lot = max(vmin, min(lot, vmax))
            lot = math.floor(lot/step) * step
            lot = round(lot,2)
            sl_pts = max(int(stop_dist/sym_info.point), sym_info.trade_stops_level+5)
            tp_pts = sl_pts * self.p.take_profit_mult
            res = self._send_order(self.p.symbol, lot, mt5.ORDER_TYPE_BUY, sl_pts, tp_pts, now)
            if res.retcode == mt5.TRADE_RETCODE_DONE:
                self.position_count += 1
                self.log(f"Open long: {lot:.2f}@{res.price:.5f} SL={sl_pts} TP={tp_pts}")
            else:
                self.log(f"Open failed: {res.comment}")
        except Exception as e:
            self.log(f"Open error: {e}")

    def _close_all(self, reason):
        pos = mt5.positions_get(symbol=self.p.symbol)
        if not pos:
            return
        for p in pos:
            typ = mt5.ORDER_TYPE_SELL if p.type==mt5.POSITION_TYPE_BUY else mt5.ORDER_TYPE_BUY
            res = self._send_order(self.p.symbol, p.volume, typ, comment=reason)
            if res.retcode==mt5.TRADE_RETCODE_DONE:
                self.position_count = max(0, self.position_count-1)
                self.log(f"Closed: {reason} PnL={p.profit:.2f}")
            else:
                self.log(f"Close failed: {res.comment}")

    def _send_order(self, symbol, lot, typ, sl_points=None, tp_points=None, now=None, comment=""):
        try:
            tick = mt5.symbol_info_tick(symbol)
            if not tick:
                raise RuntimeError("No tick data")
            price = tick.ask if typ==mt5.ORDER_TYPE_BUY else tick.bid
            info = mt5.symbol_info(symbol)
            req = {"action": mt5.TRADE_ACTION_DEAL, "symbol": symbol,
                   "volume": lot, "type": typ, "price": round(price, info.digits),
                   "deviation":20, "magic":20250620, "comment":comment,
                   "type_time":mt5.ORDER_TIME_GTC, "type_filling":mt5.ORDER_FILLING_IOC}
            if sl_points:
                req["sl"] = round(price - sl_points*info.point, info.digits) if typ==mt5.ORDER_TYPE_BUY else round(price + sl_points*info.point, info.digits)
            if tp_points:
                req["tp"] = round(price + tp_points*info.point, info.digits) if typ==mt5.ORDER_TYPE_BUY else round(price - tp_points*info.point, info.digits)
            return mt5.order_send(req)
        except Exception as e:
            self.log(f"Order error: {e}")
            return None


def run_live_trading(args):
    """Run live trading system"""
    print("Starting live trading system...")
    init_mt5(args.login, args.password, args.server)
    cerebro = bt.Cerebro()
    live = MT5LiveDataFeed(
        symbol=args.symbol,
        timeframe=getattr(mt5, f'TIMEFRAME_{args.timeframe}'),
        tick_mode=True,
        update_interval=args.update_interval,
        historical_days=0
    )
    cerebro.adddata(live)
    cerebro.addstrategy(LiveTradingStrategy,
                        symbol=args.symbol,
                        fast=args.fast,
                        slow=args.slow,
                        risk_pct=args.risk_pct)
    live.start()
    print("Live trading started, press Ctrl+C to stop...")
    try:
        cerebro.run()
    except KeyboardInterrupt:
        print("⏹Trading stopped by user")
    except Exception as e:
        print(f"System error: {e}")
    finally:
        live.stop()
        shutdown_mt5()
        print("System exited safely")

if __name__ == "__main__":
    parser = argparse.ArgumentParser("MT5 Live Trading")
    parser.add_argument("--login", type=int, default=1234)   # please input your account(default='')
    parser.add_argument("--password", type=str, default="1234")          # your password
    parser.add_argument("--server", type=str, default="MetaQuotes-Demo")
    parser.add_argument("--symbol", type=str, default="XAUUSD")
    parser.add_argument("--timeframe", type=str, default="M1",
                        choices=["M1","M5","M15","M30","H1","H4","D1"])
    parser.add_argument("--update_interval", type=float, default=1.0)
    parser.add_argument("--fast", type=int, default=20)
    parser.add_argument("--slow", type=int, default=50)
    parser.add_argument("--risk_pct", type=float, default=0.02)
    args = parser.parse_args()
    run_live_trading(args)
