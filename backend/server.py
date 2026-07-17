# ============================================================
# 后端服务 - Flask API + 数据轮询
# ============================================================
import time
import threading
import requests
from datetime import datetime, timedelta
from flask import Flask, jsonify, request, Response
from flask_cors import CORS
import config
import database
from aggregator import check_and_aggregate

app = Flask(__name__)
CORS(app)


def poll_loop():
    """后台线程：每 POLL_INTERVAL 秒从虚拟服务器拉取数据并存储"""
    # 等待虚拟服务器先启动
    time.sleep(2)

    while True:
        try:
            resp = requests.get(config.VIRTUAL_SERVER_URL, timeout=5)
            if resp.status_code == 200:
                data = resp.json()
                database.insert_raw_data(data)
                check_and_aggregate(data["timestamp"])

                # 定期清理过期数据
                if int(time.time()) % 3600 < config.POLL_INTERVAL:
                    database.cleanup_old_data()
        except requests.RequestException as e:
            print(f"[后端] 拉取数据失败: {e}")
        except Exception as e:
            print(f"[后端] 存储数据失败: {e}")

        time.sleep(config.POLL_INTERVAL)


# ==================== API 路由 ====================

@app.route("/api/latest", methods=["GET"])
def api_latest():
    """获取最新数据快照"""
    row = database.get_latest()
    if not row:
        return jsonify({"error": "暂无数据"}), 503
    # 转换 row 为普通 dict
    result = dict(row)
    # 解析 quality_top10 JSON
    if result.get("quality_top10"):
        import json
        try:
            result["quality_top10"] = json.loads(result["quality_top10"])
        except json.JSONDecodeError:
            pass
    return jsonify(result)


@app.route("/api/raw", methods=["GET"])
def api_raw():
    """获取原始数据点"""
    metric = request.args.get("metric", "")
    start = request.args.get("start")
    end = request.args.get("end")
    limit = request.args.get("limit", 200, type=int)

    if metric not in database.ALL_METRICS:
        return jsonify({"error": f"未知指标: {metric}"}), 400

    data = database.get_raw_data(metric, start=start, end=end, limit=limit)
    return jsonify(data)


@app.route("/api/stats", methods=["GET"])
def api_stats():
    """获取聚合统计数据"""
    metric = request.args.get("metric", "")
    start = request.args.get("start", "")
    end = request.args.get("end", "")
    granularity = request.args.get("granularity", "hourly")

    if metric not in database.ALL_METRICS:
        return jsonify({"error": f"未知指标: {metric}"}), 400

    if granularity not in ("raw", "hourly", "daily", "3day"):
        return jsonify({"error": f"不支持的粒度: {granularity}"}), 400

    if not start:
        start = (datetime.now() - timedelta(days=1)).isoformat()
    if not end:
        end = datetime.now().isoformat()

    data = database.get_stats(metric, start, end, granularity)
    return jsonify(data)


@app.route("/api/multi-stats", methods=["GET"])
def api_multi_stats():
    """批量获取多个指标的聚合统计数据"""
    metrics_str = request.args.get("metrics", "")
    start = request.args.get("start", "")
    end = request.args.get("end", "")
    granularity = request.args.get("granularity", "hourly")

    if not metrics_str:
        return jsonify({"error": "请指定 metrics 参数（逗号分隔）"}), 400

    metrics_list = [m.strip() for m in metrics_str.split(",") if m.strip() in database.NUMERIC_METRICS]

    if not start:
        start = (datetime.now() - timedelta(days=1)).isoformat()
    if not end:
        end = datetime.now().isoformat()

    result = {}
    for metric in metrics_list:
        data = database.get_stats(metric, start, end, granularity)
        result[metric] = data

    return jsonify(result)


@app.route("/api/export", methods=["GET"])
def api_export():
    """导出 CSV"""
    metrics_str = request.args.get("metrics", "")
    start = request.args.get("start", "")
    end = request.args.get("end", "")

    if not metrics_str:
        return jsonify({"error": "请指定 metrics 参数（逗号分隔）"}), 400

    metrics_list = [m.strip() for m in metrics_str.split(",")]
    csv_content = database.export_csv(metrics_list, start, end)

    return Response(
        csv_content,
        mimetype="text/csv",
        headers={
            "Content-Disposition": f"attachment; filename=data_{datetime.now().strftime('%Y%m%d_%H%M%S')}.csv"
        }
    )


@app.route("/api/metrics", methods=["GET"])
def api_metrics():
    """获取指标元信息列表"""
    return jsonify(database.get_metrics_info())


@app.route("/api/top10", methods=["GET"])
def api_top10():
    """获取最新的质量问题Top10"""
    data = database.get_latest_top10()
    return jsonify(data)


@app.route("/api/status", methods=["GET"])
def api_status():
    """后端状态"""
    latest = database.get_latest()
    return jsonify({
        "status": "running",
        "latest_timestamp": latest["timestamp"] if latest else None,
        "poll_interval": config.POLL_INTERVAL,
    })


if __name__ == "__main__":
    # 初始化数据库
    database.init_db()

    # 启动数据轮询线程
    t = threading.Thread(target=poll_loop, daemon=True)
    t.start()

    print(f"[后端服务] 启动于 {config.BACKEND_HOST}:{config.BACKEND_PORT}")
    print(f"[后端服务] 轮询间隔: {config.POLL_INTERVAL}s, 目标: {config.VIRTUAL_SERVER_URL}")
    app.run(host=config.BACKEND_HOST, port=config.BACKEND_PORT, debug=False)
