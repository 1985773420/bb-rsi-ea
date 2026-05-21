#!/usr/bin/env python3
"""BB+RSI 1分钟回测"""
import requests, math, time
from datetime import datetime

URL = "https://www.okx.com/api/v5/market/history-candles"
PROXY = "http://127.0.0.1:2080"
BB_P=20;BB_S=2;RSI_P=10;RSI_H=65;RSI_L=35;ATR_F=0.6
MAX_BARS=96  # 1m: 96根=1.6小时, 适配1m节奏

# 尝试多组TP/SL
VARIANTS = [
    {"name":"TP0.5/SL0.3","tp":0.005,"sl":0.003},
    {"name":"TP0.3/SL0.2","tp":0.003,"sl":0.002},
    {"name":"TP0.2/SL0.15","tp":0.002,"sl":0.0015},
    {"name":"TP0.15/SL0.1","tp":0.0015,"sl":0.001},
]

def fetch(inst="BTC-USDT", bar="1m", days=60):
    target=days*1440;bars=[];after=int(time.time()*1000)
    while len(bars)<target:
        try:
            r=requests.get(URL,params={"instId":inst,"bar":bar,"limit":300,"after":str(after)},
                          proxies={"http":PROXY,"https":PROXY},timeout=30)
            data=r.json().get("data",[])
            if not data:break
            chunk=[{"ts":int(row[0]),"c":float(row[4]),"h":float(row[2]),"l":float(row[3])} for row in data]
            bars=chunk+bars;after=int(data[-1][0]);time.sleep(0.05)
        except:break
    bars.sort(key=lambda x:x["ts"]);return bars

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

def bt(bars,tp,sl):
    bb_u,bb_l,rs,atr,am=calc(bars);trades=[]
    in_pos=None;ep=0;eb=0;eq=[1.0]
    mi=max(BB_P,RSI_P,14)+1;n=len(bars);fee=0.0007
    
    for i in range(mi,n):
        c=bars[i]["c"]
        if in_pos:
            h=i-eb;pnl=(c-ep)/ep if in_pos=="long" else (ep-c)/ep
            if pnl>=tp:trades.append({"p":pnl-fee,"r":"TP"});eq.append(eq[-1]*(1+pnl-fee));in_pos=None;continue
            if pnl<=-sl:trades.append({"p":pnl-fee,"r":"SL"});eq.append(eq[-1]*(1+pnl-fee));in_pos=None;continue
            if h>=MAX_BARS:trades.append({"p":pnl-fee,"r":"TO"});eq.append(eq[-1]*(1+pnl-fee));in_pos=None;continue
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
        trades.append({"p":pnl-fee,"r":"OPEN"})
    return trades,eq

def main():
    print("="*85)
    print("BB+RSI 1分钟回测")
    print("="*85)
    
    print("拉取1分钟数据...")
    bars_1m=fetch("BTC-USDT","1m",30)  # 30天够多了
    if len(bars_1m)<500:print("数据不足");return
    print(f"1m: {len(bars_1m)}根 | {datetime.fromtimestamp(bars_1m[0]['ts']/1000).strftime('%m-%d %H:%M')}~{datetime.fromtimestamp(bars_1m[-1]['ts']/1000).strftime('%m-%d %H:%M')}")
    
    # 也拉15m作对比
    print("拉取15分钟数据...")
    bars_15m=fetch("BTC-USDT","15m",30)
    print(f"15m: {len(bars_15m)}根 | {datetime.fromtimestamp(bars_15m[0]['ts']/1000).strftime('%m-%d %H:%M')}~{datetime.fromtimestamp(bars_15m[-1]['ts']/1000).strftime('%m-%d %H:%M')}")
    
    # 15m基准
    t15,eq15=bt(bars_15m,0.005,0.003)
    wins15=[t for t in t15 if t["p"]>0];ec15=1.0
    for t in t15:ec15*=(1+t["p"])
    print(f"\n{'='*85}")
    print(f"15m基准: {len(t15)}笔 | 胜率{len(wins15)/len(t15)*100:.1f}% | 复利{(ec15-1)*100:+.2f}%")
    
    # 1m多方案
    print(f"\n{'='*85}")
    print(f"1分钟多方案")
    print(f"{'='*85}")
    best=("",-999)
    for v in VARIANTS:
        trades,eq=bt(bars_1m,v["tp"],v["sl"])
        if not trades:continue
        wins=[t for t in trades if t["p"]>0];losses=[t for t in trades if t["p"]<=0]
        ec=1.0
        for t in trades:ec*=(1+t["p"])
        avg_w=sum(t["p"]for t in wins)/len(wins)*100 if wins else 0
        avg_l=sum(t["p"]for t in losses)/len(losses)*100 if losses else 0
        tp_n=sum(1 for t in trades if t["r"]=="TP");sl_n=sum(1 for t in trades if t["r"]=="SL")
        to_n=sum(1 for t in trades if t["r"]=="TO")
        print(f"  {v['name']:>15}: {len(trades):>4}笔 | 胜率{len(wins)/len(trades)*100:.1f}% | 复利{(ec-1)*100:+7.2f}% | "
              f"TP{tp_n} SL{sl_n} TO{to_n} | 均赢{avg_w:+.2f}% 均亏{avg_l:+.2f}%")
        if (ec-1)*100>best[1]:best=(v["name"],(ec-1)*100)
    
    print(f"\n🏆 最佳: {best[0]} (复利{best[1]:+.2f}%)")

if __name__=="__main__":
    main()
