import asyncio
import ctypes
import json
from collections.abc import Callable
from types import SimpleNamespace

import pytest

from windows_mcp.desktop import service
from windows_mcp.desktop.service import Desktop
from windows_mcp.desktop.views import Status, Window
from windows_mcp.tools import window as window_tool_module
from windows_mcp.tree.views import BoundingBox


class FakeMCP:
    def __init__(self) -> None:
        self.tools: dict[str, Callable] = {}

    def tool(self, *, name: str, **kwargs: object) -> Callable:
        def decorator(func: Callable) -> Callable:
            self.tools[name] = func
            return func

        return decorator


def _desktop() -> Desktop:
    desktop = Desktop.__new__(Desktop)
    desktop.desktop_state = None
    return desktop


def _window(title: str, handle: int = 100, process_id: int = 200) -> Window:
    return Window(
        name=title,
        is_browser=False,
        depth=0,
        status=Status.NORMAL,
        bounding_box=BoundingBox(left=0, top=0, right=100, bottom=100, width=100, height=100),
        handle=handle,
        process_id=process_id,
    )


def _patch_window_api(monkeypatch: pytest.MonkeyPatch, *, foreground: int = 100) -> list[tuple]:
    moves: list[tuple] = []
    outer_rect = {"value": (10, 20, 210, 170)}
    client_rect = {"value": (0, 0, 180, 120)}
    client_origin = {"value": (20, 50)}
    monkeypatch.setattr(service.win32gui, "IsWindow", lambda handle: handle == 100)
    monkeypatch.setattr(service.win32gui, "GetWindowRect", lambda handle: outer_rect["value"])
    monkeypatch.setattr(service.win32gui, "GetClientRect", lambda handle: client_rect["value"])
    monkeypatch.setattr(
        service.win32gui, "ClientToScreen", lambda handle, point: client_origin["value"]
    )
    monkeypatch.setattr(service.win32gui, "GetForegroundWindow", lambda: foreground)

    def move_window(handle: int, x: int, y: int, width: int, height: int, repaint: bool) -> None:
        moves.append((handle, x, y, width, height, repaint))
        outer_rect["value"] = (x, y, x + width, y + height)
        client_origin["value"] = (x + 10, y + 30)
        client_rect["value"] = (0, 0, width - 20, height - 30)

    monkeypatch.setattr(service.win32gui, "MoveWindow", move_window)
    monkeypatch.setattr(
        service, "Process", lambda pid: type("P", (), {"name": lambda self: "app.exe"})()
    )
    return moves


def test_find_exact_windows_filters_by_process_and_title(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    desktop = _desktop()
    _patch_window_api(monkeypatch)
    monkeypatch.setattr(desktop, "get_windows", lambda: ([_window("Target App")], {100}))

    result = desktop.find_exact_windows(title="target", process="APP.EXE")

    assert result == [
        {
            "handle": 100,
            "process_id": 200,
            "process": "app.exe",
            "process_path": None,
            "title": "Target App",
            "status": "Normal",
            "outer": {
                "left": 10,
                "top": 20,
                "width": 200,
                "height": 150,
                "right": 210,
                "bottom": 170,
            },
            "client": {
                "left": 20,
                "top": 50,
                "width": 180,
                "height": 120,
                "right": 200,
                "bottom": 170,
            },
        }
    ]


def test_activate_exact_window_verifies_foreground(monkeypatch: pytest.MonkeyPatch) -> None:
    desktop = _desktop()
    _patch_window_api(monkeypatch, foreground=100)
    monkeypatch.setattr(desktop, "get_windows", lambda: ([_window("Target App")], {100}))
    called: list[int] = []
    monkeypatch.setattr(desktop, "bring_window_to_top", lambda handle: called.append(handle))

    result = desktop.activate_exact_window(handle=100, process_id=200)

    assert result["handle"] == 100
    assert called == [100]


def test_activate_exact_window_fails_when_readback_differs(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    desktop = _desktop()
    _patch_window_api(monkeypatch, foreground=999)
    monkeypatch.setattr(desktop, "get_windows", lambda: ([_window("Target App")], {100}))
    monkeypatch.setattr(desktop, "bring_window_to_top", lambda handle: None)

    with pytest.raises(ValueError, match="Failed to activate"):
        desktop.activate_exact_window(handle=100, process_id=200)


def test_set_exact_client_bounds_converts_to_outer_bounds(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    desktop = _desktop()
    moves = _patch_window_api(monkeypatch)
    monkeypatch.setattr(desktop, "get_windows", lambda: ([_window("Target App")], {100}))

    desktop.set_exact_window_bounds(handle=100, process_id=200, client=[30, 70, 300, 200])

    assert moves == [(100, 20, 40, 320, 230, True)]


def test_client_bounds_adjustment_accounts_for_native_menu(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    desktop = _desktop()
    menu_flags: list[bool] = []

    monkeypatch.setattr(service.win32gui, "GetWindowLong", lambda *args: 0)
    monkeypatch.setattr(service.win32gui, "GetMenu", lambda handle: 1)

    def adjust_window_rect(
        rect_pointer: object,
        style: int,
        has_menu: bool,
        ex_style: int,
        dpi: int,
    ) -> int:
        menu_flags.append(bool(has_menu))
        rect = ctypes.cast(
            rect_pointer,
            ctypes.POINTER(ctypes.wintypes.RECT),
        ).contents
        rect.left = -10
        rect.top = -40
        rect.right = 310
        rect.bottom = 230
        return 1

    user32 = SimpleNamespace(
        GetDpiForWindow=lambda handle: 144,
        AdjustWindowRectExForDpi=adjust_window_rect,
    )
    monkeypatch.setattr(service.ctypes.windll, "user32", user32)

    result = desktop._outer_bounds_for_client(100, [30, 70, 300, 190])

    assert result == (20, 30, 320, 270)
    assert menu_flags == [True]


def test_window_tool_find_returns_json(monkeypatch: pytest.MonkeyPatch) -> None:
    desktop = _desktop()
    monkeypatch.setattr(
        desktop,
        "find_exact_windows",
        lambda **kwargs: [{"handle": 100, "title": "Target App"}],
    )
    mcp = FakeMCP()
    window_tool_module.register(mcp, get_desktop=lambda: desktop, get_analytics=lambda: None)

    result = json.loads(asyncio.run(mcp.tools["Window"](mode="find", title="Target")))

    assert result == {"windows": [{"handle": 100, "title": "Target App"}], "count": 1}


def test_window_tool_bounds_requires_handle() -> None:
    mcp = FakeMCP()
    window_tool_module.register(mcp, get_desktop=_desktop, get_analytics=lambda: None)

    with pytest.raises(ValueError, match="handle is required"):
        asyncio.run(mcp.tools["Window"](mode="bounds", outer=[0, 0, 100, 100]))


@pytest.mark.parametrize(
    "bounds",
    [[0, 0, 0, 100], [0, 0, 100, -1], [0, 0, 100.5, 100], "not-a-list"],
)
def test_window_tool_rejects_invalid_bounds(bounds: object) -> None:
    mcp = FakeMCP()
    window_tool_module.register(mcp, get_desktop=_desktop, get_analytics=lambda: None)

    with pytest.raises((ValueError, json.JSONDecodeError)):
        asyncio.run(mcp.tools["Window"](mode="bounds", handle=100, outer=bounds))
