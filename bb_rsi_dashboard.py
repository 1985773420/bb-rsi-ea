#!/usr/bin/env python3
"""交易仪表盘 + 回测展示 — 轻量HTTP服务器"""
import json, os, time, threading
from datetime import datetime
from http.server import HTTPServer, BaseHTTPRequestHandler

STATE_FILE = "/tmp/bb_rsi_state.json"
BACKTEST_FILE = "/tmp/bb_rsi_backtest_results.json"
PORT = 8899

# 默认状态
default_state = {
    "status": "initializing",
    "balance": 0, "equity": 0,
    "position": None,
    "trades": [],
    "ws_connected": False,
    "ws_last_heartbeat": None,
    "daily_pnl": 0,
    "protections": {"max_daily_loss": -0.15, "cooldown": False},
    "updated": datetime.now().isoformat()
}

default_backtest = {
    "last_update": "未运行",
    "full_period": {},
    "periods": {},
    "weekly_pnl": [],
    "monthly_pnl": []
}

def read_state():
    try:
        with open(STATE_FILE) as f:
            return json.load(f)
    except:
        return dict(default_state)

def read_backtest():
    try:
        with open(BACKTEST_FILE) as f:
            return json.load(f)
    except:
        return dict(default_backtest)

if not os.path.exists(STATE_FILE):
    with open(STATE_FILE, "w") as f:
        json.dump(default_state, f)
if not os.path.exists(BACKTEST_FILE):
    with open(BACKTEST_FILE, "w") as f:
        json.dump(default_backtest, f)

