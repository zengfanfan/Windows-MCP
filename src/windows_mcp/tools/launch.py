"""LaunchExecutable tool - strict non-shell executable launch."""

import json
import math
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


def _as_finite_float(value: float | int | str, name: str) -> float:
    try:
        parsed = float(value)
    except (TypeError, ValueError) as exc:
        raise ValueError(f"{name} must be a finite number") from exc
    if not math.isfinite(parsed):
        raise ValueError(f"{name} must be a finite number")
    return parsed


def _as_optional_positive_int(value: int | str | None, name: str) -> int | None:
    if value is None:
        return None
    if isinstance(value, bool):
        raise ValueError(f"{name} must be a positive integer")
    try:
        parsed = int(value)
    except (TypeError, ValueError) as exc:
        raise ValueError(f"{name} must be a positive integer") from exc
    if parsed <= 0 or (isinstance(value, float) and not value.is_integer()):
        raise ValueError(f"{name} must be a positive integer")
    return parsed


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


def _validate_window_wait_options(
    *,
    get_desktop,
    wait_for_window: bool,
    window_title_match: str,
    window_process_strategy: str,
    expected_window_title: str | None,
    expected_window_process: str | None,
    expected_window_process_id: int | None,
    wait_timeout: float,
    wait_interval: float,
):
    if not wait_for_window:
        return None
    if window_title_match not in {"exact", "contains"}:
        raise ValueError('window_title_match must be "exact" or "contains"')
    if window_process_strategy not in {"launched", "any_matching_process"}:
        raise ValueError('window_process_strategy must be "launched" or "any_matching_process"')
    if window_process_strategy == "launched" and expected_window_process_id is not None:
        raise ValueError(
            "expected_window_process_id cannot override the launched process id; "
            'use window_process_strategy="any_matching_process" instead'
        )
    if window_process_strategy == "any_matching_process" and not any(
        [expected_window_title, expected_window_process, expected_window_process_id is not None]
    ):
        raise ValueError(
            "any_matching_process requires expected_window_title, expected_window_process, "
            "or expected_window_process_id"
        )
    if wait_timeout <= 0 or wait_timeout > 120:
        raise ValueError("wait_timeout must be greater than 0 and at most 120 seconds")
    if wait_interval <= 0 or wait_interval > 5:
        raise ValueError("wait_interval must be greater than 0 and at most 5 seconds")

    desktop = get_desktop()
    if desktop is None:
        raise ValueError("wait_for_window requires an initialized desktop service")
    return desktop


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
        wait_for_window = _as_bool(wait_for_window)
        if wait_for_window:
            wait_timeout = _as_finite_float(wait_timeout, "wait_timeout")
            wait_interval = _as_finite_float(wait_interval, "wait_interval")
            expected_window_process_id = _as_optional_positive_int(
                expected_window_process_id,
                "expected_window_process_id",
            )
        desktop = _validate_window_wait_options(
            get_desktop=get_desktop,
            wait_for_window=wait_for_window,
            window_title_match=window_title_match,
            window_process_strategy=window_process_strategy,
            expected_window_title=expected_window_title,
            expected_window_process=expected_window_process,
            expected_window_process_id=expected_window_process_id,
            wait_timeout=wait_timeout,
            wait_interval=wait_interval,
        )

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

        window = None
        if wait_for_window:
            deadline = time.monotonic() + wait_timeout
            process_id = (
                launched_process_id
                if window_process_strategy == "launched"
                else expected_window_process_id
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
                        f"Launched process {launched_process_id} window identity was ambiguous: "
                        f"{len(matches)} matches; the launched process was not terminated"
                    )
                if time.monotonic() >= deadline:
                    raise TimeoutError(
                        f"Timed out waiting for launched process {launched_process_id} window: "
                        f"last match count was {last_count}; the launched process was not terminated"
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
