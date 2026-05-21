#!/usr/bin/env python3
"""多维度回测：全历史 + 分周期 + 滚动窗口 + 月度/年度 + 实盘模拟"""
import sys, math, json, time
from datetime import datetime, timezone
sys.path.insert(0, '/root/.hermes/scripts')
import datastore as db

# ===== 参数 =====
TP=0.005; SL=0.003; MAX_BARS=24; FEE=0.0007
BB_P=20; BB_S=2; RSI_P=7; RSI_H=70; RSI_L=30; ATR_F=0.5

def calc_indicators(bars):
    n=len(bars); cl=[b['c']for b in bars]; hi=[b['h']for b in bars]; lo=[b['l']for b in bars]
    bb_u=[None]*n; bb_l=[None]*n
    for i in range(BB_P-1,n):
        w=cl[i-BB_P+1:i+1]; sma=sum(w)/BB_P; std=math.sqrt(sum((x-sma)**2 for x in w)/BB_P)
        bb_u[i]=sma+BB_S*std; bb_l[i]=sma-BB_S*std
    rsi=[None]*n
    for i in range(RSI_P,n):
        g=sum(max(cl[j]-cl[j-1],0)for j in range(i-RSI_P+1,i+1))/RSI_P
        l=sum(max(cl[j-1]-cl[j],0)for j in range(i-RSI_P+1,i+1))/RSI_P
        rsi[i]=100-100/(1+g/l)if l>0 else 100
    atr=[None]*n; tr_list=[]
    for i in range(n):
        if i==0: tr=hi[i]-lo[i]
        else: tr=max(hi[i]-lo[i],abs(hi[i]-cl[i-1]),abs(lo[i]-cl[i-1]))
        tr_list.append(tr)
        if i>=14: atr[i]=(sum(tr_list[i-13:i+1])/14)/cl[i]*100
    valid=[v for v in atr if v is not None]; am=sum(valid)/len(valid)if valid else 0.35
    return bb_u,bb_l,rsi,atr,am

def bt(bars, sim_live=False):
    bb_u,bb_l,rsi,atr,am=calc_indicators(bars)
    trades=[]; eq=[1.0]; pos=None; ep=0; eb=0; ets=0
    mi=max(BB_P,RSI_P,14)+1; n=len(bars)
    for i in range(mi,n):
        if pos:
            c=bars[i]['c']; h=i-eb
            if pos=='long': pnl=(c-ep)/ep
            else: pnl=(ep-c)/ep
            if pnl>=TP:
                if sim_live:
                    actual_close=ep*(1+TP)*(1-0.0002) if pos=='long' else ep*(1-TP)*(1+0.0002)
                    actual_pnl=(actual_close-ep)/ep if pos=='long' else (ep-actual_close)/ep
                else: actual_pnl=pnl
                trades.append({'pnl':actual_pnl-FEE,'ts':bars[i]['ts'],'reason':'TP'})
                eq.append(eq[-1]*(1+actual_pnl-FEE)); pos=None
            elif pnl<=-SL:
                if sim_live:
                    actual_close=ep*(1-SL)*(1-0.0002) if pos=='long' else ep*(1+SL)*(1+0.0002)
                    actual_pnl=(actual_close-ep)/ep if pos=='long' else (ep-actual_close)/ep
                else: actual_pnl=pnl
                trades.append({'pnl':actual_pnl-FEE,'ts':bars[i]['ts'],'reason':'SL'})
                eq.append(eq[-1]*(1+actual_pnl-FEE)); pos=None
            elif h>=MAX_BARS:
                if sim_live: actual_close=c*(1-0.0002) if pos=='long' else c*(1+0.0002); actual_pnl=(actual_close-ep)/ep if pos=='long' else (ep-actual_close)/ep
                else: actual_pnl=pnl
                trades.append({'pnl':actual_pnl-FEE,'ts':bars[i]['ts'],'reason':'TO'})
                eq.append(eq[-1]*(1+actual_pnl-FEE)); pos=None
            continue
        sig=None; sb=None
        for j in range(i-1,max(i-4,mi-1),-1):
            if bb_u[j] is None or rsi[j] is None or atr[j] is None: continue
            if atr[j]<am*ATR_F: continue
            cj=bars[j]['c']
            if cj>bb_u[j] and rsi[j]>RSI_H: sig='short'; sb=j; break
            elif cj<bb_l[j] and rsi[j]<RSI_L: sig='long'; sb=j; break
        if sig:
            if sim_live: ep=bars[sb]['c']*(1+0.0002) if sig=='long' else bars[sb]['c']*(1-0.0002)
            else: ep=bars[sb]['c']
            pos=sig; eb=i; ets=bars[i]['ts']
    return trades,eq

