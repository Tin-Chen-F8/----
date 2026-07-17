"""
涂装车间生产指标虚拟数据服务器
- 扁平化结构，英文字段名，含 timestamp
- 维护内部状态：单调递增字段（产量）+ 均值回归字段（大部分指标）
- quality_top10 为 JSON 字符串 (name/count/rank)
- energy_trend 为单值（能耗环比变化百分比）
"""

import json
import random
import threading
import copy
from datetime import datetime
from collections import deque
from typing import Any, Dict, Optional

from fastapi import FastAPI, Query
from fastapi.middleware.cors import CORSMiddleware

# ============================================================
# FastAPI 应用
# ============================================================

app = FastAPI(
    title="涂装车间指标数据服务",
    description="扁平化虚拟指标数据，基于内部状态微调，模拟真实车间数据波动",
    version="2.1.0",
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# ============================================================
# 状态管理
# ============================================================

_lock = threading.Lock()
_state: Dict[str, Any] = {}
_history: deque = deque(maxlen=365)
_initialized: bool = False

# ---------- 各字段的硬边界 ----------
BOUNDS: Dict[str, tuple] = {
    "production_count":          (0,   9999),
    "daily_backlog":             (0,   50),
    "backlog_count":             (0,   80),
    "utilization_rate":          (70.0, 99.0),
    "oee":                       (60.0, 98.0),
    "sequence_compliance":       (80.0, 100.0),
    "energy_per_unit":           (12.0, 55.0),
    "energy_trend":              (-10.0, 10.0),
    "equipment_operation_rate":  (75.0, 100.0),
    "ftt":                       (80.0, 99.5),
    "dpv":                       (0.3,  6.0),
    "audit":                     (65.0, 100.0),
    "performance_score":         (65.0, 100.0),
    "turnover_rate":             (0.5,  12.0),
    "training_rate":             (75.0, 100.0),
    "voc":                       (0.05, 6.0),
    "accident_rate":             (0.0,  3.0),
}

# ---------- 均值回归中心（模拟工厂稳态水平）----------
BASELINE: Dict[str, float] = {
    "utilization_rate":          88.0,
    "oee":                       82.0,
    "sequence_compliance":       92.0,
    "energy_per_unit":           32.0,
    "equipment_operation_rate":  92.0,
    "ftt":                       93.0,
    "dpv":                       2.5,
    "audit":                     85.0,
    "performance_score":         85.0,
    "turnover_rate":             5.0,
    "training_rate":             90.0,
    "voc":                       2.0,
    "accident_rate":             0.5,
}

# ---------- 当日产量目标（超过后自动换班归零）----------
DAILY_PRODUCTION_TARGET = 550

# 质量问题名称池
QUALITY_NAMES = [
    "颗粒", "流挂", "橘皮", "针孔", "缩孔",
    "色差", "光泽度不足", "附着力不合格", "膜厚不均", "起泡",
    "露底", "发白", "鱼眼", "溶剂泡", "打磨痕",
    "电泳缩孔", "中涂流挂", "面漆失光", "清漆痱子", "PVC开裂",
]


def _clamp(value: float, lo: float, hi: float) -> float:
    return max(lo, min(hi, value))


# ============================================================
# 核心：两种趋势模型
# ============================================================

def _ou_step(value: float, mean: float, lo: float, hi: float,
             theta: float = 0.12, sigma_frac: float = 0.008) -> float:
    """
    Ornstein-Uhlenbeck 均值回归过程。
    - theta: 回归速度（越大越快拉回均值）
    - sigma_frac: 噪声强度（相对均值的比例）
    适用于：稼动率、OEE、FTT、能耗、DPV、VOC 等在稳态附近波动的指标。
    """
    drift = theta * (mean - value)
    noise = mean * sigma_frac * random.gauss(0, 1)
    return round(_clamp(value + drift + noise, lo, hi), 2)


def _monotonic_step(value: int, lo: int, hi: int,
                    step_min: int = 0, step_max: int = 5) -> int:
    """
    单调递增步进（绝大部分时候增加，极小概率持平）。
    适用于：产量（当日累计）。
    """
    delta = random.randint(step_min, step_max)
    return max(lo, min(hi, value + delta))


def _random_walk_int(value: int, lo: int, hi: int,
                     delta_range: int = 2) -> int:
    """有限随机游走，用于滞留车数等短期波动型整数指标。"""
    delta = random.randint(-delta_range, delta_range)
    return max(lo, min(hi, value + delta))


# ============================================================
# 初始化 & 质量问题
# ============================================================

def _init_quality_top10() -> list:
    """生成初始 Top10 质量问题（内部 list 格式）"""
    names = random.sample(QUALITY_NAMES, 10)
    items = []
    remaining = random.randint(120, 250)
    for i, name in enumerate(names):
        if i == 9:
            count = max(1, remaining)
        else:
            count = random.randint(3, max(3, remaining // (10 - i)))
        remaining -= count
        if remaining < 0:
            remaining = 0
        items.append({"name": name, "count": count})
    items.sort(key=lambda x: x["count"], reverse=True)
    for i, item in enumerate(items):
        item["rank"] = i + 1
    return items


def _init_state() -> dict:
    """生成初始随机状态，各均值回归字段以 BASELINE 为中心散布"""
    return {
        # ---- 单调递增 ----
        "production_count":         random.randint(150, 350),

        # ---- 有限随机游走 ----
        "daily_backlog":            random.randint(2, 20),
        "backlog_count":            random.randint(5, 35),

        # ---- 均值回归（初始值围绕 BASELINE 散布）----
        "utilization_rate":         round(random.gauss(BASELINE["utilization_rate"], 4), 1),
        "oee":                      round(random.gauss(BASELINE["oee"], 4), 1),
        "sequence_compliance":      round(random.gauss(BASELINE["sequence_compliance"], 3), 1),
        "energy_per_unit":          round(random.gauss(BASELINE["energy_per_unit"], 5), 1),
        "energy_trend":             round(random.uniform(-2.0, 2.0), 1),
        "equipment_operation_rate": round(random.gauss(BASELINE["equipment_operation_rate"], 4), 1),
        "ftt":                      round(random.gauss(BASELINE["ftt"], 3), 1),
        "dpv":                      round(random.gauss(BASELINE["dpv"], 0.6), 1),
        "audit":                    round(random.gauss(BASELINE["audit"], 5), 1),
        "quality_top10":            _init_quality_top10(),
        "performance_score":        round(random.gauss(BASELINE["performance_score"], 5), 1),
        "turnover_rate":            round(random.gauss(BASELINE["turnover_rate"], 1.5), 1),
        "training_rate":            round(random.gauss(BASELINE["training_rate"], 4), 1),
        "voc":                      round(random.gauss(BASELINE["voc"], 0.6), 1),
        "accident_rate":            round(abs(random.gauss(0, 0.3)), 2),
    }


def ensure_initialized() -> None:
    global _initialized
    if not _initialized:
        with _lock:
            if not _initialized:
                s = _init_state()
                _state.clear()
                _state.update(s)
                _initialized = True


def _adjust_quality_top10(items: list) -> list:
    """微调质量问题计数：小幅波动，保留大致排名结构"""
    for item in items:
        delta = random.randint(-2, 3)
        item["count"] = max(1, item["count"] + delta)
    items.sort(key=lambda x: x["count"], reverse=True)
    for i, item in enumerate(items):
        item["rank"] = i + 1
    return items


def get_current_snapshot() -> dict:
    """获取当前状态快照（不触发微调）"""
    ensure_initialized()
    with _lock:
        s = copy.deepcopy(_state)
    s["timestamp"] = datetime.now().strftime("%Y-%m-%dT%H:%M:%S")
    s["quality_top10"] = json.dumps(s["quality_top10"], ensure_ascii=False)
    return s


def tick_state() -> dict:
    """
    触发一次状态微调，返回快照。

    趋势分类：
    ┌──────────────────────┬──────────────────────┐
    │ 单调递增             │ production_count      │
    │                      │ （超当日目标自动换班） │
    ├──────────────────────┼──────────────────────┤
    │ 均值回归（OU过程）    │ utilization_rate,     │
    │                      │ oee,                  │
    │                      │ sequence_compliance,  │
    │                      │ energy_per_unit,      │
    │                      │ equipment_op_rate,    │
    │                      │ ftt, dpv, audit,      │
    │                      │ performance_score,    │
    │                      │ turnover_rate,        │
    │                      │ training_rate,        │
    │                      │ voc, accident_rate    │
    ├──────────────────────┼──────────────────────┤
    │ 有限随机游走         │ daily_backlog,        │
    │                      │ backlog_count         │
    ├──────────────────────┼──────────────────────┤
    │ 内部竞争重排         │ quality_top10         │
    └──────────────────────┴──────────────────────┘
    """
    ensure_initialized()
    with _lock:
        old_energy = _state["energy_per_unit"]

        # ---- 单调递增：产量 ----
        pc = _state["production_count"]
        lo, hi = BOUNDS["production_count"]
        pc = _monotonic_step(pc, lo, hi, step_min=1, step_max=5)
        # 超过当日目标 → 换班清零（模拟新班次开始）
        if pc >= DAILY_PRODUCTION_TARGET:
            pc = random.randint(0, 20)
        _state["production_count"] = pc

        # ---- 均值回归：大部分浮点指标 ----
        for key in ["utilization_rate", "oee", "sequence_compliance",
                     "energy_per_unit", "equipment_operation_rate",
                     "ftt", "dpv", "audit", "performance_score",
                     "turnover_rate", "training_rate", "voc"]:
            lo, hi = BOUNDS[key]
            mean = BASELINE[key]
            _state[key] = _ou_step(_state[key], mean, lo, hi)

        # accident_rate 用更小的噪声（安全指标应非常稳定）
        _state["accident_rate"] = _ou_step(
            _state["accident_rate"], BASELINE["accident_rate"],
            *BOUNDS["accident_rate"], theta=0.15, sigma_frac=0.003,
        )

        # ---- 有限随机游走：滞留 ----
        for key in ["daily_backlog", "backlog_count"]:
            lo, hi = BOUNDS[key]
            _state[key] = _random_walk_int(_state[key], lo, hi)

        # ---- 能耗趋势（根据 energy_per_unit 变动自动计算）----
        new_energy = _state["energy_per_unit"]
        if old_energy > 0:
            trend = round((new_energy - old_energy) / old_energy * 100, 1)
        else:
            trend = 0.0
        _state["energy_trend"] = _clamp(trend, *BOUNDS["energy_trend"])

        # ---- 质量问题微调 ----
        _state["quality_top10"] = _adjust_quality_top10(_state["quality_top10"])

        # ---- 保存快照到历史 ----
        snap = copy.deepcopy(_state)
        snap["timestamp"] = datetime.now().strftime("%Y-%m-%dT%H:%M:%S")
        snap["quality_top10"] = json.dumps(snap["quality_top10"], ensure_ascii=False)
        _history.append(snap)

        return snap


# ============================================================
# 字段分组
# ============================================================

PRODUCTION_FIELDS = [
    "production_count", "daily_backlog", "backlog_count",
    "utilization_rate", "oee", "sequence_compliance",
]
EQUIPMENT_FIELDS = [
    "energy_per_unit", "energy_trend", "equipment_operation_rate",
]
QUALITY_FIELDS = ["ftt", "dpv", "audit", "quality_top10"]
MANAGEMENT_FIELDS = ["performance_score", "turnover_rate", "training_rate"]
SAFETY_FIELDS = ["voc", "accident_rate"]


def _pick_fields(snapshot: dict, fields: list) -> dict:
    return {"timestamp": snapshot["timestamp"],
            **{k: snapshot[k] for k in fields if k in snapshot}}


# ============================================================
# API 端点
# ============================================================

@app.get("/api/data", tags=["综合"])
async def get_data():
    """
    获取综合仪表盘数据（扁平化结构）。
    每次调用触发一次微调，模拟实时数据变化。
    """
    return tick_state()


@app.get("/api/production", tags=["生产指标"])
async def get_production():
    """生产指标子集（只读当前快照，不触发微调）"""
    return _pick_fields(get_current_snapshot(), PRODUCTION_FIELDS)


@app.get("/api/equipment", tags=["设备指标"])
async def get_equipment():
    """设备指标子集"""
    return _pick_fields(get_current_snapshot(), EQUIPMENT_FIELDS)


@app.get("/api/quality", tags=["技质指标"])
async def get_quality():
    """技质指标子集"""
    return _pick_fields(get_current_snapshot(), QUALITY_FIELDS)


@app.get("/api/management", tags=["管理组指标"])
async def get_management():
    """管理组指标子集"""
    return _pick_fields(get_current_snapshot(), MANAGEMENT_FIELDS)


@app.get("/api/safety", tags=["安全指标"])
async def get_safety():
    """安全指标子集"""
    return _pick_fields(get_current_snapshot(), SAFETY_FIELDS)


@app.get("/api/reset", tags=["管理"])
async def reset_state(
    seed: Optional[int] = Query(None, description="随机种子"),
):
    """重置状态为新的随机初值"""
    global _initialized
    if seed is not None:
        random.seed(seed)
    with _lock:
        s = _init_state()
        _state.clear()
        _state.update(s)
        _initialized = True
        _history.clear()
    return {"message": "状态已重置", "seed": seed}


@app.get("/api/trend/{field_name}", tags=["历史趋势"])
async def get_trend(
    field_name: str,
    limit: int = Query(30, ge=1, le=365, description="最近 N 条"),
):
    """返回指定字段的历史值 [{timestamp, value}, ...]"""
    all_fields = list(BOUNDS.keys()) + ["quality_top10", "timestamp"]
    if field_name not in all_fields:
        return {
            "error": f"未知字段 '{field_name}'",
            "available_fields": sorted(set(BOUNDS.keys()) | {"quality_top10"}),
        }
    with _lock:
        records = list(_history)[-limit:]
    return [
        {"timestamp": r.get("timestamp", ""), "value": r.get(field_name)}
        for r in records
    ]


@app.get("/api/fields", tags=["元数据"])
async def get_fields():
    """字段说明及趋势类型"""
    return {
        "fields": {
            "timestamp":                 {"label": "时间戳",           "trend": "实时"},
            "production_count":          {"label": "产量",             "trend": "单调递增（当日累计，超目标自动换班归零）"},
            "daily_backlog":             {"label": "日滞留车数",       "trend": "有限随机游走"},
            "backlog_count":             {"label": "滞留车数量",       "trend": "有限随机游走"},
            "utilization_rate":          {"label": "稼动率",           "trend": "均值回归（中心 ~88%）"},
            "oee":                       {"label": "OEE",              "trend": "均值回归（中心 ~82%）"},
            "sequence_compliance":       {"label": "顺序遵守率",       "trend": "均值回归（中心 ~92%）"},
            "energy_per_unit":           {"label": "日单台能耗",       "trend": "均值回归（中心 ~32 kWh）"},
            "energy_trend":              {"label": "能耗趋势",         "trend": "环比变化 %（由 energy_per_unit 计算）"},
            "equipment_operation_rate":  {"label": "日开动率",         "trend": "均值回归（中心 ~92%）"},
            "ftt":                       {"label": "FTT",              "trend": "均值回归（中心 ~93%）"},
            "dpv":                       {"label": "DPV",              "trend": "均值回归（中心 ~2.5）"},
            "audit":                     {"label": "AUDIT",            "trend": "均值回归（中心 ~85）"},
            "quality_top10":             {"label": "质量问题Top10",    "trend": "内部竞争微调（JSON字符串）"},
            "performance_score":         {"label": "绩效",             "trend": "均值回归（中心 ~85）"},
            "turnover_rate":             {"label": "离职率",           "trend": "均值回归（中心 ~5%）"},
            "training_rate":             {"label": "培训率",           "trend": "均值回归（中心 ~90%）"},
            "voc":                       {"label": "VOC",              "trend": "均值回归（中心 ~2.0 mg/m³）"},
            "accident_rate":             {"label": "事故率",           "trend": "均值回归（中心 ~0.5%，极低噪声）"},
        },
        "endpoints": {
            "综合数据":     "/api/data",
            "生产指标":     "/api/production",
            "设备指标":     "/api/equipment",
            "技质指标":     "/api/quality",
            "管理组指标":   "/api/management",
            "安全指标":     "/api/safety",
            "历史趋势":     "/api/trend/{field_name}?limit=30",
            "重置状态":     "/api/reset?seed=42",
        },
    }


# ============================================================
# 启动入口
# ============================================================

if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="127.0.0.1", port=9001)
