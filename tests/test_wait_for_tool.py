from __future__ import annotations

import asyncio
from collections.abc import Callable

import pytest

from windows_mcp.desktop.views import DesktopState, Status, Window
from windows_mcp.tools.input import register
from windows_mcp.tree.views import BoundingBox, Center, TextElementNode, TreeElementNode, TreeState


class FakeMCP:
    def __init__(self) -> None:
        self.tools: dict[str, Callable] = {}

    def tool(self, *, name: str, **kwargs: object) -> Callable:
        def decorator(func: Callable) -> Callable:
            self.tools[name] = func
            return func

        return decorator


class FakeDesktop:
    def __init__(
        self,
        states: list[DesktopState],
        exact_windows: list[list[dict[str, object]]] | None = None,
    ) -> None:
        self.states = states
        self.exact_windows = exact_windows or []
        self.desktop_state: DesktopState | None = None
        self.calls: list[dict[str, object]] = []
        self.find_calls: list[dict[str, object]] = []
        self.foreground_identity: dict[str, object] | None = None

    def get_state(self, **kwargs: object) -> DesktopState:
        self.calls.append(kwargs)
        if self.states:
            self.desktop_state = self.states.pop(0)
        if self.desktop_state is None:
            raise RuntimeError("FakeDesktop has no desktop state")
        return self.desktop_state

    def find_exact_windows(self, **kwargs: object) -> list[dict[str, object]]:
        self.find_calls.append(kwargs)
        if self.exact_windows:
            return self.exact_windows.pop(0)
        return []

    def get_foreground_window_identity(self) -> dict[str, object] | None:
        return self.foreground_identity


def _box() -> BoundingBox:
    return BoundingBox(left=0, top=0, right=100, bottom=40, width=100, height=40)


def _window(name: str) -> Window:
    return Window(
        name=name,
        is_browser=False,
        depth=0,
        status=Status.NORMAL,
        bounding_box=_box(),
        handle=123,
        process_id=456,
    )


def _element(
    name: str,
    *,
    window_name: str = "Notepad",
    focused: bool = False,
) -> TreeElementNode:
    return TreeElementNode(
        name=name,
        control_type="Button",
        window_name=window_name,
        bounding_box=_box(),
        center=Center(x=50, y=20),
        metadata={"has_focused": focused},
    )


def _state(
    *,
    active_window_name: str = "Notepad",
    elements: list[TreeElementNode] | None = None,
    dom_texts: list[str] | None = None,
) -> DesktopState:
    active_window = _window(active_window_name)
    return DesktopState(
        active_desktop={"name": "Desktop 1"},
        all_desktops=[],
        active_window=active_window,
        windows=[],
        tree_state=TreeState(
            interactive_nodes=elements or [],
            dom_informative_nodes=[TextElementNode(text=text) for text in (dom_texts or [])],
        ),
    )


def _register_tools(desktop: FakeDesktop) -> dict[str, Callable]:
    mcp = FakeMCP()
    register(mcp, get_desktop=lambda: desktop, get_analytics=lambda: None)
    return mcp.tools


def test_wait_for_text_polls_until_dom_text_appears() -> None:
    desktop = FakeDesktop(
        [
            _state(dom_texts=["Loading"]),
            _state(dom_texts=["Ready for search"]),
        ]
    )
    tools = _register_tools(desktop)

    result = asyncio.run(
        tools["WaitFor"](
            condition="text_exists",
            text="ready",
            timeout=1,
            interval=0.001,
            use_dom=True,
        )
    )

    assert "condition 'text_exists' satisfied" in result
    assert len(desktop.calls) == 2
    assert desktop.calls[0]["use_dom"] is True
    assert desktop.calls[0]["use_vision"] is False


def test_wait_for_active_window_matches_by_window_name() -> None:
    desktop = FakeDesktop([_state(active_window_name="Untitled - Notepad")])
    tools = _register_tools(desktop)

    result = asyncio.run(
        tools["WaitFor"](
            condition="active_window",
            window_name="notepad",
            timeout=1,
            interval=0.001,
        )
    )

    assert "active window matched" in result


def test_wait_for_focused_element_matches_text_and_window() -> None:
    desktop = FakeDesktop(
        [
            _state(
                elements=[
                    _element("Cancel", focused=False),
                    _element("Search", window_name="Command Palette", focused=True),
                ]
            )
        ]
    )
    tools = _register_tools(desktop)

    result = asyncio.run(
        tools["WaitFor"](
            condition="focused_element",
            text="search",
            window_name="palette",
            timeout=1,
            interval=0.001,
        )
    )

    assert "focused element matched 'Search'" in result


def test_wait_for_element_enabled_alias_matches_interactive_node() -> None:
    desktop = FakeDesktop([_state(elements=[_element("Submit", window_name="Checkout")])])
    tools = _register_tools(desktop)

    result = asyncio.run(
        tools["WaitFor"](
            condition="enabled",
            text="submit",
            window_name="checkout",
            timeout=1,
            interval=0.001,
        )
    )

    assert "condition 'element_enabled' satisfied" in result


