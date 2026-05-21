#!/usr/bin/env python3
"""动态杠杆 ≤20x — 按天回测 + 7天/30天汇总"""
import requests, math, time
from datetime import datetime, timezone

URL = "https://www.okx.com/api/v5/market/history-candles"
PROXY = "http://127.0.0.1:2080"
FEE=0.0007;BB_P=20;BB_S=2;RSI_P=7;RSI_H=70;RSI_L=30;ATR_F=0.5
TP=0.005;SL=0.003;MAX_B=24;BAL=37.54;btc=78000;ct_val=btc*0.01

def get_params(bal):
    if bal>750:return 10,0.5
    if bal>200:return 15,0.5
    if bal>50:return 20,0.6
    return 20,0.5

print("拉取全量数据...")
bars=[];after=int(time.time()*1000);p=0
while p<350:
    r=requests.get(URL,params={"instId":"BTC-USDT","bar":"15m","limit":300,"after":str(after)},
                   proxies={"http":PROXY,"https":PROXY},timeout=30)
    data=r.json().get("data",[])
    if not data:break
    bars=[{"ts":int(row[0]),"c":float(row[4]),"h":float(row[2]),"l":float(row[3])} for row in data]+bars
    after=int(data[-1][0]);p+=1;time.sleep(0.02)
bars.sort(key=lambda x:x["ts"])
print(f"{len(bars)}根")

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
            if pnl>=TP:trades.append({"p":pnl-FEE,"r":"TP","ts":bars[i]["ts"]});eq.append(eq[-1]*(1+pnl-FEE));in_pos=None;continue
            if pnl<=-SL:trades.append({"p":pnl-FEE,"r":"SL","ts":bars[i]["ts"]});eq.append(eq[-1]*(1+pnl-FEE));in_pos=None;continue
            if h>=MAX_B:trades.append({"p":pnl-FEE,"r":"TO","ts":bars[i]["ts"]});eq.append(eq[-1]*(1+pnl-FEE));in_pos=None;continue
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
        trades.append({"p":pnl-FEE,"r":"OPEN","ts":bars[-1]["ts"]})
    return trades,eq

print("跑全量...")
all_trades,_=bt(bars)

# 按天分组
daily={}
for t in all_trades:
    day=datetime.fromtimestamp(t["ts"]/1000,tz=timezone.utc).strftime("%Y-%m-%d")
    if day not in daily:daily[day]=[]
    daily[day].append(t)

days=sorted(daily.keys())
day_returns=[(d,sum(t["p"]for t in daily[d])) for d in days]

# 按天模拟动态杠杆
bal=BAL;losing=0;peak=bal;history=[]
last_week=None;weekly_loss_flag=False

for d,ret in day_returns:
    wk=datetime.strptime(d,"%Y-%m-%d").strftime("%Y-W%W")
    
    # 周度连亏追踪
    if wk!=last_week:
        if last_week is not None:
            week_pnl=sum(r[1]for r in day_returns if r[0].startswith(last_week[:4]) and datetime.strptime(r[0],"%Y-%m-%d").strftime("%Y-W%W")==last_week)
            if week_pnl<=0:losing+=1
            else:losing=0
        last_week=wk
    
    lev,margin=get_params(bal)
    if losing>=3:margin*=0.5
    
    ct=max(0.01,round(bal*margin/(ct_val/lev)*100)/100)
    ntl=ct*ct_val
    start=bal
    pnl_d=ret*ntl;bal+=pnl_d
    if bal<0:bal=0.01
    if bal>peak:peak=bal
    
    history.append((d,ret*100,lev,margin,ct,ntl,start,pnl_d,bal,losing>=3))

# 输出
print(f"\n全量 {len(days)} 天 | 起始${BAL:.2f} → 期末${bal:.2f} ({bal/BAL:.1f}×) | 峰值${peak:.0f}")

# 最近30天
print(f"\n{'='*85}")
print(f"最近30天逐日明细")
print(f"{'='*85}")
print(f"{'日期':<12} {'盈亏%':>7} {'杠杆':>4} {'仓位%':>6} {'张':>6} {'起始$':>8} {'盈亏$':>8} {'期末$':>8} {'半仓':>4}")
print(f"{'-'*80}")
for r in history[-30:]:
    d,ret,lev,margin,ct,ntl,start,pnl,end,losing_flag=r
    flag="✅"if ret>0 else"❌"if ret<-0.5 else"▫️"
    half="半"if losing_flag else""
    print(f"{flag}{d:<10} {ret:>+6.2f}% {lev:>3}x {half}{margin*100:>5.0f}% {ct:>5.2f} ${start:>7.2f} ${pnl:>+7.2f} ${end:>7.2f} {'半' if losing_flag else '':>4}")

# 最近7天 & 30天汇总
print(f"\n{'='*85}")
print(f"滚动窗口汇总")
print(f"{'='*85}")
for wsize,label in [(7,"7天"),(30,"30天")]:
    recent=history[-wsize:]
    total_pnl=sum(r[5]for r in recent)  # pnl_d
    total_ret_pct=(history[-1][8]/history[-wsize][6]-1)*100
    wins=sum(1 for r in recent if r[1]>0)
    print(f"\n  {label}: {wins}/{len(recent)}天盈利 | 总盈亏${total_pnl:+.2f} | 回报{total_ret_pct:+.1f}%")
    print(f"    杠杆: {history[-1][2]}x | 当前余额${history[-1][8]:.2f}")

# 里程碑天数
print(f"\n里程碑天数:")
for target in [1.5,2,3,5,10]:
    for r in history:
        if r[8]>=BAL*target:
            print(f"  {target}× ({BAL*target:.0f}$): 第{history.index(r)+1}天 {r[0]} ${r[8]:.0f}")
            break

print(f"\n最终: {len(days)}天 ${bal:.2f} ({bal/BAL:.1f}×)")
