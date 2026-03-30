# v4 GUI Styles and Constants

try:
    import darkdetect
except ImportError:
    darkdetect = None

from v4.core.config import settings

# --- Base Palette ---
# Light
L_BG = "#f5f5f7"
L_BG_SECONDARY = "#ffffff"
L_TREE_EVEN = "#ffffff"
L_TREE_ODD = "#f9f9fb"
L_TEXT = "#1d1d1f"
L_TEXT_SECONDARY = "#86868b"
L_BORDER = "#d2d2d7"

# Dark
D_BG = "#1c1c1e"
D_BG_SECONDARY = "#2c2c2e"
D_TREE_EVEN = "#1c1c1e"
D_TREE_ODD = "#2c2c2e"
D_TEXT = "#f5f5f7"
D_TEXT_SECONDARY = "#86868b"
D_BORDER = "#3a3a3c"

# Common
ACCENT = "#007aff"
SUCCESS = "#28a745"
ERROR = "#ff453a"  # Slightly brighter red for dark mode compatibility

# 投稿設定などラベル用（ライト=現行維持 / ダーク=視認性確保）
L_LABEL_ACCENT = "darkblue"   # タイトルなど
L_LABEL_SUCCESS = "darkgreen" # ソース・予約あり・画像あり
L_LABEL_MUTED = "gray"        # 予約なし・補足文
L_LABEL_WARNING = "orange"    # 警告
D_LABEL_ACCENT = "#6eb3f7"    # ダーク用 明るい青
D_LABEL_SUCCESS = "#6fcf97"   # ダーク用 明るい緑
D_LABEL_MUTED = "#a0a0a0"     # ダーク用 明るいグレー
D_LABEL_WARNING = "#ffb347"   # ダーク用 明るいオレンジ

# Fonts - Support Japanese and Western characters
# Use "Yu Gothic UI" or "Meiryo UI" for better Japanese rendering on Windows
# Fallback to "Segoe UI" for Western characters
try:
    import tkinter as tk
    from tkinter import font as tk_font
    test_root = tk.Tk()
    test_root.withdraw()
    available_fonts = tk_font.families()
    test_root.destroy()

    # Prefer Yu Gothic UI/Meiryo UI for Japanese, then fallback to Western fonts
    selected_font = "Segoe UI"  # Default fallback

    if "Yu Gothic UI" in available_fonts:
        selected_font = "Yu Gothic UI"
    elif "Meiryo UI" in available_fonts:
        selected_font = "Meiryo UI"
    elif "MS UI Gothic" in available_fonts:
        selected_font = "MS UI Gothic"
    elif "Meiryo" in available_fonts:
        selected_font = "Meiryo"
    elif "MS Gothic" in available_fonts:
        selected_font = "MS Gothic"

    FONT_MAIN = (selected_font, 10)
    FONT_BOLD = (selected_font, 10, "bold")
    FONT_TITLE = (selected_font, 12, "bold")
    FONT_SMALL = (selected_font, 8)
except Exception as e:
    # Fallback if font detection fails
    FONT_MAIN = ("Segoe UI", 10)
    FONT_BOLD = ("Segoe UI", 10, "bold")
    FONT_TITLE = ("Segoe UI", 12, "bold")
    FONT_SMALL = ("Segoe UI", 8)

# Layout
PADDING = 10
MARGIN = 5

