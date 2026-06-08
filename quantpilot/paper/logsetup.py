"""페이퍼 런 로깅 설정. 7일 무인 가동은 사후 리뷰할 로그가 필수.

회전 파일(logs/paper-{run_key}.log) + 콘솔(tmux에 라이브 표시). logs/는 gitignore.
"""
from __future__ import annotations

import logging
import re
from logging.handlers import RotatingFileHandler
from pathlib import Path


def setup_paper_logger(run_key: str, log_dir: str = "logs",
                       max_bytes: int = 2_000_000, backups: int = 5) -> logging.Logger:
    """run_key별 로거 반환(회전 파일 + 콘솔). 재호출 시 핸들러 중복 추가 안 함."""
    safe = re.sub(r"[^A-Za-z0-9._-]", "_", run_key)
    Path(log_dir).mkdir(parents=True, exist_ok=True)
    logger = logging.getLogger(f"quantpilot.paper.{safe}")
    logger.setLevel(logging.INFO)
    if logger.handlers:   # 이미 구성됨(재호출/재시작) → 중복 핸들러 방지
        return logger
    fmt = logging.Formatter("%(asctime)s %(levelname)s %(message)s")
    fh = RotatingFileHandler(str(Path(log_dir) / f"paper-{safe}.log"),
                             maxBytes=max_bytes, backupCount=backups)
    fh.setFormatter(fmt)
    sh = logging.StreamHandler()
    sh.setFormatter(fmt)
    logger.addHandler(fh)
    logger.addHandler(sh)
    logger.propagate = False
    return logger
