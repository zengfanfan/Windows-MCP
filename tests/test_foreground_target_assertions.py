import pytest

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
