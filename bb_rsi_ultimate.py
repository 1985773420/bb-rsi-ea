#!/usr/bin/env python3
"""终极回测: 最大历史数据 + 全周期 + 参数微调"""
import requests, math, time
from datetime import datetime, timezone

URL = "https://www.okx.com/api/v5/market/history-candles"
PROXY = "http://127.0.0.1:2080"
FEE = 0.0007

print("拉取最大历史数据...")
bars=[]
after=int(time.time()*1000);page=0
while page<200:
    try:
        r=requests.get(URL,params={"instId":"BTC-USDT","bar":"15m","limit":300,"after":str(after)},
                       proxies={"http":PROXY,"https":PROXY},timeout=30)
        data=r.json().get("data",[])
        if not data:break
        bars=[{"ts":int(row[0]),"c":float(row[4]),"h":float(row[2]),"l":float(row[3])} for row in data]+bars
        after=int(data[-1][0]);page+=1
        if page%20==0:print(f"  第{page}页 {len(bars)}根, {datetime.fromtimestamp(bars[0]['ts']/1000).strftime('%Y-%m')}")
        time.sleep(0.05)
    except:break
bars.sort(key=lambda x:x["ts"])
td=(bars[-1]["ts"]-bars[0]["ts"])/1000/86400
print(f"\n✅ {len(bars)}根 | {datetime.fromtimestamp(bars[0]['ts']/1000).strftime('%Y-%m-%d')}~{datetime.fromtimestamp(bars[-1]['ts']/1000).strftime('%Y-%m-%d')} | {td:.0f}天")

def calc(bars,bb_p,bb_s,rsi_p):
    cl=[b["c"]for b in bars];hi=[b["h"]for b in bars];lo=[b["l"]for b in bars];n=len(cl)
    bb_u,bb_l=[None]*n,[None]*n
    for i in range(bb_p-1,n):
        w=cl[i-bb_p+1:i+1];sma=sum(w)/bb_p;std=(sum((x-sma)**2 for x in w)/bb_p)**0.5
        bb_u[i]=sma+bb_s*std;bb_l[i]=sma-bb_s*std
    rs=[None]*n
    for i in range(rsi_p,n):
        g=sum(max(cl[j]-cl[j-1],0)for j in range(i-rsi_p+1,i+1))/rsi_p
        l=sum(max(cl[j-1]-cl[j],0)for j in range(i-rsi_p+1,i+1))/rsi_p
        rs[i]=100-100/(1+g/l)if l>0 else 100
    atr=[None]*n
    for i in range(14,n):
        tr=[max(hi[j]-lo[j],abs(hi[j]-cl[j-1]),abs(lo[j]-cl[j-1]))for j in range(i-13,i+1)]
        atr[i]=(sum(tr)/14)/cl[i]*100
    v=[v for v in atr if v is not None];am=sum(v)/len(v)if v else 0.1
    return bb_u,bb_l,rs,atr,am

def bt(bars,bb_p,bb_s,rsi_p,rsi_h,rsi_l,atr_f,tp,sl,max_b):
    bb_u,bb_l,rs,atr,am=calc(bars,bb_p,bb_s,rsi_p)
    trades=[];in_pos=None;ep=0;eb=0;eq=[1.0]
    mi=max(bb_p,rsi_p,14)+1;n=len(bars)
    for i in range(mi,n):
        c=bars[i]["c"]
        if in_pos:
            h=i-eb;pnl=(c-ep)/ep if in_pos=="long" else (ep-c)/ep
            if pnl>=tp:trades.append({"s":in_pos,"p":pnl-FEE,"r":"TP","ts":bars[i]["ts"]});eq.append(eq[-1]*(1+pnl-FEE));in_pos=None;continue
            if pnl<=-sl:trades.append({"s":in_pos,"p":pnl-FEE,"r":"SL","ts":bars[i]["ts"]});eq.append(eq[-1]*(1+pnl-FEE));in_pos=None;continue
            if h>=max_b:trades.append({"s":in_pos,"p":pnl-FEE,"r":"TO","ts":bars[i]["ts"]});eq.append(eq[-1]*(1+pnl-FEE));in_pos=None;continue
            continue
        sig=None;sig_bar=None
        for j in range(i-1,max(i-4,mi-1),-1):
            if bb_u[j] is None or rs[j] is None or atr[j] is None:continue
            if atr[j]<am*atr_f:continue
            cj=bars[j]["c"]
            if cj>bb_u[j] and rs[j]>rsi_h:sig="short";sig_bar=j;break
            elif cj<bb_l[j] and rs[j]<rsi_l:sig="long";sig_bar=j;break
        if not sig:continue
        ep=bars[sig_bar]["c"];in_pos=sig;eb=i
    if in_pos:
        c=bars[-1]["c"];pnl=(c-ep)/ep if in_pos=="long" else (ep-c)/ep
        trades.append({"s":in_pos,"p":pnl-FEE,"r":"OPEN","ts":bars[-1]["ts"]})
    return trades,eq

