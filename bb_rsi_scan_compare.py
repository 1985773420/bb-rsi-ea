#!/usr/bin/env python3
"""对比: 只扫已完成K线 vs 扫全部K线(含当前)"""
import requests, math
from datetime import datetime, timezone

GATE_URL = "https://api.gateio.ws/api/v4/spot/candlesticks"
PROXY = "http://127.0.0.1:2080"
TP_PCT=0.005;SL_PCT=0.003;MAX_BARS=24;FEE=0.0007
BB_P=20;BB_S=2;RSI_P=10;RSI_H=65;RSI_L=35;ATR_F=0.8

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

def bt(bars, scan_current=False):
    bb_u,bb_l,rs,atr,am=calc(bars)
    trades=[]
    in_pos=None;ep=0;eb=0;eq=[1.0]
    mi=max(BB_P,RSI_P,14)+1
    n=len(bars)
    
    for i in range(mi,len(bars)):
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
        
        # 扫描信号
        sig=None
        start=i-1;end=max(i-4,mi-1)
        if scan_current:
            start=i  # 包含当前K线
        for j in range(start,end,-1):
            if j>=n or bb_u[j] is None or rs[j] is None or atr[j] is None:continue
            if atr[j]<am*ATR_F:continue
            cj=bars[j]["c"]
            if cj>bb_u[j] and rs[j]>RSI_H:sig="short";ep=cj;break
            elif cj<bb_l[j] and rs[j]<RSI_L:sig="long";ep=cj;break
        if sig:in_pos=sig;eb=i
    
    if in_pos:
        c=bars[-1]["c"];pnl=(c-ep)/ep if in_pos=="long" else (ep-c)/ep
        trades.append({"s":in_pos,"pnl":pnl-FEE,"r":"OPEN"})
    return trades,eq

def main():
    print("="*85)
    print("对比回测: 已完成K线 vs 含当前K线")
    print("="*85)
    
    bars=fetch_bars(3000)
    if len(bars)<500:print("数据不足");return
    total=len(bars)
    print(f"\n{total}根K线 | {datetime.fromtimestamp(bars[0]['ts']).strftime('%m-%d %H:%M')} ~ {datetime.fromtimestamp(bars[-1]['ts']).strftime('%m-%d %H:%M')}")
    
    periods={}
    for days in [7,14,30]:
        start=max(0,total-days*96)
        periods[days]=bars[start:]
    
    for mode_name, scan_current in [("仅已完成K线(当前EA)", False), ("含当前K线", True)]:
        print(f"\n{'='*85}")
        print(f"  {mode_name}")
        print(f"{'='*85}")
        for days,pb in periods.items():
            trades,eq=bt(pb,scan_current)
            if not trades:
                print(f"  {days}天: 0笔")
                continue
            wins=[t for t in trades if t["pnl"]>0]
            losses=[t for t in trades if t["pnl"]<=0]
            cmp=(eq[-1]-1)*100
            tp_n=sum(1 for t in trades if t["r"]=="TP")
            sl_n=sum(1 for t in trades if t["r"]=="SL")
            to_n=sum(1 for t in trades if t["r"]=="TO")
            print(f"  {days}天: {len(trades):>3}笔 | 胜率{len(wins)/len(trades)*100:.1f}% | 复利{cmp:+7.2f}% | "
                  f"TP{tp_n} SL{sl_n} TO{to_n} | 均赢{sum(t['pnl']for t in wins)/len(wins)*100:+.2f}% | 均亏{sum(t['pnl']for t in losses)/len(losses)*100 if losses else 0:+.2f}%")
    
    # 汇总
    print(f"\n\n{'='*85}")
    print(f"📊 30天汇总对比")
    print(f"{'='*85}")
    for mode_name, scan_current in [("仅已完成K线", False), ("含当前K线", True)]:
        trades,eq=bt(periods[30],scan_current)
        wins=[t for t in trades if t["pnl"]>0]
        cmp=(eq[-1]-1)*100
        print(f"\n  {mode_name}: {len(trades)}笔 | 胜率{len(wins)/len(trades)*100:.1f}% | 复利{cmp:+.2f}% | 日频{len(trades)/30:.1f}")

if __name__=="__main__":
    main()
