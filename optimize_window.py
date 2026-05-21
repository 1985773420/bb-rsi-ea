#!/usr/bin/env python3
"""寻找最优: 窗口大小×ATR过滤 网格搜索"""
import sys,math,time
from datetime import datetime,timezone
sys.path.insert(0,'.')
import datastore as db

TP=0.008;SL=0.004;MAX_BARS=24;FEE=0;SLIP=0
BB_P=20;BB_S=2;RSI_P=7;RSI_H=65;RSI_L=35;LEV=15;MARGIN=0.5

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

def bt_sliding(bars,window_size,atr_base):
    trades=[];pos=None;ep=0;eb=0;total_bars=len(bars)
    step=max(50,window_size//4)

    for start in range(0,total_bars-window_size,step):
        end=min(start+window_size,total_bars)
        win=bars[max(0,end-window_size):end+1]
        if len(win)<50:continue

        bu,bl,rsi,atr,am=calc_window(win)
        n_=len(win);mi=max(BB_P,RSI_P,14)+1

        for i in range(mi,n_):
            real_i=end-len(win)+i
            if real_i<=eb:continue
            c=win[i]['c'];h_=real_i-eb if pos else 0

            if pos:
                pnl=(c-ep)/ep if pos=='long'else(ep-c)/ep
                if pnl>=TP:trades.append({'eb':eb,'ex':real_i,'side':pos,'pnl':TP,'reason':'TP','ts':win[i]['ts']});pos=None;continue
                if pnl<=-SL:trades.append({'eb':eb,'ex':real_i,'side':pos,'pnl':-SL,'reason':'SL','ts':win[i]['ts']});pos=None;continue
                if h_>=MAX_BARS:trades.append({'eb':eb,'ex':real_i,'side':pos,'pnl':pnl,'reason':'TO','ts':win[i]['ts']});pos=None;continue
                continue
            if pos:continue
            sig=None;sb=None
            for j in range(i-1,max(i-4,mi-1),-1):
                if bu[j] is None or rsi[j] is None or atr[j] is None:continue
                if n_>=2 and bu[n_-1] and bl[n_-1]:
                    bb_w=(bu[n_-1]-bl[n_-1])/win[n_-1]['c']*100
                    dyn_f=atr_base*1.8 if bb_w<8 else(atr_base*1.2 if bb_w<12 else atr_base*0.8)
                else:dyn_f=atr_base
                if atr[j]<am*dyn_f:continue
                cj=win[j]['c']
                if cj>bu[j] and rsi[j]>RSI_H:sig='short';sb=j;break
                elif cj<bl[j] and rsi[j]<RSI_L:sig='long';sb=j;break
            if sig:ep=win[sb]['c'];pos=sig;eb=real_i

    # 去重去重叠
    seen=set();unique=[]
    for t in trades:
        k=(t['eb'],t['ex'],t['side'],t['reason'])
        if k not in seen:seen.add(k);unique.append(t)
    final=[];last_exit=-1
    for t in sorted(unique,key=lambda x:x['eb']):
        if t['eb']>=last_exit:final.append(t);last_exit=t['ex']
    return final

all_bars=db.get_range(0);n=len(all_bars)

# 测试: 90天数据, 窗口200-1000 vs ATR 0.4-0.8
windows=[200,300,400,500,600,800,1000]
atrs=[0.4,0.5,0.6,0.7,0.8]
t0=time.time()
results=[]

for days,label in[(90,'90d'),(180,'180d')]:
    sub=all_bars[max(0,n-days*96):]
    print()
    print('='*65)
    print(label + ' 窗口×ATR网格搜索')
    print('='*65)
    for w in windows:
        for a in atrs:
            trades=bt_sliding(sub,w,a)
            if not trades:continue
            wins=[t for t in trades if t['pnl']>0]
            wr=len(wins)/len(trades)*100
            ret=sum(t['pnl']for t in trades)*100
            lev=ret*LEV*MARGIN
            results.append((ret,w,a,wr,len(trades),lev,label))

# 找最佳
results.sort(key=lambda x:-x[0])
best_90=[r for r in results if r[6]=='90d'][:5]
best_180=[r for r in results if r[6]=='180d'][:5]

print()
print('='*65)
print('TOP 90天组合:')
for i,(ret,w,a,wr,nt,lev,_) in enumerate(best_90):
    print(f'  #{i+1} 窗口{w} ATR{a} -> {ret:+.1f}% WR{wr:.0f}% {nt}笔 杠杆{lev:+.0f}%')

print()
print('TOP 180天组合:')
for i,(ret,w,a,wr,nt,lev,_) in enumerate(best_180):
    print(f'  #{i+1} 窗口{w} ATR{a} -> {ret:+.1f}% WR{wr:.0f}% {nt}笔 杠杆{lev:+.0f}%')

overall=sorted(results,key=lambda x:-(x[0]*0.4+sum(1 for r in results if r[2]==x[2] and r[1]==x[1])*0.3+x[3]*0.3))
best=overall[0]
print()
print('='*65)
print('OVERALL BEST: 窗口' + str(best[1]) + ' ATR' + str(best[2]))
print('  收益' + ('+' if best[0]>0 else '') + str(round(best[0],1)) + '% WR' + str(int(best[3])) + '% ' + str(best[4]) + '笔 杠杆' + ('+' if best[5]>0 else '') + str(int(best[5])) + '%')
print('耗时' + str(int(time.time()-t0)) + 's')
