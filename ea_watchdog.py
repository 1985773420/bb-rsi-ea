#!/usr/bin/env python3
"""看门狗 v6: 简洁可靠版"""
import subprocess, time, os, signal
from datetime import datetime

WS_SCRIPT = "/root/.hermes/scripts/bb_rsi_ws_ea.py"
DASH_SCRIPT = "/root/.hermes/scripts/bb_rsi_dashboard.py"
PYTHON = "/root/.hermes/hermes-agent/venv/bin/python3"
CHECK_INTERVAL = 30
GRACE_PERIOD = 120  # EA启动后120秒内不检查

def log(msg):
    print(f"[{datetime.now().strftime('%H:%M:%S')}] {msg}", flush=True)

def kill_proc(proc):
    try: os.killpg(os.getpgid(proc.pid), signal.SIGKILL)
    except:
        try: proc.kill()
        except: pass

def main():
    ws_proc = None
    dash_proc = None
    ws_start = 0
    log("看门狗 v6 启动")

    while True:
        # EA检查：进程死了就重启
        need_restart = False
        if ws_proc is None:
            need_restart = True
        elif ws_proc.poll() is not None:
            log(f"EA 退出(rc={ws_proc.returncode})，重启")
            need_restart = True

        if need_restart:
            ws_proc = subprocess.Popen([PYTHON, "-u", WS_SCRIPT], preexec_fn=os.setsid)
            ws_start = time.time()
            log(f"EA PID={ws_proc.pid}")

        # Dashboard
        if dash_proc is None or dash_proc.poll() is not None:
            if dash_proc: log("Dashboard退出，重启")
            dash_proc = subprocess.Popen([PYTHON, "-u", DASH_SCRIPT])
            log(f"DB PID={dash_proc.pid}")

        time.sleep(CHECK_INTERVAL)

if __name__ == "__main__":
    main()