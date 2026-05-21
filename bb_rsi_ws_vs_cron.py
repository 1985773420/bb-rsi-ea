#!/usr/bin/env python3
"""WS vs Cron 回测: 模拟入场时间差"""
import requests, math, time
from datetime import datetime, timezone, timedelta

URL = "https://www.okx.com/api/v5/market/history-candles"
PROXY = "http://127.0.0.1:2080"
TP=0.005;SL=0.003;MAX_BARS=24;FEE=0.0007
BB_P=20;BB_S=2;RSI_P=10;RSI_H=65;RSI_L=35;ATR_F=0.6
BAL=37.54;LEV=10

def fetch(inst="BTC-USDT", days=180):
    target=days*96;bars=[];after=int(time.time()*1000)
    while len(bars)<target:
        try:
            r=requests.get(URL,params={"instId":inst,"bar":"15m","limit":300,"after":str(after)},
                          proxies={"http":PROXY,"https":PROXY},timeout=30)
            data=r.json().get("data",[]); 
            if not data:break
            bars=[{"ts":int(row[0]),"c":float(row[4]),"h":float(row[2]),"l":float(row[3])} for row in data]+bars
            after=int(data[-1][0]);time.sleep(0.1)
        except:break
    bars.sort(key=lambda x:x["ts"]);return bars

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
    v=[v for v in atr if v is not None];am=sum(v)/len(v)if v else 0.35
    return bb_u,bb_l,rs,atr,am

def bt(bars, mode="ws"):
    """mode: ws=信号K收盘入场, cron=下一个cron触发点入场(延迟0~14分钟)"""
    bb_u,bb_l,rs,atr,am=calc(bars)
    trades=[];in_pos=None;ep=0;eb=0;eq=[1.0]
    mi=max(BB_P,RSI_P,14)+1;n=len(bars)
    
    for i in range(mi,n):
        c=bars[i]["c"]
        if in_pos:
            h=i-eb;pnl=(c-ep)/ep if in_pos=="long" else (ep-c)/ep
            if pnl>=TP:trades.append({"s":in_pos,"pnl":pnl-FEE,"r":"TP"});eq.append(eq[-1]*(1+pnl-FEE));in_pos=None;continue
            if pnl<=-SL:trades.append({"s":in_pos,"pnl":pnl-FEE,"r":"SL"});eq.append(eq[-1]*(1+pnl-FEE));in_pos=None;continue
            if h>=MAX_BARS:trades.append({"s":in_pos,"pnl":pnl-FEE,"r":"TO"});eq.append(eq[-1]*(1+pnl-FEE));in_pos=None;continue
            continue
        
        # 扫描信号
        sig=None;sig_bar=None
        for j in range(i-1,max(i-4,mi-1),-1):
            if bb_u[j] is None or rs[j] is None or atr[j] is None:continue
            if atr[j]<am*ATR_F:continue
            cj=bars[j]["c"]
            if cj>bb_u[j] and rs[j]>RSI_H:sig="short";sig_bar=j;break
            elif cj<bb_l[j] and rs[j]<RSI_L:sig="long";sig_bar=j;break
        if not sig:continue
        
        if mode=="ws":
            # WS: 信号K线收盘价入场
            ep=bars[sig_bar]["c"]
        else:
            # Cron: 模拟延迟——入场上限15分钟后的K线收盘价
            # cron每15分钟触发一次，平均延迟7.5分钟
            # 最坏情况: 下根K线(t+15min)，最好: 当前K(t+0)
            # 取平均值: 延迟1根K线
            ep=bars[min(sig_bar+1, n-1)]["c"]
        
        in_pos=sig;eb=i
    
    if in_pos:
        c=bars[-1]["c"];pnl=(c-ep)/ep if in_pos=="long" else (ep-c)/ep
        trades.append({"s":in_pos,"pnl":pnl-FEE,"r":"OPEN"})
    return trades,eq

def main():
    print("="*75)
    print("WS vs Cron 入场时机回测")
    print("="*75)
    
    bars=fetch("BTC-USDT", 180)
    if len(bars)<500:print("数据不足");return
    print(f"\n✅ {len(bars)}根 | {datetime.fromtimestamp(bars[0]['ts']/1000).strftime('%Y-%m-%d')} ~ {datetime.fromtimestamp(bars[-1]['ts']/1000).strftime('%Y-%m-%d')}")
    
    for mode,label in [("ws","WS(信号K收盘)"), ("cron","Cron(延迟1K)")]:
        results={}
        for days in [30,60,90,180]:
            start=max(0,len(bars)-days*96)
            trades,eq=bt(bars[start:],mode)
            if not trades:continue
            wins=[t for t in trades if t["pnl"]>0]
            comp=(eq[-1]-1)*100
            results[days]={"n":len(trades),"wr":len(wins)/len(trades)*100,"comp":comp}
        
        print(f"\n{'='*75}")
        print(f"  {label}")
        for days in [30,60,90,180]:
            r=results[days]
            print(f"  {days}天: {r['n']:>4}笔 | 胜率{r['wr']:.1f}% | 复利{r['comp']:+7.2f}%")
        
        # 核心对比: 找同信号不同入场价的交易对
        tws,_=bt(bars,mode="ws")
        tcron,_=bt(bars,mode="cron")
        n=min(len(tws),len(tcron))
        slippage=0
        for i in range(n):
            slippage+=tws[i]["pnl"]-tcron[i]["pnl"]
        print(f"  累计滑点: {slippage*100:+.2f}%")
    
    # 汇总
    print(f"\n{'='*75}")
    print(f"汇总: 180天")
    for mode,label in [("ws","WS "),("cron","Cron")]:
        trades,_=bt(bars,mode)
        wins=[t for t in trades if t["pnl"]>0]
        comp=(1.0,);ec=1.0
        for t in trades:ec*=(1+t["pnl"])
        print(f"  {label}: {len(trades)}笔 | 胜率{len(wins)/len(trades)*100:.1f}% | 复利{(ec-1)*100:+.2f}%")

if __name__=="__main__":
    main()
