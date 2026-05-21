#!/usr/bin/env python3
"""7天滚动窗口全历史报表"""
import requests, math, time
from datetime import datetime, timezone

URL = "https://www.okx.com/api/v5/market/history-candles"
PROXY = "http://127.0.0.1:2080"
FEE=0.0007;BB_P=20;BB_S=2;RSI_P=7;RSI_H=70;RSI_L=30;ATR_F=0.5
TP=0.005;SL=0.003;MAX_B=24

print("拉取全量数据...")
bars=[];after=int(time.time()*1000);p=0
while p<300:
    try:
        r=requests.get(URL,params={"instId":"BTC-USDT","bar":"15m","limit":300,"after":str(after)},
                       proxies={"http":PROXY,"https":PROXY},timeout=30)
        data=r.json().get("data",[])
        if not data:break
        bars=[{"ts":int(row[0]),"c":float(row[4]),"h":float(row[2]),"l":float(row[3])} for row in data]+bars
        after=int(data[-1][0]);p+=1
        if p%40==0:print(f"  {p}页 {len(bars)}根")
        time.sleep(0.02)
    except:break
bars.sort(key=lambda x:x["ts"])
td=(bars[-1]["ts"]-bars[0]["ts"])/1000/86400
print(f"\n✅ {len(bars)}根 | {datetime.fromtimestamp(bars[0]['ts']/1000).strftime('%Y-%m-%d')}~{datetime.fromtimestamp(bars[-1]['ts']/1000).strftime('%Y-%m-%d')} | {td:.0f}天")

def calc(bars):
    cl=[b["c"]for b in bars];hi=[b["h"]for b in bars];lo=[b["l"]for b in bars];n=len(cl)
    bb_u,bb_l=[None]*n,[None]*n
    for i in range(BB_P-1,n):
        w=cl[i-BB_P+1:i+1];sma=sum(w)/BB_P;std=(sum((x-sma)**2 for x in w)/BB_P)**0.5
        bb_u[i]=sma+BB_S*std;bb_l[i]=sma-BB_S*std
    rs=[None]*n
    for i in range(RSI_P,n):
        g=sum(max(cl[j]-cl[j-1],0)for j in range(i-RSI_P+1,i+1))/RSI_P
        l=sum(max(cl[j-1]-cl[j],0)for j in range(i-RSI_P+1,i+1))/RSI_P
        rs[i]=100-100/(1+g/l)if l>0 else 100
    atr=[None]*n
    for i in range(14,n):
        tr=[max(hi[j]-lo[j],abs(hi[j]-cl[j-1]),abs(lo[j]-cl[j-1]))for j in range(i-13,i+1)]
        atr[i]=(sum(tr)/14)/cl[i]*100
    v=[v for v in atr if v is not None];am=sum(v)/len(v)if v else 0.1
    return bb_u,bb_l,rs,atr,am

def bt(bars):
    bb_u,bb_l,rs,atr,am=calc(bars);trades=[]
    in_pos=None;ep=0;eb=0;eq=[1.0]
    mi=max(BB_P,RSI_P,14)+1;n=len(bars)
    for i in range(mi,n):
        c=bars[i]["c"]
        if in_pos:
            h=i-eb;pnl=(c-ep)/ep if in_pos=="long" else (ep-c)/ep
            if pnl>=TP:trades.append({"p":pnl-FEE,"r":"TP"});eq.append(eq[-1]*(1+pnl-FEE));in_pos=None;continue
            if pnl<=-SL:trades.append({"p":pnl-FEE,"r":"SL"});eq.append(eq[-1]*(1+pnl-FEE));in_pos=None;continue
            if h>=MAX_B:trades.append({"p":pnl-FEE,"r":"TO"});eq.append(eq[-1]*(1+pnl-FEE));in_pos=None;continue
            continue
        sig=None;sig_bar=None
        for j in range(i-1,max(i-4,mi-1),-1):
            if bb_u[j] is None or rs[j] is None or atr[j] is None:continue
            if atr[j]<am*ATR_F:continue
            cj=bars[j]["c"]
            if cj>bb_u[j] and rs[j]>RSI_H:sig="short";sig_bar=j;break
            elif cj<bb_l[j] and rs[j]<RSI_L:sig="long";sig_bar=j;break
        if not sig:continue
        ep=bars[sig_bar]["c"];in_pos=sig;eb=i
    if in_pos:
        c=bars[-1]["c"];pnl=(c-ep)/ep if in_pos=="long" else (ep-c)/ep
        trades.append({"p":pnl-FEE,"r":"OPEN"})
    return trades,eq

# 滚动7天窗口 (每天一个窗口)
total=len(bars);W=7*96
windows=[];results=[]

for start in range(0,total-W,96):  # 每天一个窗口
    end=start+W
    if end>total:break
    windows.append((start,end))

