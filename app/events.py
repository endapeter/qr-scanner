"""In-process publish/subscribe broker for Server-Sent Events.

Every connected dashboard gets its own queue; scans are broadcast to all of
them and the client filters by its selected class.
"""

from __future__ import annotations

import json
import queue
from typing import Any


class ScanBroker:
    def __init__(self) -> None:
        self._clients: list[queue.Queue[str]] = []

    def subscribe(self) -> queue.Queue[str]:
        q: queue.Queue[str] = queue.Queue(maxsize=100)
        self._clients.append(q)
        return q

    def unsubscribe(self, q: queue.Queue[str]) -> None:
        try:
            self._clients.remove(q)
        except ValueError:
            pass

    def publish(self, event_type: str, data: dict[str, Any]) -> None:
        message = json.dumps({"type": event_type, **data}, default=str)
        for q in list(self._clients):
            try:
                q.put_nowait(message)
            except queue.Full:
                # A stalled client would block the scan path; drop the event for it.
                self._clients.remove(q)


broker = ScanBroker()
