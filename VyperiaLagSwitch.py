"""
Vyperia's Lag Switch

Firewall lag switch behavior credited to SquareszLeaf/Leaf-LagSwitch:
https://github.com/SquareszLeaf/Leaf-LagSwitch
"""

import atexit
import ctypes as ct
from ctypes import wintypes
import json
import os
import queue
import subprocess as sp
import sys
import tkinter as tk
import threading
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Optional

import customtkinter as ctk
import keyboard
import psutil
from PIL import Image, ImageDraw


APP_NAME = "Vyperia's Lag Switch"
ICON_PATH = Path(__file__).resolve().parent / "assets" / "VyperiaLagSwitch.ico"
SETTINGS_PATH = Path(os.getenv("APPDATA", str(Path.home()))) / "VyperiaLagSwitch" / "settings.json"
DEFAULT_KEYBIND = "f6"
WHOLE_SYSTEM_LABEL = "Whole System"
RULE_PREFIX = "Vyperia_LagSwitch"
SYSTEM_OUT_RULE = f"{RULE_PREFIX}_System_Out"
SYSTEM_IN_RULE = f"{RULE_PREFIX}_System_In"
APP_OUT_RULE = f"{RULE_PREFIX}_App_Out"
APP_IN_RULE = f"{RULE_PREFIX}_App_In"
OVERLAY_POSITIONS = [
    "Top Left",
    "Top Center",
    "Top Right",
    "Center Left",
    "Center",
    "Center Right",
    "Bottom Left",
    "Bottom Center",
    "Bottom Right",
]

BG = "#090612"
PANEL = "#130d24"
PANEL_ALT = "#1b1233"
PANEL_BORDER = "#3c246f"
ACCENT = "#9b5cff"
ACCENT_HOVER = "#7d45dd"
ACCENT_DARK = "#4b278b"
TEXT = "#f4efff"
MUTED = "#b9a9da"
OFF_RED = "#ff5d8f"
ON_GREEN = "#4dffa9"
WARN = "#ffb86b"
COLOR_PRESETS = {
    "Green": "#4dffa9",
    "Red": "#ff5d8f",
    "Purple": "#9b5cff",
    "Cyan": "#52d6ff",
    "Yellow": "#ffdf6e",
    "White": "#f4efff",
}


class SHFILEINFO(ct.Structure):
    _fields_ = [
        ("hIcon", wintypes.HICON),
        ("iIcon", ct.c_int),
        ("dwAttributes", wintypes.DWORD),
        ("szDisplayName", wintypes.WCHAR * 260),
        ("szTypeName", wintypes.WCHAR * 80),
    ]


class ICONINFO(ct.Structure):
    _fields_ = [
        ("fIcon", wintypes.BOOL),
        ("xHotspot", wintypes.DWORD),
        ("yHotspot", wintypes.DWORD),
        ("hbmMask", wintypes.HBITMAP),
        ("hbmColor", wintypes.HBITMAP),
    ]


class BITMAP(ct.Structure):
    _fields_ = [
        ("bmType", wintypes.LONG),
        ("bmWidth", wintypes.LONG),
        ("bmHeight", wintypes.LONG),
        ("bmWidthBytes", wintypes.LONG),
        ("bmPlanes", wintypes.WORD),
        ("bmBitsPixel", wintypes.WORD),
        ("bmBits", wintypes.LPVOID),
    ]


class BITMAPINFOHEADER(ct.Structure):
    _fields_ = [
        ("biSize", wintypes.DWORD),
        ("biWidth", wintypes.LONG),
        ("biHeight", wintypes.LONG),
        ("biPlanes", wintypes.WORD),
        ("biBitCount", wintypes.WORD),
        ("biCompression", wintypes.DWORD),
        ("biSizeImage", wintypes.DWORD),
        ("biXPelsPerMeter", wintypes.LONG),
        ("biYPelsPerMeter", wintypes.LONG),
        ("biClrUsed", wintypes.DWORD),
        ("biClrImportant", wintypes.DWORD),
    ]


class BITMAPINFO(ct.Structure):
    _fields_ = [
        ("bmiHeader", BITMAPINFOHEADER),
        ("bmiColors", wintypes.DWORD * 3),
    ]


SHGFI_ICON = 0x000000100
SHGFI_SMALLICON = 0x000000001
DIB_RGB_COLORS = 0
BI_RGB = 0


@dataclass(frozen=True)
class TargetApp:
    label: str
    exe_path: Optional[str]
    pid: Optional[int]
    process_count: int = 1


def load_file_icon(exe_path: str, size: int = 24) -> Optional[Image.Image]:
    shinfo = SHFILEINFO()
    result = ct.windll.shell32.SHGetFileInfoW(
        exe_path,
        0,
        ct.byref(shinfo),
        ct.sizeof(shinfo),
        SHGFI_ICON | SHGFI_SMALLICON,
    )
    if not result or not shinfo.hIcon:
        return None

    try:
        image = hicon_to_image(shinfo.hIcon)
        if image is None:
            return None
        return image.resize((size, size), Image.Resampling.LANCZOS)
    finally:
        ct.windll.user32.DestroyIcon(shinfo.hIcon)


