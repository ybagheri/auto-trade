from __future__ import annotations

import json
from decimal import Decimal
from pathlib import Path

from auto_trade.adapters.terminal import DryRunTerminalAdapter
from auto_trade.application.risk import RiskEngine
from auto_trade.application.workflow import ExecutionWorkflow
from auto_trade.domain.enums import ExecutionStatus
from auto_trade.domain.models import ExecutionPolicy, RiskLimits, TradeSignal
from auto_trade.domain.protocols import KillSwitch
from auto_trade.infrastructure.configuration import AppConfig
from auto_trade.infrastructure.logging import AuditLogger
from auto_trade.infrastructure.signals import FileSignalProvider

from ..helpers import signal_data


def test_signal_provider_to_workflow_integration(tmp_path: Path) -> None:
    signal_path = tmp_path / "signal.json"
    signal_path.write_text(json.dumps(signal_data()), encoding="utf-8")
    provider = FileSignalProvider(tmp_path)
    provider.start()
    signal = provider.receive()
    config = AppConfig.from_env()
    workflow = ExecutionWorkflow(
        adapter=DryRunTerminalAdapter(),
        risk_engine=RiskEngine(RiskLimits({"EURUSD"}, Decimal("0.10"), 5, 10)),
        profile=config.terminal_profile(),
        policy=ExecutionPolicy(dry_run=True),
        kill_switch=KillSwitch(),
        audit=AuditLogger(tmp_path / "logs").record,
    )
    result = workflow.execute(TradeSignal.from_dict(signal.to_dict()))
    assert result.status is ExecutionStatus.DRY_RUN
