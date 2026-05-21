#!/usr/bin/env python3
"""直接对比: 多组参数在6年数据上的表现"""
import sys,math,time
from datetime import datetime,timezone
sys.path.insert(0,'/root/.hermes/scripts');import datastore as db

FEE=0.0007;BAL=37.48

def ic(bars,bb_p,bb_s,rsi_p):
    n=len(bars);cl=[b['c']for b in bars];hi=[b['h']for b in bars];lo=[b['l']for b in bars]
    bu=[None]*n;bl=[None]*n
    for i in range(bb_p-1,n):
        w=cl[i-bb_p+1:i+1];sma=sum(w)/bb_p;std=math.sqrt(sum((x-sma)**2 for x in w)/bb_p)
        bu[i]=sma+bb_s*std;bl[i]=sma-bb_s*std
    r=[None]*n
    for i in range(rsi_p,n):
        g=sum(max(cl[j]-cl[j-1],0)for j in range(i-rsi_p+1,i+1))/rsi_p
        l=sum(max(cl[j-1]-cl[j],0)for j in range(i-rsi_p+1,i+1))/rsi_p
        r[i]=100-100/(1+g/l)if l>0 else 100
    atr=[None]*n;tl=[]
    for i in range(n):
        if i==0:tr=hi[i]-lo[i]
        else:tr=max(hi[i]-lo[i],abs(hi[i]-cl[i-1]),abs(lo[i]-cl[i-1]))
        tl.append(tr)
        if i>=14:atr[i]=(sum(tl[-14:])/14)/cl[i]*100
    v=[x for x in atr if x];am=sum(v)/len(v)if v else 0.35
    return bu,bl,r,atr,am

def bt(bars,bb_p,bb_s,rsi_p,rh,rl,atr_f,tp,sl,mb):
    bu,bl,rsi,atr,am=ic(bars,bb_p,bb_s,rsi_p)
    trades=[];eq=[1.0];pos=None;ep=0;eb=0;mi=max(bb_p,rsi_p,14)+1;n=len(bars)
    for i in range(mi,n):
        if pos:
            c=bars[i]['c'];h=i-eb;pnl=(c-ep)/ep if pos=='long'else(ep-c)/ep
            if pnl>=tp:trades.append({'pnl':pnl-FEE});eq.append(eq[-1]*(1+pnl-FEE));pos=None;continue
            if pnl<=-sl:trades.append({'pnl':pnl-FEE});eq.append(eq[-1]*(1+pnl-FEE));pos=None;continue
            if h>=mb:trades.append({'pnl':pnl-FEE});eq.append(eq[-1]*(1+pnl-FEE));pos=None;continue
            continue
        sig=None;sb=None
        for j in range(i-1,max(i-4,mi-1),-1):
            if bu[j] is None or rsi[j] is None or atr[j] is None:continue
            if atr_f>0 and atr[j]<am*atr_f:continue
            cj=bars[j]['c']
            if cj>bu[j] and rsi[j]>rh:sig='short';sb=j;break
            elif cj<bl[j] and rsi[j]<rl:sig='long';sb=j;break
        if sig:pos=sig;ep=bars[sb]['c'];eb=i
    if pos:c=bars[-1]['c'];pnl=(c-ep)/ep if pos=='long'else(ep-c)/ep;trades.append({'pnl':pnl-FEE})
    return trades,eq

def analyze(trades,eq):
    if not trades:return None
    total=(eq[-1]-1)*100;wins=[t for t in trades if t['pnl']>0]
    wr=len(wins)/len(trades)*100;peak=1.0;dd=0
    for v in eq:
        if v>peak:peak=v
        if(peak-v)/peak>dd:dd=(peak-v)/peak
    days=(bars[-1]['ts']-bars[0]['ts'])/86400000
    annual=total/max(1,days)*365
    return total,wr,dd*100,annual,len(trades)

bars=db.get_range(0)
t0=time.time()
print(f"数据:{len(bars)}根 | {(bars[-1]['ts']-bars[0]['ts'])/86400000:.0f}天\n")

# 12组精心选择的参数对比
params=[
  ("当前最优",  20,2,7,65,35,0.6,0.004,0.0025,20),
  ("原版参数",  20,2,7,70,30,0.5,0.005,0.003,24),
  ("BB14紧",    14,2,7,65,35,0.6,0.004,0.0025,20),
  ("BB20松RSI", 20,2,7,60,40,0.5,0.005,0.003,24),
  ("宽TP",      20,2,7,65,35,0.6,0.008,0.003,24),
  ("无ATR过滤", 20,2,7,65,35,0,  0.005,0.003,24),
  ("高频紧TP",  20,2,5,60,40,0.4,0.003,0.002,16),
  ("BB14+宽ATR",14,2,10,70,30,0.7,0.006,0.004,24),
  ("超紧",      20,2,7,65,35,0.5,0.003,0.002,16),
  ("BB10",      10,2,7,65,35,0.5,0.005,0.003,24),
  ("RSI14保守", 20,2,14,70,30,0.6,0.006,0.004,30),
  ("极限高频",  14,2,5,55,45,0.3,0.004,0.0025,16),
]

print(f"{'策略':<14}{'年化%':>8}{'总收益%':>10}{'胜率%':>6}{'回撤%':>6}{'交易':>6}{'TP%':>5}{'SL%':>5}")
print("-"*65)
for name,bb_p,bb_s,r_p,rh,rl,af,tp,sl,mb in params:
    trades,eq=bt(bars,bb_p,bb_s,r_p,rh,rl,af,tp,sl,mb)
    r=analyze(trades,eq)
    if r:
        tot,wr,dd,ann,nt=r
        print(f"{name:<14}{ann:>+7.0f}%{tot:>+9.0f}%{wr:>5.0f}%{dd:>5.0f}%{nt:>6}{tp*100:>5.1f}{sl*100:>5.2f}")

print(f"\n耗时{(time.time()-t0):.0f}s")
