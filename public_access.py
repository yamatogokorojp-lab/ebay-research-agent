"""Lightweight process-wide guard against excessive calls to paid external APIs.

This is not an identity or DDoS protection service. For sustained public
production traffic, also enforce limits on the hosting platform/API provider.
"""
from collections import deque
from threading import Lock
from time import monotonic

class RequestBudget:
    def __init__(self, per_minute: int = 12, per_hour: int = 120):
        self.per_minute = per_minute
        self.per_hour = per_hour
        self._lock = Lock()
        self._minute = deque()
        self._hour = deque()

    def allow(self) -> bool:
        with self._lock:
            t = monotonic()
            while self._minute and self._minute[0] < t - 60:
                self._minute.popleft()
            while self._hour and self._hour[0] < t - 3600:
                self._hour.popleft()
            if len(self._minute) >= self.per_minute or len(self._hour) >= self.per_hour:
                return False
            self._minute.append(t)
            self._hour.append(t)
            return True
