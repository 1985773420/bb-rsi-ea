#!/usr/bin/env python3
"""含滑点+手续费的真实回测对比"""
import sys,math,time
from datetime import datetime,timezone
sys.path.insert(0,'/root/.hermes/scripts');import datastore as db

FEE=0.0007;SLIP_ENTRY=0.0002;SLIP_EXIT=0.0002  # 万7费+万2滑点×2
BAL=37.48

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

def bt_live(bars,bb_p,bb_s,rsi_p,rh,rl,atr_f,tp,sl,mb):
    """真实回测：含入场滑点+出场滑点+手续费"""
    bu,bl,rsi,atr,am=ic(bars,bb_p,bb_s,rsi_p)
    trades=[];eq=[1.0];pos=None;ep=0;eb=0;mi=max(bb_p,rsi_p,14)+1;n=len(bars)
    for i in range(mi,n):
        if pos:
            c=bars[i]['c'];h=i-eb;pnl=(c-ep)/ep if pos=='long'else(ep-c)/ep
            if pnl>=tp:
                actual_close=ep*(1+tp)*(1-SLIP_EXIT) if pos=='long' else ep*(1-tp)*(1+SLIP_EXIT)
                actual_pnl=(actual_close-ep)/ep if pos=='long' else (ep-actual_close)/ep
                trades.append({'pnl':actual_pnl-FEE});eq.append(eq[-1]*(1+actual_pnl-FEE));pos=None;continue
            if pnl<=-sl:
                actual_close=ep*(1-sl)*(1-SLIP_EXIT) if pos=='long' else ep*(1+sl)*(1+SLIP_EXIT)
                actual_pnl=(actual_close-ep)/ep if pos=='long' else (ep-actual_close)/ep
                trades.append({'pnl':actual_pnl-FEE});eq.append(eq[-1]*(1+actual_pnl-FEE));pos=None;continue
            if h>=mb:
                actual_close=c*(1-SLIP_EXIT) if pos=='long' else c*(1+SLIP_EXIT)
                actual_pnl=(actual_close-ep)/ep if pos=='long' else (ep-actual_close)/ep
                trades.append({'pnl':actual_pnl-FEE});eq.append(eq[-1]*(1+actual_pnl-FEE));pos=None;continue
            continue
        sig=None;sb=None
        for j in range(i-1,max(i-4,mi-1),-1):
            if bu[j] is None or rsi[j] is None or atr[j] is None:continue
            if atr_f>0 and atr[j]<am*atr_f:continue
            cj=bars[j]['c']
            if cj>bu[j] and rsi[j]>rh:sig='short';sb=j;break
            elif cj<bl[j] and rsi[j]<rl:sig='long';sb=j;break
        if sig:
            # 入场滑点：做多→更高成本，做空→更低收入
            ep=bars[sb]['c']*(1+SLIP_ENTRY) if sig=='long' else bars[sb]['c']*(1-SLIP_ENTRY)
            pos=sig;eb=i
    if pos:
        c=bars[-1]['c']
        actual_pnl=(c-ep)/ep if pos=='long'else(ep-c)/ep
        trades.append({'pnl':actual_pnl-FEE})
    return trades,eq

def analyze(trades,eq):
    if not trades:return None
    total=(eq[-1]-1)*100;wins=[t for t in trades if t['pnl']>0]
    wr=len(wins)/len(trades)*100 if trades else 0
    peak=1.0;dd=0
    for v in eq:
        if v>peak:peak=v
        if(peak-v)/peak>dd:dd=(peak-v)/peak
    days=(bars[-1]['ts']-bars[0]['ts'])/86400000
    annual=total/max(1,days)*365
    # 用当前余额模拟真实收益
    bal=BAL;margin=0.8;lev=9
    for t in trades:
        ct_val=BAL*0.01;sz=max(0.01,round(bal*margin/(ct_val/lev)*100)/100)
        bal*=(1+t['pnl'])
    return total,wr,dd*100,annual,len(trades),bal

bars=db.get_range(0)
t0=time.time()
total_days=(bars[-1]['ts']-bars[0]['ts'])/86400000

print(f"数据:{len(bars)}根 | {total_days:.0f}天 | 滑点万2×2+手续费万7")
print()

# 多组参数对比
params=[
  ("当前超紧",    20,2,7,65,35,0.5,0.003,0.002,16),
  ("TP0.4/SL0.25",20,2,7,65,35,0.5,0.004,0.0025,20),
  ("TP0.5/SL0.3", 20,2,7,65,35,0.6,0.005,0.003,24),
  ("TP0.6/SL0.3", 20,2,7,65,35,0.6,0.006,0.003,24),
  ("TP0.6/SL0.4", 20,2,7,65,35,0.6,0.006,0.004,24),
  ("TP0.8/SL0.4", 20,2,7,65,35,0.5,0.008,0.004,24),
  ("原版",         20,2,7,70,30,0.5,0.005,0.003,24),
]

print(f"{'策略':<16}{'年化%':>8}{'总收益%':>10}{'胜率%':>6}{'回撤%':>6}{'交易':>6}{'余额':>10}{'TP%':>5}{'SL%':>5}")
print("-"*80)
for name,bb_p,bb_s,r_p,rh,rl,af,tp,sl,mb in params:
    trades,eq=bt_live(bars,bb_p,bb_s,r_p,rh,rl,af,tp,sl,mb)
    r=analyze(trades,eq)
    if r:
        tot,wr,dd,ann,nt,fbal=r
        pnl=fbal-BAL
        print(f"{name:<16}{ann:>+7.0f}%{tot:>+9.0f}%{wr:>5.0f}%{dd:>5.0f}%{nt:>6}{fbal:>9.2f}{tp*100:>5.1f}{sl*100:>5.2f}")

# 微调最优
print(f"\n--- 微调 ---")
best=None
for tp in[0.003,0.004,0.005,0.006,0.008]:
 for sl in[0.002,0.0025,0.003,0.004]:
  for mb in[16,20,24]:
   if sl>=tp:continue
   trades,eq=bt_live(bars,20,2,7,65,35,0.5,tp,sl,mb)
   r=analyze(trades,eq)
   if r and (best is None or r[0]>best[0]):
       best=(r[0],r[1],r[2],r[3],r[4],r[5],tp,sl,mb)

print(f"最优: TP{best[6]*100:.1f}% SL{best[7]*100:.2f}% 超时{best[8]} → 年化{best[0]:+.0f}% 胜率{best[2]:.0f}% 余额${best[5]:.2f}")
print(f"\n耗时{(time.time()-t0):.0f}s")