class Handler(BaseHTTPRequestHandler):
    def do_GET(self):
        if self.path == "/api/state":
            self.send_response(200)
            self.send_header("Content-Type", "application/json")
            self.end_headers()
            self.wfile.write(json.dumps(read_state()).encode())
            return

        if self.path == "/api/backtest":
            self.send_response(200)
            self.send_header("Content-Type", "application/json")
            self.end_headers()
            self.wfile.write(json.dumps(read_backtest()).encode())
            return

        if self.path == "/" or self.path == "/index.html":
            state = read_state()
            bt = read_backtest()
            pos = state.get("position")
            trades = state.get("trades", [])[-20:]

            pos_html = ""
            if pos:
                color = "#4caf50" if (pos.get("pnl_pct") or 0) > 0 else "#f44336"
                pos_html = f"""
                <div class="card">
                    <h3>📌 当前持仓</h3>
                    <div class="pos-row">
                        <span>{'🔴 做空' if pos['side']=='short' else '🟢 做多'} {pos['size']}张</span>
                        <span>入场 {pos['entry_px']:.0f}</span>
                        <span style="color:{color}">盈亏 {pos.get('pnl_pct',0):+.2f}% (${pos.get('pnl',0):+.2f})</span>
                    </div>
                </div>"""

            trade_rows = ""
            for t in reversed(trades):
                c = "#4caf50" if t["pnl"] > 0 else "#f44336"
                trade_rows += f"<tr><td>{t['time']}</td><td>{t['side']}</td><td style='color:{c}'>{t['pnl']*100:+.2f}%</td><td>{t['reason']}</td></tr>"

            # 回测数据
            full = bt.get("full_period", {})
            periods = bt.get("periods", {})
            weekly = bt.get("weekly_pnl", [])
            monthly = bt.get("monthly_pnl", [])
            last_update = bt.get("last_update", "未运行")

            full_html = ""
            if full:
                full_html = f"""
                <div class="card">
                    <h3>📊 全历史回测</h3>
                    <div class="stat"><span class="label">回测时间</span><span class="value">{full.get('date_range','—')}</span></div>
                    <div class="stat"><span class="label">总交易</span><span class="value">{full.get('total_trades',0)}笔</span></div>
                    <div class="stat"><span class="label">胜率</span><span class="value">{full.get('win_rate',0):.1f}%</span></div>
                    <div class="stat"><span class="label">总收益</span><span class="value green">{full.get('total_return',0):+.2f}%</span></div>
                    <div class="stat"><span class="label">最大回撤</span><span class="value red">{full.get('max_drawdown',0):.2f}%</span></div>
                    <div class="stat"><span class="label">盈亏比</span><span class="value">{full.get('profit_loss_ratio',0):.2f}</span></div>
                    <div class="stat"><span class="label">平均盈利</span><span class="value green">{full.get('avg_win',0):+.2f}%</span></div>
                    <div class="stat"><span class="label">平均亏损</span><span class="value red">{full.get('avg_loss',0):+.2f}%</span></div>
                </div>"""

            periods_html = ""
            if periods:
                rows = ""
                for label, p in periods.items():
                    ret_color = "#4caf50" if p.get("total_return",0) > 0 else "#f44336"
                    rows += f"""<tr>
                        <td>{label}</td>
                        <td>{p.get('total_trades',0)}</td>
                        <td>{p.get('win_rate',0):.1f}%</td>
                        <td style="color:{ret_color}">{p.get('total_return',0):+.2f}%</td>
                        <td style="color:#f44336">{p.get('max_drawdown',0):.2f}%</td>
                        <td>{p.get('profit_loss_ratio',0):.2f}</td>
                    </tr>"""
                periods_html = f"""
                <div class="card">
                    <h3>📈 分周期回测</h3>
                    <table>
                        <tr><th>周期</th><th>交易数</th><th>胜率</th><th>总收益</th><th>最大回撤</th><th>盈亏比</th></tr>
                        {rows}
                    </table>
                </div>"""

            weekly_html = ""
            if weekly:
                rows = ""
                for w in weekly[-8:]:
                    c = "#4caf50" if w.get("pnl",0) > 0 else "#f44336"
                    rows += f"<tr><td>{w.get('week','—')}</td><td style='color:{c}'>{w.get('pnl',0)*100:+.2f}%</td><td>{w.get('trades',0)}</td></tr>"
                weekly_html = f"""
                <div class="card">
                    <h3>📅 近8周盈亏</h3>
                    <table>
                        <tr><th>周</th><th>盈亏</th><th>交易数</th></tr>
                        {rows}
                    </table>
                </div>"""

            monthly_html = ""
            if monthly:
                rows = ""
                for m in monthly[-6:]:
                    c = "#4caf50" if m.get("pnl",0) > 0 else "#f44336"
                    rows += f"<tr><td>{m.get('month','—')}</td><td style='color:{c}'>{m.get('pnl',0)*100:+.2f}%</td><td>{m.get('trades',0)}</td></tr>"
                monthly_html = f"""
                <div class="card">
                    <h3>📅 近6月盈亏</h3>
                    <table>
                        <tr><th>月</th><th>盈亏</th><th>交易数</th></tr>
                        {rows}
                    </table>
                </div>"""

            html = f"""<!DOCTYPE html>
<html><head><meta charset="utf-8"><meta http-equiv="refresh" content="5">
<title>BB+RSI EA Dashboard</title>
<style>
*{{margin:0;padding:0;box-sizing:border-box}}
body{{background:#f5f7fa;color:#24292e;font-family:-apple-system,BlinkMacSystemFont,'Segoe UI',monospace;padding:20px}}
h1{{color:#0366d6;margin-bottom:20px;font-size:22px}}
.grid{{display:grid;grid-template-columns:repeat(auto-fit,minmax(280px,1fr));gap:16px}}
.card{{background:#ffffff;border:1px solid #e1e4e8;border-radius:8px;padding:16px;box-shadow:0 1px 3px rgba(0,0,0,0.08)}}
.card h3{{color:#0366d6;margin-bottom:12px;font-size:14px}}
.stat{{display:flex;justify-content:space-between;padding:4px 0;font-size:13px}}
.stat .label{{color:#586069}}.stat .value{{font-weight:bold;color:#24292e}}
.green{{color:#28a745}}.red{{color:#d73a49}}.yellow{{color:#dbab09}}
.pos-row{{display:flex;justify-content:space-between;padding:8px 0;font-size:14px}}
table{{width:100%;border-collapse:collapse;font-size:12px}}
th,td{{padding:6px 8px;text-align:left;border-bottom:1px solid #e1e4e8}}
th{{color:#586069;background:#f6f8fa}}
.status-dot{{display:inline-block;width:8px;height:8px;border-radius:50%;margin-right:6px}}
.status-ok{{background:#28a745}}.status-err{{background:#d73a49}}
.section-title{{color:#0366d6;font-size:16px;margin:20px 0 10px;border-bottom:2px solid #0366d6;padding-bottom:6px}}
</style></head><body>
<h1>🤖 BB+RSI EA Dashboard</h1>

<div class="section-title">⚡ 实盘状态</div>
<div class="grid">
    <div class="card">
        <h3>💰 账户</h3>
        <div class="stat"><span class="label">余额</span><span class="value">${state['balance']:.2f}</span></div>
        <div class="stat"><span class="label">权益</span><span class="value">${state.get('equity',state['balance']):.2f}</span></div>
        <div class="stat"><span class="label">当日盈亏</span><span class="value {'green' if state.get('daily_pnl',0)>0 else 'red'}">${state.get('daily_pnl',0):+.2f}</span></div>
    </div>
    <div class="card">
        <h3>📡 连接</h3>
        <div class="stat"><span class="label">WebSocket</span><span class="value"><span class="status-dot {'status-ok' if state.get('ws_connected') else 'status-err'}"></span>{'已连接' if state.get('ws_connected') else '断开'}</span></div>
        <div class="stat"><span class="label">最后心跳</span><span class="value">{state.get('ws_last_heartbeat','—')}</span></div>
        <div class="stat"><span class="label">保护状态</span><span class="value {'yellow' if state.get('protections',{}).get('cooldown') else 'green'}">{'冷却中' if state.get('protections',{}).get('cooldown') else '正常'}</span></div>
    </div>
    {pos_html}
</div>

<div class="card" style="margin-top:16px">
    <h3>📋 最近交易 ({len(trades)}笔)</h3>
    <table>
        <tr><th>时间</th><th>方向</th><th>盈亏</th><th>原因</th></tr>
        {trade_rows}
    </table>
</div>

<div class="section-title">📊 回测数据 (更新: {last_update})</div>
<div class="grid">
    {full_html}
    {periods_html}
</div>
<div class="grid">
    {weekly_html}
    {monthly_html}
</div>

<div style="margin-top:16px;color:#586069;font-size:11px">
    更新: {state.get('updated','—')} | 自动刷新 5s | 回测每周一自动更新 | 保护: 日亏>{abs(state.get('protections',{}).get('max_daily_loss',0.15))*100:.0f}%触发冷却
</div>
</body></html>"""

            self.send_response(200)
            self.send_header("Content-Type", "text/html; charset=utf-8")
            self.end_headers()
            self.wfile.write(html.encode())
            return

        self.send_response(404); self.end_headers()

def start_server():
    server = HTTPServer(("0.0.0.0", PORT), Handler)
    print(f"[Dashboard] http://0.0.0.0:{PORT}")
    server.serve_forever()

if __name__ == "__main__":
    start_server()