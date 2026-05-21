#!/usr/bin/env python3
"""BB+RSI v2 机会点分析 — 按日统计信号频率"""
import requests, math
from datetime import datetime, timezone, timedelta
from collections import defaultdict

GATE_URL = "https://api.gateio.ws/api/v4/spot/candlesticks"
PROXY = "http://127.0.0.1:2080"

TP_PCT=0.005; SL_PCT=0.003; MAX_BARS=24; FEE=0.0007
BB_PERIOD=20; BB_STD=2; RSI_PERIOD=10; RSI_H=65; RSI_L=35; ATR_F=0.8

def fetch_all(target=3000):
    bars=[]
    for _ in range(5):
        to= bars[0]["ts"] if bars else None
        p={"currency_pair":"BTC_USDT","interval":"15m","limit":1000}; 
        if to: p["to"]=to
        try:
            r=requests.get(GATE_URL,params=p,proxies={"http":PROXY,"https":PROXY},timeout=30)
            d=r.json()
            if not d: break
            c=[{"ts":int(row[0]),"o":float(row[5]),"h":float(row[3]),"l":float(row[4]),"c":float(row[2])} for row in d]
            if bars: c=[b for b in c if b["ts"]<bars[0]["ts"]]
            bars=c+bars
            if len(bars)>=target: break
        except: break
    bars.sort(key=lambda x:x["ts"])
    return bars

def calc(bars):
    cl=[b["c"]for b in bars];hi=[b["h"]for b in bars];lo=[b["l"]for b in bars];n=len(cl)
    bb_u,bb_l=[None]*n,[None]*n
    for i in range(BB_PERIOD-1,n):
        w=cl[i-BB_PERIOD+1:i+1];sma=sum(w)/BB_PERIOD;std=(sum((x-sma)**2 for x in w)/BB_PERIOD)**0.5
        bb_u[i]=sma+BB_STD*std;bb_l[i]=sma-BB_STD*std
    rs=[None]*n
    for i in range(RSI_PERIOD,n):
        g=sum(max(cl[j]-cl[j-1],0)for j in range(i-RSI_PERIOD+1,i+1))/RSI_PERIOD
        l=sum(max(cl[j-1]-cl[j],0)for j in range(i-RSI_PERIOD+1,i+1))/RSI_PERIOD
        rs[i]=100-100/(1+g/l)if l>0 else 100
    atr=[None]*n
    for i in range(14,n):
        tr=[max(hi[j]-lo[j],abs(hi[j]-cl[j-1]),abs(lo[j]-cl[j-1]))for j in range(i-13,i+1)]
        atr[i]=(sum(tr)/14)/cl[i]*100
    v=[v for v in atr if v is not None];am=sum(v)/len(v)if v else 0.35
    return bb_u,bb_l,rs,atr,am

