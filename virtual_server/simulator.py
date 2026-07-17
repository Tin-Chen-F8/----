# ============================================================
# 数据模拟器 - 18个工业指标的趋势模拟
# ============================================================
import random
import json
from datetime import datetime, timedelta


class MetricSimulator:
    """单个数值指标的模拟器：基准值缓慢漂移 + 随机噪声"""

    def __init__(self, min_val, max_val, noise_std, drift_per_hour):
        self.min = min_val
        self.max = max_val
        self.noise_std = noise_std
        self.drift_per_hour = drift_per_hour
        self.base = random.uniform(min_val, max_val)

    def tick(self, dt_seconds):
        """dt_seconds: 经过的模拟时间(秒)"""
        hours = dt_seconds / 3600.0
        self.base += self.drift_per_hour * hours * random.uniform(-1, 1)
        self.base = max(self.min, min(self.max, self.base))
        value = self.base + random.gauss(0, self.noise_std)
        value = max(self.min, min(self.max, value))
        return value


class ProductionSimulator:
    """产量模拟器：日累计递增，每日午夜重置"""

    def __init__(self, max_daily=200):
        self.max_daily = max_daily
        self.reset()

    def reset(self):
        self.daily_total = random.uniform(0, 20)
        # 每条数据(10s仿真时间)的基准增量
        self.increment_per_second = random.uniform(0.0015, 0.0035)

    def tick(self, dt_seconds):
        self.daily_total += self.increment_per_second * dt_seconds * random.uniform(0.4, 1.6)
        self.daily_total = min(self.max_daily, self.daily_total)
        return round(self.daily_total, 1)


class Top10Simulator:
    """质量问题Top10模拟器：每N个tick随机交换排名并微调数量"""

    ISSUE_NAMES = ["颗粒", "流挂", "橘皮", "针孔", "色差",
                   "缩孔", "气泡", "划伤", "油污", "飞漆"]

    def __init__(self):
        self.issues = []
        base_counts = [23, 18, 15, 12, 10, 8, 7, 5, 4, 3]
        for i, (name, count) in enumerate(zip(self.ISSUE_NAMES, base_counts)):
            self.issues.append({"rank": i + 1, "name": name, "count": count})

    def tick(self):
        # 随机交换相邻两项
        idx = random.randint(0, 8)
        self.issues[idx], self.issues[idx + 1] = self.issues[idx + 1], self.issues[idx]
        # 微调数量
        for issue in self.issues:
            issue["count"] = max(1, issue["count"] + random.randint(-3, 3))
        # 按数量重新排序
        self.issues.sort(key=lambda x: x["count"], reverse=True)
        for i, issue in enumerate(self.issues):
            issue["rank"] = i + 1
        return self.issues

    def to_json(self):
        return json.dumps(self.issues, ensure_ascii=False)


class DataSimulator:
    """总模拟器：管理18个指标的状态和生成"""

    def __init__(self, config):
        self.config = config
        self.logical_time = datetime.now()
        self.last_midnight = self.logical_time.replace(hour=0, minute=0, second=0, microsecond=0)
        self.tick_count = 0

        # ---- 高频指标（每tick更新）----
        self.high_freq = {
            "daily_backlog":           MetricSimulator(0, 30, 2, 5),
            "backlog_count":           MetricSimulator(0, 15, 1, 3),
            "utilization_rate":        MetricSimulator(75, 98, 0.5, 3),
            "oee":                     MetricSimulator(65, 92, 0.3, 2),
            "sequence_compliance":     MetricSimulator(85, 99, 0.2, 1),
            "energy_per_unit":         MetricSimulator(50, 120, 1.0, 8),
            "energy_trend":            MetricSimulator(-5, 5, 0.1, 0.5),
            "equipment_operation_rate": MetricSimulator(80, 99, 0.3, 2),
            "ftt":                     MetricSimulator(88, 99, 0.5, 2),
            "dpv":                     MetricSimulator(0.5, 5.0, 0.3, 0.5),
            "voc":                     MetricSimulator(5, 50, 2.0, 5),
        }

        # ---- 中频指标（每 MID_FREQ_TICKS 更新）----
        self.mid_freq = {
            "audit": MetricSimulator(60, 100, 1.0, 3),
        }

        # ---- 低频指标（每 LOW_FREQ_TICKS 更新）----
        self.low_freq = {
            "performance_score": MetricSimulator(70, 100, 1.0, 2),
            "turnover_rate":     MetricSimulator(1, 8, 0.3, 0.5),
            "training_rate":     MetricSimulator(80, 100, 0.5, 1),
            "accident_rate":     MetricSimulator(0, 0.5, 0.02, 0.02),
        }

        self.production = ProductionSimulator(max_daily=200)
        self.top10 = Top10Simulator()

        # 缓存当前值（初始化时生成一次）
        self._cache = {}
        self._init_cache()

    def _init_cache(self):
        """首次初始化所有指标值"""
        dt0 = 1.0  # 初始用1秒模拟时间
        for name, sim in self.high_freq.items():
            self._cache[name] = round(sim.tick(dt0), 4)
        for name, sim in self.mid_freq.items():
            self._cache[name] = round(sim.tick(dt0), 4)
        for name, sim in self.low_freq.items():
            self._cache[name] = round(sim.tick(dt0), 4)
        self._cache["production_count"] = self.production.tick(dt0)
        self._cache["quality_top10"] = self.top10.to_json()

    def tick(self):
        """执行一次数据生成，返回完整的18个指标字典"""
        dt = self.config.DATA_INTERVAL * self.config.TIME_SCALE
        self.tick_count += 1
        self.logical_time += timedelta(seconds=dt)

        # ---- 午夜检查：产量重置 ----
        today_midnight = self.logical_time.replace(hour=0, minute=0, second=0, microsecond=0)
        if today_midnight > self.last_midnight:
            self.production.reset()
            self.last_midnight = today_midnight

        # ---- 高频指标 ----
        for name, sim in self.high_freq.items():
            self._cache[name] = round(sim.tick(dt), 4)

        # ---- 产量 ----
        self._cache["production_count"] = self.production.tick(dt)

        # ---- 中频指标 ----
        if self.tick_count % self.config.MID_FREQ_TICKS == 0:
            mid_dt = dt * self.config.MID_FREQ_TICKS
            for name, sim in self.mid_freq.items():
                self._cache[name] = round(sim.tick(mid_dt), 4)
            self.top10.tick()
            self._cache["quality_top10"] = self.top10.to_json()

        # ---- 低频指标 ----
        if self.tick_count % self.config.LOW_FREQ_TICKS == 0:
            low_dt = dt * self.config.LOW_FREQ_TICKS
            for name, sim in self.low_freq.items():
                self._cache[name] = round(sim.tick(low_dt), 4)

        # ---- 组装返回 ----
        data = dict(self._cache)
        data["timestamp"] = self.logical_time.isoformat()
        return data
