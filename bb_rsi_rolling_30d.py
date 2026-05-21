#!/usr/bin/env python3
"""30天滚动窗口回测 — 全量历史"""
import requests, math, time
from datetime import datetime, timezone

URL = "https://www.okx.com/api/v5/market/history-candles"
PROXY = "http://127.0.0.1:2080"
FEE=0.0007;BB_P=20;BB_S=2;RSI_P=7;RSI_H=70;RSI_L=30;ATR_F=0.5
TP=0.005;SL=0.003;MAX_B=24

print("拉取最大历史数据...")
bars=[];after=int(time.time()*1000);page=0
while page<300:
    try:
        r=requests.get(URL,params={"instId":"BTC-USDT","bar":"15m","limit":300,"after":str(after)},
                       proxies={"http":PROXY,"https":PROXY},timeout=30)
        data=r.json().get("data",[])
        if not data:break
        bars=[{"ts":int(row[0]),"c":float(row[4]),"h":float(row[2]),"l":float(row[3])} for row in data]+bars
        after=int(data[-1][0]);page+=1
        if page%30==0:print(f"  第{page}页 {len(bars)}根, {datetime.fromtimestamp(bars[0]['ts']/1000).strftime('%Y-%m')}")
        time.sleep(0.03)
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

# 滚动30天窗口
WINDOW_DAYS = 30
STEP_DAYS = 7  # 每7天一个窗口
window_bars = WINDOW_DAYS * 96

windows = []
total = len(bars)
for start in range(0, total - window_bars, STEP_DAYS * 96):
    end = start + window_bars
    windows.append(bars[start:end])

print(f"\n滚动 {len(windows)} 个30天窗口...")
results = []
for i, w in enumerate(windows):
    t, eq = bt(w)
    if not t: 
        results.append({"n":0,"wr":0,"comp":0,"dd":0})
        continue
    w_=[tt for tt in t if tt["p"]>0]
    ec=1.0
    for tt in t:ec*=(1+tt["p"])
    comp=(ec-1)*100;wr=len(w_)/len(t)*100
    
    peak=1.0;max_dd=0
    for v in eq:
        if v>peak:peak=v
        if peak-v>max_dd:max_dd=peak-v
    
    results.append({"n":len(t),"wr":wr,"comp":comp,"dd":max_dd*100,
                    "start":datetime.fromtimestamp(w[0]["ts"]/1000).strftime("%Y-%m-%d")})

# 统计
valid = [r for r in results if r["n"]>0]
pos_windows = [r for r in valid if r["comp"]>0]
neg_windows = [r for r in valid if r["comp"]<=0]

print(f"\n{'='*75}")
print(f"📊 30天滚动窗口统计 ({len(valid)}个窗口)")
print(f"{'='*75}")
print(f"  盈利窗口: {len(pos_windows)} ({len(pos_windows)/len(valid)*100:.0f}%)")
print(f"  亏损窗口: {len(neg_windows)} ({len(neg_windows)/len(valid)*100:.0f}%)")
print(f"  平均收益: {sum(r['comp']for r in valid)/len(valid):+.2f}%")
print(f"  平均交易: {sum(r['n']for r in valid)/len(valid):.0f}笔/30天")
print(f"  平均胜率: {sum(r['wr']for r in valid)/len(valid):.1f}%")
print(f"  最佳窗口: {max(r['comp']for r in valid):+.2f}%")
print(f"  最差窗口: {min(r['comp']for r in valid):+.2f}%")
print(f"  最大回撤: {max(r['dd']for r in valid):.1f}%")

# 分布
print(f"\n  收益分布:")
bins = [(-30,-10),(-10,-5),(-5,0),(0,5),(5,10),(10,20),(20,50)]
for lo,hi in bins:
    cnt=sum(1 for r in valid if lo<=r["comp"]<hi)
    bar="█"*cnt
    print(f"  {lo:>+4}%~{hi:>+3}%: {cnt:>3}个 {bar}")

# 近12个月逐月
print(f"\n{'='*75}")
print(f"近12个30天窗口逐月")
print(f"{'='*75}")
print(f"{'窗口':<12} {'交易':>5} {'胜率':>7} {'复利':>9} {'回撤':>7}")
print(f"{'-'*45}")
for r in results[-12:]:
    flag="✅"if r["comp"]>0 else"❌"
    print(f"{flag} {r['start']:<8} {r['n']:>5} {r['wr']:>6.1f}% {r['comp']:>+8.2f}% {r['dd']:>6.1f}%")

# 20x/80% 收益估算
bal=37.54;lev=20;margin_pct=0.8
btc_=bars[-1]["c"];ct_val=btc_*0.01;ct=round(bal*margin_pct/(ct_val/lev)*100)/100
ntl=ct*ct_val
avg_comp=sum(r["comp"]for r in valid)/len(valid)
monthly=avg_comp/100*ntl
print(f"\n💰 20×/80%: {ct:.2f}张 ${ntl:.0f}名义 | 月均收益{avg_comp:+.2f}% = ${monthly:+.2f}/30天窗")
