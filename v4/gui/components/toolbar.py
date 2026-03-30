import tkinter as tk
from tkinter import ttk
from .. import styles


class Toolbar(ttk.Frame):
    """Toolbar component with action buttons"""

    def __init__(
        self,
        parent,
        on_refresh=None,
        on_post=None,
        on_settings=None,
        on_template_edit=None,
        on_bulk_delete=None,
        on_batch_schedule=None,
        on_fetch_feed=None,
        on_classify_live=None,
        on_schedule_view=None,
        on_image_assign=None,
        on_websub_retry=None,
        show_rss_controls=False,
        show_websub_retry=False,
    ):
        super().__init__(parent)
        self.pack(side=tk.TOP, fill=tk.X, padx=styles.PADDING, pady=styles.MARGIN)

        self._show_rss = show_rss_controls
        self._show_websub_retry = show_websub_retry
        self._on_fetch_feed = on_fetch_feed
        self._on_classify_live = on_classify_live
        self._on_websub_retry = on_websub_retry

        ttk.Separator(self, orient=tk.VERTICAL).pack(side=tk.LEFT, fill=tk.Y, padx=styles.MARGIN)

        self.refresh_btn = ttk.Button(self, text="🔄 再読込", command=on_refresh)
        self.refresh_btn.pack(side=tk.LEFT, padx=styles.MARGIN)

        # 動的: WebSub 再接続 + RSS 系（フォールバック / poll）
        self.dynamic_frame = ttk.Frame(self)
        self.websub_retry_btn = ttk.Button(
            self.dynamic_frame,
            text="🔌 WebSubに再接続",
            command=on_websub_retry,
        )
        self.fetch_feed_btn = ttk.Button(
            self.dynamic_frame,
            text="📡 新着取得 / RSS更新",
            command=on_fetch_feed,
        )
        self.classify_live_btn = ttk.Button(
            self.dynamic_frame,
            text="🎬 Live判定",
            command=on_classify_live,
        )

        self._mid_sep = ttk.Separator(self, orient=tk.VERTICAL)

        self._apply_dynamic_section()

        ttk.Button(self, text="📝 テンプレート", command=on_template_edit).pack(side=tk.LEFT, padx=styles.MARGIN)

        self.post_btn = ttk.Button(self, text="📤 投稿", command=on_post)
        self.post_btn.pack(side=tk.LEFT, padx=styles.MARGIN)

        self.schedule_btn = ttk.Button(self, text="📅 一括スケジュール", command=on_batch_schedule)
        self.schedule_btn.pack(side=tk.LEFT, padx=styles.MARGIN)

        self.del_btn = ttk.Button(self, text="🗑️ 一括削除", command=on_bulk_delete)
        self.del_btn.pack(side=tk.LEFT, padx=styles.MARGIN)

        self.image_assign_btn = ttk.Button(self, text="🖼️ 画像設定", command=on_image_assign)
        self.image_assign_btn.pack(side=tk.LEFT, padx=styles.MARGIN)

        self.schedule_view_btn = ttk.Button(self, text="📅 投稿予定一覧", command=on_schedule_view)
        self.schedule_view_btn.pack(side=tk.LEFT, padx=styles.MARGIN)

        ttk.Separator(self, orient=tk.VERTICAL).pack(side=tk.LEFT, fill=tk.Y, padx=styles.MARGIN)

        ttk.Button(self, text="⚙️ 設定", command=on_settings).pack(side=tk.RIGHT, padx=styles.MARGIN)

    def _apply_dynamic_section(self):
        for w in self.dynamic_frame.winfo_children():
            w.pack_forget()
        self.dynamic_frame.pack_forget()
        self._mid_sep.pack_forget()

        any_mid = self._show_websub_retry or self._show_rss
        if not any_mid:
            return

        self.dynamic_frame.pack(side=tk.LEFT, fill=tk.Y)
        if self._show_websub_retry and self._on_websub_retry:
            self.websub_retry_btn.pack(side=tk.LEFT, padx=styles.MARGIN)
        if self._show_rss and self._on_fetch_feed and self._on_classify_live:
            self.fetch_feed_btn.pack(side=tk.LEFT, padx=styles.MARGIN)
            self.classify_live_btn.pack(side=tk.LEFT, padx=styles.MARGIN)
        self._mid_sep.pack(side=tk.LEFT, fill=tk.Y, padx=styles.MARGIN)

    def set_rss_controls_visible(self, show: bool):
        self._show_rss = show
        self._apply_dynamic_section()

    def set_websub_retry_visible(self, show: bool):
        self._show_websub_retry = show
        self._apply_dynamic_section()

    def set_post_state(self, enabled: bool):
        state = tk.NORMAL if enabled else tk.DISABLED
        self.post_btn.config(state=state)

    def set_schedule_state(self, enabled: bool):
        state = tk.NORMAL if enabled else tk.DISABLED
        self.schedule_btn.config(state=state)

    def set_image_assign_state(self, enabled: bool):
        """画像設定は 1 件だけ選択時のみ有効"""
        state = tk.NORMAL if enabled else tk.DISABLED
        self.image_assign_btn.config(state=state)
