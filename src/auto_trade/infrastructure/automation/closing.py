"""The guarded position close.

Closing is the second control in this project that changes an account, so it is
governed exactly like the order control: refused by default, matched by name,
and verified afterwards by independent observation.

The hard part is not the click. The Trade grid on this build exposes a row's
rectangle but no row text, so a ticket cannot be read out of it. Rather than
guess a row, this module refuses whenever the mapping is not unambiguous:

- the observed snapshot must contain the ticket that is about to be closed;
- the snapshot must contain exactly one position, because that is the only case
  where "the first grid row" is provably the intended one;
- the grid must expose one position row, optionally followed by the account
  summary row MT5 renders underneath it;
- the context menu must contain exactly one entry named ``Close Position``, and
  that entry must carry the automation id measured on this build.

Anything else is a refusal, and the ticket is left open for a human.
"""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass
from typing import Any

# Measured on Alpari MT5 build 6184 by opening the Trade row context menu.
CLOSE_MENU_ITEM_NAME = "Close Position"
CLOSE_MENU_ITEM_ID = "33033"

# The Trade grid, and the account summary row MT5 draws below the positions.
TRADE_LIST_ID = "10328"
MAX_GRID_ROWS = 2

# Menu entries that look close enough to be dangerous by name alone. The name
# match below is exact, so these can never be selected; they are listed to make
# the reason for the exact match explicit.
FORBIDDEN_MENU_ITEMS = ("Close by", "Close 50%", "Close All", "Modify or Delete")


@dataclass(frozen=True)
class CloseGate:
    """Whether a position close may be used at all.

    ``enabled`` is an explicit opt-in, separate from the order control's opt-in.
    Closing is never reachable because an order was allowed.
    """

    enabled: bool = False
    dry_run: bool = True
    demo_only: bool = True
    kill_switch_active: bool = False

    def refusal(self) -> str:
        if not self.enabled:
            return "closing is disabled; set AUTO_TRADE_ENABLE_CLOSE=true to allow it"
        if self.kill_switch_active:
            return "kill switch is active"
        if self.dry_run:
            return "dry-run is enforced"
        if self.demo_only is False:
            return "demo-only policy is not satisfied"
        return ""


def only_close_entry(names: list[tuple[str, str]]) -> tuple[str, str]:
    """Return the one entry that is the close control, or refuse.

    Both the visible name and the measured automation id must match exactly one
    element. A menu without the entry, with a second candidate, or with a near
    miss such as ``Close by`` is refused rather than resolved by preference.
    """
    by_name = [
        (name, control_id)
        for name, control_id in names
        if name.split("\t")[0].strip() == CLOSE_MENU_ITEM_NAME
    ]
    if not by_name:
        raise LookupError(f"context menu has no {CLOSE_MENU_ITEM_NAME!r} entry")
    if len(by_name) > 1:
        raise LookupError(f"context menu has {len(by_name)} {CLOSE_MENU_ITEM_NAME!r} entries")
    name, control_id = by_name[0]
    if control_id != CLOSE_MENU_ITEM_ID:
        raise LookupError(
            f"{CLOSE_MENU_ITEM_NAME!r} has automation id {control_id!r}, "
            f"expected {CLOSE_MENU_ITEM_ID!r}"
        )
    return name, control_id


def position_row(rows: Sequence[Any]) -> Any:
    """Return the grid row that provably holds the intended position.

    With one open position, the first row is the position and the only optional
    second row is the account summary. Any other shape is refused, because a
    ticket cannot be matched to a row without reading the row's text.
    """
    if not 1 <= len(rows) <= MAX_GRID_ROWS:
        raise LookupError(
            f"the trade grid exposes {len(rows)} rows; refusing to guess which row "
            f"holds the position (expected 1, or 1 plus the account summary row)"
        )
    return rows[0]