print(f"\n计算 {len(windows)} 个7天窗口...")
for si,(start,end) in enumerate(windows):
    if si%50==0:print(f"  {si}/{len(windows)}...")
    t,eq=bt(bars[start:end])
    if not t:results.append(None);continue
    w=[tt for tt in t if tt["p"]>0];l=[tt for tt in t if tt["p"]<=0]
    ec=1.0
    for tt in t:ec*=(1+tt["p"])
    comp=(ec-1)*100;wr=len(w)/len(t)*100 if t else 0
    
    peak=1.0;max_dd=0
    for v in eq:
        if v>peak:peak=v
        if peak-v>max_dd:max_dd=peak-v
    
    results.append({
        "start":datetime.fromtimestamp(bars[start]["ts"]/1000,tz=timezone.utc).strftime("%Y-%m-%d"),
        "end":datetime.fromtimestamp(bars[end-1]["ts"]/1000,tz=timezone.utc).strftime("%Y-%m-%d"),
        "n":len(t),"wr":wr,"comp":comp,"dd":max_dd*100,
        "av_w":sum(tt["p"]for tt in w)/len(w)*100 if w else 0,
        "av_l":sum(tt["p"]for tt in l)/len(l)*100 if l else 0
    })

valid=[r for r in results if r is not None]
pos=[r for r in valid if r["comp"]>0];neg=[r for r in valid if r["comp"]<=0]

print(f"\n{'='*80}")
print(f"📊 7天滚动窗口全历史报表 ({len(valid)}个窗口, {td:.0f}天)")
print(f"{'='*80}")
print(f"")
print(f"  盈利能力:")
print(f"    盈利窗口: {len(pos)} ({len(pos)/len(valid)*100:.0f}%)")
print(f"    亏损窗口: {len(neg)} ({len(neg)/len(valid)*100:.0f}%)")
print(f"    平均收益: {sum(r['comp']for r in valid)/len(valid):+.2f}%")
print(f"    中位收益: {sorted(r['comp']for r in valid)[len(valid)//2]:+.2f}%")
print(f"    最佳窗口: {max(r['comp']for r in valid):+.2f}% ({max(r['start']for r in valid if r['comp']==max(rr['comp']for rr in valid))})")
print(f"    最差窗口: {min(r['comp']for r in valid):+.2f}% ({min(r['start']for r in valid if r['comp']==min(rr['comp']for rr in valid))})")
print(f"")
print(f"  交易统计:")
avg_n=sum(r['n']for r in valid)/len(valid)
avg_wr=sum(r['wr']for r in valid)/len(valid)
avg_dd=sum(r['dd']for r in valid)/len(valid)
print(f"    平均交易: {avg_n:.0f}笔/7天")
print(f"    平均胜率: {avg_wr:.1f}%")
print(f"    平均回撤: {avg_dd:.1f}%")
print(f"    最大回撤: {max(r['dd']for r in valid):.1f}%")

# 收益分布
print(f"\n  收益分布:")
buckets=[(-20,-10),(-10,-5),(-5,-2),(-2,0),(0,2),(2,5),(5,10),(10,20),(20,50)]
for lo,hi in buckets:
    cnt=sum(1 for r in valid if lo<=r["comp"]<hi)
    bar="█"*cnt
    pct=cnt/len(valid)*100
    print(f"    {lo:>+4}%~{hi:>+3}%: {cnt:>4}个 ({pct:>4.1f}%) {bar}")

# 按年统计
print(f"\n  按年统计:")
for year in sorted(set(r["start"][:4] for r in valid)):
    yr=[r for r in valid if r["start"].startswith(year)]
    yp=[r for r in yr if r["comp"]>0]
    avg=sum(r['comp']for r in yr)/len(yr)
    print(f"    {year}: {len(yr)}窗口 | {len(yp)}盈/{len(yr)-len(yp)}亏 ({len(yp)/len(yr)*100:.0f}%) | 均值{avg:+.2f}%")

# 最近30个窗口明细
print(f"\n{'='*80}")
print(f"最近30个7天窗口明细")
print(f"{'='*80}")
print(f"{'窗口':<24} {'交易':>5} {'胜率':>7} {'收益':>8} {'回撤':>7} {'均盈':>7} {'均亏':>7}")
print(f"{'-'*70}")
for r in valid[-30:]:
    flag="✅" if r["comp"]>0 else "❌"
    print(f"{flag} {r['start']}~{r['end']} {r['n']:>5} {r['wr']:>6.1f}% {r['comp']:>+7.2f}% {r['dd']:>6.1f}% {r['av_w']:>+6.2f}% {r['av_l']:>+6.2f}%")

# 20x/80%收益
bal=37.54;lev=20;mp=0.8;btc_=bars[-1]["c"];ct_val=btc_*0.01
ct=round(bal*mp/(ct_val/lev)*100)/100;ntl=ct*ct_val
avg_comp=sum(r['comp']for r in valid)/len(valid)
monthly=avg_comp/100*ntl
print(f"\n💰 20×/80% {ct:.2f}张 ${ntl:.0f}名义 | 7天均值{avg_comp:+.2f}% = ${avg_comp/100*ntl:+.2f}/周 | 月化${monthly*4.3:+.0f}")
