from datetime import UTC, datetime
from typing import Any


def signal_data(signal_id: str = "signal-1", now: datetime | None = None) -> dict[str, Any]:
    current = now or datetime.now(UTC)
    return {
        "id": signal_id,
        "timestamp": current.isoformat(),
        "source": "test",
        "symbol": "eurusd",
        "action": "BUY",
        "volume": 0.1,
    }
