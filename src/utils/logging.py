from __future__ import annotations

import logging
import sys
from pathlib import Path

_CONFIGURED = False


def setup_logging(level: str = "INFO", log_file: str | Path | None = None) -> None:
    global _CONFIGURED
    if _CONFIGURED:
        return
    level_int = getattr(logging, level.upper(), logging.INFO)
    root = logging.getLogger()
    root.setLevel(level_int)

    # Windows 콘솔(cp949)에서도 한글·특수문자 로그가 깨지지 않도록 UTF-8 로 맞춘다.
    if hasattr(sys.stdout, "reconfigure"):
        try:
            sys.stdout.reconfigure(encoding="utf-8", errors="replace")
        except (AttributeError, ValueError):  # pragma: no cover - 일부 래퍼 스트림
            pass

    fmt = logging.Formatter(
        fmt="[%(asctime)s] [%(levelname)s] %(name)s: %(message)s",
        datefmt="%Y-%m-%d %H:%M:%S",
    )
    handler = logging.StreamHandler(sys.stdout)
    handler.setFormatter(fmt)
    root.addHandler(handler)

    if log_file:
        Path(log_file).parent.mkdir(parents=True, exist_ok=True)
        fh = logging.FileHandler(str(log_file), encoding="utf-8")
        fh.setFormatter(fmt)
        root.addHandler(fh)

    # 외부 라이브러리 로그 축소
    logging.getLogger("urllib3").setLevel(logging.WARNING)
    logging.getLogger("httpx").setLevel(logging.WARNING)
    _CONFIGURED = True


def get_logger(name: str) -> logging.Logger:
    return logging.getLogger(name)