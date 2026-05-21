#!/usr/bin/env python3
"""Phase1: 54组合粗扫 + Phase2: Top5精细调参 → 最优策略搜索"""
import sys, math, json, time
from datetime import datetime, timezone
sys.path.insert(0,'/root/.hermes/scripts')
import datastore as db

FEE=0.0007; MAX_BARS=24

# ===== 预计算所有指标 (一次计算,所有组合复用) =====
def precompute_indicators(bars):
    n=len(bars); cl=[b['c']for b in bars]; hi=[b['h']for b in bars]; lo=[b['l']for b in bars]
    data={'n':n,'cl':cl,'hi':hi,'lo':lo}

    # BB 变体: period=14,20,30  (std固定2)
    for bb_p in [14,20,30]:
        bb_u=[None]*n; bb_l=[None]*n; bb_m=[None]*n
        for i in range(bb_p-1,n):
            w=cl[i-bb_p+1:i+1]; sma=sum(w)/bb_p; std=math.sqrt(sum((x-sma)**2 for x in w)/bb_p)
            bb_u[i]=sma+2*std; bb_l[i]=sma-2*std; bb_m[i]=sma
        data[f'bb{bb_p}_u']=bb_u; data[f'bb{bb_p}_l']=bb_l; data[f'bb{bb_p}_m']=bb_m

    # RSI 变体: period=7,10,14
    for rsi_p in [7,10,14]:
        rsi=[None]*n; gains=[0]*(rsi_p); losses=[0]*(rsi_p)
        for i in range(n):
            if i==0: gains.append(0); losses.append(0)
            else: ch=cl[i]-cl[i-1]; gains.append(max(ch,0)); losses.append(max(-ch,0))
            if i>=rsi_p:
                ag=sum(gains[-rsi_p:])/rsi_p; al=sum(losses[-rsi_p:])/rsi_p
                rsi[i]=100-100/(1+ag/al) if al>0 else 100
        data[f'rsi{rsi_p}']=rsi

    # ATR (period=14固定,只看百分比)
    atr_pct=[None]*n; tr_list=[]
    for i in range(n):
        if i==0: tr=hi[i]-lo[i]
        else: tr=max(hi[i]-lo[i],abs(hi[i]-cl[i-1]),abs(lo[i]-cl[i-1]))
        tr_list.append(tr)
        if i>=14: atr_pct[i]=(sum(tr_list[-14:])/14)/cl[i]*100
    valid=[v for v in atr_pct if v is not None]
    data['atr']=atr_pct; data['atr_mean']=sum(valid)/len(valid) if valid else 0.35

    return data

def backtest_with_precomputed(bars, d, bb_p, rsi_p, rsi_h, rsi_l, atr_f, tp, sl):
    bb_u=d[f'bb{bb_p}_u']; bb_l=d[f'bb{bb_p}_l']; rsi=d[f'rsi{rsi_p}']
    atr=d['atr']; am=d['atr_mean']; n=d['n']
    trades=[]; eq=[1.0]; pos=None; ep=0; eb=0
    mi=max(bb_p,rsi_p,14)+1

    for i in range(mi,n):
        if pos:
            c=bars[i]['c']; held=i-eb
            pnl=(c-ep)/ep if pos=='long' else (ep-c)/ep
            if pnl>=tp: trades.append({'pnl':pnl-FEE}); eq.append(eq[-1]*(1+pnl-FEE)); pos=None; continue
            if pnl<=-sl: trades.append({'pnl':pnl-FEE}); eq.append(eq[-1]*(1+pnl-FEE)); pos=None; continue
            if held>=MAX_BARS: trades.append({'pnl':pnl-FEE}); eq.append(eq[-1]*(1+pnl-FEE)); pos=None; continue
            continue

        sig=None; sb=None
        for j in range(i-1,max(i-4,mi-1),-1):
            if bb_u[j] is None or rsi[j] is None or atr[j] is None: continue
            if atr[j]<am*atr_f: continue
            cj=bars[j]['c']
            if cj>bb_u[j] and rsi[j]>rsi_h: sig='short'; sb=j; break
            elif cj<bb_l[j] and rsi[j]<rsi_l: sig='long'; sb=j; break
        if sig: pos=sig; ep=bars[sb]['c']; eb=i

    return trades,eq

def score(trades,eq):
    if not trades or len(trades)<10: return -999
    total=(eq[-1]-1)*100; wins=[t for t in trades if t['pnl']>0]
    wr=len(wins)/len(trades)*100; peak=1.0; max_dd=0.0
    for v in eq:
        if v>peak: peak=v
        dd=(peak-v)/peak
        if dd>max_dd: max_dd=dd
    # score = 总收益 / (1+回撤) * 胜率系数
    dd_penalty=1+max_dd*2  # 回撤惩罚
    return total/dd_penalty*wr/100, total, wr, max_dd*100

