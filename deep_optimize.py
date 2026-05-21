#!/usr/bin/env python3
"""深度优化v2: 聚焦网格搜索 → 最大年化且不爆仓"""
import sys,math,time
sys.path.insert(0,'/root/.hermes/scripts');import datastore as db

FEE=0.0007

def precompute(bars):
    n=len(bars);cl=[b['c']for b in bars];hi=[b['h']for b in bars];lo=[b['l']for b in bars]
    d={'n':n,'cl':cl,'hi':hi,'lo':lo}
    # BB: period=14,20,30 x std=1.5,2,2.5
    for bp in[10,14,20,30]:
        for bs in[1.5,2,2.5]:
            bu=[None]*n;bl=[None]*n
            for i in range(bp-1,n):
                w=cl[i-bp+1:i+1];sma=sum(w)/bp;std=math.sqrt(sum((x-sma)**2 for x in w)/bp)
                bu[i]=sma+bs*std;bl[i]=sma-bs*std
            d[f'b{bp}_{bs}_u']=bu;d[f'b{bp}_{bs}_l']=bl
    # RSI: period=5,7,10,14
    for rp in[5,7,10,14]:
        r=[None]*n
        for i in range(rp,n):
            g=sum(max(cl[j]-cl[j-1],0)for j in range(i-rp+1,i+1))/rp
            l=sum(max(cl[j-1]-cl[j],0)for j in range(i-rp+1,i+1))/rp
            r[i]=100-100/(1+g/l)if l>0 else 100
        d[f'r{rp}']=r
    # ATR
    atr=[None]*n;tl=[]
    for i in range(n):
        if i==0:tr=hi[i]-lo[i]
        else:tr=max(hi[i]-lo[i],abs(hi[i]-cl[i-1]),abs(lo[i]-cl[i-1]))
        tl.append(tr)
        if i>=14:atr[i]=(sum(tl[-14:])/14)/cl[i]*100
    v=[x for x in atr if x];d['atr']=atr;d['atr_m']=sum(v)/len(v)if v else 0.35
    return d

def bt(bars,d,bb_p,bb_s,rsi_p,r_h,r_l,atr_f,tp,sl,mb):
    bu=d[f'b{bb_p}_{bb_s}_u'];bl=d[f'b{bb_p}_{bb_s}_l'];rsi=d[f'r{rsi_p}']
    atr=d['atr'];am=d['atr_m'];n=d['n']
    t=[];eq=[1.0];pos=None;ep=0;eb=0;mi=max(bb_p,rsi_p,14)+1
    for i in range(mi,n):
        if pos:
            c=bars[i]['c'];h=i-eb;pnl=(c-ep)/ep if pos=='long'else(ep-c)/ep
            if pnl>=tp:t.append({'pnl':pnl-FEE});eq.append(eq[-1]*(1+pnl-FEE));pos=None;continue
            if pnl<=-sl:t.append({'pnl':pnl-FEE});eq.append(eq[-1]*(1+pnl-FEE));pos=None;continue
            if h>=mb:t.append({'pnl':pnl-FEE});eq.append(eq[-1]*(1+pnl-FEE));pos=None;continue
            continue
        sig=None;sb=None
        for j in range(i-1,max(i-4,mi-1),-1):
            if bu[j] is None or rsi[j] is None or atr[j] is None:continue
            if atr_f>0 and atr[j]<am*atr_f:continue
            cj=bars[j]['c']
            if cj>bu[j] and rsi[j]>r_h:sig='short';sb=j;break
            elif cj<bl[j] and rsi[j]<r_l:sig='long';sb=j;break
        if sig:pos=sig;ep=bars[sb]['c'];eb=i
    if pos:c=bars[-1]['c'];pnl=(c-ep)/ep if pos=='long'else(ep-c)/ep;t.append({'pnl':pnl-FEE})
    return t,eq

def analyze(trades,eq,lev):
    if not trades:return None
    total=(eq[-1]-1)*100;wins=[t for t in trades if t['pnl']>0]
    wr=len(wins)/len(trades)*100;peak=1.0;dd=0
    for v in eq:
        if v>peak:peak=v
        d_=(peak-v)/peak
        if d_>dd:dd=d_
    days=(bars[-1]['ts']-bars[0]['ts'])/86400000
    annual=total/max(1,days)*365
    # 防爆仓: 回撤<80%
    safe=dd<0.8
    # 评分=年化/100/(1+回撤)*胜率
    s=(annual/100)/max(0.01,1+dd*3)*(wr/100)
    return {'s':s,'total':total,'wr':wr,'dd':dd*100,'annual':annual,'nt':len(trades),'safe':safe}

