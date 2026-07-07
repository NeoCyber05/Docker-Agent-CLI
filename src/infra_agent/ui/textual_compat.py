"""Compatibility patches for Textual framework bugs."""

from __future__ import annotations

from textual.screen import Screen

_PATCHED = False


def patch_selection_none_parent_crash() -> None:
    """Guard Screen._forward_event against a Textual race condition.

    If the widget under a MouseDown is removed from the DOM in the same
    tick the click is processed (e.g. a permission/confirm dialog answered
    via keyboard right as a click lands on it), Textual's arbitrary text
    selection code dereferences a None parent and crashes the whole app
    (AttributeError: 'NoneType' object has no attribute 'region').
    Confirmed still present in Textual 8.2.8 (latest); see
    https://github.com/Textualize/textual/issues/5629 / #6596.

    This does NOT disable text selection - normal clicks/drags keep
    working exactly as before. It only turns this specific, narrow crash
    into a no-op (the vanished widget simply doesn't start a selection).
    """
    global _PATCHED
    if _PATCHED:
        return
    _PATCHED = True
    original = Screen._forward_event

    def _safe_forward_event(self: Screen, event: object):
        try:
            return original(self, event)
        except AttributeError as err:
            if "region" not in str(err):
                raise
            self._select_state = None
            return None
        except AssertionError:
            # Textual 8.2.7 asserts parent is a Widget during selection start;
            # 8.2.8 drops the assert but can still crash on container.region.
            from textual import events as textual_events

            if isinstance(event, textual_events.MouseEvent):
                self._select_state = None
                return None
            raise

    Screen._forward_event = _safe_forward_event  # type: ignore[method-assign]


__all__ = ["patch_selection_none_parent_crash"]
