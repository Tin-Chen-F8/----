# ============================================================
# 后端 - 数据库层 (SQLite)
# ============================================================
import sqlite3
import json
import csv
import io
from datetime import datetime, timedelta
import config

# ---- 18个数值指标的列名列表（quality_top10 是 TEXT/JSON，单独处理）----
NUMERIC_METRICS = [
    "production_count", "daily_backlog", "backlog_count",
    "utilization_rate", "oee", "sequence_compliance",
    "energy_per_unit", "energy_trend", "equipment_operation_rate",
    "ftt", "dpv", "audit",
    "performance_score", "turnover_rate", "training_rate",
    "voc", "accident_rate",
]

ALL_METRICS = NUMERIC_METRICS + ["quality_top10"]

# ---- 指标显示名称 ----
METRIC_LABELS = {
    "production_count": "产量",
    "daily_backlog": "日滞留车数",
    "backlog_count": "滞留车数量",
    "utilization_rate": "稼动率",
    "oee": "OEE",
    "sequence_compliance": "顺序遵守率",
    "energy_per_unit": "日单台能耗",
    "energy_trend": "日单台能耗趋势",
    "equipment_operation_rate": "日开动率",
    "ftt": "FTT",
    "dpv": "DPV",
    "audit": "AUDIT",
    "quality_top10": "质量问题Top10",
    "performance_score": "绩效",
    "turnover_rate": "离职率",
    "training_rate": "培训率",
    "voc": "VOC",
    "accident_rate": "事故率",
}

METRIC_UNITS = {
    "production_count": "台",
    "daily_backlog": "辆",
    "backlog_count": "辆",
    "utilization_rate": "%",
    "oee": "%",
    "sequence_compliance": "%",
    "energy_per_unit": "kWh/台",
    "energy_trend": "",
    "equipment_operation_rate": "%",
    "ftt": "%",
    "dpv": "个/台",
    "audit": "分",
    "quality_top10": "",
    "performance_score": "分",
    "turnover_rate": "%",
    "training_rate": "%",
    "voc": "mg/m³",
    "accident_rate": "%",
}

METRIC_CATEGORIES = {
    "production": ["production_count", "daily_backlog", "backlog_count",
                   "utilization_rate", "oee", "sequence_compliance"],
    "equipment": ["energy_per_unit", "energy_trend", "equipment_operation_rate"],
    "quality": ["ftt", "dpv", "audit", "quality_top10"],
    "management": ["performance_score", "turnover_rate", "training_rate"],
    "safety": ["voc", "accident_rate"],
}


def get_db():
    """获取数据库连接（每次调用创建新连接，线程安全）"""
    conn = sqlite3.connect(config.DB_PATH)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode=WAL")
    return conn


def init_db():
    """初始化数据库：建表"""
    conn = get_db()
    conn.executescript("""
        CREATE TABLE IF NOT EXISTS raw_data (
            id          INTEGER PRIMARY KEY AUTOINCREMENT,
            timestamp   TEXT NOT NULL,
            production_count      REAL,
            daily_backlog         REAL,
            backlog_count         REAL,
            utilization_rate      REAL,
            oee                   REAL,
            sequence_compliance   REAL,
            energy_per_unit       REAL,
            energy_trend          REAL,
            equipment_operation_rate REAL,
            ftt                   REAL,
            dpv                   REAL,
            audit                 REAL,
            quality_top10         TEXT,
            performance_score     REAL,
            turnover_rate         REAL,
            training_rate         REAL,
            voc                   REAL,
            accident_rate         REAL
        );

        CREATE INDEX IF NOT EXISTS idx_raw_ts ON raw_data(timestamp);

        CREATE TABLE IF NOT EXISTS stats_agg (
            id              INTEGER PRIMARY KEY AUTOINCREMENT,
            period_start    TEXT NOT NULL,
            granularity     TEXT NOT NULL,
            metric_name     TEXT NOT NULL,
            avg_val         REAL,
            max_val         REAL,
            min_val         REAL,
            sample_count    INTEGER,
            UNIQUE(period_start, granularity, metric_name)
        );

        CREATE INDEX IF NOT EXISTS idx_stats_query
            ON stats_agg(metric_name, granularity, period_start);

        CREATE TABLE IF NOT EXISTS agg_checkpoint (
            granularity     TEXT PRIMARY KEY,
            last_period_start TEXT NOT NULL
        );
    """)
    conn.commit()
    conn.close()


def insert_raw_data(data: dict):
    """插入一条原始数据记录"""
    conn = get_db()
    columns = ["timestamp"] + NUMERIC_METRICS + ["quality_top10"]
    placeholders = ",".join(["?"] * len(columns))
    values = [
        data.get("timestamp", datetime.now().isoformat()),
    ]
    for m in NUMERIC_METRICS:
        values.append(data.get(m))
    values.append(data.get("quality_top10"))
    sql = f"INSERT INTO raw_data ({','.join(columns)}) VALUES ({placeholders})"
    conn.execute(sql, values)
    conn.commit()
    conn.close()


def get_latest():
    """获取最新一条数据"""
    conn = get_db()
    row = conn.execute("SELECT * FROM raw_data ORDER BY id DESC LIMIT 1").fetchone()
    conn.close()
    if row:
        return dict(row)
    return None


