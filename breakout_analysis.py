#!/usr/bin/env python3
"""分析大爆发月的前置条件"""
import sys,math
from datetime import datetime,timezone
from collections import defaultdict
sys.path.insert(0,'.');import datastore as db

TP=0.008;SL=0.004;MAX_BARS=24
FEE=0.0007;SLIP=0.0002;ATR_F=0.5
LEV=15;MARGIN=0.5

def ic(bars):
    n=len(bars);cl=[b['c']for b in bars];hi=[b['h']for b in bars];lo=[b['l']for b in bars]
    bu=[None]*n;bl=[None]*n;bb_w=[None]*n
    for i in range(19,n):
        w=cl[i-19:i+1];sma=sum(w)/20;std=math.sqrt(sum((x-sma)**2 for x in w)/20)
        bu[i]=sma+2*std;bl[i]=sma-2*std;bb_w[i]=(bu[i]-bl[i])/sma*100
    rsi=[None]*n
    for i in range(7,n):
        g=sum(max(cl[j]-cl[j-1],0)for j in range(i-6,i+1))/7
        l=sum(max(cl[j-1]-cl[j],0)for j in range(i-6,i+1))/7
        rsi[i]=100-100/(1+g/l)if l>0 else 100
    atr=[None]*n;tl=[]
    for i in range(n):
        if i==0:tr=hi[i]-lo[i]
        else:tr=max(hi[i]-lo[i],abs(hi[i]-cl[i-1]),abs(lo[i]-cl[i-1]))
        tl.append(tr)
        if i>=14:atr[i]=(sum(tl[-14:])/14)/cl[i]*100
    v=[x for x in atr if x];am=sum(v)/len(v)if v else 0.35
    return bb_w,rsi,atr,am

bars=db.get_range(0)
bb_w,rsi,atr,am=ic(bars)

# 每月统计
monthly={}
for i,b in enumerate(bars):
    m=datetime.fromtimestamp(b['ts']/1000,tz=timezone.utc).strftime('%Y-%m')
    if m not in monthly:monthly[m]={'bb_w':[],'atr':[],'rsi':[],'price':[]}
    if bb_w[i]:monthly[m]['bb_w'].append(bb_w[i])
    if atr[i]:monthly[m]['atr'].append(atr[i])
    if rsi[i]:monthly[m]['rsi'].append(rsi[i])
    monthly[m]['price'].append(b['c'])

# 大爆发月: 月收益>20%的月份
big_months = ['2020-05','2021-01','2021-06','2022-03','2022-05','2023-01',
              '2024-05','2024-09','2026-01','2026-03']

print("="*75)
print("📊 大爆发月(>20%收益)的前置条件分析")
print("="*75)

# 大爆发月之前1-2个月的特征
pre_big={'bb_w':[],'atr':[],'rsi':[]}
for bm in big_months:
    # 找前1-2个月
    all_months=sorted(monthly.keys())
    idx=all_months.index(bm) if bm in all_months else -1
    if idx>0:
        for offset in[1,2]:
            if idx-offset>=0:
                pm=all_months[idx-offset]
                pre_big['bb_w'].extend(monthly[pm]['bb_w'])
                pre_big['atr'].extend(monthly[pm]['atr'])
                pre_big['rsi'].extend(monthly[pm]['rsi'])

# 全部月份的平均(作为基线)
all_bbw=[sum(v)/len(v) for v in [monthly[m]['bb_w'] for m in monthly if monthly[m]['bb_w']]]
avg_bbw_all=sum(all_bbw)/len(all_bbw)

print(f"\n大爆发月之前1-2个月的平均特征:")
pbw=sum(pre_big['bb_w'])/len(pre_big['bb_w']) if pre_big['bb_w'] else 0
pat=sum(pre_big['atr'])/len(pre_big['atr']) if pre_big['atr'] else 0
prs=sum(pre_big['rsi'])/len(pre_big['rsi']) if pre_big['rsi'] else 0
print(f"  BB宽度: {pbw:.1f}% (全历史均值 {avg_bbw_all:.1f}%)")
print(f"  ATR: {pat:.3f}%")
print(f"  RSI: {prs:.0f}")

# 当前月份特征
cur_m='2026-05'
cur_bbw=sum(monthly[cur_m]['bb_w'])/len(monthly[cur_m]['bb_w']) if monthly[cur_m]['bb_w'] else 0
cur_atr=sum(monthly[cur_m]['atr'])/len(monthly[cur_m]['atr']) if monthly[cur_m]['atr'] else 0
cur_rsi=sum(monthly[cur_m]['rsi'])/len(monthly[cur_m]['rsi']) if monthly[cur_m]['rsi'] else 0
cur_price=monthly[cur_m]['price'][-1] if monthly[cur_m]['price'] else 0

print(f"\n当前({cur_m})市场特征:")
print(f"  BB宽度: {cur_bbw:.1f}%")
print(f"  ATR: {cur_atr:.3f}%")
print(f"  RSI: {cur_rsi:.0f}")
print(f"  BTC价格: ${cur_price:.0f}")

# 历史规律
print(f"\n📅 历史大爆发月份:")
for bm in big_months:
    idx=sorted(monthly.keys()).index(bm) if bm in monthly else -1
    prev=''
    if idx>=1:prev=f"(前月BB宽:{sum(monthly[sorted(monthly.keys())[idx-1]]['bb_w'])/len(monthly[sorted(monthly.keys())[idx-1]]['bb_w']):.1f}%)"
    print(f"  {bm} {prev}")

# 季节性
print(f"\n📊 月度胜率(按月份,全部年份汇总):")
month_season={}
for m_str in sorted(monthly.keys()):
    mm=m_str[-2:]
    if mm not in month_season:month_season[mm]=[]
    bw=sum(monthly[m_str]['bb_w'])/len(monthly[m_str]['bb_w']) if monthly[m_str]['bb_w'] else 0
    month_season[mm].append(bw)

for mm in sorted(month_season.keys()):
    avg_bw=sum(month_season[mm])/len(month_season[mm])
    freq=sum(1 for bw in month_season[mm] if bw>12)/len(month_season[mm])*100
    bar='█'*int(freq/5)
    print(f"  {mm}月: 平均BB宽{avg_bw:.1f}% | 大波动概率{freq:.0f}% {bar}")

print(f"\n💡 大爆发通常发生在:")
print(f"  ① 前1-2个月BB宽度收窄(蓄力)")
print(f"  ② ATR从低位开始扩张(波动回归)")
print(f"  ③ 价格突破长期震荡区间")
print(f"  当前BB宽{cur_bbw:.1f}%{' → 已在窄幅蓄力阶段' if cur_bbw<10 else ''}")