def analyze(trades,eq):
    if not trades: return None
    total_ret=(eq[-1]-1)*100; wins=[t for t in trades if t['pnl']>0]; loses=[t for t in trades if t['pnl']<=0]
    wr=len(wins)/len(trades)*100; peak=1.0; max_dd=0.0
    for v in eq:
        if v>peak: peak=v
        dd=(peak-v)/peak
        if dd>max_dd: max_dd=dd
    aw=sum(t['pnl']for t in wins)/len(wins)*100 if wins else 0; al=sum(t['pnl']for t in loses)/len(loses)*100 if loses else 0
    plr=abs(aw/al) if al!=0 else 0; longs=sum(1 for t in trades if 'long' in str(t.get('reason',''))) or sum(1 for t in trades if t.get('side','')=='long')
    tp_n=sum(1 for t in trades if t['reason']=='TP'); sl_n=sum(1 for t in trades if t['reason']=='SL'); to_n=sum(1 for t in trades if t['reason']=='TO')
    # 连续亏损
    consec=0; max_consec=0
    for t in trades:
        if t['pnl']<=0: consec+=1; max_consec=max(max_consec,consec)
        else: consec=0
    # 日级回撤
    return {'total_trades':len(trades),'total_return':total_ret,'win_rate':wr,'max_drawdown':max_dd*100,
            'avg_win':aw,'avg_loss':al,'plr':plr,'longs':longs,'shorts':len(trades)-longs,
            'tp':tp_n,'sl':sl_n,'to':to_n,'max_consec':max_consec}

def rolling_window(bars, window_days=30):
    window_bars=window_days*96; rets=[]
    for i in range(0,len(bars)-window_bars,96): # 每天取一个窗口减少计算量
        sub=bars[i:i+window_bars]
        trades,eq=bt(sub,False)
        if trades and len(trades)>=3:
            rets.append((eq[-1]-1)*100)
    return rets