# ===== 当前最优参数全周期回测 =====
BB_P,BB_S,RSI_P=15,2,7
RSI_H,RSI_L,ATR_F=70,30,0.4
TP,SL,MAX_B=0.005,0.003,24

print(f"\n{'='*85}")
print(f"当前最优: BB({BB_P},{BB_S}) RSI{RSI_P}[{RSI_H}/{RSI_L}] x{ATR_F} TP{TP*100}% SL{SL*100}%")
print(f"{'='*85}")

all_trades,all_eq=bt(bars,BB_P,BB_S,RSI_P,RSI_H,RSI_L,ATR_F,TP,SL,MAX_B)
total_bars=len(bars)

for days,label in [(1,"1天"),(3,"3天"),(7,"7天"),(30,"1月"),(90,"3月"),(180,"半年"),(int(td),"全部")]:
    start=max(0,total_bars-days*96)
    trades,eq=bt(bars[start:],BB_P,BB_S,RSI_P,RSI_H,RSI_L,ATR_F,TP,SL,MAX_B)
    if not trades:continue
    wins=[t for t in trades if t["p"]>0];losses=[t for t in trades if t["p"]<=0]
    ec=1.0
    for t in trades:ec*=(1+t["p"])
    comp=(ec-1)*100;wr=len(wins)/len(trades)*100
    tp_n=sum(1 for t in trades if t["r"]=="TP");sl_n=sum(1 for t in trades if t["r"]=="SL")
    longs=sum(1 for t in trades if t["s"]=="long")
    avg_w=sum(t["p"]for t in wins)/len(wins)*100 if wins else 0
    avg_l=sum(t["p"]for t in losses)/len(losses)*100 if losses else 0
    
    dd_str=""
    if days>=30:
        peak=1.0;max_dd=0
        for v in eq:
            if v>peak:peak=v
            if peak-v>max_dd:max_dd=peak-v
    
    print(f"  {label:<6}: {len(trades):>4}笔 | 胜率{wr:.1f}% | 复利{comp:+7.2f}% | "
          f"多{longs}/空{len(trades)-longs} | TP{tp_n} SL{sl_n} | 均赢{avg_w:+.2f}% 均亏{avg_l:+.2f}%",end="")
    if days>=30:print(f" | 回撤{max_dd*100:.1f}%")
    else:print()

# 月度
print(f"\n{'='*85}")
print(f"月度盈亏")
print(f"{'='*85}")
monthly={}
for t in all_trades:
    m=datetime.fromtimestamp(t["ts"]/1000,tz=timezone.utc).strftime("%Y-%m")
    monthly[m]=monthly.get(m,0)+t["p"]
pos=sum(1 for v in monthly.values() if v>0)
print(f"{len(monthly)}个月, {pos}盈/{len(monthly)-pos}亏")
for m in sorted(monthly.keys()):
    bar="█"*int(abs(monthly[m]*100))
    print(f"  {m}: {monthly[m]*100:+6.2f}% {bar}")

# 各年
print(f"\n{'='*85}")
print(f"各年度")
print(f"{'='*85}")
for y in sorted(set(datetime.fromtimestamp(t["ts"]/1000,tz=timezone.utc).year for t in all_trades)):
    yt=[t for t in all_trades if datetime.fromtimestamp(t["ts"]/1000,tz=timezone.utc).year==y]
    if len(yt)<50:continue
    yw=[t for t in yt if t["p"]>0];yec=1.0
    for t in yt:yec*=(1+t["p"])
    print(f"  {y}: {len(yt)}笔 | 胜率{len(yw)/len(yt)*100:.1f}% | 复利{(yec-1)*100:+.2f}%")

