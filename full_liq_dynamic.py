#!/usr/bin/env python3
"""全量爆仓验证: window300+ATR0.4 + 动态杠杆"""
import sys,math,time
from datetime import datetime,timezone
sys.path.insert(0,'.')
import datastore as db

TP=0.008;SL=0.004;MAX_BARS=24;FEE=0.0007;SLIP=0.0002
BB_P=20;BB_S=2;RSI_P=7;RSI_H=65;RSI_L=35;ATR_F=0.4;WINDOW=300

def get_dyn(bal):
    if bal>750:return 5,0.3
    if bal>200:return 10,0.4
    if bal>50:return 15,0.5
    return 15,0.5

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

def bt_dynamic(bars,bal0):
    trades=[];pos=None;ep=0;eb=0;n=len(bars);step=max(50,WINDOW//4)
    bal=bal0;peak=bal;min_bal=bal;min_bar=0;max_dd=0;dd_bar=0
    consec_sl=0;max_cs=0;cs_bar=0;liquidated=False;liq_bar=0

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
                lev,mg=get_dyn(bal)
                if pnl>=TP:
                    ac=ep*(1+TP)*(1-SLIP)if pos=='long' else ep*(1-TP)*(1+SLIP)
                    ap=(ac-ep)/ep if pos=='long' else (ep-ac)/ep;net=ap-FEE
                    trades.append({'pnl':net,'ts':win[i]['ts'],'reason':'TP'});pos=None
                    bal*=(1+net*mg*lev);consec_sl=0
                    if bal<=0:liquidated=True;liq_bar=ri;break
                    if bal>peak:peak=bal
                    continue
                if pnl<=-SL:
                    ac=ep*(1-SL)*(1-SLIP)if pos=='long' else ep*(1+SL)*(1+SLIP)
                    ap=(ac-ep)/ep if pos=='long' else (ep-ac)/ep;net=ap-FEE
                    trades.append({'pnl':net,'ts':win[i]['ts'],'reason':'SL'});pos=None
                    bal*=(1+net*mg*lev);consec_sl+=1
                    if consec_sl>max_cs:max_cs=consec_sl;cs_bar=ri
                    if bal<=0:liquidated=True;liq_bar=ri;break
                    if bal>peak:peak=bal
                    dd=(peak-bal)/peak if peak>0 else 0
                    if dd>max_dd:max_dd=dd;dd_bar=ri
                    if bal<min_bal:min_bal=bal;min_bar=ri
                    continue
                if h>=MAX_BARS:
                    ac=c*(1-SLIP)if pos=='long' else c*(1+SLIP)
                    ap=(ac-ep)/ep if pos=='long'else(ep-ac)/ep;net=ap-FEE
                    trades.append({'pnl':net,'ts':win[i]['ts'],'reason':'TO'});pos=None
                    bal*=(1+net*mg*lev);consec_sl=0
                    if bal<=0:liquidated=True;liq_bar=ri;break
                    if bal>peak:peak=bal
                    continue
                continue
            if liquidated:break
            if pos:continue
            sig=None;sb=None
            for j in range(i-1,max(i-4,mi-1),-1):
                if bu[j] is None or rsi[j] is None or atr[j] is None:continue
                if nw>=2 and bu[nw-1] and bl[nw-1]:
                    bb_w=(bu[nw-1]-bl[nw-1])/win[nw-1]['c']*100
                    dyn_f=ATR_F*1.8 if bb_w<8 else(ATR_F*1.2 if bb_w<12 else ATR_F*0.8)
                else:dyn_f=ATR_F
                if atr[j]<am*dyn_f:continue
                cj=win[j]['c']
                if cj>bu[j] and rsi[j]>RSI_H:sig='short';sb=j;break
                elif cj<bl[j] and rsi[j]<RSI_L:sig='long';sb=j;break
            if sig:ep=win[sb]['c']*(1+SLIP)if sig=='long' else win[sb]['c']*(1-SLIP);pos=sig;eb=ri
        if liquidated:break
    if pos and not liquidated:
        c=bars[-1]['c'];lev,mg=get_dyn(bal)
        pnl=(c-ep)/ep if pos=='long'else(ep-c)/ep
        ap=(c-ep)/ep if pos=='long'else(ep-c)/ep;net=ap-FEE
        bal*=(1+net*mg*lev)
    return trades,bal,liquidated,liq_bar,min_bal,min_bar,max_dd,dd_bar,max_cs,cs_bar

all_bars=db.get_range(0);n=len(all_bars)
total_days=(all_bars[-1]['ts']-all_bars[0]['ts'])/86400000
t0=time.time()

trades,bal,liq,liq_bar,min_b,min_bar,max_dd,dd_bar,max_cs,cs_bar = bt_dynamic(all_bars,37.48)

print('动态杠杆爆仓验证 | window300 ATR0.4')
print(str(n)+'根 '+str(int(total_days))+'天')
print()

if liq:
    dt=datetime.fromtimestamp(all_bars[liq_bar]['ts']/1000)
    print('爆仓! '+dt.strftime('%Y-%m-%d %H:%M'))
else:
    wins=[t for t in trades if t['pnl']>0]
    wr=len(wins)/len(trades)*100
    ann=(bal/37.48-1)/total_days*365*100
    min_dt=datetime.fromtimestamp(all_bars[min_bar]['ts']/1000).strftime('%Y-%m-%d')
    dd_dt=datetime.fromtimestamp(all_bars[dd_bar]['ts']/1000).strftime('%Y-%m-%d')
    cs_dt=datetime.fromtimestamp(all_bars[cs_bar]['ts']/1000).strftime('%Y-%m-%d')

    print('交易:'+str(len(trades))+'笔 WR'+str(int(wr))+'%')
    print('最低余额: $'+str(round(min_b,2))+' ('+min_dt+')')
    print('最大回撤: '+str(round(max_dd*100,1))+'% ('+dd_dt+')')
    print('最大连亏:'+str(max_cs)+'笔 ('+cs_dt+')')
    print('最终余额: $'+str(round(bal,2)))
    print('年化:'+str(int(ann))+'%')
    print('爆仓: 从未')

    # 年度
    yb=37.48
    for y in range(2019,2027):
        for t in trades:
            if datetime.fromtimestamp(t['ts']/1000).year==y:
                lev,mg=get_dyn(yb)
                yb*=(1+t['pnl']*mg*lev)
        if y>2019:print('  '+str(y)+'末: $'+str(round(yb,2)))

print()
print('耗时'+str(int(time.time()-t0))+'s')