def get_raw_data(metric: str, start: str = None, end: str = None, limit: int = 200):
    """查询最新 limit 条原始数据点（按时间升序返回）"""
    conn = get_db()
    if metric == "quality_top10":
        conn.close()
        return []
    where = "1=1"
    params = []
    if start:
        where += " AND timestamp >= ?"
        params.append(start)
    if end:
        where += " AND timestamp <= ?"
        params.append(end)
    sql = (
        f"SELECT timestamp, {metric} as value FROM ("
        f"  SELECT timestamp, {metric} FROM raw_data WHERE {where} "
        f"  ORDER BY timestamp DESC LIMIT ?"
        f") ORDER BY timestamp ASC"
    )
    params.append(limit)
    rows = conn.execute(sql, params).fetchall()
    conn.close()
    return [{"timestamp": r["timestamp"], "value": r["value"]} for r in rows]


def get_stats(metric: str, start: str, end: str, granularity: str):
    """
    查询聚合统计数据。
    granularity: 'raw' | 'hourly' | 'daily' | '3day'
    'raw' 直接查 raw_data 聚合
    """
    if metric == "quality_top10":
        return []

    if granularity == "raw":
        # 查原始数据，按时间排序
        conn = get_db()
        rows = conn.execute(
            f"SELECT timestamp, {metric} as value FROM raw_data "
            "WHERE timestamp >= ? AND timestamp <= ? ORDER BY timestamp ASC",
            (start, end)
        ).fetchall()
        conn.close()
        return [{"timestamp": r["timestamp"], "value": r["value"]} for r in rows]

    # 查预聚合表
    conn = get_db()
    rows = conn.execute(
        "SELECT period_start, avg_val, max_val, min_val, sample_count "
        "FROM stats_agg "
        "WHERE metric_name = ? AND granularity = ? "
        "AND period_start >= ? AND period_start <= ? "
        "ORDER BY period_start ASC",
        (metric, granularity, start, end)
    ).fetchall()
    conn.close()
    return [{
        "period_start": r["period_start"],
        "avg": r["avg_val"],
        "max": r["max_val"],
        "min": r["min_val"],
        "count": r["sample_count"],
    } for r in rows]


def run_aggregation(granularity: str, period_start: str, period_end: str):
    """对指定时间段执行聚合，写入 stats_agg 表"""
    conn = get_db()

    if granularity == "hourly":
        time_filter = "timestamp >= ? AND timestamp < ?"
    elif granularity == "daily":
        time_filter = "timestamp >= ? AND timestamp < ?"
    elif granularity == "3day":
        time_filter = "timestamp >= ? AND timestamp < ?"
    else:
        conn.close()
        return

    for metric in NUMERIC_METRICS:
        sql = f"""
            INSERT OR REPLACE INTO stats_agg
                (period_start, granularity, metric_name, avg_val, max_val, min_val, sample_count)
            SELECT
                ?,
                ?,
                ?,
                ROUND(AVG({metric}), 4),
                ROUND(MAX({metric}), 4),
                ROUND(MIN({metric}), 4),
                COUNT({metric})
            FROM raw_data
            WHERE {time_filter} AND {metric} IS NOT NULL
        """
        conn.execute(sql, (period_start, granularity, metric, period_start, period_end))

    conn.commit()
    conn.close()


def get_checkpoint(granularity: str) -> str | None:
    """获取某粒度的上次聚合时间点"""
    conn = get_db()
    row = conn.execute(
        "SELECT last_period_start FROM agg_checkpoint WHERE granularity = ?",
        (granularity,)
    ).fetchone()
    conn.close()
    return row["last_period_start"] if row else None


def set_checkpoint(granularity: str, period_start: str):
    """记录聚合完成的时间点"""
    conn = get_db()
    conn.execute(
        "INSERT OR REPLACE INTO agg_checkpoint (granularity, last_period_start) VALUES (?, ?)",
        (granularity, period_start)
    )
    conn.commit()
    conn.close()


def export_csv(metrics_list: list[str], start: str, end: str) -> str:
    """导出 CSV 字符串"""
    conn = get_db()

    valid_metrics = [m for m in metrics_list if m in NUMERIC_METRICS]
    if not valid_metrics:
        conn.close()
        return "timestamp\n"

    columns = ["timestamp"] + valid_metrics
    sql = f"SELECT {', '.join(columns)} FROM raw_data WHERE timestamp >= ? AND timestamp <= ? ORDER BY timestamp ASC"
    rows = conn.execute(sql, (start, end)).fetchall()

    output = io.StringIO()
    writer = csv.writer(output)
    # 表头用中文
    header = ["时间"] + [METRIC_LABELS.get(m, m) for m in valid_metrics]
    writer.writerow(header)
    for row in rows:
        writer.writerow([row[c] for c in columns])

    conn.close()
    return output.getvalue()


def cleanup_old_data():
    """删除超过 RAW_RETENTION_DAYS 天的原始数据"""
    cutoff = (datetime.now() - timedelta(days=config.RAW_RETENTION_DAYS)).isoformat()
    conn = get_db()
    conn.execute("DELETE FROM raw_data WHERE timestamp < ?", (cutoff,))
    conn.commit()
    conn.close()


def get_metrics_info():
    """返回所有指标的元信息（名称、单位、分类）"""
    info = []
    for key in ALL_METRICS:
        category = None
        for cat, metrics in METRIC_CATEGORIES.items():
            if key in metrics:
                category = cat
                break
        info.append({
            "key": key,
            "label": METRIC_LABELS.get(key, key),
            "unit": METRIC_UNITS.get(key, ""),
            "category": category,
        })
    return info


def get_latest_top10():
    """获取最新的质量问题Top10 JSON"""
    conn = get_db()
    row = conn.execute(
        "SELECT quality_top10 FROM raw_data WHERE quality_top10 IS NOT NULL ORDER BY id DESC LIMIT 1"
    ).fetchone()
    conn.close()
    if row and row["quality_top10"]:
        return json.loads(row["quality_top10"])
    return []
