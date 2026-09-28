from __future__ import annotations

import os
from dataclasses import dataclass
from decimal import Decimal
from pathlib import Path

from ...domain.enums import ConfirmationPolicy
from ...domain.models import ExecutionPolicy, RiskLimits, TerminalProfile
from ..signals import HttpSignalProvider
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

    def http_signal_provider(self) -> HttpSignalProvider | None:
        """Return the configured HTTP signal source, or ``None`` when unset.

        The provider is returned unstarted: it still refuses a non-loopback or
        unauthenticated source when it is started.
        """
        if not self.http_signal_url:
            return None
        return HttpSignalProvider(self.http_signal_url, self.http_signal_token)
