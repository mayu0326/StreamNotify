import tkinter as tk
from tkinter import ttk
from .. import styles

class Footer(ttk.Frame):
    """Status bar / Footer component"""
    def __init__(self, parent):
        super().__init__(parent)
        self.pack(side=tk.BOTTOM, fill=tk.X, padx=styles.PADDING, pady=styles.MARGIN)

        self.status_label = ttk.Label(
            self,
            text="準備完了",
            relief=tk.SUNKEN,
            anchor=tk.W,
            font=styles.FONT_MAIN
        )
        self.status_label.pack(fill=tk.X)

    def set_status(self, text: str, is_error: bool = False):
        color = styles.COLOR_ERROR if is_error else styles.COLOR_TEXT
        self.status_label.config(text=text, foreground=color)
        self.update_idletasks()
