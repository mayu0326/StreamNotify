import tkinter as tk
from tkinter import ttk, messagebox
from datetime import datetime
from .. import styles

class ScheduleDialog:
    """Dialog for editing scheduled post time"""
    def __init__(self, parent, video_id, initial_time, on_save):
        self.parent = parent
        self.video_id = video_id
        self.on_save = on_save

        # Window setup
        self.window = tk.Toplevel(parent)
        self.window.title("🗓️ スケジュール設定")
        self.window.geometry("400x300")
        self.window.resizable(False, False)
        self.window.transient(parent)
        self.window.grab_set()

        # Apply theme to window
        self.window.configure(bg=styles.ThemeManager.COLOR_BG)

        # Data
        if isinstance(initial_time, str):
            try:
                # Expecting DB format: YYYY-MM-DD HH:MM:SS
                self.dt = datetime.strptime(initial_time, "%Y-%m-%d %H:%M:%S")
            except:
                self.dt = datetime.now()
        elif isinstance(initial_time, datetime):
            self.dt = initial_time
        else:
            self.dt = datetime.now()

        self.setup_ui()

    def setup_ui(self):
        container = ttk.Frame(self.window, padding=styles.PADDING)
        container.pack(fill=tk.BOTH, expand=True)

        ttk.Label(container, text=f"動画 ID: {self.video_id}", font=styles.FONT_BOLD).pack(pady=(0, styles.MARGIN*2))
        ttk.Label(container, text="投稿予約日時を指定してください:").pack(anchor=tk.W)

        # Date/Time selector (Simple entry for now, can be improved with calendar widget)
        time_frame = ttk.Frame(container, padding=styles.PADDING)
        time_frame.pack(fill=tk.X)

        self.var_date = tk.StringVar(value=self.dt.strftime("%Y-%m-%d"))
        self.var_time = tk.StringVar(value=self.dt.strftime("%H:%M:%S"))

        ttk.Label(time_frame, text="日付 (YYYY-MM-DD):").grid(row=0, column=0, sticky=tk.W)
        ttk.Entry(time_frame, textvariable=self.var_date, width=15).grid(row=0, column=1, pady=styles.MARGIN)

        ttk.Label(time_frame, text="時刻 (HH:MM:SS):").grid(row=1, column=0, sticky=tk.W)
        ttk.Entry(time_frame, textvariable=self.var_time, width=15).grid(row=1, column=1, pady=styles.MARGIN)

        # Help
        ttk.Label(container, text="※ JST(日本標準時)で入力してください", font=("Segoe UI", 9), foreground="gray").pack(pady=styles.MARGIN)

        # Buttons
        btn_frame = ttk.Frame(container)
        btn_frame.pack(side=tk.BOTTOM, fill=tk.X, pady=(styles.MARGIN, 0))

        ttk.Button(btn_frame, text="キャンセル", command=self.window.destroy).pack(side=tk.RIGHT, padx=styles.MARGIN)
        ttk.Button(btn_frame, text="✅ 保存", command=self.save).pack(side=tk.RIGHT, padx=styles.MARGIN)

    def save(self):
        date_str = self.var_date.get().strip()
        time_str = self.var_time.get().strip()

        try:
            full_str = f"{date_str} {time_str}"
            # Validation
            final_dt = datetime.strptime(full_str, "%Y-%m-%d %H:%M:%S")
            self.on_save(self.video_id, final_dt)
            self.window.destroy()
        except ValueError:
            messagebox.showerror("入力エラー", "日付または時刻の形式が正しくありません。\n例: 2025-01-22 19:00:00")
