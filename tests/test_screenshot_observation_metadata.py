from windows_mcp.desktop.views import DesktopState, Size
from windows_mcp.tools._snapshot_helpers import build_snapshot_response
from windows_mcp.tree.views import BoundingBox, TreeState


def test_snapshot_response_includes_observation_metadata() -> None:
    state = DesktopState(
        active_desktop={"name": "Desktop 1"},
        all_desktops=[],
        active_window=None,
        windows=[],
        cursor_position=(10, 20),
        screenshot_original_size=Size(width=400, height=300),
        screenshot_scale=0.5,
        screenshot_region=BoundingBox(left=100, top=200, right=500, bottom=500, width=400, height=300),
        screenshot_backend="pillow",
        screenshot_observation_id="obs-123",
        screenshot_captured_at_utc="2026-07-10T12:00:00+00:00",
        screenshot_coordinate_mapping={
            "coordinate_space": "virtual_desktop",
            "screen_origin": {"x": 100, "y": 200},
            "original_size": {"width": 400, "height": 300},
            "returned_size": {"width": 200, "height": 150},
            "image_to_screen": {"scale": 2.0},
        },
        tree_state=TreeState(),
    )

    response = build_snapshot_response(
        {
            "desktop_state": state,
            "interactive_elements": "",
            "scrollable_elements": "",
            "semantic_tree": "",
            "windows": "",
            "active_window": "",
            "active_desktop": "",
            "all_desktops": "",
            "screenshot_bytes": None,
        },
        include_ui_details=False,
    )

    text = response[0]
    assert "Screenshot Observation ID: obs-123" in text
    assert "Screenshot Captured At UTC: 2026-07-10T12:00:00+00:00" in text
    assert "Screenshot Backend: pillow" in text
    assert "Screenshot Coordinate Mapping:" in text
    assert '"screen_origin": {"x": 100, "y": 200}' in text
