#!/usr/bin/env python3
"""杠杆×策略组合极致对比：含滑点+手续费"""
import sys,math,time
from datetime import datetime,timezone
sys.path.insert(0,'/root/.hermes/scripts');import datastore as db

FEE=0.0007;SLIP=0.0002;BAL=37.48

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

def bt(bars,bb_p,bb_s,rsi_p,rh,rl,af,tp,sl,mb):
    bu,bl,rsi,atr,am=ic(bars,bb_p,bb_s,rsi_p)
    trades=[];eq=[1.0];pos=None;ep=0;eb=0;mi=max(bb_p,rsi_p,14)+1;n=len(bars)
    for i in range(mi,n):
        if pos:
            c=bars[i]['c'];h=i-eb;pnl=(c-ep)/ep if pos=='long'else(ep-c)/ep
            if pnl>=tp:
                ac=ep*(1+tp)*(1-SLIP)if pos=='long' else ep*(1-tp)*(1+SLIP)
                ap=(ac-ep)/ep if pos=='long' else (ep-ac)/ep
                trades.append({'pnl':ap-FEE});eq.append(eq[-1]*(1+ap-FEE));pos=None;continue
            if pnl<=-sl:
                ac=ep*(1-sl)*(1-SLIP)if pos=='long' else ep*(1+sl)*(1+SLIP)
                ap=(ac-ep)/ep if pos=='long' else (ep-ac)/ep
                trades.append({'pnl':ap-FEE});eq.append(eq[-1]*(1+ap-FEE));pos=None;continue
            if h>=mb:
                ac=c*(1-SLIP)if pos=='long' else c*(1+SLIP)
                ap=(ac-ep)/ep if pos=='long' else(ep-ac)/ep
                trades.append({'pnl':ap-FEE});eq.append(eq[-1]*(1+ap-FEE));pos=None;continue
            continue
        sig=None;sb=None
        for j in range(i-1,max(i-4,mi-1),-1):
            if bu[j] is None or rsi[j] is None or atr[j] is None:continue
            if af>0 and atr[j]<am*af:continue
            cj=bars[j]['c']
            if cj>bu[j] and rsi[j]>rh:sig='short';sb=j;break
            elif cj<bl[j] and rsi[j]<rl:sig='long';sb=j;break
        if sig:ep=bars[sb]['c']*(1+SLIP)if sig=='long' else bars[sb]['c']*(1-SLIP);pos=sig;eb=i
    if pos:c=bars[-1]['c'];ap=(c-ep)/ep if pos=='long'else(ep-c)/ep;trades.append({'pnl':ap-FEE})
    return trades,eq

bars=db.get_range(0);t0=time.time()
total_days=(bars[-1]['ts']-bars[0]['ts'])/86400000

# 最佳参数组合们 + 杠杆扫描
combos=[
    ("BB20 R7[65/35] A0.5 TP0.8/SL0.4",20,2,7,65,35,0.5,0.008,0.004,24),
    ("BB20 R7[65/35] A0.6 TP0.6/SL0.3",20,2,7,65,35,0.6,0.006,0.003,24),
    ("BB20 R7[60/40] A0.4 TP0.8/SL0.4",20,2,7,60,40,0.4,0.008,0.004,20),
    ("BB14 R5[60/40] A0.3 TP0.6/SL0.3",14,2,5,60,40,0.3,0.006,0.003,16),
    ("BB20 R7[65/35] A0.0 TP0.8/SL0.4",20,2,7,65,35,0,  0.008,0.004,20),
]

print(f"数据:{len(bars)}根/{total_days:.0f}天 | 滑点万2+费万7\n")
print(f"{'策略':<32}{'杠杆':>5}{'保证金':>5}{'年化%':>9}{'胜率%':>6}{'回撤%':>6}{'交易':>6}{'余额':>10}{'爆仓'}")
print("-"*90)

for name,bb_p,bb_s,r_p,rh,rl,af,tp,sl,mb in combos:
    trades,eq=bt(bars,bb_p,bb_s,r_p,rh,rl,af,tp,sl,mb)
    if not trades:continue
    total=(eq[-1]-1)*100;wins=[t for t in trades if t['pnl']>0]
    wr=len(wins)/len(trades)*100;peak=1.0;dd=0
    for v in eq:
        if v>peak:peak=v
        if(peak-v)/peak>dd:dd=(peak-v)/peak
    ann=total/total_days*365
    for lev in[9,12,15,20]:
        for mg in[0.7,0.8]:
            bal=BAL;blown=False
            for t in trades:
                ct_val=78000*0.01;sz=max(0.01,round(bal*mg/(ct_val/lev)*100)/100)
                new_bal=bal*(1+t['pnl'])
                if new_bal<=0:blown=True;break
                bal=new_bal
            if blown:print(f"{name:<32}{lev:>5}{mg:>5.0f}{ann:>9.0f}%{wr:>5.0f}%{dd*100:>5.0f}%{len(trades):>6}{'爆仓':>10}💥");continue
            print(f"{name:<32}{lev:>5}{mg:>5.0f}{ann:>9.0f}%{wr:>5.0f}%{dd*100:>5.0f}%{len(trades):>6}{bal:>10.2f}")
    print()

print(f"耗时{(time.time()-t0):.0f}s")
