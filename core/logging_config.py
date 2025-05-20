# core/logging_config.py
"""
structlog でコンソール + ファイル出力を同時設定
-----------------------------------------------
import するだけで全ロガーに適用される。
"""

import json
import logging
import sys
from pathlib import Path
import structlog

# ---------- 出力ファイル ----------
LOG_DIR = Path("logs")
LOG_DIR.mkdir(exist_ok=True)
log_file = LOG_DIR / "agent.log"

# ---------- 標準 logging 基本設定 ----------
logging.basicConfig(
    level=logging.INFO,
    format="%(message)s",          # structlog が後で整形
    handlers=[
        logging.StreamHandler(sys.stdout),
        logging.FileHandler(log_file, encoding="utf-8"),
    ],
    force=True,                    # 既存ハンドラを置換
)

# ---------- structlog のラッパー ----------
structlog.configure(
    wrapper_class=structlog.make_filtering_bound_logger(logging.INFO),
    processors=[
        structlog.processors.add_log_level,
        structlog.processors.TimeStamper(fmt="iso"),
        # Stream 用: 人間が読みやすいカラー JSON
        structlog.dev.ConsoleRenderer(colors=True)  # Console
        if sys.stdout.isatty()
        else structlog.processors.JSONRenderer(),   # ファイル
    ],
)

# ---------- ルートロガーを structlog 化 ----------
logger = structlog.get_logger("root")
logger.info("🟢 structlog 初期化完了", log_file=str(log_file))
