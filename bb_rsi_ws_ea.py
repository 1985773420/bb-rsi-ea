#!/usr/bin/env python3
"""BB+RSI EA v6 — REST实时轮询版 (3s间隔, 替代WS candle)"""
import json, math, time, threading, subprocess, os, sys, requests
from datetime import datetime, timezone

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import datastore as db

# ===== 策略参数 =====
INST_ID = "BTC-USDT-SWAP"
TP_PCT = 0.008; SL_PCT = 0.004; MAX_BARS = 24; FEE_PCT = 0.0007
BB_PERIOD = 20; BB_STD = 2; RSI_PERIOD = 7
RSI_HIGH = 65; RSI_LOW = 35; ATR_VOL_FILTER = 0.5
POLL_INTERVAL = 3  # REST 轮询间隔(秒) — 实时级别

def get_dynamic_params(balance):
    if balance > 750: return 5, 0.3
    if balance > 200: return 10, 0.4
    if balance > 50:  return 15, 0.5
    return 15, 0.5

SERVER_CHAN_KEY = "SCT121277TOGysWEkqkfgn2tJJQzDvPfVD"
STATE_FILE = "/tmp/bb_rsi_state.json"
OKX_BIN = "/root/.nvm/versions/node/v23.11.1/bin/okx"
OKX_ENV = {"PATH":"/root/.nvm/versions/node/v23.11.1/bin:/usr/bin","HOME":"/root"}
PROXY = {"http":"http://127.0.0.1:2080","https":"http://127.0.0.1:2080"}

# ===== 全局状态 =====
candles = []
in_position = False; last_signal_bar = 0; lock = threading.Lock()
daily_pnl = 0.0; last_day = None
trade_history = []
weekly_pnl = 0.0; current_week = None; consecutive_losing_weeks = 0
effective_margin = 0.8
last_pos_state = {"side":None,"size":0,"entry_px":0}
entry_balance = 0

def log(msg):
    print(f"[{datetime.now().strftime('%H:%M:%S')}] {msg}", flush=True)

# ==================== 实时数据获取 ====================
def fetch_realtime_candles():
    """
    通过 REST candles 端点获取实时K线（含当前未完成K线）
    返回最新50根蜡烛列表(已排序), 当前K线的confirm状态
    """
    try:
        r = requests.get(
            "https://www.okx.com/api/v5/market/candles",
            params={"instId":INST_ID,"bar":"15m","limit":50},
            proxies=PROXY, timeout=5
        )
        data = r.json().get("data",[])
        if not data: return None

        bars = []
        for row in data:
            ts, o, h, l, c = int(row[0]), float(row[1]), float(row[2]), float(row[3]), float(row[4])
            confirmed = row[8] if len(row) > 8 else "1"
            bars.append({"ts":ts,"o":o,"h":h,"l":l,"c":c,"confirmed":confirmed=="1"})

        bars.sort(key=lambda x:x["ts"])
        return bars
    except Exception as e:
        return None

def store_completed_candles(bars):
    """将已完成的蜡烛存入SQLite"""
    completed = [(b["ts"],b["o"],b["h"],b["l"],b["c"]) for b in bars if b.get("confirmed")]
    if completed:
        db.insert_candles(completed)

def load_initial():
    """启动时从SQLite加载历史数据"""
    global candles
    bars = db.get_recent(500)
    if bars:
        # 标记为已完成
        for b in bars: b["confirmed"] = True
        with lock: candles = bars
        return True
    return False

