"""Win32 structures, API bindings and desktop health for input ownership."""

import ctypes
from ctypes import wintypes

_LRESULT = ctypes.c_ssize_t
_HOOKPROC = ctypes.WINFUNCTYPE(_LRESULT, ctypes.c_int, wintypes.WPARAM, wintypes.LPARAM)
_WNDPROC = ctypes.WINFUNCTYPE(_LRESULT, wintypes.HWND, wintypes.UINT, wintypes.WPARAM, wintypes.LPARAM)


class _WndClass(ctypes.Structure):
    _fields_ = [
        ("cbSize", wintypes.UINT), ("style", wintypes.UINT), ("lpfnWndProc", _WNDPROC),
        ("cbClsExtra", ctypes.c_int), ("cbWndExtra", ctypes.c_int),
        ("hInstance", wintypes.HINSTANCE), ("hIcon", wintypes.HICON),
        ("hCursor", wintypes.HANDLE), ("hbrBackground", wintypes.HBRUSH),
        ("lpszMenuName", wintypes.LPCWSTR), ("lpszClassName", wintypes.LPCWSTR),
        ("hIconSm", wintypes.HICON),
    ]


class _MouseHookData(ctypes.Structure):
    _fields_ = [
        ("pt", wintypes.POINT), ("mouseData", wintypes.DWORD),
        ("flags", wintypes.DWORD), ("time", wintypes.DWORD),
        ("dwExtraInfo", ctypes.c_size_t),
    ]


class _KeyHookData(ctypes.Structure):
    _fields_ = [
        ("vkCode", wintypes.DWORD), ("scanCode", wintypes.DWORD),
        ("flags", wintypes.DWORD), ("time", wintypes.DWORD),
        ("dwExtraInfo", ctypes.c_size_t),
    ]


class _RawDevice(ctypes.Structure):
    _fields_ = [
        ("usUsagePage", wintypes.USHORT), ("usUsage", wintypes.USHORT),
        ("dwFlags", wintypes.DWORD), ("hwndTarget", wintypes.HWND),
    ]


class _RawHeader(ctypes.Structure):
    _fields_ = [
        ("dwType", wintypes.DWORD), ("dwSize", wintypes.DWORD),
        ("hDevice", wintypes.HANDLE), ("wParam", wintypes.WPARAM),
    ]


class _RawMouse(ctypes.Structure):
    _fields_ = [
        ("usFlags", wintypes.USHORT), ("usButtonFlags", wintypes.USHORT),
        ("usButtonData", wintypes.USHORT), ("ulRawButtons", wintypes.DWORD),
        ("lLastX", ctypes.c_long), ("lLastY", ctypes.c_long),
        ("ulExtraInformation", wintypes.DWORD),
    ]


_user32 = ctypes.WinDLL("user32", use_last_error=True)
_kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
_user32.SetWindowsHookExW.argtypes = [ctypes.c_int, _HOOKPROC, wintypes.HINSTANCE, wintypes.DWORD]
_user32.SetWindowsHookExW.restype = wintypes.HHOOK
_user32.CallNextHookEx.argtypes = [wintypes.HHOOK, ctypes.c_int, wintypes.WPARAM, wintypes.LPARAM]
_user32.CallNextHookEx.restype = _LRESULT
_user32.UnhookWindowsHookEx.argtypes = [wintypes.HHOOK]
_user32.RegisterClassExW.argtypes = [ctypes.POINTER(_WndClass)]
_user32.RegisterClassExW.restype = ctypes.c_ushort
_user32.CreateWindowExW.argtypes = [
    wintypes.DWORD, wintypes.LPCWSTR, wintypes.LPCWSTR, wintypes.DWORD,
    ctypes.c_int, ctypes.c_int, ctypes.c_int, ctypes.c_int,
    wintypes.HWND, wintypes.HANDLE, wintypes.HINSTANCE, ctypes.c_void_p,
]
_user32.CreateWindowExW.restype = wintypes.HWND
_user32.DestroyWindow.argtypes = [wintypes.HWND]
_user32.UnregisterClassW.argtypes = [wintypes.LPCWSTR, wintypes.HINSTANCE]
_user32.OpenInputDesktop.argtypes = [wintypes.DWORD, wintypes.BOOL, wintypes.DWORD]
_user32.OpenInputDesktop.restype = wintypes.HANDLE
_user32.CloseDesktop.argtypes = [wintypes.HANDLE]
_user32.GetUserObjectInformationW.argtypes = [
    wintypes.HANDLE, ctypes.c_int, ctypes.c_void_p, wintypes.DWORD, ctypes.POINTER(wintypes.DWORD),
]
_user32.GetUserObjectInformationW.restype = wintypes.BOOL
_user32.RegisterRawInputDevices.argtypes = [ctypes.POINTER(_RawDevice), wintypes.UINT, wintypes.UINT]
_user32.GetRawInputData.argtypes = [
    wintypes.HANDLE, wintypes.UINT, ctypes.c_void_p, ctypes.POINTER(wintypes.UINT), wintypes.UINT,
]
_user32.GetRawInputData.restype = wintypes.UINT
_user32.DefWindowProcW.argtypes = [wintypes.HWND, wintypes.UINT, wintypes.WPARAM, wintypes.LPARAM]
_user32.DefWindowProcW.restype = _LRESULT
_kernel32.GetModuleHandleW.argtypes = [wintypes.LPCWSTR]
_kernel32.GetModuleHandleW.restype = wintypes.HINSTANCE
_wts = ctypes.WinDLL("wtsapi32", use_last_error=True)
_wts.WTSQuerySessionInformationW.argtypes = [
    wintypes.HANDLE, wintypes.DWORD, ctypes.c_int,
    ctypes.POINTER(ctypes.c_void_p), ctypes.POINTER(wintypes.DWORD),
]
_wts.WTSQuerySessionInformationW.restype = wintypes.BOOL
_wts.WTSFreeMemory.argtypes = [ctypes.c_void_p]

