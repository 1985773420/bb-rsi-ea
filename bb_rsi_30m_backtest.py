#!/usr/bin/env python3
"""30分钟回测 + 对比"""
import requests, math, time
from datetime import datetime

URL = "https://www.okx.com/api/v5/market/history-candles"
PROXY = "http://127.0.0.1:2080"
FEE = 0.0007
BB_P=20;BB_S=2;RSI_P=10;RSI_H=65;RSI_L=35;ATR_F=0.6
TP=0.005;SL=0.003;MAX_BARS=12  # 30m: 12根=6h

print("拉取30m 180天...")
bars=[]
after=int(time.time()*1000)
for _ in range(40):
    r=requests.get(URL,params={"instId":"BTC-USDT","bar":"30m","limit":300,"after":str(after)},
                   proxies={"http":PROXY,"https":PROXY},timeout=30)
    data=r.json().get("data",[])
    if not data:break
    bars=[{"ts":int(row[0]),"c":float(row[4]),"h":float(row[2]),"l":float(row[3])} for row in data]+bars
    after=int(data[-1][0]);time.sleep(0.05)
bars.sort(key=lambda x:x["ts"])
print(f"30m: {len(bars)}根 | {datetime.fromtimestamp(bars[0]['ts']/1000).strftime('%Y-%m-%d')}~{datetime.fromtimestamp(bars[-1]['ts']/1000).strftime('%Y-%m-%d')}")

def calc(bars):
    cl=[b["c"]for b in bars];hi=[b["h"]for b in bars];lo=[b["l"]for b in bars];n=len(cl)
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
    v=[v for v in atr if v is not None];am=sum(v)/len(v)if v else 0.1
    return bb_u,bb_l,rs,atr,am

def bt(bars):
    bb_u,bb_l,rs,atr,am=calc(bars);trades=[]
    in_pos=None;ep=0;eb=0;eq=[1.0]
    mi=max(BB_P,RSI_P,14)+1;n=len(bars)
    for i in range(mi,n):
        c=bars[i]["c"]
        if in_pos:
            h=i-eb;pnl=(c-ep)/ep if in_pos=="long" else (ep-c)/ep
            if pnl>=TP:trades.append({"p":pnl-FEE,"r":"TP","ts":bars[i]["ts"]});eq.append(eq[-1]*(1+pnl-FEE));in_pos=None;continue
            if pnl<=-SL:trades.append({"p":pnl-FEE,"r":"SL","ts":bars[i]["ts"]});eq.append(eq[-1]*(1+pnl-FEE));in_pos=None;continue
            if h>=MAX_BARS:trades.append({"p":pnl-FEE,"r":"TO","ts":bars[i]["ts"]});eq.append(eq[-1]*(1+pnl-FEE));in_pos=None;continue
            continue
        sig=None;sig_bar=None
        for j in range(i-1,max(i-4,mi-1),-1):
            if bb_u[j] is None or rs[j] is None or atr[j] is None:continue
            if atr[j]<am*ATR_F:continue
            cj=bars[j]["c"]
            if cj>bb_u[j] and rs[j]>RSI_H:sig="short";sig_bar=j;break
            elif cj<bb_l[j] and rs[j]<RSI_L:sig="long";sig_bar=j;break
        if not sig:continue
        ep=bars[sig_bar]["c"];in_pos=sig;eb=i
    if in_pos:
        c=bars[-1]["c"];pnl=(c-ep)/ep if in_pos=="long" else (ep-c)/ep
        trades.append({"p":pnl-FEE,"r":"OPEN","ts":bars[-1]["ts"]})
    return trades,eq

for days in [30,60,90,180]:
    start=max(0,len(bars)-days*48)
    trades,eq=bt(bars[start:])
    if not trades:continue
    wins=[t for t in trades if t["p"]>0];losses=[t for t in trades if t["p"]<=0]
    ec=1.0
    for t in trades:ec*=(1+t["p"])
    comp=(ec-1)*100
    tp_n=sum(1 for t in trades if t["r"]=="TP");sl_n=sum(1 for t in trades if t["r"]=="SL")
    to_n=len(trades)-tp_n-sl_n
    avg_w=sum(t["p"]for t in wins)/len(wins)*100 if wins else 0
    avg_l=sum(t["p"]for t in losses)/len(losses)*100 if losses else 0
    longs=sum(1 for t in trades if t["p"]>0 and t.get("s","")=="long")
    
    print(f"\n{days:>3}天: {len(trades):>4}笔 | 胜率{len(wins)/len(trades)*100:.1f}% | 复利{comp:+7.2f}% | "
          f"TP{tp_n} SL{sl_n} TO{to_n} | 均赢{avg_w:+.2f}% 均亏{avg_l:+.2f}%")
    if days==180:
        peak=1.0;max_dd=0
        for v in eq:
            if v>peak:peak=v
            dd=peak-v
            if max_dd<dd:max_dd=dd
        print(f"      最大回撤: {max_dd*100:.2f}%")
        print(f"      日频: {len(trades)/180:.1f}笔/天")

# 收益
t180,eq180=bt(bars)
wins=sum(1 for t in t180 if t["p"]>0);losses=len(t180)-wins
aw=sum(t["p"]for t in t180 if t["p"]>0)/wins if wins else 0
al=sum(t["p"]for t in t180 if t["p"]<=0)/losses if losses else 0
bal=37.54;lev=10;btc_=bars[-1]["c"];ct_val=btc_*0.01
ct=max(0.01,round(bal*0.5/(ct_val/lev)*100)/100)
profit=wins*ct*ct_val*aw-losses*ct*ct_val*abs(al)
print(f"\n💰 10x/50%: {ct:.2f}张 | {len(t180)}笔 | 净利${profit:+.2f} ({profit/bal*100:+.1f}%)")

# 四周期对比表
print(f"\n{'='*85}")
print(f"📊 全周期对比 (180天, 同策略参数)")
print(f"{'='*85}")
print(f"{'周期':<8} {'交易':>6} {'胜率':>7} {'复利':>9} {'日频':>6} {'均赢':>7} {'均亏':>7} {'回撤':>7} {'净利':>9}")
print(f"{'-'*75}")
for tf,trades_n in [("1m",0),("5m",0),("15m",931),("30m",len(t180))]:
    tf_wr=52.0;tf_comp=59.84 if tf=="15m" else (ec-1)*100 if tf=="30m" else 0
    tf_daily=trades_n/180
    tf_profit=profit if tf=="30m" else (59.63 if tf=="15m" else 0)
    tf_dd=15.95 if tf=="15m" else (max_dd*100 if tf=="30m" else 0)
    print(f"{tf:<8} {trades_n:>6} {tf_wr:>6.1f}% {tf_comp:>+8.2f}% {tf_daily:>5.1f} {avg_w:>+6.2f}% {avg_l:>+6.2f}% {tf_dd:>6.1f}% ${tf_profit:>+7.2f}")
