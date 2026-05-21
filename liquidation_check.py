#!/usr/bin/env python3
"""全量爆仓检测 v2：正确杠杆倍率"""
import sys,math,time
from datetime import datetime,timezone
sys.path.insert(0,'/root/.hermes/scripts');import datastore as db

TP=0.008;SL=0.004;MAX_BARS=24;FEE=0.0007
BB_P=20;BB_S=2;RSI_P=7;RSI_H=65;RSI_L=35;ATR_F=0.5
SLIP=0.0002;LEV=15;MARGIN=0.8

def ic(bars):
    n=len(bars);cl=[b['c']for b in bars];hi=[b['h']for b in bars];lo=[b['l']for b in bars]
    bu=[None]*n;bl=[None]*n
    for i in range(BB_P-1,n):
        w=cl[i-BB_P+1:i+1];sma=sum(w)/BB_P;std=math.sqrt(sum((x-sma)**2 for x in w)/BB_P)
        bu[i]=sma+BB_S*std;bl[i]=sma-BB_S*std
    r=[None]*n
    for i in range(RSI_P,n):
        g=sum(max(cl[j]-cl[j-1],0)for j in range(i-RSI_P+1,i+1))/RSI_P
        l=sum(max(cl[j-1]-cl[j],0)for j in range(i-RSI_P+1,i+1))/RSI_P
        r[i]=100-100/(1+g/l)if l>0 else 100
    atr=[None]*n;tl=[]
    for i in range(n):
        if i==0:tr=hi[i]-lo[i]
        else:tr=max(hi[i]-lo[i],abs(hi[i]-cl[i-1]),abs(lo[i]-cl[i-1]))
        tl.append(tr)
        if i>=14:atr[i]=(sum(tl[-14:])/14)/cl[i]*100
    v=[x for x in atr if x];am=sum(v)/len(v)if v else 0.35
    return bu,bl,r,atr,am

def simulate(bars,bal0,lev,mg):
    bu,bl,rsi,atr,am=ic(bars)
    bal=bal0;pos=None;ep=0;eb=0;mi=max(BB_P,RSI_P,14)+1;n=len(bars)
    trades=[];eq=[bal0];max_bal=bal0;max_dd=0;deepest_dd_bar=0
    liquidated=False;liq_bar=0

    for i in range(mi,n):
        c=bars[i]['c'];h=i-eb if pos else 0
        if pos:
            pnl=(c-ep)/ep if pos=='long'else(ep-c)/ep
            if pnl>=TP:
                ac=ep*(1+TP)*(1-SLIP)if pos=='long' else ep*(1-TP)*(1+SLIP)
                ap=(ac-ep)/ep if pos=='long' else (ep-ac)/ep;net=ap-FEE
                bal*=(1+net*mg*lev)  # 杠杆倍率
                trades.append({'pnl':net,'ts':bars[i]['ts'],'reason':'TP','bal':bal});pos=None;continue
            if pnl<=-SL:
                ac=ep*(1-SL)*(1-SLIP)if pos=='long' else ep*(1+SL)*(1+SLIP)
                ap=(ac-ep)/ep if pos=='long' else (ep-ac)/ep;net=ap-FEE
                bal*=(1+net*mg*lev)
                trades.append({'pnl':net,'ts':bars[i]['ts'],'reason':'SL','bal':bal});pos=None;continue
            if h>=MAX_BARS:
                ac=c*(1-SLIP)if pos=='long' else c*(1+SLIP)
                ap=(ac-ep)/ep if pos=='long'else(ep-ac)/ep;net=ap-FEE
                bal*=(1+net*mg*lev)
                trades.append({'pnl':net,'ts':bars[i]['ts'],'reason':'TO','bal':bal});pos=None;continue
            # 检查爆仓：净值为负
            if bal<=0:liquidated=True;liq_bar=i;break
            eq.append(bal);continue

        sig=None;sb=None
        for j in range(i-1,max(i-4,mi-1),-1):
            if bu[j] is None or rsi[j] is None or atr[j] is None:continue
            if atr[j]<am*ATR_F:continue
            cj=bars[j]['c']
            if cj>bu[j] and rsi[j]>RSI_H:sig='short';sb=j;break
            elif cj<bl[j] and rsi[j]<RSI_L:sig='long';sb=j;break
        if sig:
            epx=bars[sb]['c'];ep=epx*(1+SLIP)if sig=='long' else epx*(1-SLIP)
            pos=sig;eb=i

        eq.append(bal)
        if bal>max_bal:max_bal=bal
        dd=(max_bal-bal)/max_bal if max_bal>0 else 0
        if dd>max_dd:max_dd=dd;deepest_dd_bar=i

    return trades,eq,max_dd,liquidated,liq_bar,deepest_dd_bar

bars=db.get_range(0);t0=time.time()
total_days=(bars[-1]['ts']-bars[0]['ts'])/86400000

for lev,mg,label in[(15,0.8,'15x/80%'),(12,0.7,'12x/70%'),(10,0.6,'10x/60%'),(15,0.5,'15x/50%')]:
    trades,eq,max_dd,liquidated,liq_bar,dd_bar=simulate(bars,37.48,lev,mg)
    final=eq[-1];wins=[t for t in trades if t['pnl']>0]
    wr=len(wins)/len(trades)*100 if trades else 0
    ann=(final/37.48-1)/total_days*365*100
    status='🔴爆仓'if liquidated else'🟢安全'
    dd_pct=max_dd*100
    liq_dt=datetime.fromtimestamp(bars[liq_bar]['ts']/1000).strftime('%Y-%m-%d')if liquidated else '-'
    dd_dt=datetime.fromtimestamp(bars[dd_bar]['ts']/1000).strftime('%Y-%m-%d')if dd_bar<len(bars)else'-'
    print(f"{label:<10} {status:<6} 最终${final:>10.2f} 年化{ann:>+7.0f}% WR{wr:>4.0f}% DD{dd_pct:>5.1f}% {len(trades):>5}笔 DDdate:{dd_dt}")

print(f"\n{time.time()-t0:.0f}s")
