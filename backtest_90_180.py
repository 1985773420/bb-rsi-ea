#!/usr/bin/env python3
"""90d/180d backtest + 24h signal check"""
import sys,math,subprocess
from datetime import datetime,timezone
sys.path.insert(0,'.')
import datastore as db

TP=0.008;SL=0.004;MAX_BARS=24;FEE=0;SLIP=0
BB_P=20;BB_S=2;RSI_P=7;RSI_H=65;RSI_L=35;ATR_F=0.6;LEV=15;MARGIN=0.5

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
    bu,bl,rsi,atr,am=ic(bars)
    trades=[];pos=None;ep=0;eb=0;mi=max(BB_P,RSI_P,14)+1;n=len(bars)
    for i in range(mi,n):
        c=bars[i]['c'];h=i-eb if pos else 0
        if pos:
            pnl=(c-ep)/ep if pos=='long'else(ep-c)/ep
            if pnl>=TP:trades.append({'eb':eb,'ex':i,'side':pos,'pnl':TP,'reason':'TP','ts':bars[i]['ts']});pos=None;continue
            if pnl<=-SL:trades.append({'eb':eb,'ex':i,'side':pos,'pnl':-SL,'reason':'SL','ts':bars[i]['ts']});pos=None;continue
            if h>=MAX_BARS:trades.append({'eb':eb,'ex':i,'side':pos,'pnl':pnl,'reason':'TO','ts':bars[i]['ts']});pos=None;continue
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
        if sig:ep=bars[sb]['c'];pos=sig;eb=i
    if pos:c=bars[-1]['c'];pnl=(c-ep)/ep if pos=='long'else(ep-c)/ep
    trades.append({'eb':eb,'ex':len(bars)-1,'side':pos,'pnl':pnl,'reason':'OPEN','ts':bars[-1]['ts']})
    return trades

all_bars=db.get_range(0);n=len(all_bars)

for label,days in [('90天',90),('180天',180)]:
    sub=all_bars[max(0,n-days*96):]
    trades=bt(sub)
    wins=[t for t in trades if t['pnl']>0]
    wr=len(wins)/len(trades)*100 if trades else 0
    total_pnl=sum(t['pnl']for t in trades)*100

    monthly={}
    for t in trades:
        m=datetime.fromtimestamp(t['ts']/1000).strftime('%Y-%m')
        if m not in monthly:monthly[m]={'trades':[],'pnl':0,'wins':0}
        monthly[m]['trades'].append(t)
        monthly[m]['pnl']+=t['pnl']
        if t['pnl']>0:monthly[m]['wins']+=1

    print()
    print('='*60)
    print(label + ' | ATR0.6 | 无费无滑点')
    print(str(len(trades)) + '笔 WR' + str(int(wr)) + '% 纯策略' + ('+' if total_pnl>0 else '') + str(round(total_pnl,1)) + '%')

    bal=35.91
    for m in sorted(monthly.keys()):
        mt=monthly[m]['trades'];mp=monthly[m]['pnl'];mw=monthly[m]['wins']
        for t in mt:bal*=(1+t['pnl']*MARGIN*LEV)
        tp_n=sum(1 for t in mt if t['reason']=='TP')
        sl_n=sum(1 for t in mt if t['reason']=='SL')
        to_n=sum(1 for t in mt if t['reason']=='TO')
        print()
        print(m + ' ' + str(len(mt)) + 't WR' + str(int(mw/len(mt)*100)) + '% PnL' + ('+' if mp>0 else '') + str(round(mp*100,1)) + '% Bal $' + str(round(bal,2)) + ' TP' + str(tp_n) + '/SL' + str(sl_n) + '/TO' + str(to_n))
        for t in mt[:3]:
            et=datetime.fromtimestamp(all_bars[t['eb']]['ts']/1000).strftime('%m/%d %H:%M')
            xt=datetime.fromtimestamp(t['ts']/1000).strftime('%m/%d %H:%M')
            c='+'if t['pnl']>0 else''
            print('  ' + et + ' ' + t['side'] + ' ' + c + str(round(t['pnl']*100,2)) + '% [' + t['reason'] + ']')

    print()
    print(label + ' Bal: $35.91 -> $' + str(round(bal,2)) + ' (' + str(int((bal/35.91-1)*100)) + '%)')

print()
print('='*60)
print('近24h EA实际交易:')
r=subprocess.run(['journalctl','-u','bb-rsi-ea','--no-pager','--since','24 hours ago'],capture_output=True,text=True)
for line in r.stdout.split('\n'):
    if '开仓' in line:
        print(line[line.find(']:')+2:])
