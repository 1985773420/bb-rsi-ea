"""
数据存储模块 — SQLite 持久化
数据库文件: /var/lib/bb_rsi/data.db
表: btc_swap_15m (ts INT PRIMARY KEY, open REAL, high REAL, low REAL, close REAL)
"""
import sqlite3, os, time, threading
from datetime import datetime

DB_PATH = "/var/lib/bb_rsi/data.db"
TABLE = "btc_swap_15m"

def _now():
    return datetime.now().strftime("%H:%M:%S.%f")[:12]

def _get_conn():
    """获取数据库连接"""
    os.makedirs(os.path.dirname(DB_PATH), exist_ok=True)
    conn = sqlite3.connect(DB_PATH)
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute("PRAGMA synchronous=NORMAL")
    conn.execute("PRAGMA cache_size=-8000")  # 8MB cache
    return conn

def init_db():
    """初始化数据库"""
    conn = _get_conn()
    conn.execute("""
        CREATE TABLE IF NOT EXISTS btc_swap_15m (
            ts INTEGER PRIMARY KEY,
            open REAL NOT NULL,
            high REAL NOT NULL,
            low REAL NOT NULL,
            close REAL NOT NULL
        )
    """)
    conn.execute("CREATE INDEX IF NOT EXISTS idx_ts ON btc_swap_15m(ts)")
    conn.commit()
    conn.close()
    print(f"[DB] 数据库初始化完成: {DB_PATH}", flush=True)

def insert_candles(bars):
    """
    批量插入蜡烛数据，重复ts自动跳过
    bars: [(ts, open, high, low, close), ...] 或 [{ts:,o:,h:,l:,c:}, ...]
    返回新增条数
    """
    if not bars:
        return 0
    conn = _get_conn()
    count = 0
    if isinstance(bars[0], dict):
        rows = [(b["ts"], b["o"], b["h"], b["l"], b["c"]) for b in bars]
    else:
        rows = [(int(r[0]), float(r[1]), float(r[2]), float(r[3]), float(r[4])) for r in bars]
    conn.execute("BEGIN")
    for ts, o, h, l, c in rows:
        try:
            conn.execute(
                "INSERT INTO btc_swap_15m(ts,open,high,low,close) VALUES(?,?,?,?,?)",
                (ts, o, h, l, c)
            )
            count += 1
        except sqlite3.IntegrityError:
            pass
    conn.commit()
    conn.close()
    return count

def insert_one(ts, o, h, l, c):
    """插入单条数据"""
    conn = _get_conn()
    try:
        conn.execute("INSERT INTO btc_swap_15m(ts,open,high,low,close) VALUES(?,?,?,?,?)",
                     (ts, o, h, l, c))
        conn.commit()
        conn.close()
        return True
    except sqlite3.IntegrityError:
        conn.close()
        return False

def get_recent(n=500):
    """
    获取最近n根K线，用于策略实时计算
    返回 [{ts,o,h,l,c}, ...] 按时间升序
    """
    conn = _get_conn()
    cur = conn.execute(
        "SELECT ts,open,high,low,close FROM btc_swap_15m ORDER BY ts DESC LIMIT ?",
        (n,)
    )
    rows = cur.fetchall()
    conn.close()
    # 转为dict列表并正序排列
    bars = [{"ts": r[0], "o": r[1], "h": r[2], "l": r[3], "c": r[4]} for r in reversed(rows)]
    return bars

def get_range(from_ts, to_ts=None, limit=None):
    """
    按时间范围查询，用于回测
    返回 [{ts,o,h,l,c}, ...] 按时间升序
    """
    conn = _get_conn()
    if to_ts:
        sql = "SELECT ts,open,high,low,close FROM btc_swap_15m WHERE ts>=? AND ts<=? ORDER BY ts ASC"
        params = (from_ts, to_ts)
    else:
        sql = "SELECT ts,open,high,low,close FROM btc_swap_15m WHERE ts>=? ORDER BY ts ASC"
        params = (from_ts,)
    if limit:
        sql += " LIMIT ?"
        params = params + (limit,)
    cur = conn.execute(sql, params)
    rows = cur.fetchall()
    conn.close()
    return [{"ts": r[0], "o": r[1], "h": r[2], "l": r[3], "c": r[4]} for r in rows]

def get_latest_ts():
    """获取最新时间戳"""
    conn = _get_conn()
    cur = conn.execute("SELECT MAX(ts) FROM btc_swap_15m")
    row = cur.fetchone()
    conn.close()
    return row[0] if row[0] else 0

def count():
    """总数据量"""
    conn = _get_conn()
    cur = conn.execute("SELECT COUNT(*) FROM btc_swap_15m")
    row = cur.fetchone()
    conn.close()
    return row[0]

def get_stats():
    """统计信息"""
    conn = _get_conn()
    cur = conn.execute("""
        SELECT COUNT(*), MIN(ts), MAX(ts),
               MIN(close), MAX(close)
        FROM btc_swap_15m
    """)
    row = cur.fetchone()
    conn.close()
    if not row or row[0] == 0:
        return None
    return {
        "count": row[0],
        "from_ts": row[1],
        "to_ts": row[2],
        "min_price": row[3],
        "max_price": row[4],
    }

def get_last_update_time():
    """获取最后更新时间"""
    conn = _get_conn()
    cur = conn.execute("SELECT MAX(ts) FROM btc_swap_15m")
    row = cur.fetchone()
    conn.close()
    if row and row[0]:
        return datetime.fromtimestamp(row[0]/1000).strftime("%Y-%m-%d %H:%M")
    return "无数据"

# ==== 初始化 ====
init_db()