def main():
    print("="*90)
    print("📊 BB+RSI v6 多维度回测 (BTC-USDT-SWAP 合约)")
    print("="*90)
    print(f"参数: BB({BB_P},{BB_S}) RSI{RSI_P}[{RSI_H}/{RSI_L}] ATR×{ATR_F} TP{TP*100}% SL{SL*100}% FEE{FEE*100}%")

    # 加载全量
    bars = db.get_range(0)
    total=len(bars)
    days_covered=(bars[-1]['ts']-bars[0]['ts'])/1000/86400
    s_dt=datetime.fromtimestamp(bars[0]['ts']/1000,tz=timezone.utc).strftime('%Y-%m-%d')
    e_dt=datetime.fromtimestamp(bars[-1]['ts']/1000,tz=timezone.utc).strftime('%Y-%m-%d')
    print(f"\n数据: {total}根 | {s_dt} → {e_dt} ({days_covered:.0f}天/{days_covered/365:.1f}年)")

    # === 1. 全历史回测 ===
    print(f"\n{'─'*90}")
    print("【1】全历史回测")
    trades,eq=bt(bars,False)
    r=analyze(trades,eq)
    print(f"  交易{r['total_trades']}笔 | 胜率{r['win_rate']:.1f}% | 总收益{r['total_return']:+.2f}% | 回撤{r['max_drawdown']:.1f}%")
    print(f"  做多{r['longs']}/做空{r['shorts']} | TP{r['tp']} SL{r['sl']} TO{r['to']}")
    print(f"  均赢{r['avg_win']:+.2f}% 均亏{r['avg_loss']:+.2f}% 盈亏比{r['plr']:.2f} | 连续亏损{r['max_consec']}笔")

    # === 2. 分周期回测 ===
    print(f"\n{'─'*90}")
    print(f"{'【2】分周期回测':<20} {'交易':>6} {'胜率':>6} {'总收益':>10} {'回撤':>8} {'盈亏比':>6}")
    n=len(bars)
    for days,label in [(7,'7天'),(30,'30天'),(90,'90天'),(180,'180天'),(365,'1年')]:
        start=max(0,n-days*96)
        trades,eq=bt(bars[start:],False)
        r=analyze(trades,eq)
        if r:
            print(f"  {label:<18} {r['total_trades']:>6} {r['win_rate']:>5.1f}% {r['total_return']:>+9.2f}% {r['max_drawdown']:>7.1f}% {r['plr']:>5.2f}")

    # === 3. 滚动30天窗口 ===
    print(f"\n{'─'*90}")
    print("【3】滚动30天窗口分析")
    rets=rolling_window(bars,30)
    if rets:
        pos=sum(1 for r in rets if r>0)
        print(f"  窗口数:{len(rets)} | 盈利:{pos}({pos/len(rets)*100:.1f}%) | 均值:{sum(rets)/len(rets):+.2f}%")
        print(f"  最好:{max(rets):+.2f}% | 最差:{min(rets):+.2f}%")

    # === 4. 月度分析 ===
    print(f"\n{'─'*90}")
    print("【4】月度盈亏")
    monthly={}
    for t in trades:
        m=datetime.fromtimestamp(t['ts']/1000,tz=timezone.utc).strftime('%Y-%m')
        monthly[m]=monthly.get(m,0)+t['pnl']
    pos_months=sum(1 for v in monthly.values() if v>0)
    print(f"  {len(monthly)}个月 | {pos_months}盈/{len(monthly)-pos_months}亏 | 胜率{pos_months/len(monthly)*100:.1f}%")
    months=sorted(monthly.keys())
    for m in months[-12:]:
        v=monthly[m]*100; bar='█'*min(int(abs(v)),50)
        print(f"  {m}: {v:+7.2f}% {bar}")

    # === 5. 年度分析 ===
    print(f"\n{'─'*90}")
    print("【5】各年度")
    for y in sorted(set(datetime.fromtimestamp(t['ts']/1000,tz=timezone.utc).year for t in trades)):
        yt=[t for t in trades if datetime.fromtimestamp(t['ts']/1000,tz=timezone.utc).year==y]
        if len(yt)<30: continue
        yw=[t for t in yt if t['pnl']>0]; yec=1.0
        for t in yt: yec*=(1+t['pnl'])
        print(f"  {y}: {len(yt)}笔 | 胜率{len(yw)/len(yt)*100:.1f}% | 复利{(yec-1)*100:+.2f}% | 月均{(yec**(1/12)-1)*100:+.2f}%")

    # === 6. 实盘模拟(近90天) ===
    print(f"\n{'─'*90}")
    print("【6】实盘模拟(近90天,含滑点万2/延迟1根K线)")
    trades,eq=bt(bars[max(0,n-90*96):],True)
    r=analyze(trades,eq)
    if r:
        print(f"  交易{r['total_trades']}笔 | 胜率{r['win_rate']:.1f}% | 总收益{r['total_return']:+.2f}% | 回撤{r['max_drawdown']:.1f}%")

    print(f"\n{'='*90}")
    print("✅ 多维度回测完成")

if __name__=="__main__":
    main()