def hicon_to_image(hicon) -> Optional[Image.Image]:
    icon_info = ICONINFO()
    if not ct.windll.user32.GetIconInfo(hicon, ct.byref(icon_info)):
        return None

    color_bitmap = icon_info.hbmColor or icon_info.hbmMask
    bitmap = BITMAP()
    try:
        if not color_bitmap:
            return None
        if not ct.windll.gdi32.GetObjectW(color_bitmap, ct.sizeof(bitmap), ct.byref(bitmap)):
            return None

        width = int(bitmap.bmWidth)
        height = int(bitmap.bmHeight)
        if icon_info.hbmColor == 0:
            height //= 2
        if width <= 0 or height <= 0:
            return None

        screen_dc = ct.windll.user32.GetDC(None)
        mem_dc = ct.windll.gdi32.CreateCompatibleDC(screen_dc)
        old_obj = ct.windll.gdi32.SelectObject(mem_dc, color_bitmap)
        try:
            bitmap_info = BITMAPINFO()
            bitmap_info.bmiHeader.biSize = ct.sizeof(BITMAPINFOHEADER)
            bitmap_info.bmiHeader.biWidth = width
            bitmap_info.bmiHeader.biHeight = -height
            bitmap_info.bmiHeader.biPlanes = 1
            bitmap_info.bmiHeader.biBitCount = 32
            bitmap_info.bmiHeader.biCompression = BI_RGB

            buffer = ct.create_string_buffer(width * height * 4)
            lines = ct.windll.gdi32.GetDIBits(
                mem_dc,
                color_bitmap,
                0,
                height,
                buffer,
                ct.byref(bitmap_info),
                DIB_RGB_COLORS,
            )
            if lines == 0:
                return None
            return Image.frombuffer("RGBA", (width, height), buffer, "raw", "BGRA", 0, 1).copy()
        finally:
            ct.windll.gdi32.SelectObject(mem_dc, old_obj)
            ct.windll.gdi32.DeleteDC(mem_dc)
            ct.windll.user32.ReleaseDC(None, screen_dc)
    finally:
        if icon_info.hbmColor:
            ct.windll.gdi32.DeleteObject(icon_info.hbmColor)
        if icon_info.hbmMask:
            ct.windll.gdi32.DeleteObject(icon_info.hbmMask)


