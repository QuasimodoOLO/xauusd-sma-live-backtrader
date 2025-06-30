# XAUUSD SMA Crossover - Backtrader

Backtrader-based **Gold (XAUUSD) SMA Crossover Strategy** 
Supports historical backtesting + MetaTrader 5 live automated trading with integrated ATR dynamic positions, stop-loss/take-profit and cost simulation.

| Modules | Backtesting | Live | 
|------|------|------| 
| Data feed | MT5 Historical | MT5 Tick / 1min Real Time | 
| Logic | 20/50 SMA Golden Cross Entry, ATR x 2 Stop Loss, ATR x 3 Take Profit | Same as Backtesting | 
| Risk Control | Risk per trade = 2% of account equity, Fixed $7/lot commission | Same as Backtesting |

## Highlights
- **Adaptive lot size**: dynamic calculation of positions based on ATR and account balance  
- **Spread + Slippage Simulation**: backtesting closer to the real deal  
- **Customized MT5 real-time data feed**: push to Backtrader in seconds  
- **Complete trading lifecycle**: order placement → automatically pending SL/TP → monitoring floating profit and loss  
- Built-in indicator analysis (Sharpe, Retracement, Win Rate, Profit Factor)

## Quick Start

```bash
# Clone the repository 
git clone https://github.com/<your username>/xauusd-sma-backtrader.git 
cd xauusd-sma-backtrader 
pip install -r requirements.txt # see dependencies below

# 1) Run backtest 
python backtest.py

# 2) Run live (default with demo account, please change to your own actually) 
python live_sma.py --login 123456 --password "passwd" --server "MetaQuotes-Demo"
----------------------------------------------------------------------------------------------
# XAUUSD SMA Crossover - Backtrader

基于 Backtrader 的 **黄金 (XAUUSD) 双均线交叉策略**  
支持历史回测 + MetaTrader 5 实盘自动交易，集成 ATR 动态仓位、止损止盈与成本模拟。

| 模块 | 回测 | 实盘 |
|------|------|------|
| 数据源 | MT5 历史报价 | MT5 Tick / 1min 实时 |
| 逻辑 | 20/50 SMA 金叉进场、ATR×2 止损、ATR×3 止盈 | 同回测 |
| 风控 | 每笔风险 = 账户净值 2%，固定 $7/lot 佣金 | 同回测 |

## 亮点
- **自适应手数**：根据 ATR 和账户余额动态计算仓位  
- **点差+滑点模拟**：回测更贴近真实成交  
- **自定义 MT5 实时数据 Feed**：秒级推送到 Backtrader  
- **完整交易生命周期**：下单→自动挂 SL/TP→监控浮动盈亏  
- 内置指标分析（Sharpe、回撤、胜率、Profit Factor）

## 快速开始

```bash
# 克隆仓库
git clone https://github.com/<你的用户名>/xauusd-sma-backtrader.git
cd xauusd-sma-backtrader
pip install -r requirements.txt   # 见下方依赖

# 1）跑回测
python backtest_sma.py

# 2）跑实盘（默认用演示账号，实际请改成自己的）
python live_sma.py --login 123456 --password "passwd" --server "MetaQuotes-Demo"