# ==================== 技术指标与信号 ====================
def calc_indicators():
    with lock: bars = list(candles)
    if len(bars) < 50: return None
    cl = [b["c"] for b in bars]; hi = [b["h"] for b in bars]; lo = [b["l"] for b in bars]; n = len(bars)
    bb_u, bb_l = [None]*n, [None]*n
    for i in range(BB_PERIOD-1, n):
        w = cl[i-BB_PERIOD+1:i+1]; sma = sum(w)/BB_PERIOD
        std = math.sqrt(sum((x-sma)**2 for x in w)/BB_PERIOD)
        bb_u[i] = sma+BB_STD*std; bb_l[i] = sma-BB_STD*std
    rsi = [None]*n
    for i in range(RSI_PERIOD, n):
        gains = sum(max(cl[j]-cl[j-1],0) for j in range(i-RSI_PERIOD+1,i+1))/RSI_PERIOD
        losses = sum(max(cl[j-1]-cl[j],0) for j in range(i-RSI_PERIOD+1,i+1))/RSI_PERIOD
        rsi[i] = 100-100/(1+gains/losses) if losses>0 else 100
    atr_pct = [None]*n
    for i in range(14, n):
        tr = [max(hi[j]-lo[j],abs(hi[j]-cl[j-1]),abs(lo[j]-cl[j-1])) for j in range(i-13,i+1)]
        atr_pct[i] = (sum(tr)/14)/cl[i]*100
    valid = [v for v in atr_pct if v is not None]; atr_mean = sum(valid)/len(valid) if valid else 0.35
    return {"bb_u":bb_u,"bb_l":bb_l,"rsi":rsi,"atr":atr_pct,"atr_mean":atr_mean,"n":n}

def check_signal():
    ind = calc_indicators()
    if ind is None: return None,0
    bb_u,bb_l,rsi,atr,atr_mean = ind["bb_u"],ind["bb_l"],ind["rsi"],ind["atr"],ind["atr_mean"]
    n = ind["n"]; latest_idx = n-1
    # 动态ATR过滤: BB窄=震荡=严格, BB宽=趋势=宽松
    with lock:
        if n>=2 and bb_u[latest_idx] and bb_l[latest_idx]:
            bb_w = (bb_u[latest_idx]-bb_l[latest_idx])/candles[latest_idx]["c"]*100
            if bb_w < 8: dyn_f = ATR_VOL_FILTER*1.8
            elif bb_w < 12: dyn_f = ATR_VOL_FILTER*1.2
            else: dyn_f = ATR_VOL_FILTER*0.8
        else: dyn_f = ATR_VOL_FILTER
    for idx in range(latest_idx-1, max(latest_idx-4,50), -1):
        if bb_u[idx] is None or rsi[idx] is None or atr[idx] is None: continue
        if atr[idx] < atr_mean*dyn_f: continue
        with lock: c = candles[idx]["c"]
        if c > bb_u[idx] and rsi[idx] > RSI_HIGH: return "short",idx
        elif c < bb_l[idx] and rsi[idx] < RSI_LOW: return "long",idx
    return None,0

# ==================== OKX 交互 ====================
def okx_cli(*args):
    cmd = [OKX_BIN,"--live","--json"] + list(args)
    r = subprocess.run(cmd,capture_output=True,text=True,timeout=60,env=OKX_ENV)
    output = r.stdout.strip()
    if output.startswith("Update available"): output = output.split("\n",1)[-1].strip()
    try: return json.loads(output)
    except: return None

def send_wechat(title, content):
    try:
        requests.post(f"https://sctapi.ftqq.com/{SERVER_CHAN_KEY}.send",
                      data={"title":title,"desp":content}, timeout=10)
    except: pass

def get_positions():
    result = okx_cli("swap","positions","--instId",INST_ID)
    if not result: return []
    pos = []
    for p in result:
        if isinstance(p,dict) and float(p.get("pos",0) or 0) != 0:
            pos.append({"side":"long" if float(p["pos"])>0 else "short",
                       "size":abs(float(p["pos"])),"avgPx":float(p.get("avgPx",0))})
    return pos

def get_balance():
    result = okx_cli("account","balance")
    if not result: return 0
    for item in result:
        if isinstance(item,dict):
            te = float(item.get("totalEq",0))
            if te>0: return te
    return 0

