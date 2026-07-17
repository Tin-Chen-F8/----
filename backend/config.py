# ============================================================
# 后端服务 - 可调参数配置
# ============================================================

POLL_INTERVAL = 10           # 轮询虚拟服务器间隔(秒)
RAW_RETENTION_DAYS = 7       # 原始数据保留天数
VIRTUAL_SERVER_URL = "http://127.0.0.1:9001/api/data"
BACKEND_HOST = "127.0.0.1"
BACKEND_PORT = 9002
DB_PATH = "data.db"          # SQLite 数据库文件路径
