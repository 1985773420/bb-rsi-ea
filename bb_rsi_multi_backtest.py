#!/usr/bin/env python3
"""BB+RSI v2 多币种回测: BTC vs ETH vs SOL"""
import requests, math
from datetime import datetime, timezone

GATE_URL = "https://api.gateio.ws/api/v4/spot/candlesticks"
PROXY = "http://127.0.0.1:2080"
TP_PCT=0.005;SL_PCT=0.003;MAX_BARS=24;FEE=0.0007
BB_P=20;BB_S=2;RSI_P=10;RSI_H=65;RSI_L=35;ATR_F=0.6

COINS = [
    {"name": "BTC", "symbol": "BTC_USDT", "price": 77900, "ct_val": 0.01, "ct_ccy": "BTC"},
    {"name": "ETH", "symbol": "ETH_USDT", "price": 2600, "ct_val": 0.1, "ct_ccy": "ETH"},
    {"name": "SOL", "symbol": "SOL_USDT", "price": 140, "ct_val": 10, "ct_ccy": "SOL"},
]

def fetch_bars(symbol, n=2000):
    bars=[]
    for _ in range(4):
        to=bars[0]["ts"] if bars else None
        p={"currency_pair":symbol,"interval":"15m","limit":1000}
        if to:p["to"]=to
        try:
            r=requests.get(GATE_URL,params=p,proxies={"http":PROXY,"https":PROXY},timeout=30)
            d=r.json()
            if not d:break
            c=[{"ts":int(row[0]),"c":float(row[2]),"h":float(row[3]),"l":float(row[4])} for row in d]
            if bars:c=[b for b in c if b["ts"]<bars[0]["ts"]]
            bars=c+bars
            if len(bars)>=n:break
        except:break
    bars.sort(key=lambda x:x["ts"])
    return bars

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

def bt(bars):
    bb_u,bb_l,rs,atr,am=calc(bars)
    trades=[];in_pos=None;ep=0;eb=0;eq=[1.0]
    mi=max(BB_P,RSI_P,14)+1;n=len(bars)
    for i in range(mi,n):
        if in_pos:
            h=i-eb;c=bars[i]["c"];pnl=(c-ep)/ep if in_pos=="long" else (ep-c)/ep
            if pnl>=TP_PCT:
                trades.append({"s":in_pos,"pnl":pnl-FEE,"r":"TP"})
                eq.append(eq[-1]*(1+pnl-FEE));in_pos=None;continue
            if pnl<=-SL_PCT:
                trades.append({"s":in_pos,"pnl":pnl-FEE,"r":"SL"})
                eq.append(eq[-1]*(1+pnl-FEE));in_pos=None;continue
            if h>=MAX_BARS:
                trades.append({"s":in_pos,"pnl":pnl-FEE,"r":"TO"})
                eq.append(eq[-1]*(1+pnl-FEE));in_pos=None;continue
            continue
        sig=None
        for j in range(i-1,max(i-4,mi-1),-1):
            if bb_u[j] is None or rs[j] is None or atr[j] is None:continue
            if atr[j]<am*ATR_F:continue
            cj=bars[j]["c"]
            if cj>bb_u[j] and rs[j]>RSI_H:sig="short";ep=cj;break
            elif cj<bb_l[j] and rs[j]<RSI_L:sig="long";ep=cj;break
        if sig:in_pos=sig;eb=i
    if in_pos:
        c=bars[-1]["c"];pnl=(c-ep)/ep if in_pos=="long" else (ep-c)/ep
        trades.append({"s":in_pos,"pnl":pnl-FEE,"r":"OPEN"})
    return trades,eq

