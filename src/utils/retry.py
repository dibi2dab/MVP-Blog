from __future__ import annotations

import random
import time
from collections.abc import Callable
from functools import wraps
from typing import Any, TypeVar

T = TypeVar("T")


class RetryExhaustedError(Exception):
    pass


def retry(
    max_attempts: int = 3,
    base_delay: float = 2.0,
    max_delay: float = 60.0,
    backoff_factor: float = 2.0,
    jitter: bool = True,
    exceptions: tuple[type[Exception], ...] = (Exception,),
    logger: Any = None,
) -> Callable[[Callable[..., T]], Callable[..., T]]:
    """지수 백오프 + 지터 기반 재시도 데코레이터. rate limit 대응."""

    def decorator(func: Callable[..., T]) -> Callable[..., T]:
        @wraps(func)
        def wrapper(*args: Any, **kwargs: Any) -> T:
            delay = base_delay
            last_err: Exception | None = None
            for attempt in range(1, max_attempts + 1):
                try:
                    return func(*args, **kwargs)
                except exceptions as e:
                    last_err = e
                    if logger:
                        logger.warning(
                            "%s attempt %d/%d failed: %s (retry in %.1fs)",
                            func.__name__,
                            attempt,
                            max_attempts,
                            e,
                            delay,
                        )
                    if attempt == max_attempts:
                        break
                    time.sleep(delay)
                    if jitter:
                        delay = min(max_delay, delay * backoff_factor) + random.uniform(0, delay * 0.25)
                    else:
                        delay = min(max_delay, delay * backoff_factor)
            raise RetryExhaustedError(f"{func.__name__} failed after {max_attempts} attempts") from last_err

        return wrapper

    return decorator


def retry_call(func: Callable[..., T], *args: Any, **kwargs: Any) -> T:
    """데코레이터 없이 함수 호출에 재시도를 적용한다."""
    cfg = kwargs.pop("retry_cfg", None) or {}
    decorated = retry(**cfg)(func)
    return decorated(*args, **kwargs)