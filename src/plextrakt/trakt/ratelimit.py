import time


class WriteRateLimiter:
    def __init__(self, min_interval: float = 1.0, clock=time.monotonic, sleep=time.sleep):
        self._min_interval = min_interval
        self._clock = clock
        self._sleep = sleep
        self._last: float | None = None

    def wait(self) -> None:
        if self._last is not None:
            elapsed = self._clock() - self._last
            if elapsed < self._min_interval:
                self._sleep(self._min_interval - elapsed)
        self._last = self._clock()