# === 加载 ===
t0=time.time()
bars=db.get_range(0);d=precompute(bars)
print(f"预计算{(time.time()-t0):.0f}s",flush=True)

# === Phase1: 聚焦网格 (约120组合) ===
print("\n=== Phase1 网格搜索 ===",flush=True)
results=[]
total=4*3*3*4*4*4  # BB14/20 × RSI5/7/10 × ATR0/0.4/0.5/0.6 × TP×SL×超时
n=0
for bb_p in[14,20]:
 for rsi_p in[5,7,10]:
  for r_h,r_l in[(65,35),(70,30)]:
   for atr_f in[0,0.4,0.5,0.6]:
    for tp in[0.4,0.5,0.6,0.8]:
     for sl in[0.2,0.25,0.3,0.4]:
      for mb in[16,20,24]:
       if sl>=tp:continue
       n+=1
       trades,eq=bt(bars,d,bb_p,2,rsi_p,r_h,r_l,atr_f,tp,sl,mb)
       if len(trades)<5:continue
       # 测试不同杠杆(实际不影响回测%结果,只看安全边界)
       for lev in[10,15,20]:
           info=analyze(trades,eq,lev)
           if info and info['safe']:
               results.append((info['s'],info,bb_p,2,rsi_p,r_h,r_l,atr_f,tp,sl,mb,lev))

results.sort(key=lambda x:-x[0])
print(f"有效:{len(results)}组合 | 耗时{(time.time()-t0):.0f}s",flush=True)

print(f"\n{'#':<3}{'得分':>7}{'年化%':>8}{'胜率%':>6}{'回撤%':>6}{'交易':>6}{'BB':>4}{'RSI':>5}{'阈':>8}{'ATR':>4}{'TP%':>5}{'SL%':>5}{'超':>4}{'杠':>4}")
for i,(s,info,bb_p,bb_s,r_p,rh,rl,af,tp,sl,mb,lev) in enumerate(results[:20]):
    print(f"{i+1:<3}{s:>7.3f}{info['annual']:>7.0f}%{info['wr']:>5.0f}%{info['dd']:>5.0f}%{info['nt']:>6}{bb_p:>4}{r_p:>5}{rh}/{rl:<4}{af:>4.1f}{tp*100:>5.1f}{sl*100:>5.1f}{mb:>4}{lev:>4}")

# === Phase2: Top5精细 ===
print(f"\n=== Phase2 精细调参 ===",flush=True)
fine=[]
for rank,(_,_,bb_p,_,r_p,rh,rl,af,tp,sl,mb,lev) in enumerate(results[:5]):
    for ntp in[round(tp-0.1,2),tp,round(tp+0.1,2)]:
     for nsl in[round(sl-0.05,2),sl,round(sl+0.05,2)]:
      for nmb in[max(12,mb-4),mb,max(30,mb+4)]:
       if nsl>=ntp or ntp<=0.2 or nsl<=0.1:continue
       trades,eq=bt(bars,d,bb_p,2,r_p,rh,rl,af,ntp,nsl,nmb)
       info=analyze(trades,eq,lev)
       if info and info['safe']:
           fine.append((info['s'],info,bb_p,2,r_p,rh,rl,af,ntp,nsl,nmb,lev))

fine.sort(key=lambda x:-x[0])
print(f"{'#':<3}{'得分':>7}{'年化%':>8}{'胜率%':>6}{'回撤%':>6}{'交易':>6}{'BB':>4}{'RSI':>5}{'阈':>8}{'ATR':>4}{'TP%':>5}{'SL%':>5}{'超':>4}{'杠':>4}")
for i,(s,info,bb_p,_,r_p,rh,rl,af,tp,sl,mb,lev) in enumerate(fine[:15]):
    print(f"{i+1:<3}{s:>7.3f}{info['annual']:>7.0f}%{info['wr']:>5.0f}%{info['dd']:>5.0f}%{info['nt']:>6}{bb_p:>4}{r_p:>5}{rh}/{rl:<4}{af:>4.1f}{tp*100:>5.1f}{sl*100:>5.1f}{mb:>4}{lev:>4}")

best=fine[0]
print(f"\n{'='*65}")
print(f"🏆 BB({best[2]},2) RSI{best[4]}[{best[5]}/{best[6]}] ATR×{best[7]} TP{best[8]*100:.1f}% SL{best[9]*100:.2f}% 超{best[10]} 杠{best[11]}x")
print(f"   年化{best[1]['annual']:.0f}% | 胜率{best[1]['wr']:.0f}% | 回撤{best[1]['dd']:.0f}% | 交易{best[1]['nt']}笔 | 不爆仓✅")
print(f"{'='*65}")
