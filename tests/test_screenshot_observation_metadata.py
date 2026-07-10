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
        screenshot_region=BoundingBox(
            left=100, top=200, right=500, bottom=500, width=400, height=300
        ),
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
        screenshot_target_window={
            "handle": 100,
            "process_id": 200,
            "process": "app.exe",
            "process_path": "C:\\Tools\\app.exe",
            "title": "Target",
            "outer": {"left": 1, "top": 2, "width": 300, "height": 200},
            "client": {"left": 9, "top": 40, "width": 284, "height": 153},
        },
        screenshot_display_inventory=[
            {
                "index": 0,
                "device_name": "\\\\.\\DISPLAY1",
                "effective_dpi": 144,
                "scale": 1.5,
                "orientation": "landscape",
            }
        ],
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
    assert "Screenshot Target Window:" in text
    assert '"process_path": "C:\\\\Tools\\\\app.exe"' in text
    assert "Screenshot Display Inventory:" in text
    assert '"effective_dpi": 144' in text
