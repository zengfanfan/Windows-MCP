"""LaunchExecutable tool - strict non-shell executable launch."""

import json
import subprocess
import time
from pathlib import Path
from typing import Literal

from fastmcp import Context
from mcp.types import ToolAnnotations
from psutil import Process
from windows_mcp.infrastructure import with_analytics


def _as_args(value: list[str] | str | None) -> list[str]:
    if value is None:
        return []
    if isinstance(value, list):
        args = value
    else:
        args = json.loads(value)
    if not isinstance(args, list) or not all(isinstance(arg, str) for arg in args):
        raise ValueError("args must be a list of strings")
    return args


def _as_bool(value: bool | str) -> bool:
    return value is True or (isinstance(value, str) and value.lower() == "true")


def _resolve_executable(executable: str) -> Path:
    path = Path(executable).expanduser().resolve()
    if not path.is_file():
        raise ValueError(f"Executable does not exist: {path}")
    return path


def _resolve_cwd(cwd: str | None) -> Path | None:
    if cwd is None:
        return None
    path = Path(cwd).expanduser().resolve()
    if not path.is_dir():
        raise ValueError(f"Working directory does not exist: {path}")
    return path


def _process_executable(pid: int) -> str | None:
    try:
        return Process(pid).exe()
    except Exception:
        return None


def register(mcp, *, get_desktop, get_analytics):
    @mcp.tool(
        name="LaunchExecutable",
        description=(
            "Strictly launch one executable path with separated argv and optional cwd. "
            "Does not use a shell, Start Menu search, fuzzy matching, or file associations."
        ),
        annotations=ToolAnnotations(
            title="LaunchExecutable",
            readOnlyHint=False,
            destructiveHint=False,
            idempotentHint=False,
            openWorldHint=False,
        ),
    )
    @with_analytics(get_analytics(), "LaunchExecutable-Tool")
    def launch_executable_tool(
        executable: str,
        args: list[str] | str | None = None,
        cwd: str | None = None,
        wait_for_window: bool | str = False,
        expected_window_title: str | None = None,
        expected_window_process: str | None = None,
        expected_window_process_id: int | None = None,
        window_title_match: Literal["exact", "contains"] = "contains",
        window_process_strategy: Literal["launched", "any_matching_process"] = "launched",
        wait_timeout: float = 10.0,
        wait_interval: float = 0.25,
        ctx: Context = None,
    ) -> str:
        resolved_executable = _resolve_executable(executable)
        resolved_cwd = _resolve_cwd(cwd)
        resolved_args = _as_args(args)

        process = subprocess.Popen(
            [str(resolved_executable), *resolved_args],
            cwd=str(resolved_cwd) if resolved_cwd is not None else None,
            shell=False,
            stdin=subprocess.DEVNULL,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            close_fds=True,
        )
        launched_process_id = process.pid
        actual_executable = _process_executable(launched_process_id)
        wait_for_window = _as_bool(wait_for_window)

        window = None
        if wait_for_window:
            if window_title_match not in {"exact", "contains"}:
                raise ValueError('window_title_match must be "exact" or "contains"')
            if window_process_strategy not in {"launched", "any_matching_process"}:
                raise ValueError(
                    'window_process_strategy must be "launched" or "any_matching_process"'
                )
            if wait_timeout <= 0 or wait_timeout > 120:
                raise ValueError("wait_timeout must be greater than 0 and at most 120 seconds")
            if wait_interval <= 0 or wait_interval > 5:
                raise ValueError("wait_interval must be greater than 0 and at most 5 seconds")

            desktop = get_desktop()
            if desktop is None:
                raise ValueError("wait_for_window requires an initialized desktop service")
            deadline = time.monotonic() + wait_timeout
            process_id = (
                expected_window_process_id
                if expected_window_process_id is not None
                else launched_process_id
                if window_process_strategy == "launched"
                else None
            )
            last_count = 0
            while True:
                matches = desktop.find_exact_windows(
                    title=expected_window_title,
                    title_match=window_title_match,
                    process=expected_window_process,
                    process_id=process_id,
                    handle=None,
                )
                last_count = len(matches)
                if len(matches) == 1:
                    window = matches[0]
                    break
                if len(matches) > 1:
                    raise ValueError(
                        f"Launched window identity was ambiguous: {len(matches)} matches"
                    )
                if time.monotonic() >= deadline:
                    raise TimeoutError(
                        f"Timed out waiting for launched window: last match count was {last_count}"
                    )
                time.sleep(wait_interval)

        return json.dumps(
            {
                "pid": launched_process_id,
                "executable": str(resolved_executable),
                "actual_executable": actual_executable,
                "args": resolved_args,
                "cwd": str(resolved_cwd) if resolved_cwd is not None else None,
                "window": window,
            },
            indent=2,
        )
