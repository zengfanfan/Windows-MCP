"""Indicator geometry, lifecycle, and screenshot exclusion checks."""

import threading
import time
from contextlib import contextmanager

from PIL import Image
import pytest

from windows_mcp.desktop import control_overlay, flash_overlay
from windows_mcp.desktop.service import Desktop


@pytest.fixture(autouse=True)
def _stop_indicator():
    control_overlay.stop()
    yield
    control_overlay.stop()


def _assert_premultiplied(bgra: bytes) -> None:
    for offset in range(0, len(bgra), 4):
        blue, green, red, alpha = bgra[offset : offset + 4]
        assert blue <= alpha and green <= alpha and red <= alpha


def _alpha_at(bgra: bytes, width: int, x: int, y: int) -> int:
    return bgra[(y * width + x) * 4 + 3]


def test_notice_uses_clear_english_and_transparent_corners():
    assert control_overlay._NOTICE_TITLE == "AI is controlling this computer"
    assert control_overlay._NOTICE_HINT == "Press Ctrl + Alt + Shift + Backspace to take over"
    assert control_overlay._NOTICE_SHORTCUT == "Ctrl + Alt + Shift + Backspace"
    assert control_overlay._NOTICE_NOTE == "AI resumes after 10 seconds without your input"
    notice = control_overlay._notice_bitmap(1920)
    assert notice is not None
    width, height, bgra = notice
    assert 540 <= width < 1920 and height >= 120  # Full-sized type on an ordinary monitor.
    assert len(bgra) == width * height * 4
    assert _alpha_at(bgra, width, 0, 0) == 0
    assert _alpha_at(bgra, width, 10, height // 2) == 230  # 230/255 is 0.9 rounded.
    assert max(bgra[3::4]) == 255  # Text stays fully legible while the glow breathes.
    assert any(bgra[offset : offset + 4] == b"\x00\x00\x00\xff" for offset in range(0, len(bgra), 4))
    narrow = control_overlay._notice_bitmap(300)
    assert narrow is not None and narrow[0] <= 268


def test_notice_outer_glow_fades_without_changing_the_panel():
    width, height = 400, 100
    pad = control_overlay._NOTICE_GLOW_PAD
    glow = control_overlay._notice_glow_bitmap(width, height, (45, 145, 255))
    glow_width = width + 2 * pad
    _assert_premultiplied(glow)
    assert len(glow) == glow_width * (height + 2 * pad) * 4
    middle_y = pad + height // 2
    assert _alpha_at(glow, glow_width, pad + width // 2, middle_y) == 0
    assert _alpha_at(glow, glow_width, 0, 0) == 0
    assert 208 <= max(glow[3::4]) <= 212  # Twice the previous aura peak of about 105.
    assert _alpha_at(glow, glow_width, pad - 1, middle_y) > _alpha_at(
        glow, glow_width, pad - 15, middle_y
    ) > 0


def test_breath_opacity_is_smooth_periodic_and_never_disappears():
    opacity = control_overlay._breath_opacity
    period = control_overlay._BREATH_PERIOD_SECONDS
    assert opacity(0) == opacity(period) == 255
    assert opacity(period / 2) == control_overlay._BREATH_MIN_ALPHA == 140
    assert opacity(period / 4) == opacity(3 * period / 4)
    frames = [opacity(index * control_overlay._REFRESH_SECONDS) for index in range(61)]
    assert all(140 <= value <= 255 for value in frames)
    assert max(abs(a - b) for a, b in zip(frames, frames[1:])) <= 7


def test_layer_opacity_updates_only_on_change_and_fails_closed(monkeypatch):
    layer = object.__new__(control_overlay._Layer)
    layer.hwnd = 123
    layer.x, layer.y, layer.width, layer.height = 10, 20, 1, 1
    layer.bgra = bytes((0, 0, 0, 0))
    layer.opacity = None
    calls = []

    def push_bitmap(*args, **kwargs):
        calls.append((args, kwargs))

    monkeypatch.setattr(flash_overlay, "_push_bitmap", push_bitmap)
    layer.set_opacity(200)
    layer.set_opacity(200)
    layer.set_opacity(140)
    assert calls == [
        ((123, 10, 20, 1, 1, layer.bgra), {"opacity": 200}),
        ((123, 10, 20, 1, 1, layer.bgra), {"opacity": 140}),
    ]

    def failed_upload(*args, **kwargs):
        raise OSError("upload failed")

    monkeypatch.setattr(flash_overlay, "_push_bitmap", failed_upload)
    with pytest.raises(OSError, match="upload failed"):
        layer.set_opacity(255)
    assert layer.opacity == 140


def test_edge_and_cursor_have_soft_glow_without_a_solid_contour():
    size = control_overlay._BORDER
    assert size == 56  # The requested doubling of the former 28-pixel glow.
    for side in ("left", "right", "top", "bottom"):
        width = size * 3 if side in ("top", "bottom") else size
        height = size if side in ("top", "bottom") else size * 3
        edge = control_overlay._edge_bitmap(width, height, side, (45, 145, 255))
        assert len(edge) == width * height * 4
        _assert_premultiplied(edge)
        alphas = (
            [_alpha_at(edge, width, x, height // 2) for x in range(width)]
            if side in ("left", "right")
            else [_alpha_at(edge, width, width // 2, y) for y in range(height)]
        )
        if side in ("right", "bottom"):
            alphas.reverse()
        assert alphas[0] == max(alphas) == 240  # Twice the previous edge opacity.
        assert alphas[-1] == 0
        assert all(a >= b for a, b in zip(alphas, alphas[1:]))
        assert max(a - b for a, b in zip(alphas, alphas[1:])) <= 8
        assert 30 <= alphas[40] <= 50  # The glow remains broad but fades inward.

    glow = control_overlay._cursor_bitmap((45, 145, 255))
    width = control_overlay._CURSOR_SIZE
    assert len(glow) == width**2 * 4
    _assert_premultiplied(glow)
    alphas = [glow[((width // 2) * width + x) * 4 + 3] for x in range(width // 2, width)]
    assert glow[3] == 0  # Transparent square corners.
    assert alphas[0] == 0 < alphas[10]  # Cursor center is fully transparent.
    assert alphas[10] > alphas[25] > alphas[-1]
    assert alphas[-1] == 0
    assert max(alphas) == 176  # Twice the previous cursor glow peak of 88.
    assert max(abs(a - b) for a, b in zip(alphas, alphas[1:])) < 30


def test_corner_glow_joins_edges_without_double_opacity():
    border = control_overlay._BORDER
    width = border * 4
    top = control_overlay._edge_bitmap(width, border, "top", (45, 145, 255))
    bottom = control_overlay._edge_bitmap(width, border, "bottom", (45, 145, 255))
    left = control_overlay._edge_bitmap(border, border, "left", (45, 145, 255))
    assert _alpha_at(top, width, 0, 0) == control_overlay._glow_alpha(0)
    assert _alpha_at(top, width, width - 1, 0) == control_overlay._glow_alpha(0)
    for horizontal in (top, bottom):
        for x_depth in (1, 5, 10, 20, 40, 55):
            side_alpha = _alpha_at(left, border, x_depth, border // 2)
            for y_depth in (1, 5, 10, 20, 40, 55):
                y = y_depth if horizontal is top else border - 1 - y_depth
                straight_alpha = _alpha_at(horizontal, width, width // 2, y)
                expected = control_overlay._glow_alpha(min(x_depth, y_depth))
                assert expected <= max(side_alpha, straight_alpha)
                assert _alpha_at(horizontal, width, x_depth, y) == expected
                assert _alpha_at(horizontal, width, width - 1 - x_depth, y) == expected


def test_multimonitor_creates_narrow_clickthrough_layers(monkeypatch):
    made = []

    class FakeLayer:
        def __init__(self, x, y, width, height, bgra, name, *, breathes=True):
            made.append((x, y, width, height, name, breathes))

        def close(self):
            pass

    monkeypatch.setattr(control_overlay, "_Layer", FakeLayer)
    monkeypatch.setattr(control_overlay._user32, "GetCursorPos", lambda ptr: True)
    rects = ((-1920, 0, 0, 1080), (0, 0, 2560, 1440))
    layers, ring = control_overlay._build_layers(rects, pending=False)
    assert len(layers) == 12
    assert ring is not None
    border = control_overlay._BORDER
    assert made[0][:4] == (-1920, 0, 1920, border)
    assert made[2][:4] == (-1920, border, border, 1080 - 2 * border)
    assert made[3][:4] == (-border, border, border, 1080 - 2 * border)
    assert made[4][1] == border and made[4][4:] == ("0_notice_glow", True)
    assert made[5][1] == border + control_overlay._NOTICE_GLOW_PAD
    assert made[5][4:] == ("0_notice", False)
    assert made[4][0] == made[5][0] - control_overlay._NOTICE_GLOW_PAD
    assert abs((made[5][0] + made[5][2] / 2) - (-1920 / 2)) <= 1
    assert made[6][:4] == (0, 0, 2560, border)
    assert made[8][:4] == (0, border, border, 1440 - 2 * border)
    assert made[9][:4] == (2560 - border, border, border, 1440 - 2 * border)
    assert made[10][1] == border and made[10][4:] == ("1_notice_glow", True)
    assert made[11][1] == border + control_overlay._NOTICE_GLOW_PAD
    assert made[11][4:] == ("1_notice", False)
    assert abs((made[11][0] + made[11][2] / 2) - 1280) <= 1
    assert all(
        w <= border or h <= border
        for _, _, w, h, name, _ in made
        if name != "cursor" and not name.endswith(("notice", "notice_glow"))
    )


@pytest.mark.parametrize("width", [300, 400])
def test_notice_glow_stays_on_its_monitor_when_narrow(monkeypatch, width):
    made = []

    class FakeLayer:
        def __init__(self, x, y, layer_width, height, bgra, name, *, breathes=True):
            made.append((x, y, layer_width, height, name))

        def close(self):
            pass

    monkeypatch.setattr(control_overlay, "_Layer", FakeLayer)
    monkeypatch.setattr(control_overlay._user32, "GetCursorPos", lambda ptr: True)
    control_overlay._build_layers(((100, 0, 100 + width, 300),), pending=False)
    glow = next(layer for layer in made if layer[4] == "0_notice_glow")
    assert 100 <= glow[0]
    assert glow[0] + glow[2] <= 100 + width


def test_layer_failure_closes_prior_windows(monkeypatch):
    closed = []

    class FailingLayer:
        count = 0

        def __init__(self, *args):
            self.count = FailingLayer.count
            FailingLayer.count += 1
            if self.count == 2:
                raise OSError("window creation failed")

        def close(self):
            closed.append(self.count)

    monkeypatch.setattr(control_overlay, "_Layer", FailingLayer)
    with pytest.raises(OSError, match="window creation failed"):
        control_overlay._build_layers(((0, 0, 800, 600),), pending=False)
    assert closed == [1, 0]


def test_capture_suspends_and_restores_including_error(monkeypatch):
    calls = []

    class FakeIndicator:
        def change(self, **kwargs):
            calls.append(kwargs)

    monkeypatch.setattr(control_overlay, "_instance", FakeIndicator())
    with pytest.raises(ValueError, match="capture failed"):
        with control_overlay.suspend_for_capture():
            calls.append("capture")
            raise ValueError("capture failed")
    assert calls == [{"suspended": 1}, "capture", {"suspended": -1}]


def test_indicator_lifecycle_and_no_restore_after_takeover(monkeypatch):
    events = []

    class FakeLayer:
        hwnd = 1

        def __init__(self, name):
            self.name = name
            self.breathes = name != "notice"

        def set_opacity(self, value):
            events.append(("opacity", self.name, value))

        def show(self):
            events.append("show")

        def hide(self):
            events.append("hide")

        def move(self, x, y):
            pass

        def close(self):
            events.append("close")

    monkeypatch.setattr(control_overlay, "_monitor_rects", lambda: ((0, 0, 800, 600),))
    monkeypatch.setattr(
        control_overlay,
        "_build_layers",
        lambda rects, pending: (
            [FakeLayer("edge"), FakeLayer("notice_glow"), FakeLayer("notice")],
            FakeLayer("cursor"),
        ),
    )
    monkeypatch.setattr(control_overlay, "_breath_opacity", lambda elapsed: 177)
    monkeypatch.setattr(control_overlay._user32, "GetCursorPos", lambda ptr: True)
    monkeypatch.setattr(flash_overlay, "_pump_messages", lambda hwnd: None)
    assert control_overlay.is_healthy() is False
    control_overlay.start()
    assert control_overlay.is_healthy() is True
    control_overlay.set_active(True)
    assert events.count("show") == 4
    assert ("opacity", "edge", 177) in events
    assert ("opacity", "notice_glow", 177) in events
    assert ("opacity", "cursor", 177) in events
    assert not any(event == ("opacity", "notice", 177) for event in events)
    with control_overlay.suspend_for_capture():
        assert events.count("hide") == 4
        control_overlay.set_active(False)
    assert events.count("show") == 4
    control_overlay.stop()
    assert control_overlay.is_healthy() is False
    assert events.count("close") == 4


def test_pending_indicator_never_flashes_cursor_layer(monkeypatch):
    events = []

    class FakeLayer:
        hwnd = 1
        breathes = True

        def __init__(self, name):
            self.name = name

        def set_opacity(self, value):
            pass

        def show(self):
            events.append(("show", self.name))

        def hide(self):
            events.append(("hide", self.name))

        def move(self, x, y):
            pass

        def close(self):
            pass

    monkeypatch.setattr(control_overlay, "_monitor_rects", lambda: ((0, 0, 800, 600),))
    monkeypatch.setattr(
        control_overlay,
        "_build_layers",
        lambda rects, pending: ([FakeLayer(f"edge_{pending}")], FakeLayer(f"cursor_{pending}")),
    )
    monkeypatch.setattr(control_overlay._user32, "GetCursorPos", lambda ptr: True)
    monkeypatch.setattr(flash_overlay, "_pump_messages", lambda hwnd: None)
    control_overlay.start()
    control_overlay.set_active(True)
    control_overlay.set_pending(True)
    control_overlay.stop()
    assert ("show", "edge_True") in events
    assert ("show", "cursor_True") not in events


def test_failed_indicator_reports_unhealthy(monkeypatch):
    class FailedIndicator:
        thread = threading.current_thread()
        stopping = False
        error = RuntimeError("window failed")

        def stop(self):
            pass

    monkeypatch.setattr(control_overlay, "_instance", FailedIndicator())
    assert control_overlay.is_healthy() is False


def test_alive_but_stalled_indicator_reports_unhealthy(monkeypatch):
    class StalledIndicator:
        thread = threading.current_thread()  # still alive, but no heartbeat refresh
        stopping = False
        error = None
        heartbeat = time.monotonic() - 2.0

        def stop(self):
            pass

    monkeypatch.setattr(control_overlay, "_instance", StalledIndicator())
    assert control_overlay.is_healthy() is False


def test_actual_owner_thread_stall_expires_heartbeat(monkeypatch):
    entered = threading.Event()
    release = threading.Event()

    def stalled_monitor_lookup():
        entered.set()
        release.wait(timeout=3.0)
        raise RuntimeError("simulated window owner failure")

    monkeypatch.setattr(control_overlay, "_monitor_rects", stalled_monitor_lookup)
    control_overlay.start()
    indicator = control_overlay._instance
    assert indicator is not None
    with indicator.condition:
        indicator.active = True
        indicator.condition.notify_all()
    assert entered.wait(timeout=1.0)
    try:
        time.sleep(1.1)
        assert indicator.thread.is_alive()
        assert control_overlay.is_healthy() is False
    finally:
        release.set()
        control_overlay.stop()


def test_fresh_indicator_heartbeat_reports_healthy(monkeypatch):
    class FreshIndicator:
        thread = threading.current_thread()
        stopping = False
        error = None
        heartbeat = time.monotonic()

        def stop(self):
            pass

    monkeypatch.setattr(control_overlay, "_instance", FreshIndicator())
    assert control_overlay.is_healthy() is True


def test_stop_failure_retains_owner_for_retry(monkeypatch):
    class SlowOwner:
        calls = 0

        def stop(self):
            self.calls += 1
            if self.calls == 1:
                raise RuntimeError("join timed out")

    owner = SlowOwner()
    monkeypatch.setattr(control_overlay, "_instance", owner)
    with pytest.raises(RuntimeError, match="join timed out"):
        control_overlay.stop()
    assert control_overlay._instance is owner
    control_overlay.stop()
    assert control_overlay._instance is None
    assert owner.calls == 2


def test_failed_start_keeps_uncleaned_owner_and_prevents_stacking(monkeypatch):
    created = []

    class FailedOwner:
        def __init__(self):
            self.stopping = False
            self.error = None
            self.heartbeat = time.monotonic()
            self.thread = threading.current_thread()
            self.stop_calls = 0
            created.append(self)

        def start(self):
            raise RuntimeError("startup failed")

        def stop(self):
            self.stopping = True
            self.stop_calls += 1
            if self.stop_calls == 1:
                raise RuntimeError("join timed out")

    monkeypatch.setattr(control_overlay, "_Indicator", FailedOwner)
    with pytest.raises(RuntimeError, match="cleanup is pending"):
        control_overlay.start()
    assert control_overlay._instance is created[0]
    with pytest.raises(RuntimeError, match="requires stop"):
        control_overlay.start()
    assert len(created) == 1
    control_overlay.stop()
    assert control_overlay._instance is None


def test_failed_start_clears_owner_after_successful_cleanup(monkeypatch):
    class FailedOwner:
        def start(self):
            raise RuntimeError("startup failed")

        def stop(self):
            pass

    monkeypatch.setattr(control_overlay, "_Indicator", FailedOwner)
    with pytest.raises(RuntimeError, match="startup failed"):
        control_overlay.start()
    assert control_overlay._instance is None


def test_two_captures_are_serialized(monkeypatch):
    active = 0
    peak = 0
    barrier = threading.Barrier(3)

    class FakeIndicator:
        def change(self, **kwargs):
            nonlocal active, peak
            active += kwargs["suspended"]
            peak = max(peak, active)

    monkeypatch.setattr(control_overlay, "_instance", FakeIndicator())

    def capture():
        barrier.wait()
        with control_overlay.suspend_for_capture():
            threading.Event().wait(0.02)

    threads = [threading.Thread(target=capture) for _ in range(2)]
    for thread in threads:
        thread.start()
    barrier.wait()
    for thread in threads:
        thread.join()
    assert active == 0
    assert peak == 1


@pytest.mark.parametrize("backend", ["dxcam", "mss", "pillow"])
def test_screenshot_capture_runs_only_while_indicator_hidden(monkeypatch, backend):
    events = []

    @contextmanager
    def suspended():
        events.append("hide")
        try:
            yield
        finally:
            events.append("restore")

    monkeypatch.setattr(control_overlay, "suspend_for_capture", suspended)
    monkeypatch.setattr(
        flash_overlay, "cancel_active_flash", lambda: events.append("cancel flash") or True
    )
    monkeypatch.setattr(flash_overlay, "show_capture_flash", lambda rect: events.append("show flash"))
    monkeypatch.setattr(
        "windows_mcp.desktop.service.screenshot_capture.capture",
        lambda rect: (events.append("capture") or Image.new("RGB", (2, 2)), backend),
    )
    desktop = Desktop.__new__(Desktop)
    desktop.get_screenshot()
    assert desktop._last_screenshot_backend == backend
    assert events == ["hide", "cancel flash", "capture", "restore", "show flash"]


def test_screenshot_error_restores_indicator_without_flash(monkeypatch):
    events = []

    @contextmanager
    def suspended():
        events.append("hide")
        try:
            yield
        finally:
            events.append("restore")

    monkeypatch.setattr(control_overlay, "suspend_for_capture", suspended)
    monkeypatch.setattr(flash_overlay, "cancel_active_flash", lambda: True)
    monkeypatch.setattr(flash_overlay, "show_capture_flash", lambda rect: events.append("flash"))

    def failing_capture(rect):
        events.append("capture")
        raise OSError("capture failed")

    monkeypatch.setattr("windows_mcp.desktop.service.screenshot_capture.capture", failing_capture)
    with pytest.raises(OSError, match="capture failed"):
        Desktop.__new__(Desktop).get_screenshot()
    assert events == ["hide", "capture", "restore"]


def test_unclosed_flash_prevents_new_capture(monkeypatch):
    events = []

    @contextmanager
    def suspended():
        events.append("hide")
        try:
            yield
        finally:
            events.append("restore")

    monkeypatch.setattr(control_overlay, "suspend_for_capture", suspended)
    monkeypatch.setattr(flash_overlay, "cancel_active_flash", lambda: False)
    monkeypatch.setattr(
        "windows_mcp.desktop.service.screenshot_capture.capture",
        lambda rect: events.append("capture"),
    )
    with pytest.raises(RuntimeError, match="did not close"):
        Desktop.__new__(Desktop).get_screenshot()
    assert events == ["hide", "restore"]