# ==================== 持仓同步 ====================
def sync_position_state():
    global in_position, last_pos_state, entry_balance, trade_history, daily_pnl, weekly_pnl
    actual_positions = get_positions()
    has_actual = len(actual_positions) > 0
    if has_actual:
        log(f"[持仓同步] 检测到持仓: {actual_positions[0]['side']} {actual_positions[0]['size']}张 @{actual_positions[0]['avgPx']}")
    if has_actual:
        p = actual_positions[0]
        last_pos_state = {"side":p["side"],"size":p["size"],"entry_px":p["avgPx"]}
        in_position = True
        return True
    else:
        if in_position and last_pos_state["side"] is not None:
            balance = get_balance()
            if entry_balance > 0:
                # 扣除滑点+手续费的净盈亏
                entry_cost = last_pos_state["entry_px"] * 0.0002 * last_pos_state["size"] * 0.01
                exit_cost = balance * (0.0002 + 0.0007)
                net_change = balance - entry_balance - entry_cost - exit_cost
                pnl = net_change / entry_balance if entry_balance > 0 else 0
                daily_pnl += pnl; weekly_pnl += pnl
                trade_history.append({"time":datetime.now().strftime("%m-%d %H:%M"),
                    "side":last_pos_state["side"],"pnl":round(pnl,4),"reason":"CLOSE","entry":last_pos_state["entry_px"]})
                log(f"[平仓] {last_pos_state['side']} PnL={pnl*100:+.2f}%")
                send_wechat(f"BB+RSI平仓 {last_pos_state['side']}",f"盈亏:{pnl*100:+.2f}%")
        in_position = False
        last_pos_state = {"side":None,"size":0,"entry_px":0}
        entry_balance = 0
        return False

# ==================== 执行 ====================
def execute_signal(signal, signal_idx):
    global in_position, last_signal_bar, entry_balance, last_pos_state
    sync_position_state()
    if in_position: return
    if daily_pnl < -0.15: return
    if signal_idx == last_signal_bar: return

    with lock: entry_px = candles[signal_idx]["c"]
    balance = get_balance()
    dlev, dmargin = get_dynamic_params(balance)
    if consecutive_losing_weeks >= 3: dmargin *= 0.5

    okx_cli("swap","leverage","--instId",INST_ID,"--lever",str(dlev),"--mgnMode","isolated")
    margin_use = balance*dmargin*0.95; contract_val = entry_px*0.01
    sz = max(0.01, round(margin_use/(contract_val/dlev)*100)/100)

    if signal == "short":
        tp_px = round(entry_px*(1-TP_PCT),1); sl_px = round(entry_px*(1+SL_PCT),1); side = "sell"
    else:
        tp_px = round(entry_px*(1+TP_PCT),1); sl_px = round(entry_px*(1-SL_PCT),1); side = "buy"

    args = ["swap","place","--instId",INST_ID,"--side",side,"--sz",str(sz),
            "--ordType","limit","--px",str(entry_px),"--tdMode","isolated"]
    if tp_px: args += ["--tpTriggerPx",str(tp_px),"--tpOrdPx=-1"]
    if sl_px: args += ["--slTriggerPx",str(sl_px),"--slOrdPx=-1"]

    result = okx_cli(*args)
    if result and isinstance(result,list) and len(result)>0 and result[0].get("sCode")=="0":
        in_position = True; last_signal_bar = signal_idx
        entry_balance = balance
        last_pos_state = {"side":signal,"size":sz,"entry_px":entry_px}
        msg = f"BB+RSI v6 {signal} {sz}张\n入场:{entry_px:.1f} TP:{tp_px} SL:{sl_px}\n保证金${margin_use:.0f} @{dlev}x"
        log(f"[开仓] {signal} {sz}张 @{entry_px:.1f}")
        send_wechat(f"BB+RSI开仓 {signal}", msg)
        trade_history.append({"time":datetime.now().strftime("%m-%d %H:%M"),
            "side":signal,"pnl":0,"reason":"OPEN","entry":entry_px})

