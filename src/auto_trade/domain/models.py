from __future__ import annotations

from collections.abc import Mapping
from datetime import UTC, datetime
from decimal import Decimal, InvalidOperation
from typing import Any

from .enums import AccountType, ConfirmationPolicy, ExecutionStatus, OrderAction
from .exceptions import InvalidSignalError


def utc_now() -> datetime:
    return datetime.now(UTC)


def _decimal(value: Any, field: str) -> Decimal:
    try:
        result = Decimal(str(value))
    except (InvalidOperation, ValueError) as exc:
        raise InvalidSignalError(f"{field} must be numeric") from exc
    if not result.is_finite():
        raise InvalidSignalError(f"{field} must be finite")
    return result


def _timestamp(value: Any) -> datetime:
    if not isinstance(value, str) or not value.strip():
        raise InvalidSignalError("timestamp is required")
    normalized = value[:-1] + "+00:00" if value.endswith("Z") else value
    try:
        parsed = datetime.fromisoformat(normalized)
    except ValueError as exc:
        raise InvalidSignalError("timestamp must be ISO-8601") from exc
    if parsed.tzinfo is None:
        raise InvalidSignalError("timestamp must include a timezone")
    return parsed.astimezone(UTC)


class TradeSignal:
    def __init__(
        self,
        signal_id: str,
        timestamp: datetime,
        source: str,
        symbol: str,
        action: OrderAction,
        volume: Decimal,
        order_type: str | None = None,
        price: Decimal | None = None,
        stop_loss: Decimal | None = None,
        take_profit: Decimal | None = None,
        comment: str = "",
        strategy: str = "",
        confidence: float | None = None,
        expiration: datetime | None = None,
        metadata: Mapping[str, Any] | None = None,
    ) -> None:
        if not signal_id.strip():
            raise InvalidSignalError("id is required")
        if not source.strip():
            raise InvalidSignalError("source is required")
        if not symbol.strip():
            raise InvalidSignalError("symbol is required")
        if volume <= 0:
            raise InvalidSignalError("volume must be positive")
        if confidence is not None and not 0 <= confidence <= 1:
            raise InvalidSignalError("confidence must be between 0 and 1")
        self.signal_id = signal_id
        self.timestamp = timestamp.astimezone(UTC)
        self.source = source
        self.symbol = symbol.upper()
        self.action = action
        self.volume = volume
        self.order_type = order_type
        self.price = price
        self.stop_loss = stop_loss
        self.take_profit = take_profit
        self.comment = comment
        self.strategy = strategy
        self.confidence = confidence
        self.expiration = expiration.astimezone(UTC) if expiration else None
        self.metadata = dict(metadata or {})

    @classmethod
    def from_dict(cls, data: Mapping[str, Any]) -> TradeSignal:
        if not isinstance(data, Mapping):
            raise InvalidSignalError("signal must be an object")
        required = ("id", "timestamp", "source", "symbol", "action", "volume")
        missing = [key for key in required if key not in data]
        if missing:
            raise InvalidSignalError(f"missing fields: {', '.join(missing)}")
        try:
            action = OrderAction(str(data["action"]).upper())
        except ValueError as exc:
            raise InvalidSignalError("action is not supported") from exc
        return cls(
            signal_id=str(data["id"]),
            timestamp=_timestamp(data["timestamp"]),
            source=str(data["source"]),
            symbol=str(data["symbol"]),
            action=action,
            volume=_decimal(data["volume"], "volume"),
            order_type=str(data["order_type"]) if data.get("order_type") else None,
            price=_decimal(data["price"], "price") if data.get("price") is not None else None,
            stop_loss=_decimal(data["stop_loss"], "stop_loss")
            if data.get("stop_loss") is not None
            else None,
            take_profit=_decimal(data["take_profit"], "take_profit")
            if data.get("take_profit") is not None
            else None,
            comment=str(data.get("comment", "")),
            strategy=str(data.get("strategy", "")),
            confidence=float(data["confidence"]) if data.get("confidence") is not None else None,
            expiration=_timestamp(data["expiration"]) if data.get("expiration") else None,
            metadata=data.get("metadata", {}),
        )

    def is_expired(self, now: datetime | None = None) -> bool:
        if self.expiration is None:
            return False
        return (now or utc_now()) >= self.expiration

    def to_dict(self) -> dict[str, Any]:
        return {
            "id": self.signal_id,
            "timestamp": self.timestamp.isoformat().replace("+00:00", "Z"),
            "source": self.source,
            "symbol": self.symbol,
            "action": self.action.value,
            "volume": str(self.volume),
            "order_type": self.order_type,
            "price": str(self.price) if self.price is not None else None,
            "stop_loss": str(self.stop_loss) if self.stop_loss is not None else None,
            "take_profit": str(self.take_profit) if self.take_profit is not None else None,
            "comment": self.comment,
            "strategy": self.strategy,
            "confidence": self.confidence,
            "expiration": self.expiration.isoformat().replace("+00:00", "Z")
            if self.expiration
            else None,
            "metadata": self.metadata,
        }