def main():
    print("="*80)
    print("BB+RSI v2 最近一月机会点分析 (TP0.5/SL0.3)")
    print("="*80)
    
    bars=fetch_all(3000)
    if len(bars)<500: print("数据不足");return
    
    bb_u,bb_l,rs,atr,am=calc(bars)
    mi=max(BB_PERIOD,RSI_PERIOD,14)+1
    
    # 统计每天的信号、交易、盈亏
    daily_signals=defaultdict(lambda:{"short":0,"long":0,"trades":0,"pnl":0})
    trades=[]
    in_pos=None;ep=0;eb=0
    eq=[1.0]
    
    for i in range(mi,len(bars)):
        if in_pos:
            h=i-eb;c=bars[i]["c"];pnl=(c-ep)/ep if in_pos=="long" else (ep-c)/ep
            if pnl>=TP_PCT:
                trades.append({"dt":datetime.fromtimestamp(bars[i]["ts"],tz=timezone.utc),"s":in_pos,"e":ep,"x":c,"pnl":pnl-FEE,"r":"TP"})
                eq.append(eq[-1]*(1+pnl-FEE))
                day=datetime.fromtimestamp(bars[i]["ts"],tz=timezone.utc).strftime("%m-%d")
                daily_signals[day]["trades"]+=1;daily_signals[day]["pnl"]+=pnl-FEE
                in_pos=None;continue
            if pnl<=-SL_PCT:
                trades.append({"dt":datetime.fromtimestamp(bars[i]["ts"],tz=timezone.utc),"s":in_pos,"e":ep,"x":c,"pnl":pnl-FEE,"r":"SL"})
                eq.append(eq[-1]*(1+pnl-FEE))
                day=datetime.fromtimestamp(bars[i]["ts"],tz=timezone.utc).strftime("%m-%d")
                daily_signals[day]["trades"]+=1;daily_signals[day]["pnl"]+=pnl-FEE
                in_pos=None;continue
            if h>=MAX_BARS:
                trades.append({"dt":datetime.fromtimestamp(bars[i]["ts"],tz=timezone.utc),"s":in_pos,"e":ep,"x":c,"pnl":pnl-FEE,"r":"TO"})
                eq.append(eq[-1]*(1+pnl-FEE))
                day=datetime.fromtimestamp(bars[i]["ts"],tz=timezone.utc).strftime("%m-%d")
                daily_signals[day]["trades"]+=1;daily_signals[day]["pnl"]+=pnl-FEE
                in_pos=None;continue
            continue
        
        # 扫描信号
        sig=None
        for j in range(i-1,max(i-4,mi-1),-1):
            if bb_u[j] is None or rs[j] is None or atr[j] is None: continue
            if atr[j]<am*ATR_F: continue
            cj=bars[j]["c"]
            if cj>bb_u[j] and rs[j]>RSI_H: sig="short";ep=cj;break
            elif cj<bb_l[j] and rs[j]<RSI_L: sig="long";ep=cj;break
        
        if sig:
            day=datetime.fromtimestamp(bars[i]["ts"],tz=timezone.utc).strftime("%m-%d")
            daily_signals[day][sig]+=1
            in_pos=sig;eb=i
    
    # 按日输出
    print(f"\n{'日期':<8} {'做空信号':>8} {'做多信号':>8} {'交易':>6} {'盈亏':>9}")
    print("-"*45)
    
    total_s=0;total_t=0;total_p=0
    sorted_days=sorted(daily_signals.keys())[-30:]
    for day in sorted_days:
        d=daily_signals[day]
        tp=""
        if d["pnl"]>0:tp=f"${d['pnl']*3*100:+.2f}".replace("+-","-")  # ~$3/笔
        elif d["pnl"]<0:tp=f"${d['pnl']*3*100:+.2f}".replace("+-","-")
        else:tp="—"
        print(f"{day:<8} {d['short']:>8} {d['long']:>8} {d['trades']:>6} {tp:>9}")
        total_s+=d["short"]+d["long"];total_t+=d["trades"];total_p+=d["pnl"]
    
    print("-"*45)
    print(f"{'合计':<8} {total_s:>8} {'':>8} {total_t:>6} ${total_p*3*100:>+.2f}")
    
    # 最近7天逐笔
    print(f"\n{'='*80}")
    print("最近7天逐笔明细")
    print(f"{'='*80}")
    print(f"{'#':>3} {'时间':<20} {'方向':<6} {'入场':>9} {'出场':>9} {'盈亏':>8} {'原因':<6}")
    print("-"*65)
    recent=[t for t in trades if t["dt"]>=datetime(2026,5,14,tzinfo=timezone.utc)]
    wins=[t for t in recent if t["pnl"]>0]
    for i,t in enumerate(recent,1):
        ts=t["dt"].strftime("%m-%d %H:%M");ar="↑多"if t["s"]=="long" else "↓空"
        print(f"{i:>3} {ts:<20} {ar:<6} {t['e']:>9.1f} {t['x']:>9.1f} {t['pnl']*100:>+7.2f}% {t['r']:<6}")
    
    if recent:
        print(f"\n近期: {len(recent)}笔, 胜率{len(wins)/len(recent)*100:.1f}%, "
              f"累计{sum(t['pnl']for t in recent)*3*100:+.2f}$")

if __name__=="__main__":
    main()
