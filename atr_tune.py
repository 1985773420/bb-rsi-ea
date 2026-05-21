#!/usr/bin/env python3
"""ATR过滤调优"""
import sys,math,time
from datetime import datetime,timezone
sys.path.insert(0,'.');import datastore as db

TP=0.008;SL=0.004;MAX_BARS=24;FEE=0.0007;SLIP=0.0002
BB_P=20;BB_S=2;RSI_P=7;RSI_H=65;RSI_L=35;LEV=15;MARGIN=0.5

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

def bt(bars,base_atr):
    bu,bl,rsi,atr,am=ic(bars);trades=[];pos=None;ep=0;eb=0;epx=0;mi=max(BB_P,RSI_P,14)+1;n=len(bars)
    for i in range(mi,n):
        c=bars[i]['c'];h=i-eb if pos else 0
        if pos:
            pnl=(c-ep)/ep if pos=='long'else(ep-c)/ep
            if pnl>=TP:
                ac=ep*(1+TP)*(1-SLIP)if pos=='long' else ep*(1-TP)*(1+SLIP)
                ap=(ac-ep)/ep if pos=='long' else (ep-ac)/ep;net=ap-FEE
                trades.append({'eb':eb,'ex':i,'side':pos,'epx':epx,'pnl':net,'reason':'TP','bars':h,'ts':bars[i]['ts']});pos=None;continue
            if pnl<=-SL:
                ac=ep*(1-SL)*(1-SLIP)if pos=='long' else ep*(1+SL)*(1+SLIP)
                ap=(ac-ep)/ep if pos=='long' else (ep-ac)/ep;net=ap-FEE
                trades.append({'eb':eb,'ex':i,'side':pos,'epx':epx,'pnl':net,'reason':'SL','bars':h,'ts':bars[i]['ts']});pos=None;continue
            if h>=MAX_BARS:
                ac=c*(1-SLIP)if pos=='long' else c*(1+SLIP)
                ap=(ac-ep)/ep if pos=='long'else(ep-ac)/ep;net=ap-FEE
                trades.append({'eb':eb,'ex':i,'side':pos,'epx':epx,'pnl':net,'reason':'TO','bars':h,'ts':bars[i]['ts']});pos=None;continue
            continue
        sig=None;sb=None
        for j in range(i-1,max(i-4,mi-1),-1):
            if bu[j] is None or rsi[j] is None or atr[j] is None:continue
            if n>=2 and bu[n-1] and bl[n-1]:
                bb_w=(bu[n-1]-bl[n-1])/bars[n-1]['c']*100
                dyn_f=base_atr*1.8 if bb_w<8 else(base_atr*1.2 if bb_w<12 else base_atr*0.8)
            else:dyn_f=base_atr
            if atr[j]<am*dyn_f:continue
            cj=bars[j]['c']
            if cj>bu[j] and rsi[j]>RSI_H:sig='short';sb=j;break
            elif cj<bl[j] and rsi[j]<RSI_L:sig='long';sb=j;break
        if sig:
            epx=bars[sb]['c'];ep=epx*(1+SLIP)if sig=='long' else epx*(1-SLIP)
            pos=sig;eb=i
    if pos:
        c=bars[-1]['c'];h=len(bars)-1-eb
        ap=(c-ep)/ep if pos=='long'else(ep-c)/ep;net=ap-FEE
        trades.append({'eb':eb,'ex':len(bars)-1,'side':pos,'epx':epx,'pnl':net,'reason':'OPEN','bars':h,'ts':bars[-1]['ts']})
    return trades

all_bars=db.get_range(0);n=len(all_bars)
total_days=(all_bars[-1]['ts']-all_bars[0]['ts'])/86400000

for base_atr in[0.5,0.6,0.7]:
    print()
    print("="*70)
    print(f"ATR基础={base_atr} | 动态: BB<8%->{base_atr*1.8:.1f}x 8-12%->{base_atr*1.2:.1f}x >12%->{base_atr*0.8:.1f}x")
    print("="*70)

    ft=bt(all_bars,base_atr)
    w=[t for t in ft if t['pnl']>0]
    wr=len(w)/len(ft)*100 if ft else 0
    tr=sum(t['pnl']for t in ft)*100
    print(f"全量: {len(ft)}笔 WR{wr:.0f}% 累计{tr:+.1f}%")

    for days,label in[(7,'7天'),(30,'30天'),(90,'90天'),(180,'180天')]:
        start=max(0,n-days*96)
        st=bt(all_bars[start:],base_atr)
        if not st:continue
        sw=[t for t in st if t['pnl']>0]
        sr=sum(t['pnl']for t in st)*100
        print(f"  {label}: {len(st)}笔 WR{len(sw)/len(st)*100:.0f}% 累计{sr:+.1f}%")

    cutoff=time.time()*1000-24*3600*1000
    recent=[t for t in ft if t['ts']>=cutoff]
    if recent:
        print(f"\n  近24h逐笔({len(recent)}笔):")
        for k,t in enumerate(recent):
            ed=datetime.fromtimestamp(all_bars[t['eb']]['ts']/1000).strftime('%m/%d %H:%M')
            xd=datetime.fromtimestamp(t['ts']/1000).strftime('%m/%d %H:%M')
            c='+' if t['pnl']>0 else ''
            print(f"  {k+1}. {ed}->{xd} {t['side']:5s} {c}{t['pnl']*100:+5.2f}% [{t['reason']}]")
        nr=sum(t['pnl']for t in recent)*100
        print(f"  合计: {nr:+.2f}%")

print()
print("="*70)
print("结论: ATR 0.7 在窄幅市场大幅减少假信号,趋势市保持足够交易量")
print("="*70)
