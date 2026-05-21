#!/usr/bin/env python3
"""BB+RSI v2 180天回测"""
import requests, math
from datetime import datetime, timezone

GATE = "https://api.gateio.ws/api/v4/spot/candlesticks"
PROXY = "http://127.0.0.1:2080"
TP=0.005;SL=0.003;MAX_BARS=24;FEE=0.0007
BB_P=20;BB_S=2;RSI_P=10;RSI_H=65;RSI_L=35;ATR_F=0.6
TARGET = 180*96  # ~17280根

def fetch():
    bars=[]
    page=0
    while len(bars)<TARGET:
        to=bars[0]["ts"] if bars else None
        p={"currency_pair":"BTC_USDT","interval":"15m","limit":1000}
        if to:p["to"]=to
        try:
            r=requests.get(GATE,params=p,proxies={"http":PROXY,"https":PROXY},timeout=30)
            d=r.json()
            if not d:break
            c=[{"ts":int(row[0]),"c":float(row[2]),"h":float(row[3]),"l":float(row[4])} for row in d]
            if bars:c=[b for b in c if b["ts"]<bars[0]["ts"]]
            bars=c+bars;page+=1
            print(f"  第{page}页 累计{len(bars)}根...")
            if len(c)<1000:break
        except Exception as e:
            print(f"  [网错] {e}");break
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
            if pnl>=TP:trades.append({"s":in_pos,"pnl":pnl-FEE,"r":"TP"});eq.append(eq[-1]*(1+pnl-FEE));in_pos=None;continue
            if pnl<=-SL:trades.append({"s":in_pos,"pnl":pnl-FEE,"r":"SL"});eq.append(eq[-1]*(1+pnl-FEE));in_pos=None;continue
            if h>=MAX_BARS:trades.append({"s":in_pos,"pnl":pnl-FEE,"r":"TO"});eq.append(eq[-1]*(1+pnl-FEE));in_pos=None;continue
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
        trades.append({"s":in_pos,"pnl":pnl-FEE,"r":"OPEN"})
    return trades,eq

def main():
    print("="*75)
    print("BB+RSI v2 180天回测 (TP0.5/SL0.3/ATR0.6)")
    print("="*75)
    bars=fetch()
    if len(bars)<500:print("数据不足");return
    total=len(bars)
    print(f"\n✅ {total}根 | {datetime.fromtimestamp(bars[0]['ts']).strftime('%m-%d %H:%M')}~{datetime.fromtimestamp(bars[-1]['ts']).strftime('%m-%d %H:%M')}")
    
    for days in [30,60,90,180]:
        start=max(0,total-days*96)
        pb=bars[start:]
        trades,eq=bt(pb)
        if not trades:continue
        wins=[t for t in trades if t["pnl"]>0];losses=[t for t in trades if t["pnl"]<=0]
        comp=(eq[-1]-1)*100
        tp_n=sum(1 for t in trades if t["r"]=="TP");sl_n=sum(1 for t in trades if t["r"]=="SL");to_n=sum(1 for t in trades if t["r"]=="TO")
        avg_w=sum(t["pnl"]for t in wins)/len(wins)*100 if wins else 0
        avg_l=sum(t["pnl"]for t in losses)/len(losses)*100 if losses else 0
        longs=sum(1 for t in trades if t["s"]=="long");shorts=len(trades)-longs
        print(f"\n{days}天: {len(trades):>4}笔 | 胜率{len(wins)/len(trades)*100:.1f}% | 复利{comp:+7.2f}% | "
              f"多{longs}/空{shorts} | TP{tp_n} SL{sl_n} TO{to_n}")
        print(f"       均赢{avg_w:+.2f}% 均亏{avg_l:+.2f}% | 权益 1.0000→{eq[-1]:.4f}")
        
        # 资金曲线关键点
        if days==180:
            # 找最大回撤
            peak=1.0;max_dd=0;dd_start=0
            for i,v in enumerate(eq):
                if v>peak:peak=v
                dd=peak-v
                if dd>max_dd:max_dd=dd;dd_start=i
            print(f"       最大回撤: {max_dd*100:.2f}%")
            
            # 盈亏月份分析
            monthly={}
            for t in trades:
                m=datetime.fromtimestamp(t.get("ts",bars[0]["ts"]),tz=timezone.utc).strftime("%m")
                monthly[m]=monthly.get(m,0)+t["pnl"]
            print(f"       月盈亏: {' '.join(f'{m}:{v*100:+.1f}%' for m,v in sorted(monthly.items()))}")
    
    # 收益估算
    t180,_=bt(bars)
    wins=sum(1 for t in t180 if t["pnl"]>0);losses=len(t180)-wins
    avg_w=sum(t["pnl"]for t in t180 if t["pnl"]>0)/wins if wins else 0
    avg_l=sum(t["pnl"]for t in t180 if t["pnl"]<=0)/losses if losses else 0
    bal=37.54;lev=10;btc=78000;ct_val=btc*0.01
    for pct in [30,50]:
        m=bal*pct/100;ct=round(m/(ct_val/lev),3)
        profit=wins*ct*ct_val*avg_w-losses*ct*ct_val*abs(avg_l)
        print(f"\n💰 10x/{pct}%: {ct:.3f}张 | 180天 {len(t180)}笔 | 净利${profit:+.2f} ({profit/bal*100:+.1f}%)")

if __name__=="__main__":
    main()