def main():
    t0=time.time()
    print("加载225k数据...", flush=True)
    bars=db.get_range(0)
    print(f"预计算指标...", flush=True)
    d=precompute_indicators(bars)
    print(f"预计算完成 ({time.time()-t0:.1f}s)", flush=True)

    # === Phase1: 54组合粗扫 ===
    bb_periods=[14,20,30]
    rsi_periods=[7,10,14]
    rsi_thresholds=[(65,35),(70,30)]
    atr_filters=[0.4,0.5,0.6]
    tp_sl=[(0.005,0.003)]  # 固定TP/SL先

    results=[]
    total_combos=len(bb_periods)*len(rsi_periods)*len(rsi_thresholds)*len(atr_filters)*len(tp_sl)
    n=0

    print(f"\n=== Phase1: {total_combos}组合粗扫 ===")
    for bb_p in bb_periods:
        for rsi_p in rsi_periods:
            for rsi_h,rsi_l in rsi_thresholds:
                for atr_f in atr_filters:
                    for tp,sl in tp_sl:
                        n+=1
                        trades,eq=backtest_with_precomputed(bars,d,bb_p,rsi_p,rsi_h,rsi_l,atr_f,tp,sl)
                        s,tot,wr,dd=score(trades,eq)
                        results.append((s,tot,wr,dd,len(trades),bb_p,rsi_p,rsi_h,rsi_l,atr_f,tp,sl))
                        if n%10==0: print(f"  {n}/{total_combos} ({time.time()-t0:.0f}s)", flush=True)

    # 排名
    results.sort(key=lambda x:-x[0])
    print(f"\n=== Phase1 Top10 ===")
    print(f"{'排名':<4} {'得分':>8} {'总收益':>10} {'胜率':>6} {'回撤':>6} {'交易':>6} {'BB':>4} {'RSI':>5} {'阈值':>8} {'ATR':>5} {'TP/SL':>10}")
    for i,(s,tot,wr,dd,nt,bb_p,rsi_p,rsi_h,rsi_l,atr_f,tp,sl) in enumerate(results[:10]):
        print(f"{i+1:<4} {s:>8.1f} {tot:>+9.2f}% {wr:>5.1f}% {dd:>5.1f}% {nt:>6} {bb_p:>4} {rsi_p:>4} {rsi_h}/{rsi_l:<4} {atr_f:>5.2f} {tp*100:.0f}/{sl*100:.0f}%")

    # === Phase2: Top3 精细调参 ===
    print(f"\n=== Phase2: Top3精细调参 ===")
    fine_results=[]
    for rank,(_,_,_,_,_,bb_p,rsi_p,rsi_h,rsi_l,atr_f,tp,sl) in enumerate(results[:3]):
        # 变体: BB std, TP/SL, MAX_BARS
        for bb_s in [1.5,2,2.5]:
            for n_tp,n_sl in [(0.004,0.0025),(0.005,0.003),(0.006,0.004),(0.008,0.004)]:
                for mb in [16,20,24,30]:
                    global MAX_BARS; MAX_BARS=mb
                    trades,eq=backtest_with_precomputed(bars,d,bb_p,rsi_p,rsi_h,rsi_l,atr_f,n_tp,n_sl)
                    s,tot,wr,dd=score(trades,eq)
                    fine_results.append((s,tot,wr,dd,len(trades),bb_p,bb_s,rsi_p,rsi_h,rsi_l,atr_f,n_tp,n_sl,mb))

    fine_results.sort(key=lambda x:-x[0])
    print(f"{'排名':<4} {'得分':>8} {'总收益':>10} {'胜率':>6} {'回撤':>6} {'交易':>6} {'BB':>6} {'RSI':>5} {'阈值':>8} {'ATR':>5} {'TP/SL':>10} {'超时'}")
    for i,(s,tot,wr,dd,nt,bb_p,bb_s,rsi_p,rsi_h,rsi_l,atr_f,tp,sl,mb) in enumerate(fine_results[:10]):
        print(f"{i+1:<4} {s:>8.1f} {tot:>+9.2f}% {wr:>5.1f}% {dd:>5.1f}% {nt:>6} {bb_p}/{bb_s} {rsi_p:>4} {rsi_h}/{rsi_l:<4} {atr_f:>5.2f} {tp*100:.0f}/{sl*100:.0f}%{'':>3} {mb}")

    # === 最优参数 ===
    best=fine_results[0]
    print(f"\n{'='*80}")
    print(f"🏆 最优参数：BB({best[5]},{best[6]}) RSI{best[7]}[{best[8]}/{best[9]}] ATR×{best[10]} TP{best[11]*100:.0f}% SL{best[12]*100:.1f}% 超时{best[13]}bar")
    print(f"   得分:{best[0]:.1f} | 总收益:{best[1]:+.2f}% | 胜率:{best[2]:.1f}% | 回撤:{best[3]:.1f}% | 交易:{best[4]}笔")
    print(f"{'='*80}")

    print(f"\n总耗时: {time.time()-t0:.1f}s")

if __name__=="__main__":
    main()
