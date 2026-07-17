# ============================================================
# 虚拟服务器 - Flask API
# ============================================================
import time
import threading
from flask import Flask, jsonify
from simulator import DataSimulator
import config

app = Flask(__name__)
simulator = DataSimulator(config)

# 线程安全锁
_lock = threading.Lock()
_latest_data = None


def data_generation_loop():
    """后台线程：每 DATA_INTERVAL 秒生成一次数据"""
    global _latest_data
    while True:
        with _lock:
            _latest_data = simulator.tick()
        time.sleep(config.DATA_INTERVAL)


@app.route("/api/data", methods=["GET"])
def get_data():
    """返回最新一次的数据快照"""
    with _lock:
        if _latest_data is None:
            return jsonify({"error": "数据尚未生成"}), 503
        return jsonify(_latest_data)


@app.route("/api/status", methods=["GET"])
def get_status():
    """返回服务器状态，方便调试"""
    return jsonify({
        "status": "running",
        "time_scale": config.TIME_SCALE,
        "interval": config.DATA_INTERVAL,
    })


if __name__ == "__main__":
    # 启动后台数据生成线程
    t = threading.Thread(target=data_generation_loop, daemon=True)
    t.start()

    print(f"[虚拟服务器] 启动于 {config.SERVER_HOST}:{config.SERVER_PORT}")
    print(f"[虚拟服务器] 时间倍速: {config.TIME_SCALE}x, 刷新间隔: {config.DATA_INTERVAL}s")
    app.run(host=config.SERVER_HOST, port=config.SERVER_PORT, debug=False)
