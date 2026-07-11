import pytest

from windows_mcp.desktop import service
from windows_mcp.desktop.service import Desktop


def _desktop() -> Desktop:
    desktop = Desktop.__new__(Desktop)
    desktop.desktop_state = None
    return desktop


def test_assert_foreground_target_returns_none_without_guards() -> None:
    desktop = _desktop()

    assert desktop.assert_foreground_target() is None


def test_assert_foreground_target_accepts_matching_title_and_process(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    desktop = _desktop()

    monkeypatch.setattr(
        desktop,
        "get_foreground_window_identity",
        lambda: {
            "handle": 100,
            "title": "Untitled - Notepad",
            "process": "notepad.exe",
            "process_id": 123,
            "outer": {"left": 0, "top": 0, "width": 100, "height": 100},
            "client": {"left": 0, "top": 0, "width": 100, "height": 100},
        },
    )

    result = desktop.assert_foreground_target(
        expected_window_title="notepad",
        expected_process="NOTEPAD.EXE",
        expected_window_handle=100,
        expected_process_id=123,
    )

    assert result == {
        "handle": 100,
        "title": "Untitled - Notepad",
        "process": "notepad.exe",
        "process_id": 123,
        "outer": {"left": 0, "top": 0, "width": 100, "height": 100},
        "client": {"left": 0, "top": 0, "width": 100, "height": 100},
    }


def test_assert_foreground_target_rejects_title_mismatch(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    desktop = _desktop()

    monkeypatch.setattr(
        desktop,
        "get_foreground_window_identity",
        lambda: {
            "handle": 100,
            "title": "Calculator",
            "process": "calc.exe",
            "process_id": 123,
            "outer": {"left": 0, "top": 0, "width": 100, "height": 100},
            "client": {"left": 0, "top": 0, "width": 100, "height": 100},
        },
    )

    with pytest.raises(ValueError, match="expected_window_title"):
        desktop.assert_foreground_target(expected_window_title="Notepad")


def test_assert_foreground_target_rejects_process_mismatch(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    desktop = _desktop()

    monkeypatch.setattr(
        desktop,
        "get_foreground_window_identity",
        lambda: {
            "handle": 100,
            "title": "Untitled - Notepad",
            "process": "notepad.exe",
            "process_id": 123,
            "outer": {"left": 0, "top": 0, "width": 100, "height": 100},
            "client": {"left": 0, "top": 0, "width": 100, "height": 100},
        },
    )

    with pytest.raises(ValueError, match="expected_process"):
        desktop.assert_foreground_target(expected_process="note.exe")


def test_assert_foreground_target_rejects_missing_foreground(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    desktop = _desktop()

    monkeypatch.setattr(desktop, "get_foreground_window_identity", lambda: None)

    with pytest.raises(ValueError, match="No foreground window"):
        desktop.assert_foreground_target(expected_process="notepad.exe")


def test_type_revalidates_target_after_focus_click_before_text(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    desktop = _desktop()
    events: list[str] = []
    expected_identity = {
        "handle": 100,
        "process_id": 123,
        "process": "notepad.exe",
        "title": "Notepad",
    }

    monkeypatch.setattr(service.uia, "Click", lambda *args, **kwargs: events.append("click"))
    monkeypatch.setattr(
        service.uia,
        "SendKeys",
        lambda *args, **kwargs: events.append("send_keys"),
    )

    def assert_target(**kwargs: object) -> dict[str, object]:
        events.append("guard")
        assert kwargs["expected_window_handle"] == 100
        return expected_identity

    monkeypatch.setattr(desktop, "assert_foreground_target", assert_target)

    result = desktop.type(
        loc=(10, 20),
        text="hello",
        expected_window_handle=100,
    )

    assert result == expected_identity
    assert events == ["click", "guard", "send_keys"]


def test_type_revalidates_after_waits_and_before_each_keyboard_action(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    desktop = _desktop()
    events: list[str] = []

    monkeypatch.setattr(service.uia, "Click", lambda *args, **kwargs: events.append("click"))
    monkeypatch.setattr(service, "sleep", lambda duration: events.append(f"sleep:{duration}"))
    monkeypatch.setattr(
        service.uia,
        "SendKeys",
        lambda keys, **kwargs: events.append(f"send:{keys}"),
    )
    monkeypatch.setattr(
        desktop,
        "assert_foreground_target",
        lambda **kwargs: events.append("guard") or {"handle": 100, "process_id": 123},
    )

    desktop.type(
        loc=(10, 20),
        text="hello",
        clear=True,
        press_enter=True,
        expected_window_handle=100,
    )

    assert events == [
        "click",
        "sleep:0.5",
        "guard",
        "send:{Ctrl}a",
        "guard",
        "send:{Back}",
        "guard",
        "send:hello",
        "guard",
        "send:{Enter}",
    ]


def test_type_restores_clipboard_when_post_wait_guard_fails(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    desktop = _desktop()
    clipboard_writes: list[str] = []
    guard_calls = 0

    monkeypatch.setattr(service.uia, "Click", lambda *args, **kwargs: None)
    monkeypatch.setattr(service.uia, "GetClipboardText", lambda: "previous")
    monkeypatch.setattr(service.uia, "SetClipboardText", clipboard_writes.append)
    monkeypatch.setattr(service, "sleep", lambda duration: None)
    monkeypatch.setattr(
        service.uia,
        "SendKeys",
        lambda *args, **kwargs: pytest.fail("text must not be pasted after guard failure"),
    )

    def assert_target(**kwargs: object) -> dict[str, object]:
        nonlocal guard_calls
        guard_calls += 1
        if guard_calls == 2:
            raise ValueError("foreground target mismatch")
        return {"handle": 100, "process_id": 123}

    monkeypatch.setattr(desktop, "assert_foreground_target", assert_target)

    with pytest.raises(ValueError, match="foreground target mismatch"):
        desktop.type(
            loc=(10, 20),
            text="this text is long enough to paste",
            expected_window_handle=100,
        )

    assert clipboard_writes == ["this text is long enough to paste", "previous"]
