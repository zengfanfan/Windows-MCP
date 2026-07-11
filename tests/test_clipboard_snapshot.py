import ctypes

from windows_mcp.uia import core


def test_clipboard_snapshot_reports_open_failure(monkeypatch) -> None:
    monkeypatch.setattr(core, "_OpenClipboard", lambda value: False)

    assert core.TryGetClipboardText() == (False, "", False)


def test_clipboard_snapshot_preserves_empty_clipboard(monkeypatch) -> None:
    close_calls: list[bool] = []

    monkeypatch.setattr(core, "_OpenClipboard", lambda value: True)
    monkeypatch.setattr(
        core.ctypes.windll.user32,
        "IsClipboardFormatAvailable",
        lambda format_type: False,
    )
    monkeypatch.setattr(core.ctypes.windll.user32, "CountClipboardFormats", lambda: 0)
    monkeypatch.setattr(
        core.ctypes.windll.user32,
        "CloseClipboard",
        lambda: close_calls.append(True),
    )

    assert core.TryGetClipboardText() == (True, "", False)
    assert close_calls == [True]


def test_clipboard_snapshot_refuses_non_text_clipboard(monkeypatch) -> None:
    close_calls: list[bool] = []

    monkeypatch.setattr(core, "_OpenClipboard", lambda value: True)
    monkeypatch.setattr(
        core.ctypes.windll.user32,
        "IsClipboardFormatAvailable",
        lambda format_type: False,
    )
    monkeypatch.setattr(core.ctypes.windll.user32, "CountClipboardFormats", lambda: 1)
    monkeypatch.setattr(
        core.ctypes.windll.user32,
        "CloseClipboard",
        lambda: close_calls.append(True),
    )

    assert core.TryGetClipboardText() == (False, "", False)
    assert close_calls == [True]


def test_clipboard_snapshot_refuses_additional_formats(monkeypatch) -> None:
    close_calls: list[bool] = []

    monkeypatch.setattr(core, "_OpenClipboard", lambda value: True)
    monkeypatch.setattr(
        core.ctypes.windll.user32,
        "IsClipboardFormatAvailable",
        lambda format_type: True,
    )
    monkeypatch.setattr(core.ctypes.windll.user32, "CountClipboardFormats", lambda: 2)
    monkeypatch.setattr(
        core.ctypes.windll.user32,
        "CloseClipboard",
        lambda: close_calls.append(True),
    )

    assert core.TryGetClipboardText() == (False, "", False)
    assert close_calls == [True]


def test_clipboard_snapshot_reads_unicode_text(monkeypatch) -> None:
    text_buffer = ctypes.create_unicode_buffer("previous")
    close_calls: list[bool] = []
    unlock_calls: list[int] = []

    monkeypatch.setattr(core, "_OpenClipboard", lambda value: True)
    monkeypatch.setattr(
        core.ctypes.windll.user32,
        "IsClipboardFormatAvailable",
        lambda format_type: True,
    )
    monkeypatch.setattr(core.ctypes.windll.user32, "CountClipboardFormats", lambda: 1)
    monkeypatch.setattr(core.ctypes.windll.user32, "GetClipboardData", lambda format_type: 123)
    monkeypatch.setattr(
        core.ctypes.windll.kernel32,
        "GlobalLock",
        lambda handle: ctypes.addressof(text_buffer),
    )
    monkeypatch.setattr(
        core.ctypes.windll.kernel32,
        "GlobalUnlock",
        lambda handle: unlock_calls.append(handle.value),
    )
    monkeypatch.setattr(
        core.ctypes.windll.user32,
        "CloseClipboard",
        lambda: close_calls.append(True),
    )

    assert core.TryGetClipboardText() == (True, "previous", True)
    assert unlock_calls == [123]
    assert close_calls == [True]


def test_clear_clipboard_reports_result_and_closes(monkeypatch) -> None:
    close_calls: list[bool] = []

    monkeypatch.setattr(core, "_OpenClipboard", lambda value: True)
    monkeypatch.setattr(core.ctypes.windll.user32, "EmptyClipboard", lambda: True)
    monkeypatch.setattr(
        core.ctypes.windll.user32,
        "CloseClipboard",
        lambda: close_calls.append(True),
    )

    assert core.ClearClipboard() is True
    assert close_calls == [True]
