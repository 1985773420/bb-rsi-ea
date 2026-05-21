#!/usr/bin/env python3
"""今天 (5/21) 回测"""
import requests, math
from datetime import datetime, timezone, timedelta

GATE_URL = "https://api.gateio.ws/api/v4/spot/candlesticks"
PROXY = "http://127.0.0.1:2080"
TP=0.005;SL=0.003;MAX_BARS=24;FEE=0.0007
BB_P=20;BB_S=2;RSI_P=10;RSI_H=65;RSI_L=35;ATR_F=0.6
BALANCE=37.54;LEV=10;BTC=78000;CT_VAL=BTC*0.01

r = requests.get(GATE_URL, params={"currency_pair":"BTC_USDT","interval":"15m","limit":200},
                 proxies={"http":PROXY,"https":PROXY}, timeout=30)
bars = [{"ts":int(row[0]),"c":float(row[2]),"h":float(row[3]),"l":float(row[4])} for row in r.json()]
bars.sort(key=lambda x:x["ts"])

# 今天 UTC+8 0点起
t0 = datetime(2026,5,21,0,0,0,tzinfo=timezone.utc) - timedelta(hours=8)
today = [b for b in bars if b["ts"]/1000 >= t0.timestamp()]
if not today: print("无数据");exit()

cl=[b["c"] for b in today];hi=[b["h"] for b in today];lo=[b["l"] for b in today]
n=len(cl)

bb_u,bb_l=[None]*n,[None]*n
for i in range(BB_P-1,n):
    w=cl[i-BB_P+1:i+1];sma=sum(w)/BB_P;std=(sum((x-sma)**2 for x in w)/BB_P)**0.5
    bb_u[i]=sma+BB_S*std;bb_l[i]=sma-BB_S*std
rs=[None]*n
for i in range(RSI_P,n):
    g=sum(max(cl[j]-cl[j-1],0)for j in range(i-RSI_P+1,i+1))/RSI_P
    l=sum(max(cl[j-1]-cl[j],0)for j in range(i-RSI_P+1,i+1))/RSI_P
    rs[i]=100-100/(1+g/l)if l>0 else 100
atr=[None]*n
for i in range(14,n):
    tr=[max(hi[j]-lo[j],abs(hi[j]-cl[j-1]),abs(lo[j]-cl[j-1]))for j in range(i-13,i+1)]
    atr[i]=(sum(tr)/14)/cl[i]*100
am=sum(v for v in atr if v is not None)/sum(1 for v in atr if v is not None)

print("="*70)
print(f"今天回测 (5/21) | {len(today)}根K线 | {datetime.fromtimestamp(today[0]['ts']).strftime('%H:%M')}~{datetime.fromtimestamp(today[-1]['ts']).strftime('%H:%M')}")
print(f"开盘: {today[0]['c']:.0f} | 当前: {today[-1]['c']:.0f} | {today[-1]['c']/today[0]['c']-1:+.2%}")
print("="*70)

# 扫描所有已完成K线找信号
mi=max(BB_P,RSI_P,14)+1
signals=[]
for i in range(mi,n-1):
    for j in range(i-1,max(i-4,mi-1),-1):
        if bb_u[j] is None or rs[j] is None or atr[j] is None:continue
        if atr[j]<am*ATR_F:continue
        cj=bars[j]["c"] if j<len(bars) else None
        if cj is None:continue
        ts=datetime.fromtimestamp(today[j]["ts"]).strftime("%H:%M")
        if cj>bb_u[j] and rs[j]>RSI_H:
            signals.append((ts,"short",cj,bb_u[j],rs[j],atr[j]))
            break
        elif cj<bb_l[j] and rs[j]<RSI_L:
            signals.append((ts,"long",cj,bb_l[j],rs[j],atr[j]))
            break

print(f"\n📊 今天信号扫描 (已触发={len(signals)}个)")
for ts,sig,px,bb,rsi_val,atr_val in signals:
    print(f"  {ts} {sig:>6} px={px:.0f} BB={'上'if sig=='short'else'下'}={bb:.0f} RSI={rsi_val:.1f} ATR={atr_val:.3f}%")

# 模拟今天交易
trades=[]
in_pos=None;ep=0;eb=0
for i in range(mi,n):
    c=cl[i]
    if in_pos:
        h=i-eb;pnl=(c-ep)/ep if in_pos=="long" else (ep-c)/ep
        if pnl>=TP:
            trades.append((in_pos,ep,c,pnl-FEE,"TP"));in_pos=None;continue
        if pnl<=-SL:
            trades.append((in_pos,ep,c,pnl-FEE,"SL"));in_pos=None;continue
        if h>=MAX_BARS:
            trades.append((in_pos,ep,c,pnl-FEE,"TO"));in_pos=None;continue
        continue
    sig=None
    for j in range(i-1,max(i-4,mi-1),-1):
        if bb_u[j] is None or rs[j] is None or atr[j] is None:continue
        if atr[j]<am*ATR_F:continue
        cj=cl[j]
        if cj>bb_u[j] and rs[j]>RSI_H:sig="short";ep=cj;break
        elif cj<bb_l[j] and rs[j]<RSI_L:sig="long";ep=cj;break
    if sig:in_pos=sig;eb=i

if in_pos:
    c=cl[-1];pnl=(c-ep)/ep if in_pos=="long" else (ep-c)/ep
    trades.append((in_pos,ep,c,pnl-FEE,"OPEN"))

print(f"\n📈 今天模拟交易 ({len(trades)}笔)")
dollar_total=0
for i,(side,entry,exit_,pnl,reason) in enumerate(trades,1):
    print(f"  {i}. {side:>5} {entry:.0f}→{exit_:.0f} {pnl*100:+.2f}% [{reason}]")

print(f"\n💰 仓位收益对比")
for label,pct in [("10x/30%",30),("10x/50%",50)]:
    m=BALANCE*pct/100;mp=CT_VAL/LEV;ct=round(m/mp,3)
    notional=ct*CT_VAL
    total=sum(notional*t[3] for t in trades)
    print(f"  {label}: {ct:.3f}张 ${notional:.0f}名义 → 盈亏 ${total:+.2f}")

# 实盘当前
entry=77923;current=today[-1]["c"]
live_pnl=(entry-current)/entry*100
print(f"\n📌 实盘持仓: SHORT 入场{entry} 当前{current:.0f} 浮动{live_pnl:+.2f}%")
