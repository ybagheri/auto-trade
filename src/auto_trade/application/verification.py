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
            protection = self._protection_mismatch(request, candidates[0])
            if protection is not None:
                return VerificationOutcome(False, protection)
            return VerificationOutcome(
                True,
                "new matching position detected",
                candidates[0].position_id,
            )
        if not candidates:
            return VerificationOutcome(False, "no new matching position detected")
        return VerificationOutcome(False, "multiple new matching positions detected")

    @staticmethod
    def _protection_mismatch(request: OrderRequest, position: PositionSnapshot) -> str | None:
        """Why the new position's protection does not match the approval, if it does not.

        A fill with the right volume but no stop loss would otherwise verify
        clean -- the one outcome this check exists to catch, and the reason a
        level the snapshot does not carry counts as a mismatch rather than as
        "nothing to compare". A request without a level asks nothing: there is
        no approved protection to carry.
        """
        if request.stop_loss is not None and position.stop_loss != request.stop_loss:
            return (
                "new position does not carry the approved stop loss "
                f"(approved {request.stop_loss}, observed {position.stop_loss}); "
                "refusing to report a fill MT5 may have left unprotected"
            )
        if request.take_profit is not None and position.take_profit != request.take_profit:
            return (
                "new position does not carry the approved take profit "
                f"(approved {request.take_profit}, observed {position.take_profit}); "
                "refusing to report a fill MT5 may have left unprotected"
            )
        return None

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
