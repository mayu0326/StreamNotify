"""
VideoDetailDialog - 動画情報詳細表示ウィンドウ（v3互換）

v3 の PostSettingsWindow の「情報表示」部分を v4 向けに移植。
投稿前に動画の全情報（投稿済みフラグ・スケジュール・画像プレビューなど）を一覧表示し、
そのまま投稿・スケジュール設定・画像設定へ進めるランチャー的ウィンドウ。
"""

import tkinter as tk
from tkinter import ttk, messagebox
import logging
from pathlib import Path
from typing import Optional

from v4.gui import styles

logger = logging.getLogger("v4.gui.video_detail")

# GUI（video_table）のタイプ表示と同じマッピング
STATUS_TO_DISPLAY = {
    "upload": "動画",
    "premiere": "プレミア",
    "live": "配信中",
    "archive": "アーカイブ",
    "schedule": "予約配信",
    "video": "動画",
    "completed": "アーカイブ",
}

try:
    from PIL import Image, ImageTk
    PIL_AVAILABLE = True
except ImportError:
    PIL_AVAILABLE = False


class VideoDetailDialog:
    """動画情報詳細表示ウィンドウ"""

    def __init__(self, parent, video_id: str, db, on_refresh=None):
        self.parent = parent
        self.video_id = video_id
        self.db = db
        self.on_refresh = on_refresh
        self._photo = None  # GC防止

        video = db.get_video_by_id(video_id)
        if not video:
            messagebox.showerror("エラー", f"動画情報が見つかりません: {video_id}")
            return
        self.video = video

        self._build_window()

    # ------------------------------------------------------------------ #
    # UI
    # ------------------------------------------------------------------ #

    def _build_window(self):
        v = self.video
        win = tk.Toplevel(self.parent)
        win.title(f"📹 動画詳細 - {self.video_id}")
        win.geometry("700x640")
        win.resizable(True, True)
        win.transient(self.parent)
        win.configure(bg=styles.ThemeManager.COLOR_BG)
        self.window = win

        # ---- メインスクロール領域 ----
        main_canvas = tk.Canvas(win, bg=styles.ThemeManager.COLOR_BG, highlightthickness=0)
        vsb = ttk.Scrollbar(win, orient=tk.VERTICAL, command=main_canvas.yview)
        main_canvas.configure(yscrollcommand=vsb.set)

        vsb.pack(side=tk.RIGHT, fill=tk.Y)
        main_canvas.pack(side=tk.TOP, fill=tk.BOTH, expand=True)

        inner = ttk.Frame(main_canvas)
        win_id = main_canvas.create_window((0, 0), window=inner, anchor="nw")

        def _on_frame_configure(e):
            main_canvas.configure(scrollregion=main_canvas.bbox("all"))
        inner.bind("<Configure>", _on_frame_configure)

        def _on_canvas_resize(e):
            main_canvas.itemconfig(win_id, width=e.width)
        main_canvas.bind("<Configure>", _on_canvas_resize)

        def _on_mousewheel(event):
            if main_canvas.winfo_exists():
                main_canvas.yview_scroll(int(-1 * (event.delta / 120)), "units")
            else:
                main_canvas.unbind_all("<MouseWheel>")
        main_canvas.bind_all("<MouseWheel>", _on_mousewheel)
        main_canvas.bind("<Destroy>", lambda e: main_canvas.unbind_all("<MouseWheel>"))

        pad = styles.PADDING

        # ---- 1. 動画情報 ----
        info_lf = ttk.LabelFrame(inner, text="📹 動画情報", padding=pad)
        info_lf.pack(fill=tk.X, padx=pad, pady=(pad, 4))

        status_raw = (v.get("video_status") or "").strip().lower()
        type_display = STATUS_TO_DISPLAY.get(status_raw, status_raw or "–")
        rows = [
            ("タイトル",    v.get("title") or "–"),
            ("Video ID",    v.get("video_id") or "–"),
            ("チャンネル",  v.get("channel_name") or "–"),
            ("サービス",    (v.get("service") or "–").upper()),
            ("タイプ",      type_display),
            ("公開日時",    v.get("published_at") or "–"),
            ("URL",         v.get("video_url") or "–"),
        ]
        for row_i, (label, value) in enumerate(rows):
            ttk.Label(info_lf, text=f"{label}:", font=styles.FONT_BOLD, width=12,
                      anchor=tk.E).grid(row=row_i, column=0, sticky=tk.E, padx=(0, 6))
            lbl = ttk.Label(info_lf, text=str(value), font=styles.FONT_MAIN,
                            wraplength=510, anchor=tk.W, justify=tk.LEFT)
            lbl.grid(row=row_i, column=1, sticky=tk.W)

        # ---- 2. 投稿状況 ----
        post_lf = ttk.LabelFrame(inner, text="📊 投稿状況", padding=pad)
        post_lf.pack(fill=tk.X, padx=pad, pady=4)

        is_posted = bool(v.get("posted_to_bluesky"))
        posted_text = "✅ 投稿済み" if is_posted else "❌ 未投稿"
        posted_color = "#2e7d32" if is_posted else "#c62828"
        ttk.Label(post_lf, text=posted_text, foreground=posted_color,
                  font=styles.FONT_BOLD).pack(anchor=tk.W)

        posted_at = v.get("posted_at")
        if posted_at:
            ttk.Label(post_lf, text=f"投稿日時: {posted_at}",
                      font=styles.FONT_MAIN).pack(anchor=tk.W)

        sched = v.get("scheduled_at") or v.get("scheduled_start_time")
        if sched:
            ttk.Label(post_lf, text=f"投稿予約: {sched}",
                      foreground="#1565c0", font=styles.FONT_MAIN).pack(anchor=tk.W)
        else:
            ttk.Label(post_lf, text="投稿予約: なし",
                      foreground=styles.ThemeManager.COLOR_TEXT_SECONDARY,
                      font=styles.FONT_MAIN).pack(anchor=tk.W)

        # ---- 3. 画像情報 ----
        img_lf = ttk.LabelFrame(inner, text="🖼️ 登録画像情報", padding=pad)
        img_lf.pack(fill=tk.X, padx=pad, pady=4)

        image_filename = v.get("image_filename")
        image_mode = v.get("image_mode")

        img_left = ttk.Frame(img_lf)
        img_left.pack(side=tk.LEFT, anchor=tk.NW, fill=tk.BOTH, expand=True)

        if image_filename:
            # テーマに応じた視認性の良い色（ライトは現行、ダークは明るい色）
            ttk.Label(
                img_left,
                text=f"ファイル: {image_filename}",
                foreground=styles.ThemeManager.COLOR_LABEL_ACCENT,
                font=styles.FONT_MAIN,
            ).pack(anchor=tk.W)
            ttk.Label(img_left, text=f"モード: {image_mode or '–'}",
                      font=styles.FONT_MAIN).pack(anchor=tk.W)
            # 画像プレビュー（右寄せ）
            self._load_image_preview(img_lf, image_filename, image_mode,
                                     (v.get("service") or "youtube").lower())
        else:
            ttk.Label(img_left, text="画像未登録",
                      foreground=styles.ThemeManager.COLOR_TEXT_SECONDARY,
                      font=styles.FONT_MAIN).pack(anchor=tk.W)

        # ---- 4. アクションボタン ----
        btn_lf = ttk.LabelFrame(inner, text="⚡ アクション", padding=pad)
        btn_lf.pack(fill=tk.X, padx=pad, pady=(4, pad))

        ttk.Button(btn_lf, text="📤 投稿", command=self._open_post_dialog).pack(
            side=tk.LEFT, padx=4
        )
        ttk.Button(btn_lf, text="🗓️ スケジュール設定", command=self._open_schedule_dialog).pack(
            side=tk.LEFT, padx=4
        )
        ttk.Button(btn_lf, text="🖼️ 画像を設定", command=self._open_image_assign).pack(
            side=tk.LEFT, padx=4
        )
        ttk.Button(btn_lf, text="🔗 ブラウザで開く", command=self._open_browser).pack(
            side=tk.LEFT, padx=4
        )
        ttk.Button(btn_lf, text="❌ 閉じる", command=win.destroy).pack(
            side=tk.RIGHT, padx=4
        )

    # ------------------------------------------------------------------ #
    # image preview
    # ------------------------------------------------------------------ #

    def _load_image_preview(self, parent, filename: str, mode: Optional[str], service: str):
        """登録済み画像のプレビューを親フレームの右端に表示する。"""
        if not PIL_AVAILABLE:
            return

        site_map = {"youtube": "YouTube", "niconico": "Niconico", "twitch": "Twitch"}
        site = site_map.get(service, "YouTube")

        try:
            from v4.core.assets.images import image_manager
            base = image_manager.base_dir
        except Exception:
            base = Path("v4") / "images"

        candidate = None
        for m in (mode or "import", "import", "autopost"):
            p = base / site / m / filename
            if p.exists():
                candidate = p
                break

        if not candidate:
            return

        try:
            img = Image.open(candidate)
            img.thumbnail((120, 90), Image.LANCZOS)
            photo = ImageTk.PhotoImage(img)
            self._photo = photo  # GC防止

            lbl = ttk.Label(parent, image=photo, relief=tk.GROOVE)
            lbl.pack(side=tk.RIGHT, padx=8, anchor=tk.NE)
        except Exception as e:
            logger.debug("Preview load failed: %s", e)

    # ------------------------------------------------------------------ #
    # actions
    # ------------------------------------------------------------------ #

    def _open_post_dialog(self):
        from v4.gui.views.post_dialog import PostDialog
        PostDialog(self.window, self.video_id, self.db, on_refresh=self.on_refresh)

    def _open_schedule_dialog(self):
        sched = self.video.get("scheduled_at") or self.video.get("scheduled_start_time")

        def _on_save(vid, new_dt):
            if self.db.update_scheduled_time(vid, new_dt):
                messagebox.showinfo("成功", f"予約投稿時間を設定しました: {new_dt}")
                if self.on_refresh:
                    self.on_refresh()
                self.window.destroy()
            else:
                messagebox.showerror("エラー", "予約時間の更新に失敗しました")

        from v4.gui.views.schedule_dialog import ScheduleDialog
        ScheduleDialog(self.window, self.video_id, sched, on_save=_on_save)

    def _open_image_assign(self):
        from v4.gui.views.image_assign_dialog import ImageAssignDialog
        
        def _on_image_assign_success(filename):
            """画像登録成功時、登録済み画像表示を即座に更新。"""
            # 現在の画像データを再取得
            latest_video = self.db.get_video_by_id(self.video_id)
            if latest_video:
                self.video = latest_video
                # 親ウィンドウを一度閉じて再度開く（最新データで）
                self.window.destroy()
                if self.on_refresh:
                    self.on_refresh()
        
        ImageAssignDialog(
            self.window, self.video_id, self.db,
            on_refresh=self.on_refresh,
            on_success_callback=_on_image_assign_success
        )

    def _open_browser(self):
        import webbrowser
        url = self.video.get("video_url")
        if url:
            webbrowser.open(url)
            return
        service = (self.video.get("service") or "youtube").lower()
        vid = self.video_id
        if service == "niconico":
            webbrowser.open(f"https://www.nicovideo.jp/watch/{vid}")
        elif service == "twitch":
            ch = (self.video.get("channel_name") or "").lower()
            webbrowser.open(f"https://www.twitch.tv/{ch}")
        else:
            webbrowser.open(f"https://www.youtube.com/watch?v={vid}")
