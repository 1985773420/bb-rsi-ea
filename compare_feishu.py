#!/usr/bin/env python3
"""对比 Feishu参数 vs 当前参数 (实盘级滑动窗口)"""
import sys,math,time
from datetime import datetime,timezone
sys.path.insert(0,'.')
import datastore as db

TP=0.008;SL=0.004;MAX_BARS=24;FEE=0;SLIP=0
BB_P=20;BB_S=2;RSI_P=7;WINDOW=300;LEV=15;MARGIN=0.5

def calc_window(bars):
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
    v=[x for x in atr if x is not None];am=sum(v)/len(v)if v else 0.35
    return bu,bl,r,atr,am

def bt_sliding(bars,rh,rl,atr_base):
    trades=[];pos=None;ep=0;eb=0;n=len(bars);step=max(50,WINDOW//4)
    for start in range(0,n-WINDOW,step):
        end=min(start+WINDOW,n)
        win=bars[max(0,end-WINDOW):end+1]
        if len(win)<50:continue
        bu,bl,rsi,atr,am=calc_window(win)
        nw=len(win);mi=max(BB_P,RSI_P,14)+1
        for i in range(mi,nw):
            ri=end-len(win)+i
            if ri<=eb:continue
            c=win[i]['c'];h=ri-eb if pos else 0
            if pos:
                pnl=(c-ep)/ep if pos=='long'else(ep-c)/ep
                if pnl>=TP:trades.append({'eb':eb,'ex':ri,'side':pos,'pnl':TP,'reason':'TP','ts':win[i]['ts']});pos=None;continue
                if pnl<=-SL:trades.append({'eb':eb,'ex':ri,'side':pos,'pnl':-SL,'reason':'SL','ts':win[i]['ts']});pos=None;continue
                if h>=MAX_BARS:trades.append({'eb':eb,'ex':ri,'side':pos,'pnl':pnl,'reason':'TO','ts':win[i]['ts']});pos=None;continue
                continue
            if pos:continue
            sig=None;sb=None
            for j in range(i-1,max(i-4,mi-1),-1):
                if bu[j] is None or rsi[j] is None or atr[j] is None:continue
                if nw>=2 and bu[nw-1] and bl[nw-1]:
                    bb_w=(bu[nw-1]-bl[nw-1])/win[nw-1]['c']*100
                    dyn_f=atr_base*1.8 if bb_w<8 else(atr_base*1.2 if bb_w<12 else atr_base*0.8)
                else:dyn_f=atr_base
                if atr[j]<am*dyn_f:continue
                cj=win[j]['c']
                if cj>bu[j] and rsi[j]>rh:sig='short';sb=j;break
                elif cj<bl[j] and rsi[j]<rl:sig='long';sb=j;break
            if sig:ep=win[sb]['c'];pos=sig;eb=ri
    seen=set();unique=[]
    for t in trades:
        k=(t['eb'],t['ex'],t['side'],t['reason'])
        if k not in seen:seen.add(k);unique.append(t)
    final=[];last=-1
    for t in sorted(unique,key=lambda x:x['eb']):
        if t['eb']>=last:final.append(t);last=t['ex']
    return final

all_bars=db.get_range(0);n=len(all_bars)
total_days=(all_bars[-1]['ts']-all_bars[0]['ts'])/86400000
t0=time.time()

params=[("当前 65/35 A0.4",65,35,0.4),("Feishu 68/32 A0.48",68,32,0.48)]
print('实盘级滑动窗口回测 | window300')
print()

for days,label in[(30,'30天'),(90,'90天'),(180,'180天'),(int(total_days),'全量')]:
    sub=all_bars[max(0,n-days*96):]
    print('='*60)
    print(label+' ('+str(len(sub))+'根)')
    print('-'*40)
    for pname,rh,rl,atr_base in params:
        trades=bt_sliding(sub,rh,rl,atr_base)
        if not trades:print(pname+': 无交易');continue
        wins=[t for t in trades if t['pnl']>0]
        wr=len(wins)/len(trades)*100
        tp=sum(1 for t in trades if t['reason']=='TP')
        sl=sum(1 for t in trades if t['reason']=='SL')
        to=sum(1 for t in trades if t['reason']=='TO')
        ret=sum(t['pnl']for t in trades)*100
        lev_ret=ret*LEV*MARGIN
        bal=35.91
        for t in trades:bal*=(1+t['pnl']*MARGIN*LEV)
        best='★'if pname==max([(pname,ret) for pname,_,_,_ in params],key=lambda x:x[1])[0] else' '
        print(best+pname+': '+str(len(trades))+'笔 WR'+str(int(wr))+'% TP'+str(tp)+'/SL'+str(sl)+'/TO'+str(to)+' 收益'+('+'if ret>0 else'')+str(round(ret,1))+'% 杠杆'+('+'if lev_ret>0 else'')+str(round(lev_ret,0))+'% Bal $'+str(round(bal,2)))
    print()

print('耗时'+str(int(time.time()-t0))+'s')
