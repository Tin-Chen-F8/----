# ============================================================
# 后端 - 聚合触发逻辑
# ============================================================
from datetime import datetime, timedelta
import database


def check_and_aggregate(timestamp_str: str):
    """
    每次插入 raw_data 后调用。
    检查是否越过整点/0点/3天0点，若越过则触发对应聚合。
    """
    ts = datetime.fromisoformat(timestamp_str)

    # ---- Hourly 聚合 ----
    last_hourly = database.get_checkpoint("hourly")
    # 当前时间所属小时起点
    current_hour_start = ts.replace(minute=0, second=0, microsecond=0)
    if last_hourly is None:
        # 首次运行，不做历史补偿，标记即可
        database.set_checkpoint("hourly", current_hour_start.isoformat())
    else:
        last_dt = datetime.fromisoformat(last_hourly)
        next_hour_start = last_dt + timedelta(hours=1)
        # 如果错过了多个小时，逐个补上
        while next_hour_start <= current_hour_start:
            period_end = next_hour_start + timedelta(hours=1)
            database.run_aggregation(
                "hourly",
                next_hour_start.isoformat(),
                period_end.isoformat(),
            )
            database.set_checkpoint("hourly", next_hour_start.isoformat())
            next_hour_start += timedelta(hours=1)

    # ---- Daily 聚合 ----
    last_daily = database.get_checkpoint("daily")
    current_day_start = ts.replace(hour=0, minute=0, second=0, microsecond=0)
    if last_daily is None:
        database.set_checkpoint("daily", current_day_start.isoformat())
    else:
        last_dt = datetime.fromisoformat(last_daily)
        next_day_start = last_dt + timedelta(days=1)
        while next_day_start <= current_day_start:
            period_end = next_day_start + timedelta(days=1)
            database.run_aggregation(
                "daily",
                next_day_start.isoformat(),
                period_end.isoformat(),
            )
            database.set_checkpoint("daily", next_day_start.isoformat())
            next_day_start += timedelta(days=1)

    # ---- 3Day 聚合 ----
    last_3day = database.get_checkpoint("3day")
    if last_3day is None:
        # 从最早的可整除3天的日期开始
        base_date = current_day_start
        while base_date.day % 3 != 1:  # 对齐到 1,4,7,10,13,16,19,22,25,28,31 号
            base_date -= timedelta(days=1)
        database.set_checkpoint("3day", base_date.isoformat())
    else:
        last_dt = datetime.fromisoformat(last_3day)
        next_3day_start = last_dt + timedelta(days=3)
        while next_3day_start <= current_day_start:
            period_end = next_3day_start + timedelta(days=3)
            database.run_aggregation(
                "3day",
                next_3day_start.isoformat(),
                period_end.isoformat(),
            )
            database.set_checkpoint("3day", next_3day_start.isoformat())
            next_3day_start += timedelta(days=3)