def main():
    print("="*90)
    print("BB+RSI v2 多币种回测 (TP0.5/SL0.3/ATR0.6/近3K线)")
    print("="*90)
    
    balance=37.54;leverage=5
    
    results={}
    for coin in COINS:
        name=coin["name"];sym=coin["symbol"];price=coin["price"]
        ct_val=coin["ct_val"];ct_ccy=coin["ct_ccy"]
        
        print(f"\n{'='*90}")
        print(f"  {name} — 拉取数据中...")
        
        bars=fetch_bars(sym,2000)
        if len(bars)<500:
            print(f"  ❌ 数据不足: {len(bars)}根");continue
        
        total=len(bars)
        
        # 计算合约参数
        contract_notional = ct_val * price  # USD per contract
        margin_per = contract_notional / leverage
        
        periods={}
        for days in [7,14,30]:
            start=max(0,total-days*96)
            periods[days]=bars[start:]
        
        print(f"  {total}根K线 | {datetime.fromtimestamp(bars[0]['ts']).strftime('%m-%d %H:%M')} ~ {datetime.fromtimestamp(bars[-1]['ts']).strftime('%m-%d %H:%M')}")
        print(f"  现价: ${price:,.0f} | 合约面值: {ct_val} {ct_ccy} = ${contract_notional:,.0f}/张 | 保证金: ${margin_per:,.0f}/张")
        
        row={}
        for days,pb in periods.items():
            trades,eq=bt(pb)
            if not trades:row[days]={"n":0,"comp":0,"wr":0,"daily":0};continue
            wins=[t for t in trades if t["pnl"]>0];losses=[t for t in trades if t["pnl"]<=0]
            comp=(eq[-1]-1)*100
            tp_n=sum(1 for t in trades if t["r"]=="TP");sl_n=sum(1 for t in trades if t["r"]=="SL")
            to_n=sum(1 for t in trades if t["r"]=="TO")
            avg_w=sum(t["pnl"]for t in wins)/len(wins)*100 if wins else 0
            avg_l=sum(t["pnl"]for t in losses)/len(losses)*100 if losses else 0
            print(f"  {days}天: {len(trades):>3}笔 | 胜率{len(wins)/len(trades)*100:.1f}% | 复利{comp:+7.2f}% | "
                  f"多{sum(1 for t in trades if t['s']=='long'):>2}/空{sum(1 for t in trades if t['s']=='short'):>2} | "
                  f"TP{tp_n} SL{sl_n} TO{to_n} | 均赢{avg_w:+.2f}% 均亏{avg_l:+.2f}%")
            row[days]={"n":len(trades),"comp":comp,"wr":len(wins)/len(trades)*100,"daily":len(trades)/days}
        
        # $37.54账户收益估算
        trades30,_=bt(periods[30])
        wins30=sum(1 for t in trades30 if t["pnl"]>0);losses30=len(trades30)-wins30
        avg_w30=sum(t["pnl"]for t in trades30 if t["pnl"]>0)/wins30 if wins30 else 0
        avg_l30=sum(t["pnl"]for t in trades30 if t["pnl"]<=0)/losses30 if losses30 else 0
        
        # 最大可开张数
        max_ct = round(balance / margin_per, 4)
        # 推荐用30%保证金
        rec_ct = round(balance * 0.3 / margin_per, 4)
        rec_notional = rec_ct * contract_notional
        
        row["coin"]=coin
        row["trades30"]=trades30
        row["max_ct"]=max_ct
        row["rec_ct"]=rec_ct
        row["notional"]=contract_notional
        
        profit30 = wins30 * rec_ct * contract_notional * avg_w30 - losses30 * rec_ct * contract_notional * abs(avg_l30)
        
        print(f"\n  💰 $37.54账户: 最多{max_ct:.2f}张 | 推荐{rec_ct:.2f}张(${rec_notional:.0f}名义,30%保证金)")
        print(f"  📈 30天预估净利润: ${profit30:+.2f} ({profit30/balance*100:+.1f}%)")
        
        results[name]=row
    
    # 汇总
    print(f"\n\n{'='*90}")
    print(f"📊 三币种对比 (30天)")
    print(f"{'='*90}")
    print(f"{'币种':<6} {'现价':>8} {'合约面值':>10} {'30天交易':>8} {'胜率':>7} {'复利':>9} {'日频':>6} {'推荐张':>7} {'30天净利':>10}")
    print("-"*85)
    for name,row in results.items():
        r=row[30];c=row["coin"]
        print(f"{name:<6} ${c['price']:>7,.0f} ${row['notional']:>8,.0f} {r['n']:>8} {r['wr']:>6.1f}% {r['comp']:>+8.2f}% {r['daily']:>5.1f} {row['rec_ct']:>6.3f} ${row.get('profit','?'):>9}")

if __name__=="__main__":
    main()
