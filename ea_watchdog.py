#!/usr/bin/env python3
"""看门狗 v5: 监控 EA (v6 REST版) + Dashboard"""
import subprocess, time, os, signal
from datetime import datetime

WS_SCRIPT = "/root/.hermes/scripts/bb_rsi_ws_ea.py"
DASH_SCRIPT = "/root/.hermes/scripts/bb_rsi_dashboard.py"
PYTHON = "/root/.hermes/hermes-agent/venv/bin/python3"
STATE_FILE = "/tmp/bb_rsi_state.json"
CHECK_INTERVAL = 30

def log(msg):
    print(f"[{datetime.now().strftime('%H:%M:%S')}] {msg}", flush=True)

def kill_proc(proc):
    try: os.killpg(os.getpgid(proc.pid), signal.SIGKILL)
    except:
        try: proc.kill()
        except: pass

def is_ea_alive(proc):
    """检查EA进程是否存活"""
    if proc is None: return False
    if proc.poll() is not None: return False
    # 额外检查：状态文件是否在1分钟内更新过
    try:
        import json
        with open(STATE_FILE) as f:
            state = json.load(f)
        updated = state.get("updated", "")
        if updated:
            now = datetime.now()
            h,m,s = updated.split(":")
            st = now.replace(hour=int(h), minute=int(m), second=int(s))
            if (now - st).total_seconds() > 120:
                return False
    except:
        pass
    return True

def main():
    ws_proc = None
    dash_proc = None
    log("看门狗 v5 启动 (EA=REST实时版)")

    while True:
        if not is_ea_alive(ws_proc):
            if ws_proc:
                rc = ws_proc.poll()
                log(f"EA 异常(rc={rc})，重启...")
                kill_proc(ws_proc)
            ws_proc = subprocess.Popen([PYTHON, "-u", WS_SCRIPT], preexec_fn=os.setsid)
            log(f"EA PID={ws_proc.pid}")

        if dash_proc is None or dash_proc.poll() is not None:
            if dash_proc:
                log(f"Dashboard 退出，重启...")
            dash_proc = subprocess.Popen([PYTHON, "-u", DASH_SCRIPT])
            log(f"Dashboard PID={dash_proc.pid}")

        time.sleep(CHECK_INTERVAL)

if __name__ == "__main__":
    main()