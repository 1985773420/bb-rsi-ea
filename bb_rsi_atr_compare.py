#!/usr/bin/env python3
"""对比不同ATR波动率过滤阈值"""
import requests, math
from datetime import datetime, timezone

GATE_URL = "https://api.gateio.ws/api/v4/spot/candlesticks"
PROXY = "http://127.0.0.1:2080"
TP_PCT=0.005;SL_PCT=0.003;MAX_BARS=24;FEE=0.0007
BB_P=20;BB_S=2;RSI_P=10;RSI_H=65;RSI_L=35

def fetch_bars(n=3000):
    bars=[]
    for _ in range(5):
        to=bars[0]["ts"] if bars else None
        p={"currency_pair":"BTC_USDT","interval":"15m","limit":1000}
        if to:p["to"]=to
        try:
            r=requests.get(GATE_URL,params=p,proxies={"http":PROXY,"https":PROXY},timeout=30)
            d=r.json()
            if not d:break
            c=[{"ts":int(row[0]),"c":float(row[2]),"h":float(row[3]),"l":float(row[4])} for row in d]
            if bars:c=[b for b in c if b["ts"]<bars[0]["ts"]]
            bars=c+bars
            if len(bars)>=n:break
        except:break
    bars.sort(key=lambda x:x["ts"])
    return bars

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
    v=[v for v in atr if v is not None];am=sum(v)/len(v)if v else 0.35
    return bb_u,bb_l,rs,atr,am

def bt(bars, atr_f):
    bb_u,bb_l,rs,atr,am=calc(bars)
    trades=[]
    in_pos=None;ep=0;eb=0;eq=[1.0]
    mi=max(BB_P,RSI_P,14)+1;n=len(bars)
    
    for i in range(mi,n):
        if in_pos:
            h=i-eb;c=bars[i]["c"];pnl=(c-ep)/ep if in_pos=="long" else (ep-c)/ep
            if pnl>=TP_PCT:
                trades.append({"s":in_pos,"pnl":pnl-FEE,"r":"TP"})
                eq.append(eq[-1]*(1+pnl-FEE));in_pos=None;continue
            if pnl<=-SL_PCT:
                trades.append({"s":in_pos,"pnl":pnl-FEE,"r":"SL"})
                eq.append(eq[-1]*(1+pnl-FEE));in_pos=None;continue
            if h>=MAX_BARS:
                trades.append({"s":in_pos,"pnl":pnl-FEE,"r":"TO"})
                eq.append(eq[-1]*(1+pnl-FEE));in_pos=None;continue
            continue
        
        sig=None
        for j in range(i-1,max(i-4,mi-1),-1):
            if bb_u[j] is None or rs[j] is None or atr[j] is None:continue
            if atr_f>0 and atr[j]<am*atr_f:continue
            cj=bars[j]["c"]
            if cj>bb_u[j] and rs[j]>RSI_H:sig="short";ep=cj;break
            elif cj<bb_l[j] and rs[j]<RSI_L:sig="long";ep=cj;break
        if sig:in_pos=sig;eb=i
    
    if in_pos:
        c=bars[-1]["c"];pnl=(c-ep)/ep if in_pos=="long" else (ep-c)/ep
        trades.append({"s":in_pos,"pnl":pnl-FEE,"r":"OPEN"})
    return trades,eq

def main():
    print("="*90)
    print("ATR波动率过滤阈值对比回测")
    print("="*90)
    
    bars=fetch_bars(3000)
    if len(bars)<500:print("数据不足");return
    total=len(bars)
    print(f"\n{total}根K线 | {datetime.fromtimestamp(bars[0]['ts']).strftime('%m-%d %H:%M')} ~ {datetime.fromtimestamp(bars[-1]['ts']).strftime('%m-%d %H:%M')}")
    
    periods={}
    for days in [7,14,30]:
        start=max(0,total-days*96)
        periods[days]=bars[start:]
    
    variants=[
        ("当前 ×0.8", 0.8),
        ("×0.6", 0.6),
        ("×0.4", 0.4),
        ("×0.2", 0.2),
        ("无ATR过滤", 0),
    ]
    
    results={}
    for label, atr_f in variants:
        print(f"\n{'='*90}")
        print(f"  ATR过滤: {label}")
        print(f"{'='*90}")
        row={}
        for days,pb in periods.items():
            trades,eq=bt(pb,atr_f)
            if not trades:
                print(f"  {days}天: 0笔");row[days]={"n":0,"cmp":0,"wr":0};continue
            wins=[t for t in trades if t["pnl"]>0];losses=[t for t in trades if t["pnl"]<=0]
            cmp=(eq[-1]-1)*100
            tp_n=sum(1 for t in trades if t["r"]=="TP");sl_n=sum(1 for t in trades if t["r"]=="SL")
            to_n=sum(1 for t in trades if t["r"]=="TO")
            avg_w=sum(t["pnl"]for t in wins)/len(wins)*100 if wins else 0
            avg_l=sum(t["pnl"]for t in losses)/len(losses)*100 if losses else 0
            print(f"  {days}天: {len(trades):>3}笔 | 胜率{len(wins)/len(trades)*100:.1f}% | 复利{cmp:+7.2f}% | "
                  f"TP{tp_n} SL{sl_n} TO{to_n} | 均赢{avg_w:+.2f}% 均亏{avg_l:+.2f}%")
            row[days]={"n":len(trades),"cmp":cmp,"wr":len(wins)/len(trades)*100}
        results[label]=row
    
    # 汇总表
    print(f"\n\n{'='*90}")
    print(f"📊 30天汇总对比")
    print(f"{'='*90}")
    print(f"{'ATR过滤':<15} {'交易':>6} {'胜率':>7} {'复利':>9} {'日频':>6}")
    print(f"{'-'*45}")
    for label, _ in variants:
        r=results[label][30]
        print(f"{label:<15} {r['n']:>6} {r['wr']:>6.1f}% {r['cmp']:>+8.2f}% {r['n']/30:>5.1f}")
    
    # 推荐
    best_label=max(results,key=lambda k:results[k][30]["cmp"])
    print(f"\n🏆 最佳: {best_label} (30天复利{results[best_label][30]['cmp']:+.2f}%)")

if __name__=="__main__":
    main()
