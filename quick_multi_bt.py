#!/usr/bin/env python3
"""真实回测：杠杆×滑点×手续费全含"""
import sys,math,time
from datetime import datetime,timezone
sys.path.insert(0,'/root/.hermes/scripts');import datastore as db

TP=0.008;SL=0.004;MAX_BARS=24;FEE=0.0007
BB_P=20;BB_S=2;RSI_P=7;RSI_H=65;RSI_L=35;ATR_F=0.5
SLIP=0.0002;BAL=37.48;LEV=15;MARGIN=0.8

def ic(bars):
    n=len(bars);cl=[b['c']for b in bars];hi=[b['h']for b in bars];lo=[b['l']for b in bars]
    bu=[None]*n;bl=[None]*n
    for i in range(BB_P-1,n):
        w=cl[i-BB_P+1:i+1];sma=sum(w)/BB_P;std=math.sqrt(sum((x-sma)**2 for x in w)/BB_P)
        bu[i]=sma+BB_S*std;bl[i]=sma-BB_S*std
    rsi=[None]*n
    for i in range(RSI_P,n):
        g=sum(max(cl[j]-cl[j-1],0)for j in range(i-RSI_P+1,i+1))/RSI_P
        l=sum(max(cl[j-1]-cl[j],0)for j in range(i-RSI_P+1,i+1))/RSI_P
        rsi[i]=100-100/(1+g/l)if l>0 else 100
    atr=[None]*n;tl=[]
    for i in range(n):
        if i==0:tr=hi[i]-lo[i]
        else:tr=max(hi[i]-lo[i],abs(hi[i]-cl[i-1]),abs(lo[i]-cl[i-1]))
        tl.append(tr)
        if i>=14:atr[i]=(sum(tl[-14:])/14)/cl[i]*100
    v=[x for x in atr if x];am=sum(v)/len(v)if v else 0.35
    return bu,bl,rsi,atr,am

def bt(bars):
    bu,bl,rsi,atr,am=ic(bars);trades=[];pos=None;ep=0;eb=0;epx=0;mi=max(BB_P,RSI_P,14)+1;n=len(bars)
    for i in range(mi,n):
        if pos:
            c=bars[i]['c'];h=i-eb;pnl=(c-ep)/ep if pos=='long'else(ep-c)/ep
            if pnl>=TP:
                ac=ep*(1+TP)*(1-SLIP)if pos=='long' else ep*(1-TP)*(1+SLIP)
                ap=(ac-ep)/ep if pos=='long' else (ep-ac)/ep
                trades.append({'pnl':ap-FEE,'ts':bars[i]['ts'],'reason':'TP','entry_px':epx});pos=None;continue
            if pnl<=-SL:
                ac=ep*(1-SL)*(1-SLIP)if pos=='long' else ep*(1+SL)*(1+SLIP)
                ap=(ac-ep)/ep if pos=='long' else (ep-ac)/ep
                trades.append({'pnl':ap-FEE,'ts':bars[i]['ts'],'reason':'SL','entry_px':epx});pos=None;continue
            if h>=MAX_BARS:ac=c*(1-SLIP)if pos=='long' else c*(1+SLIP);ap=(ac-ep)/ep if pos=='long'else(ep-ac)/ep;trades.append({'pnl':ap-FEE,'ts':bars[i]['ts'],'reason':'TO','entry_px':epx});pos=None;continue
            continue
        sig=None;sb=None
        for j in range(i-1,max(i-4,mi-1),-1):
            if bu[j] is None or rsi[j] is None or atr[j] is None:continue
            if atr[j]<am*ATR_F:continue
            cj=bars[j]['c']
            if cj>bu[j] and rsi[j]>RSI_H:sig='short';sb=j;break
            elif cj<bl[j] and rsi[j]<RSI_L:sig='long';sb=j;break
        if sig:epx=bars[sb]['c'];ep=epx*(1+SLIP)if sig=='long' else epx*(1-SLIP);pos=sig;eb=i
    if pos:c=bars[-1]['c'];ap=(c-ep)/ep if pos=='long'else(ep-c)/ap;trades.append({'pnl':ap-FEE,'entry_px':epx})
    return trades

def sim_account(trades,bal,lev,mg):
    """真实账户模拟：含杠杆和合约尺寸约束"""
    for t in trades:
        px=t.get('entry_px',78000);ct_val=px*0.01  # 合约价值=价格×0.01BTC
        if ct_val<=0:ct_val=780
        margin_per=ct_val/lev
        sz=max(0.01,round(bal*mg/margin_per*100)/100)  # 最少0.01张
        bal+=bal*t['pnl']*sz*ct_val/(bal*mg)*mg  # simplified: bal*(1+t['pnl']*leverage_factor)
        # 简化模型: 每笔交易收益=bal*mg*lev*(t['pnl'])
        # 实际: profit = sz*ct_val*t['pnl'] = bal*mg*lev*t['pnl']
    return bal

bars=db.get_range(0);n=len(bars)
print("="*80)
print(f"📊 实盘回测 | TP0.8% SL0.4% | 滑点万2+费万7 | 杠杆{LEV}x")
print(f"   初始:${BAL:.2f} | 保证金{MARGIN*100:.0f}%")
print("="*80)

for h,label in[(3,'3小时'),(6,'6小时'),(12,'12小时'),(24,'24小时'),(168,'7天'),(720,'30天')]:
    bars_n=h*4;sub=bars[max(0,n-bars_n):];trades=bt(sub)
    if not trades:print(f"\n{label}: 无交易");continue
    wins=[t for t in trades if t['pnl']>0];wr=len(wins)/len(trades)*100
    ret=(1+sum(t['pnl']for t in trades)/len(trades)*len(trades))  # simplified
    # better: compound
    eq=1.0
    for t in trades:eq*=(1+t['pnl'])
    ret=(eq-1)*100;peak=1.0;dd=0
    for v in [1.0]:
        for t in trades:v*=(1+t['pnl'])
        if v>peak:peak=v
        if(peak-v)/peak>dd:dd=(peak-v)/peak
    # 杠杆收益: starting bal * (1+ret*LEV*MARGIN)
    lev_ret=ret*LEV*MARGIN
    final=BAL*(1+lev_ret/100)
    print(f"\n【{label}】{len(trades)}笔 | 胜率{wr:.0f}% | 策略收益{ret:+.2f}% | 杠杆后{lev_ret:+.1f}%")
    print(f"   余额: ${BAL:.2f} → ${final:.2f} ({final-BAL:+.2f})")
    if len(trades)<=8:
        for t in trades:
            dt=datetime.fromtimestamp(t.get('ts',0)/1000).strftime('%m/%d %H:%M')if'ts'in t else''
            c='+'if t['pnl']>0 else''
            print(f"   {dt} {t.get('reason',''):4s} {t['pnl']*100:+6.2f}%")
print(f"\n✅ 完成")