class ThemeManager:
    """Manages active color scheme based on settings and system preference."""

    current_theme = "light"

    # Active Colors (populated by apply_theme)
    COLOR_BG = L_BG
    COLOR_BG_SECONDARY = L_BG_SECONDARY
    COLOR_TREE_EVEN = L_TREE_EVEN
    COLOR_TREE_ODD = L_TREE_ODD
    COLOR_TEXT = L_TEXT
    COLOR_TEXT_SECONDARY = L_TEXT_SECONDARY
    COLOR_BORDER = L_BORDER
    COLOR_ACCENT = ACCENT
    COLOR_SUCCESS = SUCCESS
    COLOR_ERROR = ERROR
    # ラベル用（テーマで切替）
    COLOR_LABEL_ACCENT = L_LABEL_ACCENT
    COLOR_LABEL_SUCCESS = L_LABEL_SUCCESS
    COLOR_LABEL_MUTED = L_LABEL_MUTED
    COLOR_LABEL_WARNING = L_LABEL_WARNING

    @classmethod
    def resolve_theme_mode(cls) -> str:
        """Resolve 'system'/'light'/'dark' to actual 'light' or 'dark'."""
        mode = settings.app_theme.lower()
        if mode == "system":
            if darkdetect:
                return "dark" if darkdetect.isDark() else "light"
            return "light" # Fallback
        return mode

    @classmethod
    def apply_theme(cls):
        """Update active color constants based on resolved theme."""
        mode = cls.resolve_theme_mode()
        cls.current_theme = mode

        if mode == "dark":
            cls.COLOR_BG = D_BG
            cls.COLOR_BG_SECONDARY = D_BG_SECONDARY
            cls.COLOR_TREE_EVEN = D_TREE_EVEN
            cls.COLOR_TREE_ODD = D_TREE_ODD
            cls.COLOR_TEXT = D_TEXT
            cls.COLOR_TEXT_SECONDARY = D_TEXT_SECONDARY
            cls.COLOR_BORDER = D_BORDER
            cls.COLOR_ERROR = "#ff453a"
            cls.COLOR_LABEL_ACCENT = D_LABEL_ACCENT
            cls.COLOR_LABEL_SUCCESS = D_LABEL_SUCCESS
            cls.COLOR_LABEL_MUTED = D_LABEL_MUTED
            cls.COLOR_LABEL_WARNING = D_LABEL_WARNING
        else:
            cls.COLOR_BG = L_BG
            cls.COLOR_BG_SECONDARY = L_BG_SECONDARY
            cls.COLOR_TREE_EVEN = L_TREE_EVEN
            cls.COLOR_TREE_ODD = L_TREE_ODD
            cls.COLOR_TEXT = L_TEXT
            cls.COLOR_TEXT_SECONDARY = L_TEXT_SECONDARY
            cls.COLOR_BORDER = L_BORDER
            cls.COLOR_ERROR = "#d70015"
            cls.COLOR_LABEL_ACCENT = L_LABEL_ACCENT
            cls.COLOR_LABEL_SUCCESS = L_LABEL_SUCCESS
            cls.COLOR_LABEL_MUTED = L_LABEL_MUTED
            cls.COLOR_LABEL_WARNING = L_LABEL_WARNING

    @classmethod
    def configure_ttk_styles(cls, root):
        """Apply the current theme to ttk.Style and Tk widgets"""
        import tkinter.ttk as ttk
        style = ttk.Style(root)
        style.theme_use('clam')  # 'clam' is usually a good base for custom coloring

        # Colors
        bg = cls.COLOR_BG
        fg = cls.COLOR_TEXT
        sec_bg = cls.COLOR_BG_SECONDARY
        border = cls.COLOR_BORDER
        text_sec = cls.COLOR_TEXT_SECONDARY

        # General Defaults (ttk base)
        style.configure(".",
            background=bg,
            foreground=fg,
            fieldbackground=sec_bg,
            troughcolor=border,
            font=FONT_MAIN,
            borderwidth=1
        )

        # Treeview
        style.configure("Treeview",
            background=sec_bg,
            fieldbackground=sec_bg,
            foreground=fg,
            borderwidth=0,
            font=FONT_MAIN
        )
        style.configure("Treeview.Heading",
            background=bg,
            foreground=fg,
            font=FONT_BOLD,
            relief="flat"
        )
        style.map("Treeview",
                  background=[("selected", "#0078d4")],  # 青帯（v3 同様）
                  foreground=[("selected", "#ffffff")])  # 選択時は白文字で視認性確保
        style.map("Treeview.Heading",
                  background=[("active", border)])

        # Buttons (TButton)
        style.configure("TButton",
                       padding=6,
                       relief="flat",
                       background=sec_bg,
                       foreground=fg,
                       font=FONT_MAIN)
        style.map("TButton",
            background=[("active", border), ("disabled", bg)],
            foreground=[("disabled", text_sec)]
        )

        # Labels (TLabel)
        style.configure("TLabel",
                       background=bg,
                       foreground=fg,
                       font=FONT_MAIN)

        # Entry (TEntry)
        style.configure("TEntry",
                       fieldbackground=sec_bg,
                       foreground=fg,
                       font=FONT_MAIN,
                       padding=2)
        style.map("TEntry",
                  fieldbackground=[("disabled", bg)],
                  foreground=[("disabled", text_sec)])

        # Combobox (TCombobox)
        style.configure("TCombobox",
                       fieldbackground=sec_bg,
                       background=sec_bg,
                       foreground=fg,
                       font=FONT_MAIN,
                       arrowcolor=fg)
        style.map("TCombobox",
                  fieldbackground=[("readonly", sec_bg), ("disabled", bg)],
                  background=[("readonly", sec_bg)],
                  foreground=[("disabled", text_sec)],
                  arrowcolor=[("disabled", text_sec)])

        # Spinbox (TSpinbox)
        style.configure("TSpinbox",
                       fieldbackground=sec_bg,
                       background=sec_bg,
                       foreground=fg,
                       font=FONT_MAIN)
        style.map("TSpinbox",
                  fieldbackground=[("disabled", bg)],
                  foreground=[("disabled", text_sec)])

        # Checkbutton (TCheckbutton)
        style.configure("TCheckbutton",
                       background=bg,
                       foreground=fg,
                       font=FONT_MAIN)
        style.map("TCheckbutton",
                  background=[("active", bg)],
                  foreground=[("disabled", text_sec)])

        # Radiobutton (TRadiobutton)
        style.configure("TRadiobutton",
                       background=bg,
                       foreground=fg,
                       font=FONT_MAIN)
        style.map("TRadiobutton",
                  background=[("active", bg)],
                  foreground=[("disabled", text_sec)])

        # Frame (TFrame)
        style.configure("TFrame",
                       background=bg)

        # Separator (TSeparator)
        style.configure("TSeparator",
                       background=border)

        # Scrollbar (TScrollbar)
        # Windows/ttk では ▲▼（arrow）がテーマ側デフォルト色になり、ダークテーマで埋もれることがあるため上書きする
        style.configure(
            "TScrollbar",
            background=sec_bg,
            troughcolor=bg,
            bordercolor=border,
            arrowcolor=fg,
            relief="flat",
        )
        style.configure(
            "Vertical.TScrollbar",
            background=sec_bg,
            troughcolor=bg,
            bordercolor=border,
            arrowcolor=fg,
            relief="flat",
        )
        style.configure(
            "Horizontal.TScrollbar",
            background=sec_bg,
            troughcolor=bg,
            bordercolor=border,
            arrowcolor=fg,
            relief="flat",
        )

        # Tabs (TNotebook)
        style.configure("TNotebook",
                       background=bg,
                       tabmargins=[2, 5, 2, 0])
        style.configure("TNotebook.Tab",
                       background=sec_bg,
                       foreground=fg,
                       padding=[10, 2],
                       font=FONT_MAIN)
        style.map("TNotebook.Tab",
                  background=[("selected", bg)],
                  foreground=[("selected", fg)],
                  expand=[("selected", [1, 1, 1, 0])])

        # Panedwindow (TPanedwindow)
        style.configure("TPanedwindow",
                       background=bg)

        # Configure root Tk window background
        try:
            root.configure(bg=bg)
        except:
            pass

    @classmethod
    def apply_tk_styles(cls, widget):
        """
        Apply current theme colors to a Tk widget (tk.Label, tk.Frame, tk.Menu, etc).
        Use this for widgets that don't support ttk styling.
        """
        bg = cls.COLOR_BG
        fg = cls.COLOR_TEXT
        sec_bg = cls.COLOR_BG_SECONDARY

        widget.configure(bg=bg, fg=fg, font=FONT_MAIN)

    @classmethod
    def apply_tk_label_styles(cls, label, is_title=False):
        """
        Apply theme colors to tk.Label specifically.
        is_title: If True, use FONT_TITLE; if False, use FONT_MAIN.
        """
        bg = cls.COLOR_BG
        fg = cls.COLOR_TEXT
        font = FONT_TITLE if is_title else FONT_MAIN

        label.configure(bg=bg, fg=fg, font=font)

    @classmethod
    def apply_tk_menu_styles(cls, menu):
        """Apply theme colors to tk.Menu."""
        bg = cls.COLOR_BG_SECONDARY
        fg = cls.COLOR_TEXT

        menu.configure(bg=bg, fg=fg, font=FONT_MAIN, activebackground=cls.COLOR_BORDER, activeforeground=fg)

# Initial application
ThemeManager.apply_theme()

# Expose constants for backward compatibility (and easy import)
# Note: These values are set at IMPORT time.
# If theme changes at runtime, modules that imported these directly won't see updates.
# They should access ThemeManager.COLOR_... or re-import.
COLOR_BG = ThemeManager.COLOR_BG
COLOR_TREE_EVEN = ThemeManager.COLOR_TREE_EVEN
COLOR_TREE_ODD = ThemeManager.COLOR_TREE_ODD
COLOR_ACCENT = ThemeManager.COLOR_ACCENT
COLOR_TEXT = ThemeManager.COLOR_TEXT
COLOR_TEXT_SECONDARY = ThemeManager.COLOR_TEXT_SECONDARY
COLOR_SUCCESS = ThemeManager.COLOR_SUCCESS
COLOR_ERROR = ThemeManager.COLOR_ERROR
