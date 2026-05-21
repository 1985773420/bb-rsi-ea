# BB+RSI EA v6 — 量化交易系统

基于布林带+RSI的BTC-USDT永续合约量化交易系统，6年历史数据验证(2019-2026)，策略年化+1570亿%理论收益，全量历史从未爆仓。

## 系统架构

```
OKX REST API (每3秒轮询)
    │
    ▼
bb_rsi_ws_ea.py  ←→  SQLite (/var/lib/bb_rsi/data.db)
    │                      │
    ▼                      ▼
ea_watchdog.py       bb_rsi_dashboard.py (:8899)
```

## 环境要求

- Python 3.12+
- OKX Trade CLI (`npm install -g @okx_ai/okx-trade-cli`)
- sing-box 代理 (127.0.0.1:2080)
- SQLite3

## 快速部署

### 1. 克隆代码
```bash
git clone https://github.com/1985773420/bb-rsi-ea.git
cd bb-rsi-ea
```

### 2. 安装依赖
```bash
pip install websocket-client requests
npm install -g @okx_ai/okx-trade-cli
```

### 3. 配置OKX CLI
```bash
okx config
# 填入OKX API Key/Secret/Passphrase
# 国内环境需配置代理: proxy_url="http://127.0.0.1:2080"
```

### 4. 拉取历史数据
```bash
python3 fetch_swap_all.py
# 拉取BTC-USDT-SWAP全部15m K线至SQLite (~225k根, 约10分钟)
```

### 5. 启动系统
```bash
python3 ea_watchdog.py &
```
看门狗会自动启动EA和Dashboard。
- EA: 每3秒轮询REST API
- Dashboard: http://服务器IP:8899

### 6. 配置每周自动回测
```bash
crontab -e
# 添加: 0 3 * * 1 cd /path/to/ea && python3 weekly_backtest_update.py
```

## 策略参数

| 参数 | 值 | 说明 |
|------|-----|------|
| BB周期 | 20, 2σ | 布林带 |
| RSI周期 | 7 | 相对强弱指数 |
| RSI阈值 | 65/35 | 放宽信号 |
| ATR过滤 | 0.5(动态) | BB宽<8%→×1.8, 8-12%→×1.2, >12%→×0.8 |
| 止盈 | 0.8% | |
| 止损 | 0.4% | |
| 超时 | 24bar(6小时) | |
| 杠杆 | 15x | 逐仓 |
| 保证金 | 50% | |
| 品种 | BTC-USDT-SWAP | 永续合约 |

## 风险控制

- 动态杠杆: >$750→5x/30%, >$200→10x/40%, ≤$200→15x/50%
- 日内亏损保护: >15%触发冷却
- 连亏3周减半仓
- 每笔实际成本: 滑点万2×2 + 手续费万7 = 0.11%

## 数据存储

SQLite WAL模式, 8MB缓存, 主键索引:
```sql
btc_swap_15m (ts INT PRIMARY KEY, open REAL, high REAL, low REAL, close REAL)
```
数据: BTC-USDT-SWAP 15m, 2019-12 → 至今, ~225k根, ~26MB

## 回测验证

| 脚本 | 用途 |
|------|------|
| `multi_dimension_bt.py` | 全历史多维回测 |
| `quick_multi_bt.py` | 3h/6h/12h/24h/7d/30d快速回测 |
| `liquidation_check.py` | 全量爆仓检测 |
| `chop_analysis.py` | 震荡扫盘分析 |
| `weekly_backtest_update.py` | 每周自动回测+数据更新 |

### 6年全量回测结果(含滑点+手续费)

| 杠杆/保证金 | 最终余额 | 年化 | 最大回撤 | 爆仓 |
|------------|---------|------|---------|------|
| 15x/80% | $374万亿 | +1554亿% | 99.8% | 🟢否 |
| **15x/50%** | **$3.78万亿** | **+1570亿%** | **95.3%** | **🟢否** |
| 10x/60% | $1415亿 | +587亿% | 90.3% | 🟢否 |

## 状态文件

`/tmp/bb_rsi_state.json` — EA实时状态(供Dashboard读取):
```json
{
  "balance": 37.48,
  "position": {"side":"long","size":0.33,"entry_px":77121.2,"pnl_pct":0.00123,"pnl":0.31},
  "ws_connected": true,
  "daily_pnl": 0.0,
  "protections": {"max_daily_loss":-0.15,"cooldown":false}
}
```

## 注意事项

1. **必须用合约数据**: instId=BTC-USDT-SWAP, 非BTC-USDT现货
2. **回测必须含滑点+费**: 每笔0.11%成本, 不含则严重高估
3. **WS candle不可用**: 代理后帧损坏, 已用REST 3s轮询完全替代
4. **动态ATR**: 震荡市自动降低交易频率, 趋势市自动增加
5. **盈亏比>胜率**: 策略月度胜率仅35%, 靠少数趋势月暴赚

## 目录结构

```
bb-rsi-ea/
├── bb_rsi_ws_ea.py          # EA主程序 (REST实时轮询)
├── ea_watchdog.py            # 看门狗 进程守护
├── datastore.py              # SQLite存储模块
├── bb_rsi_dashboard.py       # Web仪表盘
├── fetch_swap_all.py         # 全量历史数据拉取
├── weekly_backtest_update.py # 每周自动回测
├── multi_dimension_bt.py     # 多维度回测工具
├── quick_multi_bt.py         # 多时段快速回测
├── liquidation_check.py      # 全量爆仓检测
├── chop_analysis.py          # 震荡扫盘分析
└── README.md
```
