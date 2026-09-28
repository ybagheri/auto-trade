from __future__ import annotations

import os
from dataclasses import dataclass
from decimal import Decimal
from pathlib import Path

from ...domain.enums import ConfirmationPolicy
from ...domain.exceptions import SignalSourceError
from ...domain.models import ExecutionPolicy, RiskLimits, TerminalProfile
from ...domain.protocols import SignalProvider
from ..automation.closing import CloseGate
from ..signals import HttpSignalProvider, NamedPipeSignalProvider, WebSocketSignalProvider
from .env_file import load_env_file


def _flag(name: str, default: str) -> bool:
    return os.getenv(name, default).strip().lower() in {"1", "true", "yes", "on"}


@dataclass(frozen=True)
class AppConfig:
    terminal_path: Path
    data_path: Path
    instance_name: str
    signal_directory: Path
    log_directory: Path
    policy: ExecutionPolicy
    risk: RiskLimits
    strategy_spec: str = ""
    http_signal_url: str = ""
    http_signal_token: str = ""
    pipe_signal_name: str = ""
    pipe_signal_token: str = ""
    ws_signal_url: str = ""
    ws_signal_token: str = ""

    @classmethod
    def from_env(cls) -> AppConfig:
        load_env_file()
        terminal_path = Path(
            os.getenv(
                "AUTO_TRADE_TERMINAL_PATH",
                r"C:\Program Files\Alpari MT5_2\terminal64.exe",
            )
        )
        data_path = Path(
            os.getenv(
                "AUTO_TRADE_DATA_PATH",
                r"C:\Users\BazikadeStore\AppData\Roaming\MetaQuotes\Terminal\AF19ECCF568F855DF9D3196BBF8BF315",
            )
        )
        signal_directory = Path(os.getenv("AUTO_TRADE_SIGNAL_DIR", "signals"))
        log_directory = Path(os.getenv("AUTO_TRADE_LOG_DIR", "logs"))
        allowed = frozenset(
            item.strip().upper()
            for item in os.getenv(
                "AUTO_TRADE_ALLOWED_SYMBOLS", "EURUSD,XAUUSD,YM"
            ).split(",")
            if item.strip()
        )
        return cls(
            terminal_path=terminal_path,
            data_path=data_path,
            instance_name=os.getenv("AUTO_TRADE_INSTANCE_NAME", "Alpari-MT5-Demo"),
            signal_directory=signal_directory,
            log_directory=log_directory,
            policy=ExecutionPolicy(
                dry_run=_flag("AUTO_TRADE_DRY_RUN", "true"),
                demo_only=_flag("AUTO_TRADE_DEMO_ONLY", "true"),
                confirmation=ConfirmationPolicy(
                    os.getenv(
                        "AUTO_TRADE_CONFIRMATION", "SINGLE_CONFIRMATION"
                    ).upper()
                ),
                # Final execution controls stay unavailable unless this is
                # explicitly turned on. It is never derived from a default.
                execution_enabled=_flag("AUTO_TRADE_ENABLE_EXECUTION", "false"),
            ),
            strategy_spec=os.getenv("AUTO_TRADE_STRATEGY", "").strip(),
            # The token is read from the environment and is never logged, printed
            # by diagnostics, or written to an audit record.
            http_signal_url=os.getenv("AUTO_TRADE_HTTP_SIGNAL_URL", "").strip(),
            http_signal_token=os.getenv("AUTO_TRADE_HTTP_SIGNAL_TOKEN", "").strip(),
            # Named-pipe and WebSocket sources are mutually exclusive with the
            # others only in practice: exactly one source is used per command, and
            # all three are pull-only, authenticated, and loopback-scoped.
            pipe_signal_name=os.getenv("AUTO_TRADE_PIPE_SIGNAL_NAME", "").strip(),
            pipe_signal_token=os.getenv("AUTO_TRADE_PIPE_SIGNAL_TOKEN", "").strip(),
            ws_signal_url=os.getenv("AUTO_TRADE_WS_SIGNAL_URL", "").strip(),
            ws_signal_token=os.getenv("AUTO_TRADE_WS_SIGNAL_TOKEN", "").strip(),
            risk=RiskLimits(
                allowed_symbols=allowed,
                max_volume=Decimal(os.getenv("AUTO_TRADE_MAX_VOLUME", "1.0")),
                max_orders_per_minute=int(
                    os.getenv("AUTO_TRADE_MAX_ORDERS_PER_MINUTE", "5")
                ),
                expiration_seconds=int(
                    os.getenv("AUTO_TRADE_SIGNAL_EXPIRATION_SECONDS", "10")
                ),
            ),
        )

    def terminal_profile(self) -> TerminalProfile:
        return TerminalProfile(
            name="alpari-demo",
            terminal_path=str(self.terminal_path),
            data_path=str(self.data_path),
            instance_name=self.instance_name,
        )

    def close_position_gate(self, kill_switch_active: bool) -> CloseGate:
        """Whether a position close may be used.

        Closing has its own opt-in. It is never reachable because an order was
        allowed, and it is refused while dry-run, while the kill switch is
        engaged, or when the demo-only policy is not met.
        """
        return CloseGate(
            enabled=_flag("AUTO_TRADE_ENABLE_CLOSE", "false"),
            dry_run=self.policy.dry_run,
            demo_only=self.policy.demo_only,
            kill_switch_active=kill_switch_active,
        )

    def http_signal_provider(self) -> HttpSignalProvider | None:
        """Return the configured HTTP signal source, or ``None`` when unset.

        The provider is returned unstarted: it still refuses a non-loopback or
        unauthenticated source when it is started.
        """
        if not self.http_signal_url:
            return None
        return HttpSignalProvider(self.http_signal_url, self.http_signal_token)

    def pipe_signal_provider(self) -> NamedPipeSignalProvider | None:
        if not self.pipe_signal_name:
            return None
        return NamedPipeSignalProvider(self.pipe_signal_name, self.pipe_signal_token)

    def ws_signal_provider(self) -> WebSocketSignalProvider | None:
        if not self.ws_signal_url:
            return None
        return WebSocketSignalProvider(self.ws_signal_url, self.ws_signal_token)

    def signal_source(self) -> SignalProvider | None:
        """Return the one configured pull source, or ``None`` when none is set.

        More than one configured source is refused rather than resolved by
        precedence. An operator who configured two of them has not decided which
        one is authoritative, and guessing would mean a signal can arrive from a
        source nobody is watching.
        """
        configured = {
            "AUTO_TRADE_HTTP_SIGNAL_URL": self.http_signal_provider(),
            "AUTO_TRADE_PIPE_SIGNAL_NAME": self.pipe_signal_provider(),
            "AUTO_TRADE_WS_SIGNAL_URL": self.ws_signal_provider(),
        }
        selected = sorted(name for name, provider in configured.items() if provider is not None)
        if len(selected) > 1:
            raise SignalSourceError(
                f"more than one signal source is configured ({', '.join(selected)}); "
                "configure exactly one"
            )
        if not selected:
            return None
        return configured[selected[0]]