# 最大连续亏损
consec=0;max_consec=0
for t in all_trades:
    if t["p"]<=0:consec+=1;max_consec=max(max_consec,consec)
    else:consec=0
print(f"\n最大连续亏损: {max_consec}笔")

# ===== 参数微调 =====
print(f"\n{'='*85}")
print(f"参数微调 (全量数据对比)")
print(f"{'='*85}")

# 基准
base_t,base_eq=bt(bars,15,2,7,70,30,0.4,0.005,0.003,24)
base_w=[t for t in base_t if t["p"]>0];base_ec=1.0
for t in base_t:base_ec*=(1+t["p"])
base=(base_ec-1)*100
print(f"  基准: {len(base_t)}笔 | 胜率{len(base_w)/len(base_t)*100:.1f}% | 复利{base:+7.2f}%")

variants=[
    ("BB12",12,2,7,70,30,0.4,0.005,0.003,24),
    ("BB20",20,2,7,70,30,0.4,0.005,0.003,24),
    ("RSI65/35",15,2,7,65,35,0.4,0.005,0.003,24),
    ("RSI75/25",15,2,7,75,25,0.4,0.005,0.003,24),
    ("RSI5",15,2,5,70,30,0.4,0.005,0.003,24),
    ("ATR0.3",15,2,7,70,30,0.3,0.005,0.003,24),
    ("ATR0.5",15,2,7,70,30,0.5,0.005,0.003,24),
    ("TP0.6/SL0.4",15,2,7,70,30,0.4,0.006,0.004,24),
    ("MAX16b",15,2,7,70,30,0.4,0.005,0.003,16),
    ("BB12+RSI65",12,2,7,65,35,0.4,0.005,0.003,24),
    ("BB12+ATR0.3",12,2,7,70,30,0.3,0.005,0.003,24),
]

best_label="基准";best_comp=base;best_n=len(base_t);best_wr=len(base_w)/len(base_t)*100

for label,bbp,bbs,rsip,rsih,rsil,atrf,tp,sl,maxb in variants:
    t,eq=bt(bars,bbp,bbs,rsip,rsih,rsil,atrf,tp,sl,maxb)
    if not t:continue
    w=[tt for tt in t if tt["p"]>0];ec=1.0
    for tt in t:ec*=(1+tt["p"])
    comp=(ec-1)*100;wr=len(w)/len(t)*100
    diff=comp-base
    flag="⬆" if diff>0 else "⬇" if diff<-1 else "="
    print(f"  {label:<18}: {len(t):>4}笔 | 胜率{wr:.1f}% | 复利{comp:+7.2f}% | {flag} {diff:+.1f}%")
    if comp>best_comp:best_label,best_comp,best_n,best_wr=label,comp,len(t),wr

print(f"\n🏆 基准: 复利{base:+.2f}% | {len(base_t)}笔 | 胜率{len(base_w)/len(base_t)*100:.1f}%")
if best_comp>base:
    print(f"🏆 更好: {best_label} | 复利{best_comp:+.2f}% | {best_n}笔 | 胜率{best_wr:.1f}%")
else:
    print(f"✅ 当前参数已是最优")

# 收益估算
bal=37.54;lev=10;btc_=bars[-1]["c"];ct_val=btc_*0.01;ct=max(0.01,round(bal*0.5/(ct_val/lev)*100)/100)
w_all=sum(1 for t in base_t if t["p"]>0);l_all=len(base_t)-w_all
aw=sum(t["p"]for t in base_t if t["p"]>0)/w_all if w_all else 0
al=sum(t["p"]for t in base_t if t["p"]<=0)/l_all if l_all else 0
profit=w_all*ct*ct_val*aw-l_all*ct*ct_val*abs(al)
print(f"\n💰 10x/50% {ct:.2f}张 | {len(base_t)}笔 | 总净利${profit:+.2f}")