class OrderRequest:
    def __init__(self, signal: TradeSignal) -> None:
        self.signal = signal
        self.symbol = signal.symbol
        self.action = signal.action
        self.volume = signal.volume
        self.price = signal.price
        self.stop_loss = signal.stop_loss
        self.take_profit = signal.take_profit


class TerminalProfile:
    def __init__(
        self,
        name: str,
        terminal_path: str,
        data_path: str,
        instance_name: str = "",
    ) -> None:
        self.name = name
        self.terminal_path = terminal_path
        self.data_path = data_path
        self.instance_name = instance_name


class RiskLimits:
    def __init__(
        self,
        allowed_symbols: set[str] | frozenset[str],
        max_volume: Decimal,
        max_orders_per_minute: int,
        expiration_seconds: int,
        max_open_positions: int | None = None,
    ) -> None:
        if max_volume <= 0 or max_orders_per_minute <= 0 or expiration_seconds <= 0:
            raise ValueError("risk limits must be positive")
        self.allowed_symbols = frozenset(symbol.upper() for symbol in allowed_symbols)
        self.max_volume = max_volume
        self.max_orders_per_minute = max_orders_per_minute
        self.expiration_seconds = expiration_seconds
        self.max_open_positions = max_open_positions


class ExecutionPolicy:
    def __init__(
        self,
        dry_run: bool = True,
        demo_only: bool = True,
        confirmation: ConfirmationPolicy = ConfirmationPolicy.SINGLE_CONFIRMATION,
    ) -> None:
        self.dry_run = dry_run
        self.demo_only = demo_only
        self.confirmation = confirmation


class AccountSnapshot:
    def __init__(
        self,
        account_type: AccountType = AccountType.UNKNOWN,
        open_positions: int = 0,
        connected: bool = False,
    ) -> None:
        self.account_type = account_type
        self.open_positions = open_positions
        self.connected = connected


class SymbolInfo:
    def __init__(self, symbol: str, available: bool, digits: int | None = None) -> None:
        self.symbol = symbol.upper()
        self.available = available
        self.digits = digits


class PositionSnapshot:
    def __init__(
        self,
        position_id: str,
        symbol: str,
        side: str,
        volume: Decimal,
    ) -> None:
        if not position_id.strip():
            raise ValueError("position_id is required")
        if side.upper() not in {"BUY", "SELL"}:
            raise ValueError("position side must be BUY or SELL")
        if volume <= 0:
            raise ValueError("position volume must be positive")
        self.position_id = position_id
        self.symbol = symbol.upper()
        self.side = side.upper()
        self.volume = volume


class VerificationOutcome:
    def __init__(self, verified: bool, message: str, position_id: str | None = None) -> None:
        self.verified = verified
        self.message = message
        self.position_id = position_id


class ExecutionResult:
    def __init__(
        self,
        execution_id: str,
        signal_id: str,
        status: ExecutionStatus,
        state: str,
        message: str,
        order_reference: str | None = None,
        error: str | None = None,
    ) -> None:
        self.execution_id = execution_id
        self.signal_id = signal_id
        self.status = status
        self.state = state
        self.message = message
        self.order_reference = order_reference
        self.error = error


class AuditEvent:
    def __init__(
        self,
        component: str,
        event_type: str,
        message: str,
        signal_id: str | None = None,
        execution_id: str | None = None,
        symbol: str | None = None,
        action: str | None = None,
        volume: Decimal | None = None,
        state: str | None = None,
        error: str | None = None,
    ) -> None:
        self.timestamp = utc_now().isoformat().replace("+00:00", "Z")
        self.component = component
        self.event_type = event_type
        self.message = message
        self.signal_id = signal_id
        self.execution_id = execution_id
        self.symbol = symbol
        self.action = action
        self.volume = str(volume) if volume is not None else None
        self.state = state
        self.error = error

    def to_dict(self) -> dict[str, Any]:
        return {
            "timestamp": self.timestamp,
            "component": self.component,
            "event_type": self.event_type,
            "signal_id": self.signal_id,
            "execution_id": self.execution_id,
            "symbol": self.symbol,
            "action": self.action,
            "volume": self.volume,
            "state": self.state,
            "message": self.message,
            "error": self.error,
        }