def load_settings() -> dict[str, object]:
    if not SETTINGS_PATH.exists():
        return {}
    try:
        return json.loads(SETTINGS_PATH.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {}


def clamp(value: float, minimum: float, maximum: float) -> float:
    return max(minimum, min(maximum, value))


class VyperiaLagSwitch:
    def __init__(self) -> None:
        self.settings = load_settings()
        self.block_flag = False
        self.lagswitch_active = False
        self.auto_turnoff = bool(self.settings.get("auto_turnoff", False))
        self.auto_reactivate = bool(self.settings.get("auto_reactivate", False))
        self.timer_duration = clamp(float(self.settings.get("timer_duration", 9.8)), 0.5, 10.0)
        self.reactivation_duration = clamp(float(self.settings.get("reactivation_duration", 0.2)), 0.1, 3.0)
        self.keybind = self.normalize_single_key(str(self.settings.get("keybind", DEFAULT_KEYBIND)))
        self.overlay_font_size = int(clamp(float(self.settings.get("overlay_font_size", 18)), 12, 36))
        self.overlay_show_keybind = bool(self.settings.get("overlay_show_keybind", False))
        self.overlay_compact_text = bool(self.settings.get("overlay_compact_text", False))
        self.overlay_on_color_name = str(self.settings.get("overlay_on_color", "Green"))
        self.overlay_off_color_name = str(self.settings.get("overlay_off_color", "Red"))
        if self.overlay_on_color_name not in COLOR_PRESETS:
            self.overlay_on_color_name = "Green"
        if self.overlay_off_color_name not in COLOR_PRESETS:
            self.overlay_off_color_name = "Red"
        self.keybind_temp_handler: Optional[int] = None
        self.keybind_handler: Optional[int] = None
        self.cycle_event = threading.Event()
        self.auto_cycle_thread: Optional[threading.Thread] = None
        self.targets: dict[str, TargetApp] = {}
        self.icon_cache: dict[str, ctk.CTkImage] = {}
        self.target_rows: list[ctk.CTkButton] = []
        self.active_target: Optional[TargetApp] = None
        self.prepared_target_key: Optional[str] = None
        self.current_app_rule_name: Optional[str] = None
        self.ui_events: queue.Queue[tuple[str, object]] = queue.Queue()
        self.overlay_window: Optional[tk.Toplevel] = None
        self.overlay_label: Optional[tk.Label] = None
        self.is_elevated = self.is_admin()

        ctk.set_appearance_mode("dark")
        ctk.set_default_color_theme("blue")

        self.root = ctk.CTk()
        self.root.title(APP_NAME)
        self.root.geometry("860x720")
        self.root.minsize(720, 500)
        self.root.configure(fg_color=BG)
        self.root.attributes("-topmost", bool(self.settings.get("always_on_top", True)))
        self.root.protocol("WM_DELETE_WINDOW", self.close)
        self.ui_thread_id = threading.get_ident()
        self.set_window_icon()

        self.setup_ui()
        self.refresh_targets()
        self.setup_keybind()
        self.update_status()
        if self.overlay_var.get():
            self.open_overlay()
        if self.is_elevated:
            self.root.after(300, self.clear_firewall_rules)
        self.root.after(50, self.process_ui_events)

    def set_window_icon(self) -> None:
        if not ICON_PATH.exists():
            return
        try:
            self.root.iconbitmap(default=str(ICON_PATH))
        except tk.TclError:
            pass

    def setup_ui(self) -> None:
        self.root.grid_columnconfigure(0, weight=1)
        self.root.grid_rowconfigure(1, weight=1)

        header = ctk.CTkFrame(self.root, corner_radius=0, fg_color=PANEL_ALT)
        header.grid(row=0, column=0, sticky="ew")
        header.grid_columnconfigure(0, weight=1)

        ctk.CTkLabel(
            header,
            text=APP_NAME,
            text_color=TEXT,
            font=("Segoe UI", 26, "bold"),
        ).grid(row=0, column=0, sticky="w", padx=18, pady=(16, 4))
        ctk.CTkLabel(
            header,
            text="Firewall based app or system connection toggle",
            text_color=MUTED,
            font=("Segoe UI", 13),
        ).grid(row=1, column=0, sticky="w", padx=20, pady=(0, 14))
        self.admin_label = ctk.CTkLabel(
            header,
            text="Administrator mode active" if self.is_elevated else "Run Visual Studio as administrator to use firewall toggling",
            text_color=ON_GREEN if self.is_elevated else WARN,
            font=("Segoe UI", 12, "bold"),
        )
        self.admin_label.grid(row=2, column=0, sticky="w", padx=20, pady=(0, 14))

        self.body_scroll = ctk.CTkScrollableFrame(
            self.root,
            fg_color=BG,
            scrollbar_button_color=ACCENT_DARK,
            scrollbar_button_hover_color=ACCENT_HOVER,
        )
        self.body_scroll.grid(row=1, column=0, sticky="nsew")
        self.body_scroll.grid_columnconfigure(0, weight=1, minsize=320)
        self.body_scroll.grid_columnconfigure(1, weight=2, minsize=380)

        target_panel = ctk.CTkFrame(
            self.body_scroll,
            fg_color=PANEL,
            border_color=PANEL_BORDER,
            border_width=1,
        )
        target_panel.grid(row=0, column=0, sticky="nsew", padx=(18, 9), pady=(18, 24))
        target_panel.grid_columnconfigure(0, weight=1)
        target_panel.grid_rowconfigure(4, weight=1)

        ctk.CTkLabel(
            target_panel,
            text="Target",
            text_color=TEXT,
            font=("Segoe UI", 17, "bold"),
        ).grid(row=0, column=0, sticky="w", padx=16, pady=(16, 8))

        self.target_var = ctk.StringVar(value=WHOLE_SYSTEM_LABEL)
        self.current_target_button = ctk.CTkButton(
            target_panel,
            text=WHOLE_SYSTEM_LABEL,
            anchor="w",
            height=40,
            command=lambda: None,
            fg_color=ACCENT_DARK,
            hover_color=ACCENT_DARK,
            text_color=TEXT,
        )
        self.current_target_button.grid(row=1, column=0, sticky="ew", padx=16, pady=(0, 10))

        refresh_button = ctk.CTkButton(
            target_panel,
            text="Refresh Apps",
            command=self.refresh_targets,
            fg_color=ACCENT,
            hover_color=ACCENT_HOVER,
            text_color=TEXT,
        )
        refresh_button.grid(row=2, column=0, sticky="ew", padx=16, pady=(0, 16))

        self.search_var = ctk.StringVar(value="")
        self.search_var.trace_add("write", lambda *_args: self.render_target_rows())
        self.search_entry = ctk.CTkEntry(
            target_panel,
            textvariable=self.search_var,
            placeholder_text="Search apps...",
            height=34,
            fg_color=PANEL_ALT,
            border_color=PANEL_BORDER,
            text_color=TEXT,
            placeholder_text_color=MUTED,
        )
        self.search_entry.grid(row=3, column=0, sticky="ew", padx=16, pady=(0, 10))

        self.target_list = ctk.CTkScrollableFrame(
            target_panel,
            height=300,
            fg_color=PANEL_ALT,
            border_color=PANEL_BORDER,
            border_width=1,
            scrollbar_button_color=ACCENT_DARK,
            scrollbar_button_hover_color=ACCENT_HOVER,
        )
        self.target_list.grid(row=4, column=0, sticky="nsew", padx=16, pady=(0, 12))
        self.target_list.grid_columnconfigure(0, weight=1)

        self.target_info_label = ctk.CTkLabel(
            target_panel,
            text="",
            justify="left",
            anchor="w",
            wraplength=245,
            text_color=MUTED,
        )
        self.target_info_label.grid(row=5, column=0, sticky="ew", padx=16, pady=(0, 12))

        ctk.CTkLabel(
            target_panel,
            text="Credits",
            text_color=TEXT,
            font=("Segoe UI", 15, "bold"),
        ).grid(row=6, column=0, sticky="w", padx=16, pady=(8, 4))

        ctk.CTkLabel(
            target_panel,
            text="Original lag switch firewall logic by SquareszLeaf.\nSource: SquareszLeaf/Leaf-LagSwitch",
            justify="left",
            anchor="w",
            wraplength=245,
            text_color=MUTED,
            font=("Segoe UI", 12),
        ).grid(row=7, column=0, sticky="ew", padx=16, pady=(0, 16))

        control_panel = ctk.CTkFrame(
            self.body_scroll,
            fg_color=PANEL,
            border_color=PANEL_BORDER,
            border_width=1,
        )
        control_panel.grid(row=0, column=1, sticky="nsew", padx=(9, 18), pady=(18, 24))
        control_panel.grid_columnconfigure(0, weight=1)
        control_panel.grid_columnconfigure(1, weight=1)

        self.status_label = ctk.CTkLabel(
            control_panel,
            text="Lag Switch Off",
            text_color=OFF_RED,
            font=("Segoe UI", 22, "bold"),
        )
        self.status_label.grid(row=0, column=0, columnspan=2, sticky="ew", padx=16, pady=(18, 6))

        self.toggle_button = ctk.CTkButton(
            control_panel,
            text="Turn On",
            height=54,
            font=("Segoe UI", 18, "bold"),
            command=self.toggle_lag_switch,
            fg_color=ACCENT,
            hover_color=ACCENT_HOVER,
            text_color=TEXT,
        )
        self.toggle_button.grid(row=1, column=0, columnspan=2, sticky="ew", padx=16, pady=(8, 18))

        self.keybind_label = ctk.CTkLabel(
            control_panel,
            text=f"Hotkey: {self.keybind.upper()}",
            text_color=TEXT,
            font=("Segoe UI", 14, "bold"),
        )
        self.keybind_label.grid(row=2, column=0, columnspan=2, sticky="w", padx=16, pady=(0, 6))

        ctk.CTkButton(
            control_panel,
            text="Capture Hotkey",
            command=self.change_keybind,
            fg_color=ACCENT_DARK,
            hover_color=ACCENT_HOVER,
            text_color=TEXT,
        ).grid(row=3, column=0, columnspan=2, sticky="ew", padx=16, pady=(0, 14))

        self.always_on_top_var = ctk.BooleanVar(value=bool(self.settings.get("always_on_top", True)))
        ctk.CTkCheckBox(
            control_panel,
            text="Always on top",
            variable=self.always_on_top_var,
            command=self.toggle_always_on_top,
            text_color=TEXT,
            fg_color=ACCENT,
            hover_color=ACCENT_HOVER,
            border_color=PANEL_BORDER,
        ).grid(row=4, column=0, sticky="w", padx=16, pady=(0, 10))

        self.overlay_var = ctk.BooleanVar(value=bool(self.settings.get("overlay_enabled", False)))
        ctk.CTkCheckBox(
            control_panel,
            text="Overlay",
            variable=self.overlay_var,
            command=self.toggle_overlay,
            text_color=TEXT,
            fg_color=ACCENT,
            hover_color=ACCENT_HOVER,
            border_color=PANEL_BORDER,
        ).grid(row=4, column=1, sticky="w", padx=16, pady=(0, 10))

        self.auto_turnoff_var = ctk.BooleanVar(value=self.auto_turnoff)
        ctk.CTkCheckBox(
            control_panel,
            text="Anti-timeout cycle",
            variable=self.auto_turnoff_var,
            command=self.update_auto_turnoff,
            text_color=TEXT,
            fg_color=ACCENT,
            hover_color=ACCENT_HOVER,
            border_color=PANEL_BORDER,
        ).grid(row=5, column=0, sticky="w", padx=16, pady=(0, 8))

        self.auto_reactivate_var = ctk.BooleanVar(value=self.auto_reactivate)
        ctk.CTkCheckBox(
            control_panel,
            text="Reactivate after pause",
            variable=self.auto_reactivate_var,
            command=self.update_auto_reactivate,
            text_color=TEXT,
            fg_color=ACCENT,
            hover_color=ACCENT_HOVER,
            border_color=PANEL_BORDER,
        ).grid(row=5, column=1, sticky="w", padx=16, pady=(0, 8))

        ctk.CTkLabel(
            control_panel,
            text="Overlay position",
            text_color=TEXT,
            anchor="w",
            font=("Segoe UI", 13, "bold"),
        ).grid(row=6, column=0, columnspan=2, sticky="ew", padx=16, pady=(8, 4))

        saved_overlay_position = str(self.settings.get("overlay_position", "Top Center"))
        if saved_overlay_position not in OVERLAY_POSITIONS:
            saved_overlay_position = "Top Center"
        self.overlay_position_var = ctk.StringVar(value=saved_overlay_position)
        self.overlay_position_menu = ctk.CTkOptionMenu(
            control_panel,
            variable=self.overlay_position_var,
            values=OVERLAY_POSITIONS,
            command=lambda _value: self.on_overlay_setting_changed(),
            fg_color=ACCENT_DARK,
            button_color=ACCENT,
            button_hover_color=ACCENT_HOVER,
            dropdown_fg_color=PANEL_ALT,
            dropdown_hover_color=ACCENT_DARK,
            dropdown_text_color=TEXT,
            text_color=TEXT,
        )
        self.overlay_position_menu.grid(row=7, column=0, columnspan=2, sticky="ew", padx=16, pady=(0, 14))

        self.overlay_size_label = ctk.CTkLabel(
            control_panel,
            text=f"Overlay text size: {self.overlay_font_size}px",
            anchor="w",
            text_color=TEXT,
        )
        self.overlay_size_label.grid(row=8, column=0, columnspan=2, sticky="ew", padx=16)
        self.overlay_size_slider = ctk.CTkSlider(
            control_panel,
            from_=12,
            to=36,
            number_of_steps=24,
            command=self.update_overlay_font_size,
            button_color=ACCENT,
            button_hover_color=ACCENT_HOVER,
            progress_color=ACCENT,
            fg_color=ACCENT_DARK,
        )
        self.overlay_size_slider.set(self.overlay_font_size)
        self.overlay_size_slider.grid(row=9, column=0, columnspan=2, sticky="ew", padx=16, pady=(0, 12))

        self.overlay_show_keybind_var = ctk.BooleanVar(value=self.overlay_show_keybind)
        ctk.CTkCheckBox(
            control_panel,
            text="Show hotkey on overlay",
            variable=self.overlay_show_keybind_var,
            command=self.on_overlay_setting_changed,
            text_color=TEXT,
            fg_color=ACCENT,
            hover_color=ACCENT_HOVER,
            border_color=PANEL_BORDER,
        ).grid(row=10, column=0, sticky="w", padx=16, pady=(0, 8))

        self.overlay_compact_text_var = ctk.BooleanVar(value=self.overlay_compact_text)
        ctk.CTkCheckBox(
            control_panel,
            text="Compact overlay text",
            variable=self.overlay_compact_text_var,
            command=self.on_overlay_setting_changed,
            text_color=TEXT,
            fg_color=ACCENT,
            hover_color=ACCENT_HOVER,
            border_color=PANEL_BORDER,
        ).grid(row=10, column=1, sticky="w", padx=16, pady=(0, 8))

        ctk.CTkLabel(
            control_panel,
            text="Overlay ON color",
            text_color=TEXT,
            anchor="w",
        ).grid(row=11, column=0, sticky="ew", padx=(16, 8), pady=(0, 4))
        ctk.CTkLabel(
            control_panel,
            text="Overlay OFF color",
            text_color=TEXT,
            anchor="w",
        ).grid(row=11, column=1, sticky="ew", padx=(8, 16), pady=(0, 4))

        self.overlay_on_color_var = ctk.StringVar(value=self.overlay_on_color_name)
        self.overlay_off_color_var = ctk.StringVar(value=self.overlay_off_color_name)
        self.overlay_on_color_menu = ctk.CTkOptionMenu(
            control_panel,
            variable=self.overlay_on_color_var,
            values=list(COLOR_PRESETS.keys()),
            command=lambda _value: self.on_overlay_setting_changed(),
            fg_color=ACCENT_DARK,
            button_color=ACCENT,
            button_hover_color=ACCENT_HOVER,
            dropdown_fg_color=PANEL_ALT,
            dropdown_hover_color=ACCENT_DARK,
            dropdown_text_color=TEXT,
            text_color=TEXT,
        )
        self.overlay_on_color_menu.grid(row=12, column=0, sticky="ew", padx=(16, 8), pady=(0, 14))
        self.overlay_off_color_menu = ctk.CTkOptionMenu(
            control_panel,
            variable=self.overlay_off_color_var,
            values=list(COLOR_PRESETS.keys()),
            command=lambda _value: self.on_overlay_setting_changed(),
            fg_color=ACCENT_DARK,
            button_color=ACCENT,
            button_hover_color=ACCENT_HOVER,
            dropdown_fg_color=PANEL_ALT,
            dropdown_hover_color=ACCENT_DARK,
            dropdown_text_color=TEXT,
            text_color=TEXT,
        )
        self.overlay_off_color_menu.grid(row=12, column=1, sticky="ew", padx=(8, 16), pady=(0, 14))

        self.timer_label = ctk.CTkLabel(
            control_panel,
            text=f"Active time: {self.timer_duration:.1f}s",
            anchor="w",
            text_color=TEXT,
        )
        self.timer_label.grid(row=13, column=0, columnspan=2, sticky="ew", padx=16)
        self.timer_slider = ctk.CTkSlider(
            control_panel,
            from_=0.5,
            to=10,
            number_of_steps=95,
            command=self.update_timer_duration,
            button_color=ACCENT,
            button_hover_color=ACCENT_HOVER,
            progress_color=ACCENT,
            fg_color=ACCENT_DARK,
        )
        self.timer_slider.set(self.timer_duration)
        self.timer_slider.grid(row=14, column=0, columnspan=2, sticky="ew", padx=16, pady=(0, 12))

        self.reactivation_label = ctk.CTkLabel(
            control_panel,
            text=f"Pause time: {self.reactivation_duration:.1f}s",
            anchor="w",
            text_color=TEXT,
        )
        self.reactivation_label.grid(row=15, column=0, columnspan=2, sticky="ew", padx=16)
        self.reactivation_slider = ctk.CTkSlider(
            control_panel,
            from_=0.1,
            to=3,
            number_of_steps=29,
            command=self.update_reactivation_duration,
            button_color=ACCENT,
            button_hover_color=ACCENT_HOVER,
            progress_color=ACCENT,
            fg_color=ACCENT_DARK,
        )
        self.reactivation_slider.set(self.reactivation_duration)
        self.reactivation_slider.grid(row=16, column=0, columnspan=2, sticky="ew", padx=16, pady=(0, 16))

    def refresh_targets(self) -> None:
        current_target = self.targets.get(self.target_var.get()) if hasattr(self, "target_var") else None
        current_exe = current_target.exe_path if current_target else self.settings.get("selected_target_exe")
        targets = {
            WHOLE_SYSTEM_LABEL: TargetApp(WHOLE_SYSTEM_LABEL, None, None, 1),
        }
        app_groups: dict[str, dict[str, object]] = {}

        for proc in psutil.process_iter(["pid", "name", "exe"]):
            try:
                name = proc.info.get("name")
                exe_path = proc.info.get("exe")
                pid = proc.info.get("pid")
                if not name or not exe_path or not pid:
                    continue
                key = exe_path.lower()
                group = app_groups.setdefault(
                    key,
                    {
                        "name": name,
                        "exe_path": exe_path,
                        "pids": [],
                    },
                )
                group["pids"].append(pid)
            except (psutil.AccessDenied, psutil.NoSuchProcess, psutil.ZombieProcess):
                continue

        for group in app_groups.values():
            pids = sorted(group["pids"])
            process_count = len(pids)
            suffix = f"{process_count} processes" if process_count > 1 else f"PID {pids[0]}"
            label = f"{group['name']}  |  {suffix}"
            targets[label] = TargetApp(
                label=label,
                exe_path=str(group["exe_path"]),
                pid=int(pids[0]),
                process_count=process_count,
            )

        sorted_targets = [(WHOLE_SYSTEM_LABEL, targets[WHOLE_SYSTEM_LABEL])]
        sorted_targets.extend(
            sorted(
                ((label, target) for label, target in targets.items() if label != WHOLE_SYSTEM_LABEL),
                key=lambda item: item[0].lower(),
            )
        )
        self.targets = dict(sorted_targets)
        self.render_target_rows()

        selected_label = WHOLE_SYSTEM_LABEL
        if current_exe:
            for label, target in self.targets.items():
                if target.exe_path and target.exe_path.lower() == current_exe.lower():
                    selected_label = label
                    break
        self.select_target(selected_label, reapply_active=False)

    def render_target_rows(self) -> None:
        for row in self.target_rows:
            row.destroy()
        self.target_rows.clear()

        query = self.search_var.get().strip().lower() if hasattr(self, "search_var") else ""
        visible_targets = []
        for target in self.targets.values():
            if target.label == WHOLE_SYSTEM_LABEL:
                visible_targets.append(target)
                continue
            haystack = f"{target.label} {target.exe_path or ''}".lower()
            if not query or query in haystack:
                visible_targets.append(target)

        for row_index, target in enumerate(visible_targets):
            row = ctk.CTkButton(
                self.target_list,
                text=target.label,
                image=self.get_target_icon(target),
                compound="left",
                anchor="w",
                height=34,
                fg_color="transparent",
                hover_color=ACCENT_DARK,
                text_color=TEXT,
                command=lambda label=target.label: self.select_target(label),
            )
            row.grid(row=row_index, column=0, sticky="ew", padx=6, pady=3)
            self.target_rows.append(row)

    def select_target(self, label: str, reapply_active: bool = True) -> None:
        self.target_var.set(label)
        selected = self.get_selected_target()
        self.current_target_button.configure(
            text=selected.label,
            image=self.get_target_icon(selected),
            compound="left",
        )
        self.on_target_changed(reapply_active=reapply_active)
        self.save_settings()

    def on_target_changed(self, reapply_active: bool = True) -> None:
        selected = self.get_selected_target()
        if selected.exe_path is None:
            text = "Whole System blocks inbound and outbound traffic for all apps."
        else:
            text = f"{selected.exe_path}"
        self.target_info_label.configure(text=text)
        if self.lagswitch_active and reapply_active:
            self.active_target = selected
            self.turn_on_lag_switch()

    def get_selected_target(self) -> TargetApp:
        return self.targets.get(
            self.target_var.get(),
            TargetApp(WHOLE_SYSTEM_LABEL, None, None, 1),
        )

    def get_target_icon(self, target: TargetApp) -> ctk.CTkImage:
        cache_key = target.exe_path or "__whole_system__"
        if cache_key in self.icon_cache:
            return self.icon_cache[cache_key]

        image = None
        if target.exe_path:
            try:
                image = load_file_icon(target.exe_path, 24)
            except Exception:
                image = None
        if image is None:
            image = self.get_fallback_icon(system_mode=target.exe_path is None)

        icon = ctk.CTkImage(light_image=image, dark_image=image, size=(24, 24))
        self.icon_cache[cache_key] = icon
        return icon

    def get_fallback_icon(self, system_mode: bool = False) -> Image.Image:
        image = Image.new("RGBA", (24, 24), (0, 0, 0, 0))
        draw = ImageDraw.Draw(image)
        if system_mode:
            draw.ellipse((3, 3, 21, 21), fill=ACCENT_DARK, outline=ACCENT, width=2)
            draw.arc((6, 6, 18, 18), start=0, end=360, fill=TEXT, width=1)
            draw.line((4, 12, 20, 12), fill=TEXT, width=1)
            draw.line((12, 4, 12, 20), fill=TEXT, width=1)
        else:
            draw.rounded_rectangle((3, 5, 21, 19), radius=2, fill=PANEL_ALT, outline=ACCENT, width=2)
            draw.rectangle((6, 8, 18, 16), fill="#2b1b4d")
            draw.line((7, 10, 17, 10), fill=MUTED, width=1)
            draw.line((7, 13, 14, 13), fill=MUTED, width=1)
        return image

    def toggle_lag_switch(self, event=None) -> None:
        if threading.get_ident() != self.ui_thread_id:
            self.ui_events.put(("toggle", None))
            return
        if not self.is_elevated:
            self.prompt_admin_relaunch()
            return
        if self.lagswitch_active:
            self.deactivate_lag_switch()
        else:
            self.activate_lag_switch()

    def activate_lag_switch(self) -> None:
        self.active_target = self.get_selected_target()
        self.lagswitch_active = True
        self.turn_on_lag_switch()
        if self.auto_turnoff:
            self.cycle_event.clear()
            self.auto_cycle_thread = threading.Thread(target=self.lag_cycle_loop, daemon=True)
            self.auto_cycle_thread.start()

    def deactivate_lag_switch(self) -> None:
        self.lagswitch_active = False
        self.cycle_event.set()
        self.turn_off_lag_switch()

    def lag_cycle_loop(self) -> None:
        while self.lagswitch_active and not self.cycle_event.is_set():
            if self.cycle_event.wait(self.timer_duration):
                break
            self.turn_off_lag_switch()
            if self.cycle_event.wait(self.reactivation_duration):
                break
            if not self.lagswitch_active:
                break
            if self.auto_reactivate:
                self.turn_on_lag_switch()
            else:
                self.lagswitch_active = False
                self.ui_events.put(("status", None))
                break

    def turn_on_lag_switch(self) -> None:
        target = self.active_target or self.get_selected_target()
        if target.exe_path is None:
            self.prepare_firewall_rules(target)
            self.enable_firewall_rules(True)
        else:
            if self.current_app_rule_name:
                self.delete_firewall_rule(self.current_app_rule_name)
            self.current_app_rule_name = self.make_app_rule_name(target)
            self.add_firewall_rule(self.current_app_rule_name, "out", target.exe_path, enable=True)
        self.block_flag = True
        self.update_status()

    def turn_off_lag_switch(self) -> None:
        target = self.active_target or self.get_selected_target()
        if target.exe_path is None:
            self.enable_firewall_rules(False)
        else:
            if self.current_app_rule_name:
                self.delete_firewall_rule(self.current_app_rule_name)
                self.current_app_rule_name = None
        self.block_flag = False
        self.update_status()

    def get_target_key(self, target: TargetApp) -> str:
        return target.exe_path.lower() if target.exe_path else "__whole_system__"

    def make_app_rule_name(self, target: TargetApp) -> str:
        pid_part = target.pid if target.pid is not None else "app"
        return f"{APP_OUT_RULE}_{pid_part}_{int(time.time() * 1000)}"

    def prepare_firewall_rules(self, target: TargetApp) -> None:
        if not self.is_elevated:
            return
        target_key = self.get_target_key(target)
        if self.prepared_target_key == target_key:
            return

        self.clear_firewall_rules()
        if target.exe_path is None:
            self.add_firewall_rule(SYSTEM_OUT_RULE, "out", enable=False)
            self.add_firewall_rule(SYSTEM_IN_RULE, "in", enable=False)
        else:
            self.add_firewall_rule(APP_OUT_RULE, "out", target.exe_path, enable=False)
            self.add_firewall_rule(APP_IN_RULE, "in", target.exe_path, enable=False)
        self.prepared_target_key = target_key

    def enable_firewall_rules(self, enabled: bool) -> None:
        if not self.is_elevated or self.prepared_target_key is None:
            return
        state = "yes" if enabled else "no"
        for rule_name in self.get_prepared_rule_names():
            sp.Popen(
                ["netsh", "advfirewall", "firewall", "set", "rule", f"name={rule_name}", "new", f"enable={state}"],
                creationflags=sp.CREATE_NO_WINDOW,
                stdout=sp.DEVNULL,
                stderr=sp.DEVNULL,
            )

    def get_prepared_rule_names(self) -> tuple[str, str]:
        target = self.active_target or self.get_selected_target()
        if target.exe_path is None:
            return SYSTEM_OUT_RULE, SYSTEM_IN_RULE
        return APP_OUT_RULE, APP_IN_RULE

    def add_firewall_rule(self, name: str, direction: str, exe_path: Optional[str] = None, enable: bool = True) -> None:
        if not self.is_elevated:
            return
        cmd = [
            "netsh",
            "advfirewall",
            "firewall",
            "add",
            "rule",
            f"name={name}",
            f"dir={direction}",
            "action=block",
            f"enable={'yes' if enable else 'no'}",
        ]
        if exe_path:
            cmd.append(f"program={exe_path}")
        sp.run(cmd, creationflags=sp.CREATE_NO_WINDOW, capture_output=True, text=True)

    def delete_firewall_rule(self, name: str) -> None:
        if not self.is_elevated:
            return
        sp.run(
            ["netsh", "advfirewall", "firewall", "delete", "rule", f"name={name}"],
            creationflags=sp.CREATE_NO_WINDOW,
            capture_output=True,
            text=True,
        )

    def clear_firewall_rules(self) -> None:
        if not self.is_elevated:
            return
        rule_names = [SYSTEM_OUT_RULE, SYSTEM_IN_RULE, APP_OUT_RULE, APP_IN_RULE]
        if self.current_app_rule_name:
            rule_names.append(self.current_app_rule_name)
        for rule_name in rule_names:
            sp.run(
                ["netsh", "advfirewall", "firewall", "delete", "rule", f"name={rule_name}"],
                creationflags=sp.CREATE_NO_WINDOW,
                capture_output=True,
                text=True,
            )
        self.prepared_target_key = None
        self.current_app_rule_name = None

    def update_status(self) -> None:
        if threading.get_ident() != self.ui_thread_id:
            self.ui_events.put(("status", None))
            return
        if self.block_flag:
            self.status_label.configure(text="Lag Switch On", text_color=ON_GREEN)
            self.toggle_button.configure(text="Turn Off", fg_color="#8c2452", hover_color="#6e1c42")
        else:
            self.status_label.configure(text="Lag Switch Off", text_color=OFF_RED)
            self.toggle_button.configure(text="Turn On", fg_color=ACCENT, hover_color=ACCENT_HOVER)
        self.update_overlay()

    def toggle_overlay(self) -> None:
        self.save_settings()
        if self.overlay_var.get():
            self.open_overlay()
        else:
            self.close_overlay()

    def open_overlay(self) -> None:
        if self.overlay_window is not None and self.overlay_window.winfo_exists():
            self.update_overlay()
            return

        transparent = "#05010d"
        self.overlay_window = tk.Toplevel(self.root)
        self.overlay_window.overrideredirect(True)
        self.overlay_window.configure(bg=transparent)
        self.overlay_window.attributes("-topmost", True)
        try:
            self.overlay_window.attributes("-transparentcolor", transparent)
        except tk.TclError:
            pass

        self.overlay_label = tk.Label(
            self.overlay_window,
            text="",
            bg=transparent,
            fg=COLOR_PRESETS[self.overlay_off_color_var.get()],
            font=("Segoe UI", self.overlay_font_size, "bold"),
            padx=14,
            pady=8,
        )
        self.overlay_label.pack()
        self.update_overlay()

    def close_overlay(self) -> None:
        if self.overlay_window is not None and self.overlay_window.winfo_exists():
            self.overlay_window.destroy()
        self.overlay_window = None
        self.overlay_label = None

    def update_overlay(self) -> None:
        if self.overlay_window is None or self.overlay_label is None:
            return
        if not self.overlay_window.winfo_exists():
            self.overlay_window = None
            self.overlay_label = None
            return

        state = "ON" if self.block_flag else "OFF"
        color_name = self.overlay_on_color_var.get() if self.block_flag else self.overlay_off_color_var.get()
        color = COLOR_PRESETS.get(color_name, ON_GREEN if self.block_flag else OFF_RED)
        self.overlay_label.configure(
            text=self.get_overlay_text(state),
            fg=color,
            font=("Segoe UI", self.overlay_font_size, "bold"),
        )
        self.update_overlay_position()

    def get_overlay_text(self, state: str) -> str:
        text = state if self.overlay_compact_text_var.get() else f"Vyperia Lag Switch: {state}"
        if self.overlay_show_keybind_var.get():
            text = f"{text} [{self.keybind.upper()}]"
        return text

    def update_overlay_position(self) -> None:
        if self.overlay_window is None or not self.overlay_window.winfo_exists():
            return

        self.overlay_window.update_idletasks()
        width = self.overlay_window.winfo_width()
        height = self.overlay_window.winfo_height()
        if width <= 1 or height <= 1:
            width = self.overlay_window.winfo_reqwidth()
            height = self.overlay_window.winfo_reqheight()

        margin = 28
        screen_width = self.overlay_window.winfo_screenwidth()
        screen_height = self.overlay_window.winfo_screenheight()
        position = self.overlay_position_var.get()

        x_positions = {
            "Left": margin,
            "Center": max((screen_width - width) // 2, margin),
            "Right": max(screen_width - width - margin, margin),
        }
        y_positions = {
            "Top": margin,
            "Center": max((screen_height - height) // 2, margin),
            "Bottom": max(screen_height - height - margin, margin),
        }

        if position == "Center":
            vertical = "Center"
            horizontal = "Center"
        else:
            vertical, horizontal = position.split()
        x = x_positions[horizontal]
        y = y_positions[vertical]
        self.overlay_window.geometry(f"+{x}+{y}")

    def process_ui_events(self) -> None:
        try:
            while True:
                event_name, payload = self.ui_events.get_nowait()
                if event_name == "toggle":
                    self.toggle_lag_switch()
                elif event_name == "set_keybind" and payload:
                    self.set_keybind(payload)
                elif event_name == "status":
                    self.update_status()
        except queue.Empty:
            pass

        if self.root.winfo_exists():
            self.root.after(50, self.process_ui_events)

    def save_settings(self) -> None:
        target = self.get_selected_target() if hasattr(self, "target_var") else TargetApp(WHOLE_SYSTEM_LABEL, None, None)
        data = {
            "keybind": self.keybind,
            "always_on_top": bool(self.always_on_top_var.get()) if hasattr(self, "always_on_top_var") else True,
            "auto_turnoff": bool(self.auto_turnoff),
            "auto_reactivate": bool(self.auto_reactivate),
            "overlay_enabled": bool(self.overlay_var.get()) if hasattr(self, "overlay_var") else False,
            "overlay_position": self.overlay_position_var.get() if hasattr(self, "overlay_position_var") else "Top Center",
            "overlay_font_size": int(self.overlay_font_size),
            "overlay_show_keybind": bool(self.overlay_show_keybind_var.get()) if hasattr(self, "overlay_show_keybind_var") else False,
            "overlay_compact_text": bool(self.overlay_compact_text_var.get()) if hasattr(self, "overlay_compact_text_var") else False,
            "overlay_on_color": self.overlay_on_color_var.get() if hasattr(self, "overlay_on_color_var") else "Green",
            "overlay_off_color": self.overlay_off_color_var.get() if hasattr(self, "overlay_off_color_var") else "Red",
            "timer_duration": round(float(self.timer_duration), 1),
            "reactivation_duration": round(float(self.reactivation_duration), 1),
            "selected_target_exe": target.exe_path,
        }
        try:
            SETTINGS_PATH.parent.mkdir(parents=True, exist_ok=True)
            SETTINGS_PATH.write_text(json.dumps(data, indent=2), encoding="utf-8")
        except OSError:
            pass

    def update_auto_turnoff(self) -> None:
        self.auto_turnoff = self.auto_turnoff_var.get()
        self.save_settings()

    def update_auto_reactivate(self) -> None:
        self.auto_reactivate = self.auto_reactivate_var.get()
        self.save_settings()

    def update_timer_duration(self, value: float) -> None:
        self.timer_duration = clamp(float(value), 0.5, 10.0)
        self.timer_label.configure(text=f"Active time: {self.timer_duration:.1f}s")
        self.save_settings()

    def update_reactivation_duration(self, value: float) -> None:
        self.reactivation_duration = clamp(float(value), 0.1, 3.0)
        self.reactivation_label.configure(text=f"Pause time: {self.reactivation_duration:.1f}s")
        self.save_settings()

    def toggle_always_on_top(self) -> None:
        self.root.attributes("-topmost", self.always_on_top_var.get())
        self.save_settings()

    def update_overlay_font_size(self, value: float) -> None:
        self.overlay_font_size = int(round(clamp(float(value), 12, 36)))
        self.overlay_size_label.configure(text=f"Overlay text size: {self.overlay_font_size}px")
        self.update_overlay()
        self.save_settings()

    def on_overlay_setting_changed(self) -> None:
        self.overlay_on_color_name = self.overlay_on_color_var.get()
        self.overlay_off_color_name = self.overlay_off_color_var.get()
        self.overlay_show_keybind = self.overlay_show_keybind_var.get()
        self.overlay_compact_text = self.overlay_compact_text_var.get()
        self.update_overlay()
        self.save_settings()

    def change_keybind(self) -> None:
        if self.keybind_temp_handler is not None:
            keyboard.unhook(self.keybind_temp_handler)
            self.keybind_temp_handler = None
        self.keybind_label.configure(text="Press one key...")
        self.keybind_temp_handler = keyboard.on_press(
            lambda event: self.ui_events.put(("set_keybind", event.name))
        )

    def set_keybind(self, key_name: str) -> None:
        new_keybind = self.normalize_single_key(key_name)
        if not new_keybind:
            self.keybind_label.configure(text=f"Hotkey: {self.keybind.upper()}")
            return
        if new_keybind in {"ctrl", "shift", "alt", "windows"}:
            self.keybind_label.configure(text="Invalid hotkey: choose one normal key")
            return

        if self.keybind_temp_handler is not None:
            keyboard.unhook(self.keybind_temp_handler)
            self.keybind_temp_handler = None
        if self.keybind_handler is not None:
            keyboard.unhook(self.keybind_handler)
            self.keybind_handler = None

        self.keybind = new_keybind
        self.setup_keybind()

        self.keybind_label.configure(text=f"Hotkey: {self.keybind.upper()}")
        self.update_overlay()
        self.save_settings()

    def setup_keybind(self) -> None:
        self.keybind_handler = keyboard.on_press_key(
            self.keybind,
            lambda _event: self.ui_events.put(("toggle", None)),
        )

    def normalize_single_key(self, key_name: str) -> str:
        key = str(key_name).strip().lower()
        if not key or "+" in key:
            return DEFAULT_KEYBIND
        aliases = {
            "control": "ctrl",
            "ctl": "ctrl",
            "cmd": "windows",
            "win": "windows",
            "esc": "escape",
            "leftctrl": "ctrl",
            "rightctrl": "ctrl",
            "leftcontrol": "ctrl",
            "rightcontrol": "ctrl",
            "leftshift": "shift",
            "rightshift": "shift",
            "leftalt": "alt",
            "rightalt": "alt",
        }
        return aliases.get(key, key)

    def is_admin(self) -> bool:
        try:
            return bool(ct.windll.shell32.IsUserAnAdmin())
        except Exception:
            return False

    def prompt_admin_relaunch(self) -> None:
        self.save_settings()
        restore_topmost = self.suspend_topmost_for_prompt()
        response = ct.windll.user32.MessageBoxW(
            self.root.winfo_id(),
            "Administrator access is required to enable the lag switch.\n\nRelaunch Vyperia's Lag Switch as administrator now?",
            APP_NAME,
            0x00000004 | 0x00000020 | 0x00010000,
        )
        if response != 6:
            restore_topmost()
            self.admin_label.configure(
                text="Admin access is required before the lag switch can turn on",
                text_color=WARN,
            )
            return

        if self.relaunch_as_admin():
            self.close()
        else:
            restore_topmost()
            self.admin_label.configure(
                text="Admin relaunch was cancelled or blocked by Windows",
                text_color=WARN,
            )

    def suspend_topmost_for_prompt(self):
        main_was_topmost = bool(self.always_on_top_var.get()) if hasattr(self, "always_on_top_var") else False
        overlay_was_topmost = self.overlay_window is not None and self.overlay_window.winfo_exists()
        self.root.attributes("-topmost", False)
        if overlay_was_topmost:
            self.overlay_window.attributes("-topmost", False)
        self.root.update_idletasks()

        def restore() -> None:
            if self.root.winfo_exists():
                self.root.attributes("-topmost", main_was_topmost)
            if overlay_was_topmost and self.overlay_window is not None and self.overlay_window.winfo_exists():
                self.overlay_window.attributes("-topmost", True)

        return restore

    def relaunch_as_admin(self) -> bool:
        if getattr(sys, "frozen", False):
            executable = sys.executable
            parameters = " ".join(f'"{arg}"' for arg in sys.argv[1:])
        else:
            executable = sys.executable
            script_path = Path(__file__).resolve()
            parameters = " ".join([f'"{script_path}"', *(f'"{arg}"' for arg in sys.argv[1:])])

        result = ct.windll.shell32.ShellExecuteW(
            None,
            "runas",
            executable,
            parameters,
            str(Path(__file__).resolve().parent),
            1,
        )
        return int(result) > 32

    def show_message(self, message: str) -> None:
        ct.windll.user32.MessageBoxW(0, message, APP_NAME, 0)

    def close(self) -> None:
        self.save_settings()
        self.cycle_event.set()
        self.clear_firewall_rules()
        self.close_overlay()
        if self.keybind_temp_handler is not None:
            keyboard.unhook(self.keybind_temp_handler)
        if self.keybind_handler is not None:
            keyboard.unhook(self.keybind_handler)
        self.root.destroy()

    def run(self) -> None:
        atexit.register(self.clear_firewall_rules)
        self.root.mainloop()


if __name__ == "__main__":
    app = VyperiaLagSwitch()
    app.run()
