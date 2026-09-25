from __future__ import annotations

import os
from dataclasses import dataclass
from decimal import Decimal
from pathlib import Path

from ...domain.enums import ConfirmationPolicy
from ...domain.models import ExecutionPolicy, RiskLimits, TerminalProfile


@dataclass(frozen=True)
class AppConfig:
    terminal_path: Path
    data_path: Path
    instance_name: str
    signal_directory: Path
    log_directory: Path
    policy: ExecutionPolicy
    risk: RiskLimits

    @classmethod
    def from_env(cls) -> AppConfig:
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
            instance_name=os.getenv("AUTO_TRADE_INSTANCE_NAME", "Alpari Demo"),
            signal_directory=signal_directory,
            log_directory=log_directory,
            policy=ExecutionPolicy(
                dry_run=os.getenv("AUTO_TRADE_DRY_RUN", "true").lower()
                in {"1", "true", "yes"},
                demo_only=os.getenv("AUTO_TRADE_DEMO_ONLY", "true").lower()
                in {"1", "true", "yes"},
                confirmation=ConfirmationPolicy(
                    os.getenv(
                        "AUTO_TRADE_CONFIRMATION", "SINGLE_CONFIRMATION"
                    ).upper()
                ),
            ),
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
