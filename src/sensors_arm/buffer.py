from __future__ import annotations

import threading
from collections import deque
from typing import Generic, TypeVar

from sensors_arm.frame import Frame

T = TypeVar("T")


class LatestSlot(Generic[T]):
    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._value: T | None = None

    def set(self, value: T) -> None:
        with self._lock:
            self._value = value

    def clear(self) -> None:
        with self._lock:
            self._value = None

    def get(self) -> T | None:
        with self._lock:
            return self._value


class FrameRing:
    def __init__(self, maxlen: int = 64) -> None:
        self._lock = threading.Lock()
        self._deque: deque[Frame] = deque(maxlen=max(1, maxlen))
        self.latest = LatestSlot[Frame]()

    def push(self, frame: Frame) -> None:
        with self._lock:
            self._deque.append(frame)
        self.latest.set(frame)

    def clear(self) -> None:
        with self._lock:
            self._deque.clear()
        self.latest.clear()

    def snapshot(self) -> list[Frame]:
        with self._lock:
            return list(self._deque)
