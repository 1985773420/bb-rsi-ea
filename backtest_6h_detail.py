#!/usr/bin/env python3
"""最近6小时逐笔回测"""
import sys,math,time
from datetime import datetime,timezone
sys.path.insert(0,'.');import datastore as db

TP=0.008;SL=0.004;MAX_BARS=24;FEE=0.0007;SLIP=0.0002
BB_P=20;BB_S=2;RSI_P=7;RSI_H=65;RSI_L=35;ATR_F=0.5
FUNDING_RATE=0.0001;LEV=15;MARGIN=0.5

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

def bt(bars):
    bu,bl,rsi,atr,am=ic(bars);trades=[];pos=None;ep=0;eb=0;epx=0;mi=max(BB_P,RSI_P,14)+1;n=len(bars)
    for i in range(mi,n):
        c=bars[i]['c'];h=i-eb if pos else 0
        if pos:
            pnl=(c-ep)/ep if pos=='long'else(ep-c)/ep
            if pnl>=TP:
                ac=ep*(1+TP)*(1-SLIP)if pos=='long' else ep*(1-TP)*(1+SLIP)
                ap=(ac-ep)/ep if pos=='long' else (ep-ac)/ep
                gross=(c-epx)/epx if pos=='long' else (epx-c)/epx
                trades.append({'eb':eb,'ex':i,'side':pos,'epx':epx,'ex_px':c,'gross':gross,'net':ap-FEE-(h/32*FUNDING_RATE),'reason':'TP','bars':h});pos=None;continue
            if pnl<=-SL:
                ac=ep*(1-SL)*(1-SLIP)if pos=='long' else ep*(1+SL)*(1+SLIP)
                ap=(ac-ep)/ep if pos=='long' else (ep-ac)/ep
                gross=(c-epx)/epx if pos=='long' else (epx-c)/epx
                trades.append({'eb':eb,'ex':i,'side':pos,'epx':epx,'ex_px':c,'gross':gross,'net':ap-FEE-(h/32*FUNDING_RATE),'reason':'SL','bars':h});pos=None;continue
            if h>=MAX_BARS:
                ac=c*(1-SLIP)if pos=='long' else c*(1+SLIP)
                ap=(ac-ep)/ep if pos=='long'else(ep-ac)/ep
                gross=(c-epx)/epx if pos=='long' else (epx-c)/epx
                trades.append({'eb':eb,'ex':i,'side':pos,'epx':epx,'ex_px':c,'gross':gross,'net':ap-FEE-(h/32*FUNDING_RATE),'reason':'TO','bars':h});pos=None;continue
            continue
        sig=None;sb=None
        for j in range(i-1,max(i-4,mi-1),-1):
            if bu[j] is None or rsi[j] is None or atr[j] is None:continue
            if n>=2 and bu[n-1] and bl[n-1]:
                bb_w=(bu[n-1]-bl[n-1])/bars[n-1]['c']*100
                dyn_f=ATR_F*1.8 if bb_w<8 else(ATR_F*1.2 if bb_w<12 else ATR_F*0.8)
            else:dyn_f=ATR_F
            if atr[j]<am*dyn_f:continue
            cj=bars[j]['c']
            if cj>bu[j] and rsi[j]>RSI_H:sig='short';sb=j;break
            elif cj<bl[j] and rsi[j]<RSI_L:sig='long';sb=j;break
        if sig:
            epx=bars[sb]['c'];ep=epx*(1+SLIP)if sig=='long' else epx*(1-SLIP)
            pos=sig;eb=i
    if pos:
        c=bars[-1]['c'];h=len(bars)-1-eb
        gross=(c-epx)/epx if pos=='long' else (epx-c)/epx
        ap=(c-ep)/ep if pos=='long'else(ep-c)/ep
        trades.append({'eb':eb,'ex':len(bars)-1,'side':pos,'epx':epx,'ex_px':c,'gross':gross,'net':ap-FEE-(h/32*FUNDING_RATE),'reason':'OPEN','bars':h})
    return trades

all_bars=db.get_range(0);n=len(all_bars)
sub=all_bars[max(0,n-600):]
trades=bt(sub)

now_ts=time.time()*1000;cutoff=now_ts-6*3600*1000
recent=[t for t in trades if all_bars[t['eb']]['ts']>=cutoff]

bal=35.91
if not recent:print('无交易');exit()

print(f'6小时回测 | TP0.8% SL0.4% 15x/50% | 滑点万2 费万7 资金费0.01%/8h')
print(f'初始: ${bal:.2f}')
print()
hdr=f"{'#':<3} {'开仓':<12} {'平仓':<12} {'方向':<4} {'入场':>8} {'出场':>8} {'毛盈亏':>7} {'滑点':>6} {'费':>6} {'资金费':>6} {'净盈亏':>7}"
print(hdr)
print('-'*90)

tg=0;ts=0;tf=0;tfund=0;tn=0
for k,t in enumerate(recent):
    ed=datetime.fromtimestamp(all_bars[t['eb']]['ts']/1000).strftime('%m/%d %H:%M')
    xd=datetime.fromtimestamp(all_bars[t['ex']]['ts']/1000).strftime('%m/%d %H:%M')
    pv=t['epx']*0.01*LEV*MARGIN
    gu=pv*t['gross'];su=pv*SLIP*2;fu=pv*FEE;fdu=pv*t['bars']/32*FUNDING_RATE
    nu=gu-su-fu-fdu
    tg+=gu;ts+=su;tf+=fu;tfund+=fdu;tn+=nu
    c='+'if t['net']>0 else''
    print(f'{k+1:<3} {ed:<12} {xd:<12} {t["side"]:<4} {t["epx"]:>8.1f} {t["ex_px"]:>8.1f} {t["gross"]*100:>+6.2f}% {su:>5.2f} {fu:>5.2f} {fdu:>5.2f} {c}{t["net"]*100:+6.2f}% [{t["reason"]}]')
print('-'*90)
print(f'{"汇总":>42} {tg:>+6.2f} {ts:>5.2f} {tf:>5.2f} {tfund:>5.2f} {tn:+6.2f}')
print(f'\n余额: ${bal:.2f} -> ${bal+tn:.2f} ({tn:+.2f})')