_CHORD = {0x10, 0x11, 0x12, 0x08}


def _key(vk: int) -> int:
    if vk in (0xA0, 0xA1):
        return 0x10
    if vk in (0xA2, 0xA3):
        return 0x11
    if vk in (0xA4, 0xA5):
        return 0x12
    return vk


def _mouse_button(message: int, data: int) -> tuple[int, bool] | None:
    down = {0x201: 1, 0x204: 2, 0x207: 3}
    up = {0x202: 1, 0x205: 2, 0x208: 3}
    if message in down:
        return down[message], True
    if message in up:
        return up[message], False
    if message in (0x20B, 0x20C):  # WM_XBUTTONDOWN / WM_XBUTTONUP.
        xbutton = (data >> 16) & 0xFFFF
        if xbutton in (1, 2):
            return xbutton + 3, message == 0x20B
    return None


def _read_raw_mouse(lparam: int) -> tuple[int, int, int] | None:
    """Read a relative physical mouse event; null devices are ambiguous."""
    size = wintypes.UINT()
    header_size = ctypes.sizeof(_RawHeader)
    if _user32.GetRawInputData(lparam, 0x10000003, None, ctypes.byref(size), header_size) == 0xFFFFFFFF:
        return None
    if size.value < header_size + ctypes.sizeof(_RawMouse):
        return None
    buffer = ctypes.create_string_buffer(size.value)
    if _user32.GetRawInputData(lparam, 0x10000003, buffer, ctypes.byref(size), header_size) == 0xFFFFFFFF:
        return None
    header = ctypes.cast(buffer, ctypes.POINTER(_RawHeader)).contents
    if header.dwType != 0 or not header.hDevice:
        return None
    mouse = _RawMouse.from_buffer_copy(buffer, header_size)
    if mouse.usFlags & 1:
        return None
    return int(header.hDevice), mouse.lLastX, mouse.lLastY


def _interactive_desktop() -> bool:
    """Require an active session on the normal user input desktop."""
    buffer = ctypes.c_void_p()
    length = wintypes.DWORD()
    # WTS_CURRENT_SESSION, WTSConnectState=8; WTSActive=0.
    if not _wts.WTSQuerySessionInformationW(
        None, 0xFFFFFFFF, 8, ctypes.byref(buffer), ctypes.byref(length)
    ):
        return False
    try:
        if length.value < ctypes.sizeof(ctypes.c_int):
            return False
        if ctypes.cast(buffer, ctypes.POINTER(ctypes.c_int)).contents.value != 0:
            return False
    finally:
        _wts.WTSFreeMemory(buffer)
    # The input desktop changes to Winlogon for UAC/lock screen.
    desktop = _user32.OpenInputDesktop(0, False, 0x0001)  # DESKTOP_READOBJECTS.
    if not desktop:
        return False
    try:
        name = ctypes.create_unicode_buffer(64)
        needed = wintypes.DWORD()
        return bool(_user32.GetUserObjectInformationW(
            desktop, 2, name, ctypes.sizeof(name), ctypes.byref(needed)
        )) and name.value.casefold() == "default"
    finally:
        _user32.CloseDesktop(desktop)

\n