# ==================== 状态文件 ====================
def update_state():
    global daily_pnl, last_day, weekly_pnl, current_week, consecutive_losing_weeks, effective_margin
    try:
        sync_position_state()
        balance = get_balance()
        pos_info = None
        if last_pos_state["side"] is not None:
            with lock: px = candles[-1]["c"] if candles else 0
            if px > 0:
                ep = last_pos_state["entry_px"]
                sz = last_pos_state["size"]
                pos_val = sz * ep * 0.01  # 持仓价值USD
                gross = (px - ep) * sz * 0.01 if last_pos_state["side"]=="long" else (ep - px) * sz * 0.01
                # 含全成本: 入场滑点+出场滑点+手续费
                costs = pos_val * (0.0002 + 0.0002 + 0.0007)  # 万2+万2+万7 = 0.11%
                net = gross - costs
                p = net / pos_val if pos_val > 0 else 0
                pos_info = {"side":last_pos_state["side"],"size":sz,
                           "entry_px":ep,"pnl_pct":p,"pnl":round(net,4)}
        today = datetime.now().strftime("%Y-%m-%d")
        if today != last_day: daily_pnl = 0.0; last_day = today
        week = datetime.now().strftime("%Y-W%W")
        if week != current_week:
            if current_week is not None:
                if weekly_pnl <= 0: consecutive_losing_weeks += 1
                else: consecutive_losing_weeks = 0
                effective_margin = 0.4 if consecutive_losing_weeks>=3 else 0.8
            weekly_pnl = 0.0; current_week = week
        dlev, dmargin = get_dynamic_params(balance)
        state = {
            "status":"running","balance":balance,"equity":balance,
            "position":pos_info,"ws_connected":True,
            "ws_last_heartbeat":datetime.now().strftime("%H:%M:%S"),
            "daily_pnl":daily_pnl,"weekly_pnl":weekly_pnl,
            "effective_leverage":dlev,"effective_margin":dmargin,
            "consecutive_losing":consecutive_losing_weeks,
            "trades":trade_history[-20:],
            "protections":{"max_daily_loss":-0.15,"cooldown":daily_pnl<-0.15},
            "updated":datetime.now().strftime("%H:%M:%S")
        }
        with open(STATE_FILE,"w") as f: json.dump(state,f,default=str)
    except Exception as e:
        log(f"[state] {e}")

# ==================== 主循环 (REST实时轮询) ====================
def main_loop():
    """每3秒轮询：拉最新蜡烛 → 同步持仓 → 检测信号"""
    global candles, in_position
    consecutive_failures = 0

    while True:
        time.sleep(POLL_INTERVAL)
        try:
            # 1. 获取实时K线
            bars = fetch_realtime_candles()
            if bars is None:
                consecutive_failures += 1
                if consecutive_failures > 10:
                    log(f"[拉取] 连续失败{consecutive_failures}次")
                continue
            consecutive_failures = 0

            # 2. 更新内存candles
            with lock:
                # 找到当前candles的最大ts
                existing_ts = {b["ts"] for b in candles}
                for b in bars:
                    if b["ts"] not in existing_ts:
                        candles.append(b)
                        existing_ts.add(b["ts"])
                    else:
                        # 更新现有（当前K线实时更新）
                        for i in range(len(candles)):
                            if candles[i]["ts"] == b["ts"]:
                                candles[i] = b
                                break
                if len(candles) > 500:
                    candles = candles[-500:]

            # 3. 已完成蜡烛存入SQLite
            store_completed_candles(bars)

            # 4. 同步持仓
            sync_position_state()

            # 5. 无持仓时检测信号
            if not in_position and len(candles) >= 50:
                signal, idx = check_signal()
                if signal:
                    log(f"[信号] {signal} idx={idx}")
                    execute_signal(signal, idx)

            # 6. 更新状态
            update_state()

        except Exception as e:
            log(f"[主循环] {e}")

def main():
    global candles
    log(f"EA v6 启动 | REST轮询间隔={POLL_INTERVAL}s (实时)")

    # 初始化
    if load_initial():
        log(f"从DB加载 {len(candles)} 根蜡烛")
    else:
        log("DB为空，使用REST加载...")
        bars = fetch_realtime_candles()
        if bars:
            with lock: candles = bars
            store_completed_candles(bars)
            log(f"REST加载 {len(candles)} 根")

    sync_position_state()
    update_state()

    # 启动主循环
    main_loop()

if __name__ == "__main__":
    main()