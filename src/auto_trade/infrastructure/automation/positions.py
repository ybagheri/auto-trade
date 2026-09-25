from __future__ import annotations

from decimal import Decimal, InvalidOperation
from typing import Any

from ...domain.exceptions import PositionSnapshotUnavailable
from ...domain.models import PositionSnapshot
from .window_manager import MT5WindowManager


class MT5PositionSnapshotProvider:
    def __init__(self, window_manager: MT5WindowManager) -> None:
        self.window_manager = window_manager

    def positions(self) -> tuple[PositionSnapshot, ...]:
        tables = [
            control
            for control in self.window_manager.root.descendants()
            if control.element_info.control_type == "List"
            and control.element_info.automation_id == "10328"
        ]
        if not tables:
            raise PositionSnapshotUnavailable("MT5 Trade position table was not found")
        rows = [
            control
            for control in tables[0].descendants()
            if control.element_info.control_type == "ListItem"
        ]
        if not rows:
            return ()
        snapshots = []
        for row in rows:
            snapshots.append(self._parse_row(row))
        return tuple(snapshots)

    @staticmethod
    def _parse_row(row: Any) -> PositionSnapshot:
        values = [
            str(child.window_text()).strip()
            for child in row.descendants()
            if child.element_info.control_type == "Text"
            and str(child.window_text()).strip()
        ]
        if len(values) < 5:
            raise PositionSnapshotUnavailable(
                "MT5 position row does not expose reliable Symbol/Ticket/Type/Volume values"
            )
        symbol, position_id, _time, position_type, volume_text = values[:5]
        if "buy" in position_type.lower():
            side = "BUY"
        elif "sell" in position_type.lower():
            side = "SELL"
        else:
            side = ""
        if not side:
            raise PositionSnapshotUnavailable("MT5 position row has an unsupported side")
        try:
            volume = Decimal(volume_text.replace(",", "."))
        except InvalidOperation as exc:
            raise PositionSnapshotUnavailable("MT5 position row has an invalid volume") from exc
        try:
            return PositionSnapshot(position_id, symbol, side, volume)
        except ValueError as exc:
            raise PositionSnapshotUnavailable("MT5 position row failed domain validation") from exc