def test_wait_for_text_requires_text() -> None:
    desktop = FakeDesktop([_state()])
    tools = _register_tools(desktop)

    with pytest.raises(ValueError, match="text is required"):
        asyncio.run(tools["WaitFor"](condition="text_exists"))


def test_wait_for_timeout_reports_last_observed_state() -> None:
    desktop = FakeDesktop([_state(active_window_name="Explorer")])
    tools = _register_tools(desktop)

    with pytest.raises(TimeoutError, match="active window was 'Explorer'"):
        asyncio.run(
            tools["WaitFor"](
                condition="active_window",
                window_name="Terminal",
                timeout=0.01,
                interval=0.001,
            )
        )


def test_wait_for_foreground_window_matches_exact_handle() -> None:
    desktop = FakeDesktop(
        [_state(active_window_name="Target")],
        exact_windows=[
            [
                {
                    "handle": 123,
                    "process_id": 456,
                    "process": "target.exe",
                    "title": "Target",
                }
            ]
        ],
    )
    desktop.foreground_identity = {
        "handle": 123,
        "process_id": 456,
        "process": "target.exe",
        "title": "Target",
    }
    tools = _register_tools(desktop)

    result = asyncio.run(
        tools["WaitFor"](
            condition="foreground_window",
            handle=123,
            process_id=456,
            timeout=1,
            interval=0.001,
        )
    )

    assert "condition 'foreground_window' satisfied" in result
    assert desktop.find_calls[0]["handle"] == 123
    assert desktop.find_calls[0]["process_id"] == 456


def test_wait_for_window_bounds_stable_uses_exact_identity() -> None:
    window = {
        "handle": 123,
        "process_id": 456,
        "process": "target.exe",
        "title": "Target",
        "outer": {"left": 10, "top": 20, "width": 300, "height": 200},
        "client": {"left": 12, "top": 50, "width": 296, "height": 168},
    }
    desktop = FakeDesktop([], exact_windows=[[window], [window]])
    tools = _register_tools(desktop)

    result = asyncio.run(
        tools["WaitFor"](
            condition="window_bounds_stable",
            handle=123,
            bounds=[10, 20, 300, 200],
            stable_duration=0,
            timeout=1,
            interval=0.001,
        )
    )

    assert "condition 'window_bounds_stable' satisfied" in result


def test_wait_for_window_bounds_stability_restarts_after_match_interruption() -> None:
    window = {
        "handle": 123,
        "process_id": 456,
        "process": "target.exe",
        "title": "Target",
        "outer": {"left": 10, "top": 20, "width": 300, "height": 200},
        "client": {"left": 12, "top": 50, "width": 296, "height": 168},
    }
    desktop = FakeDesktop([], exact_windows=[[window], [], [window], [window]])
    tools = _register_tools(desktop)

    result = asyncio.run(
        tools["WaitFor"](
            condition="window_bounds_stable",
            handle=123,
            stable_duration=0.001,
            timeout=1,
            interval=0.001,
        )
    )

    assert "bounds stable" in result
    assert len(desktop.find_calls) >= 4


def test_wait_for_window_disappeared_succeeds_when_exact_match_absent() -> None:
    desktop = FakeDesktop([], exact_windows=[[]])
    tools = _register_tools(desktop)

    result = asyncio.run(
        tools["WaitFor"](
            condition="window_disappeared",
            handle=123,
            stable_duration=0,
            timeout=1,
            interval=0.001,
        )
    )

    assert "condition 'window_disappeared' satisfied" in result


def test_wait_for_window_disappeared_requires_stable_absence() -> None:
    window = {
        "handle": 123,
        "process_id": 456,
        "process": "target.exe",
        "title": "Target",
    }
    desktop = FakeDesktop([], exact_windows=[[], [window], [], []])
    tools = _register_tools(desktop)

    result = asyncio.run(
        tools["WaitFor"](
            condition="window_disappeared",
            handle=123,
            stable_duration=0.001,
            timeout=1,
            interval=0.001,
        )
    )

    assert "required stable duration" in result
    assert len(desktop.find_calls) >= 4


@pytest.mark.parametrize(
    ("argument", "value"),
    [
        ("timeout", float("nan")),
        ("interval", float("inf")),
        ("stable_duration", float("nan")),
    ],
)
def test_wait_for_rejects_non_finite_timing_values(argument: str, value: float) -> None:
    desktop = FakeDesktop([_state()])
    tools = _register_tools(desktop)

    with pytest.raises(ValueError, match=f"{argument} must be a finite number"):
        asyncio.run(
            tools["WaitFor"](
                condition="foreground_window",
                handle=123,
                **{argument: value},
            )
        )
