import asyncio
import json
from collections.abc import Callable
from pathlib import Path
from types import SimpleNamespace

import pytest

from windows_mcp.tools import launch


class FakeMCP:
    def __init__(self) -> None:
        self.tools: dict[str, Callable] = {}

    def tool(self, *, name: str, **kwargs: object) -> Callable:
        def decorator(func: Callable) -> Callable:
            self.tools[name] = func
            return func

        return decorator


def _tools(desktop: object = None) -> dict[str, Callable]:
    mcp = FakeMCP()
    launch.register(mcp, get_desktop=lambda: desktop, get_analytics=lambda: None)
    return mcp.tools


def test_launch_executable_preserves_argv_and_uses_no_shell(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    exe = tmp_path / "app.exe"
    exe.write_text("", encoding="utf-8")
    cwd = tmp_path / "work dir"
    cwd.mkdir()
    popen_calls: list[dict[str, object]] = []

    def fake_popen(command: list[str], **kwargs: object) -> SimpleNamespace:
        popen_calls.append({"command": command, **kwargs})
        return SimpleNamespace(pid=1234)

    monkeypatch.setattr(launch.subprocess, "Popen", fake_popen)

    result = json.loads(
        asyncio.run(
            _tools()["LaunchExecutable"](
                executable=str(exe),
                args=["--name", "value with spaces", "", "-dash"],
                cwd=str(cwd),
            )
        )
    )

    assert result == {
        "pid": 1234,
        "executable": str(exe.resolve()),
        "actual_executable": None,
        "args": ["--name", "value with spaces", "", "-dash"],
        "cwd": str(cwd.resolve()),
        "window": None,
    }
    assert popen_calls == [
        {
            "command": [
                str(exe.resolve()),
                "--name",
                "value with spaces",
                "",
                "-dash",
            ],
            "cwd": str(cwd.resolve()),
            "shell": False,
            "stdin": launch.subprocess.DEVNULL,
            "stdout": launch.subprocess.DEVNULL,
            "stderr": launch.subprocess.DEVNULL,
            "close_fds": True,
        }
    ]


def test_launch_executable_accepts_json_string_args(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    exe = tmp_path / "app.exe"
    exe.write_text("", encoding="utf-8")
    monkeypatch.setattr(launch.subprocess, "Popen", lambda *args, **kwargs: SimpleNamespace(pid=1))

    result = json.loads(
        asyncio.run(
            _tools()["LaunchExecutable"](
                executable=str(exe),
                args='["--flag", "hello"]',
            )
        )
    )

    assert result["args"] == ["--flag", "hello"]


def test_launch_executable_rejects_missing_executable(tmp_path: Path) -> None:
    with pytest.raises(ValueError, match="Executable does not exist"):
        asyncio.run(_tools()["LaunchExecutable"](executable=str(tmp_path / "missing.exe")))


def test_launch_executable_rejects_missing_cwd(tmp_path: Path) -> None:
    exe = tmp_path / "app.exe"
    exe.write_text("", encoding="utf-8")

    with pytest.raises(ValueError, match="Working directory does not exist"):
        asyncio.run(
            _tools()["LaunchExecutable"](
                executable=str(exe),
                cwd=str(tmp_path / "missing"),
            )
        )


def test_launch_executable_can_wait_for_verified_window(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    exe = tmp_path / "app.exe"
    exe.write_text("", encoding="utf-8")
    monkeypatch.setattr(
        launch.subprocess, "Popen", lambda *args, **kwargs: SimpleNamespace(pid=1234)
    )
    window = {
        "handle": 100,
        "process_id": 1234,
        "process": "app.exe",
        "title": "Target",
    }

    class FakeDesktop:
        def __init__(self) -> None:
            self.calls: list[dict[str, object]] = []

        def find_exact_windows(self, **kwargs: object) -> list[dict[str, object]]:
            self.calls.append(kwargs)
            return [window]

    desktop = FakeDesktop()

    result = json.loads(
        asyncio.run(
            _tools(desktop)["LaunchExecutable"](
                executable=str(exe),
                wait_for_window=True,
                expected_window_title="Target",
                wait_timeout=1,
                wait_interval=0.001,
            )
        )
    )

    assert result["window"] == window
    assert desktop.calls == [
        {
            "title": "Target",
            "title_match": "contains",
            "process": None,
            "process_id": 1234,
            "handle": None,
        }
    ]
