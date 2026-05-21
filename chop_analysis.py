#!/usr/bin/env python3
"""扫盘检测：分析震荡市中策略是否被来回止损"""
import sys,math,time
from datetime import datetime,timezone
sys.path.insert(0,'.');import datastore as db

TP=0.008;SL=0.004;MAX_BARS=24;FEE=0.0007
BB_P=20;BB_S=2;RSI_P=7;RSI_H=65;RSI_L=35;ATR_F=0.5
SLIP=0.0002;LEV=15;MARGIN=0.5

def ic(bars):
    n=len(bars);cl=[b['c']for b in bars];hi=[b['h']for b in bars];lo=[b['l']for b in bars]
    bu=[None]*n;bl=[None]*n;bb_w=[None]*n
    for i in range(BB_P-1,n):
        w=cl[i-BB_P+1:i+1];sma=sum(w)/BB_P;std=math.sqrt(sum((x-sma)**2 for x in w)/BB_P)
        bu[i]=sma+BB_S*std;bl[i]=sma-BB_S*std
        bb_w[i]=(bu[i]-bl[i])/sma*100  # 布林带宽度%
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
    return bu,bl,r,atr,am,bb_w

bars=db.get_range(0)
bu,bl,rsi,atr,am,bb_w=ic(bars)
n=len(bars);mi=max(BB_P,RSI_P,14)+1

# 每月统计：连损笔数、最大连续止损
monthly={}
consec_sl=0;max_consec_sl=0;max_consec_sl_month=''
for i in range(mi,n):
    c=bars[i]['c']
    m=datetime.fromtimestamp(bars[i]['ts']/1000).strftime('%Y-%m')
    if m not in monthly:monthly[m]={'trades':0,'wins':0,'consec_sl':0,'bb_w':0,'atr':0,'pnl_sum':0}
    # 简单信号检测
    sig=None
    for j in range(i-1,max(i-4,mi-1),-1):
        if bu[j] is None or rsi[j] is None or atr[j] is None:continue
        if atr[j]<am*ATR_F:continue
        cj=bars[j]['c']
        if cj>bu[j] and rsi[j]>RSI_H:sig='short';break
        elif cj<bl[j] and rsi[j]<RSI_L:sig='long';break
    if sig:
        monthly[m]['trades']+=1
        # 简化：假设每次信号要么TP要么SL（50/50随机不行）
        # 用实际来模拟
        entry=bars[i]['c']
        # 往前看MAX_BARS根，看先触发TP还是SL
        hit=None;hit_bar=0
        for k in range(i,min(n,i+MAX_BARS)):
            if k>=n:break
            ck=bars[k]['c']
            if sig=='long':
                if ck>=entry*(1+TP):hit='TP';hit_bar=k;break
                if ck<=entry*(1-SL):hit='SL';hit_bar=k;break
            else:
                if ck<=entry*(1-TP):hit='TP';hit_bar=k;break
                if ck>=entry*(1+SL):hit='SL';hit_bar=k;break
        if hit=='TP':
            monthly[m]['wins']+=1;monthly[m]['pnl_sum']+=TP-FEE
            if consec_sl>max_consec_sl:max_consec_sl=consec_sl;max_consec_sl_month=m
            consec_sl=0
        elif hit=='SL':
            monthly[m]['pnl_sum']+=-(SL+FEE)
            consec_sl+=1
    monthly[m]['atr']+=atr[i] if atr[i] else 0
    monthly[m]['bb_w']+=bb_w[i] if bb_w[i] else 0

# 计算每月的盈亏和ATR/BB宽度关系
print(f"{'月份':<8} {'交易':>5} {'胜率':>6} {'月盈亏%':>9} {'ATR%':>7} {'BB宽%':>7} {'连亏':>4}")
print("-"*55)
worst_months=[]
for m in sorted(monthly.keys()):
    d=monthly[m]
    if d['trades']<5:continue
    wr=d['wins']/d['trades']*100 if d['trades'] else 0
    pnl_pct=d['pnl_sum']/d['trades']*100
    avg_atr=d['atr']/d['trades'] if d['trades'] else 0
    avg_bbw=d['bb_w']/d['trades'] if d['trades'] else 0
    flag='🔥'if d['pnl_sum']<-0.05 else('⚠️'if d['pnl_sum']<0 else '')
    if d['pnl_sum']<0:worst_months.append((d['pnl_sum'],m,d['trades'],wr,avg_atr,avg_bbw))
    print(f"{m:<8} {d['trades']:>5} {wr:>5.0f}% {d['pnl_sum']*100:>+8.2f}% {avg_atr:>6.3f}% {avg_bbw:>6.2f}% {d['consec_sl']:>4} {flag}")

# 最差10个月
worst_months.sort()
print(f"\n🔴 最差10个月 (震荡杀):")
print(f"{'月':<8}{'盈亏':>10}{'交易':>6}{'胜率':>6}{'ATR':>7}{'BB宽':>7}")
for pnl,m,nt,wr,at,bb in worst_months[:10]:
    print(f"{m:<8}{pnl*100:>+9.2f}%{nt:>6}{wr:>5.0f}%{at:>6.3f}%{bb:>6.2f}%")
print(f"\n最大连续止损: {max_consec_sl}笔 @ {max_consec_sl_month}")
