#!/usr/bin/env python3
"""OKX history-candles 180天完整回测"""
import requests, math, json, time
from datetime import datetime, timezone

URL = "https://www.okx.com/api/v5/market/history-candles"
PROXY = "http://127.0.0.1:2080"
TP=0.005;SL=0.003;MAX_BARS=24;FEE=0.0007
BB_P=20;BB_S=2;RSI_P=10;RSI_H=65;RSI_L=35;ATR_F=0.6

def fetch(inst="BTC-USDT", days=180):
    target = days * 96
    bars = []
    after = int(time.time() * 1000)  # 从现在开始
    
    while len(bars) < target:
        try:
            r = requests.get(URL, params={"instId":inst,"bar":"15m","limit":300,"after":str(after)},
                           proxies={"http":PROXY,"https":PROXY}, timeout=30)
            data = r.json().get("data",[])
            if not data: break
            
            chunk = [{"ts":int(row[0]),"c":float(row[4]),"h":float(row[2]),"l":float(row[3])} for row in data]
            bars = chunk + bars
            after = int(data[-1][0])  # 用最早那根的ts继续往前
            time.sleep(0.1)  # 限速
            
            if len(bars) % 1000 < 300:
                dt = datetime.fromtimestamp(bars[0]["ts"]/1000)
                print(f"  {len(bars)}根, 最早{dt.strftime('%Y-%m-%d')}")
        except Exception as e:
            print(f"  [错] {e}"); time.sleep(1)
    
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

def bt(bars):
    bb_u,bb_l,rs,atr,am=calc(bars);trades=[]
    in_pos=None;ep=0;eb=0;eq=[1.0]
    mi=max(BB_P,RSI_P,14)+1;n=len(bars)
    for i in range(mi,n):
        if in_pos:
            h=i-eb;c=bars[i]["c"];pnl=(c-ep)/ep if in_pos=="long" else (ep-c)/ep
            if pnl>=TP:trades.append({"s":in_pos,"pnl":pnl-FEE,"r":"TP","ts":bars[i]["ts"]});eq.append(eq[-1]*(1+pnl-FEE));in_pos=None;continue
            if pnl<=-SL:trades.append({"s":in_pos,"pnl":pnl-FEE,"r":"SL","ts":bars[i]["ts"]});eq.append(eq[-1]*(1+pnl-FEE));in_pos=None;continue
            if h>=MAX_BARS:trades.append({"s":in_pos,"pnl":pnl-FEE,"r":"TO","ts":bars[i]["ts"]});eq.append(eq[-1]*(1+pnl-FEE));in_pos=None;continue
            continue
        sig=None
        for j in range(i-1,max(i-4,mi-1),-1):
            if bb_u[j] is None or rs[j] is None or atr[j] is None:continue
            if atr[j]<am*ATR_F:continue
            cj=bars[j]["c"]
            if cj>bb_u[j] and rs[j]>RSI_H:sig="short";ep=cj;break
            elif cj<bb_l[j] and rs[j]<RSI_L:sig="long";ep=cj;break
        if sig:in_pos=sig;eb=i
    if in_pos:
        c=bars[-1]["c"];pnl=(c-ep)/ep if in_pos=="long" else (ep-c)/ep
        trades.append({"s":in_pos,"pnl":pnl-FEE,"r":"OPEN","ts":bars[-1]["ts"]})
    return trades,eq

def main():
    print("="*75)
    print("BB+RSI v2 180天完整回测 (OKX history-candles)")
    print("="*75)
    
    bars=fetch("BTC-USDT", 180)
    if len(bars)<500:print("数据不足");return
    print(f"\n✅ {len(bars)}根 | {datetime.fromtimestamp(bars[0]['ts']/1000).strftime('%Y-%m-%d')}~{datetime.fromtimestamp(bars[-1]['ts']/1000).strftime('%Y-%m-%d')}")
    
    for days in [30,60,90,180]:
        start=max(0,len(bars)-days*96)
        pb=bars[start:]
        trades,eq=bt(pb)
        if not trades:continue
        wins=[t for t in trades if t["pnl"]>0];losses=[t for t in trades if t["pnl"]<=0]
        comp=(eq[-1]-1)*100
        avg_w=sum(t["pnl"]for t in wins)/len(wins)*100 if wins else 0
        avg_l=sum(t["pnl"]for t in losses)/len(losses)*100 if losses else 0
        longs=sum(1 for t in trades if t["s"]=="long")
        tp_n=sum(1 for t in trades if t["r"]=="TP");sl_n=sum(1 for t in trades if t["r"]=="SL");to_n=sum(1 for t in trades if t["r"]=="TO")
        
        print(f"\n{days:>3}天: {len(trades):>4}笔 | 胜率{len(wins)/len(trades)*100:.1f}% | 复利{comp:+7.2f}% | "
              f"多{longs}/空{len(trades)-longs} | TP{tp_n} SL{sl_n} TO{to_n}")
        print(f"      均赢{avg_w:+.2f}% 均亏{avg_l:+.2f}% | 权益1→{eq[-1]:.4f}")
        
        if days==180:
            peak=1.0;max_dd=0
            for v in eq:
                if v>peak:peak=v
                dd=peak-v
                if dd>max_dd:max_dd=dd
            print(f"      最大回撤: {max_dd*100:.2f}%")
            
            # 月度分析
            monthly={}
            for t in trades:
                m=datetime.fromtimestamp(t["ts"]/1000,tz=timezone.utc).strftime("%Y-%m")
                monthly[m]=monthly.get(m,0)+t["pnl"]
            months=list(monthly.keys())
            total_pnl=sum(monthly.values())*100
            pos_months=sum(1 for v in monthly.values() if v>0)
            print(f"      月盈亏: {len(months)}个月, {pos_months}月盈利/{len(months)-pos_months}月亏损")
            for m in months[:6]:
                print(f"        {m}: {monthly[m]*100:+.2f}%")
            if len(months)>6: print(f"        ...(共{len(months)}个月)")
    
    # 收益估算
    t180,_=bt(bars)
    wins=sum(1 for t in t180 if t["pnl"]>0);losses=len(t180)-wins
    aw=sum(t["pnl"]for t in t180 if t["pnl"]>0)/wins if wins else 0
    al=sum(t["pnl"]for t in t180 if t["pnl"]<=0)/losses if losses else 0
    bal=37.54;lev=10;btc_=bars[-1]["c"];ct_val=btc_*0.01
    
    print(f"\n💰 收益预估 (BTC=${btc_:.0f})")
    for pct in [30,50]:
        m=bal*pct/100;ct=round(m/(ct_val/lev),3)
        ntl=ct*ct_val
        profit=wins*ct*ct_val*aw-losses*ct*ct_val*abs(al)
        print(f"  10x/{pct}%: {ct:.3f}张 ${ntl:.0f}名义 | {len(t180)}笔 | 净利${profit:+.2f} ({profit/bal*100:+.1f}%)")

if __name__=="__main__":
    main()
