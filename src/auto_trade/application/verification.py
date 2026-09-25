from __future__ import annotations

from collections.abc import Iterable

from ..domain.enums import OrderAction
from ..domain.models import OrderRequest, PositionSnapshot, VerificationOutcome


class PositionChangeVerifier:
    def verify(
        self,
        request: OrderRequest,
        before: Iterable[PositionSnapshot],
        after: Iterable[PositionSnapshot],
    ) -> VerificationOutcome:
        before_positions = tuple(before)
        after_positions = tuple(after)
        before_ids = {position.position_id for position in before_positions}
        expected_side = self._expected_side(request.action)
        candidates = [
            position
            for position in after_positions
            if position.position_id not in before_ids
            and position.symbol == request.symbol
            and position.side == expected_side
            and position.volume == request.volume
        ]
        if len(candidates) == 1:
            return VerificationOutcome(
                True,
                "new matching position detected",
                candidates[0].position_id,
            )
        if not candidates:
            return VerificationOutcome(False, "no new matching position detected")
        return VerificationOutcome(False, "multiple new matching positions detected")

    @staticmethod
    def _expected_side(action: OrderAction) -> str:
        if action in {
            OrderAction.BUY,
            OrderAction.BUY_LIMIT,
            OrderAction.BUY_STOP,
        }:
            return "BUY"
        if action in {
            OrderAction.SELL,
            OrderAction.SELL_LIMIT,
            OrderAction.SELL_STOP,
        }:
            return "SELL"
        raise ValueError(f"position verification is not supported for {action.value}")
