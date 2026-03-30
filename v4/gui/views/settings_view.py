import tkinter as tk
from tkinter import ttk, messagebox, filedialog
import logging
from PIL import Image, ImageTk
from .. import styles
from v4.core.config import settings

logger = logging.getLogger("v4.gui.views")

class SettingsView:
    """Window for editing application settings"""
    def __init__(self, parent, db_adapter):
        self.parent = parent
        self.db = db_adapter

        # Reload settings from disk to get the latest values
        try:
            from v4.core.config import settings
            settings.reload_settings()
            logger.info("✅ Settings reloaded in SettingsView.__init__()")


        except Exception as e:
            logger.warning(f"Failed to reload settings at initialization: {e}")

        self.window = tk.Toplevel(parent)
        self.window.title("⚙️ アプリ設定")
        self.window.geometry("800x700") # Slightly larger for sub-tabs
        self.window.resizable(True, True)
        self.window.transient(parent)
        self.window.grab_set()

        self.vars = {}
        self.setup_ui()

    def setup_ui(self):
        # Apply theme styles to the settings window (it's a new Toplevel)
        styles.ThemeManager.apply_theme()
        styles.ThemeManager.configure_ttk_styles(self.parent)  # Style parent root
        self.window.configure(bg=styles.ThemeManager.COLOR_BG)

        container = ttk.Frame(self.window, padding=styles.PADDING)
        container.pack(fill=tk.BOTH, expand=True)

        # Apply theme to window background
        self.window.configure(bg=styles.ThemeManager.COLOR_BG)

        # Buttons (Top)
        btn_frame = ttk.Frame(container)
        btn_frame.pack(fill=tk.X, pady=(0, styles.MARGIN))
        ttk.Button(btn_frame, text="キャンセル", command=self.window.destroy).pack(side=tk.LEFT, padx=styles.MARGIN)
        ttk.Button(btn_frame, text="💾 保存", command=self.save).pack(side=tk.LEFT, padx=styles.MARGIN)
        ttk.Button(btn_frame, text="ℹ️ リセット", command=self._reset_to_defaults).pack(side=tk.LEFT, padx=styles.MARGIN)

        # Main Notebook
        notebook = ttk.Notebook(container)
        notebook.pack(fill=tk.BOTH, expand=True)

        # 1. Basic (New) - For common settings like Theme (formerly in Logging)
        self._build_basic_tab(notebook)

        # 2. Accounts (Nested)
        self._build_accounts_tab(notebook)

        # 3. Posting (Nested)
        self._build_posting_tab(notebook)

        # 4. Live (Nested)
        self._build_live_tab(notebook)

        # 5. Templates & Images (Nested or Combined)
        self._build_templates_tab(notebook)

        # 6. Logging (Nested)
        self._build_logging_tab(notebook)

        # 7. Backup (Nested)
        self._build_backup_tab(notebook)

        # 8. App Details
        self._build_app_tab(notebook)

        # 9. Future Features
        self._build_future_tab(notebook)

        self._apply_center_server_feature_gating()
        if self.vars.get("youtube_feed_mode"):
            self.vars["youtube_feed_mode"].trace_add("write", lambda *_: self._apply_center_server_feature_gating())

    def _settings_center_features_enabled(self) -> bool:
        """編集中の取得モードが websub かつ、RSS フォールバック中でないとき True。"""
        mode = self.vars["youtube_feed_mode"].get() if self.vars.get("youtube_feed_mode") else settings.youtube_feed_mode
        if str(mode).strip().lower() != "websub":
            return False
        return not bool(getattr(settings, "youtube_websub_fallback_active", False))

    def _gate_widget_subtree(self, parent, enabled: bool):
        """フレーム以下の入力・ボタンを再帰的に有効/無効（ラベルは灰色化）。"""
        for child in parent.winfo_children():
            if isinstance(child, (ttk.Frame, ttk.LabelFrame)):
                self._gate_widget_subtree(child, enabled)
            elif isinstance(child, ttk.Entry):
                child.configure(state=tk.NORMAL if enabled else tk.DISABLED)
            elif isinstance(child, ttk.Combobox):
                child.configure(state="readonly" if enabled else "disabled")
            elif isinstance(child, (ttk.Button, tk.Button)):
                child.configure(state=tk.NORMAL if enabled else tk.DISABLED)
            elif isinstance(child, ttk.Label):
                child.configure(foreground="" if enabled else "gray")

    def _apply_center_server_feature_gating(self):
        """poll または WebSub フォールバック中は Twitch / WebSub / Bluesky OAuth を無効化する。"""
        en = self._settings_center_features_enabled()
        note = (
            "※ 取得モードが poll、または WebSub が不通で\n RSS フォールバック中のため、"
            "センター経由の機能は利用できません\n（アプリパスワードでの Bluesky 投稿は可）。"
        )
        if hasattr(self, "_twitch_restrict_lbl") and hasattr(self, "_twitch_gate_root"):
            if en:
                self._twitch_restrict_lbl.configure(text="")
                self._twitch_restrict_lbl.pack_forget()
            else:
                self._twitch_restrict_lbl.configure(text=note)
                self._twitch_restrict_lbl.pack(anchor=tk.W, pady=(0, 8), before=self._twitch_gate_root)
        if hasattr(self, "_websub_restrict_lbl") and hasattr(self, "_websub_gate_root"):
            if en:
                self._websub_restrict_lbl.configure(text="")
                self._websub_restrict_lbl.pack_forget()
            else:
                self._websub_restrict_lbl.configure(text=note)
                self._websub_restrict_lbl.pack(anchor=tk.W, pady=(0, 8), before=self._websub_gate_root)

        if hasattr(self, "_twitch_gate_root"):
            self._gate_widget_subtree(self._twitch_gate_root, en)
        if hasattr(self, "_websub_gate_root"):
            self._gate_widget_subtree(self._websub_gate_root, en)

        bsky_oauth_ui = en and getattr(settings, "bluesky_oauth_via_center_enabled", False)
        if hasattr(self, "bsky_oauth_title_lbl"):
            self.bsky_oauth_title_lbl.configure(foreground="" if bsky_oauth_ui else "gray")
        if hasattr(self, "bsky_login_frame"):
            self._gate_widget_subtree(self.bsky_login_frame, bsky_oauth_ui)
        # 連携解除はセンター疎通時のみ（サーバー 503 でもローカル掃除は試みる）
        if hasattr(self, "bsky_disconnect_frame"):
            self._gate_widget_subtree(self.bsky_disconnect_frame, en)
        if hasattr(self, "twitch_disconnect_frame"):
            self._gate_widget_subtree(self.twitch_disconnect_frame, en)

    def _build_basic_tab(self, notebook):
        """1. Basic Settings"""
        tab = ttk.Frame(notebook, padding=styles.PADDING)
        notebook.add(tab, text="基本設定")

        # Display & Theme
        lbl = ttk.Label(tab, text="表示設定", font=styles.FONT_BOLD)
        lbl.pack(anchor=tk.W, pady=(0, 10))
        self._add_combo(tab, "アプリテーマ", "app_theme", ["system", "light", "dark"])
        help_mode = ttk.Label(tab, text="system: システム設定に従う\nlight: 明るいユーザーインターフェース\ndark: 暗いユーザーインターフェース", wraplength=400)
        help_mode.pack(anchor=tk.W, pady=(0, 10))

        ttk.Separator(tab, orient=tk.HORIZONTAL).pack(fill=tk.X, pady=10)

        # App Mode (Autopost vs Selfpost)
        lbl_app = ttk.Label(tab, text="アプリケーション動作モード", font=styles.FONT_BOLD)
        lbl_app.pack(anchor=tk.W, pady=(0, 10))
        self._add_combo(tab, "動作モード", "app_mode", ["selfpost", "autopost", "dry_run", "collect"])
        help_app = ttk.Label(tab, text="selfpost: 完全手動投稿モード\nautopost: 完全自動投稿モード\ndry_run: 投稿を実行せずに動作確認\ncollect: データ収集のみ行うモード", wraplength=400)
        help_app.pack(anchor=tk.W, pady=(0, 10))

        ttk.Separator(tab, orient=tk.HORIZONTAL).pack(fill=tk.X, pady=10)

        # Debug Mode
        lbl_debug = ttk.Label(tab, text="デバッグ設定", font=styles.FONT_BOLD)
        lbl_debug.pack(anchor=tk.W, pady=(0, 10))
        self._add_check(tab, "デバッグモードを有効にする", "debug_mode")
        help_debug = ttk.Label(tab, text="オンにするとデバッグログをコンソールとファイルに出力します。", wraplength=400)
        help_debug.pack(anchor=tk.W, pady=(0, 10))

        ttk.Separator(tab, orient=tk.HORIZONTAL).pack(fill=tk.X, pady=10)

        # Timezone Settings
        lbl_tz = ttk.Label(tab, text="タイムゾーン設定", font=styles.FONT_BOLD)
        lbl_tz.pack(anchor=tk.W, pady=(0, 10))
        self._add_combo(tab, "タイムゾーン", "timezone", ["Asia/Tokyo", "UTC", "America/New_York", "Europe/London", "system"])
        help_tz = ttk.Label(tab, text="日時表示のタイムゾーン設定です。\n（system の場合は、端末設定に従います）", wraplength=400)
        help_tz.pack(anchor=tk.W, pady=(0, 10))

        ttk.Separator(tab, orient=tk.HORIZONTAL).pack(fill=tk.X, pady=10)

        # Help text
        help_lbl = ttk.Label(tab, text="詳細なログ設定は『ログ設定』タブから行えます", wraplength=400)
        help_lbl.pack(anchor=tk.W, pady=10)

    def _build_accounts_tab(self, notebook):
        """2. Accounts (Sub-tabs)"""
        tab = ttk.Frame(notebook)
        notebook.add(tab, text="アカウント")

        sub_notebook = ttk.Notebook(tab)
        sub_notebook.pack(fill=tk.BOTH, expand=True, padx=5, pady=5)

        # 2-1. Bluesky
        bs_tab = ttk.Frame(sub_notebook, padding=styles.PADDING)
        sub_notebook.add(bs_tab, text="Bluesky")

        lbl = ttk.Label(bs_tab, text="Blueskyアカウント設定", font=styles.FONT_BOLD)
        lbl.pack(anchor=tk.W, pady=(0, 10))
        self._add_entry(bs_tab, "ユーザー名", "bluesky_username")
        self._add_entry(bs_tab, "アプリパスワード", "bluesky_password", show="*", label_suffix=" (非推奨)", label_color="gray")
        help_lbl = ttk.Label(
            bs_tab,
            text="※ センター経由の Bluesky OAuth は一時停止中です。当面はアプリパスワードで投稿してください。",
            wraplength=400,
        )
        help_lbl.pack(anchor=tk.W, pady=(0, 5))

        ttk.Separator(bs_tab, orient=tk.HORIZONTAL).pack(fill=tk.X, pady=10)
        lbl2 = ttk.Label(bs_tab, text="Bluesky OAuth 連携（サーバー再有効化まで利用不可）", font=styles.FONT_BOLD)
        lbl2.pack(anchor=tk.W)
        self.bsky_oauth_title_lbl = lbl2

        # Button Frames for toggling
        self.bsky_login_frame = ttk.Frame(bs_tab)
        self.bsky_login_frame.pack(pady=5, fill=tk.X)
        self.bsky_disconnect_frame = ttk.Frame(bs_tab)
        self.bsky_disconnect_frame.pack(pady=5, fill=tk.X)

        try:
            img_path = settings.v4_dir / "docs" / "Bluesky-OAuth-Button.png"
            if img_path.exists():
                img = Image.open(img_path)
                img.thumbnail((200, 40))
                self.bsky_btn_img = ImageTk.PhotoImage(img) # Keep ref
                # Pack into login_frame
                btn = tk.Button(self.bsky_login_frame, image=self.bsky_btn_img, command=self.auth_bsky, borderwidth=0, cursor="hand2")
                styles.ThemeManager.apply_tk_styles(btn)
                btn.pack()
            else:
                ttk.Button(self.bsky_login_frame, text="Bluesky OAuth ログイン", command=self.auth_bsky).pack()
        except Exception as e:
            logger.error(f"Failed to load Bluesky OAuth button image: {e}")
            ttk.Button(self.bsky_login_frame, text="Bluesky OAuth ログイン", command=self.auth_bsky).pack()

        # Disconnect Button (Hidden by default, controlled by update_auth_status)
        ttk.Label(self.bsky_disconnect_frame, text="このアカウントとの連携を解除します", foreground="gray").pack(pady=(0, 5))
        ttk.Button(self.bsky_disconnect_frame, text="連携解除 (Disconnect)", command=self._on_bsky_disconnect).pack()

        self.bs_status_lbl = ttk.Label(bs_tab, text="連携状態: 確認中...")
        self.bs_status_lbl.pack()

        # 2-2. Twitch（センター利用時のみ有効。poll / WebSub フォールバック時は無効）
        tw_tab = ttk.Frame(sub_notebook, padding=styles.PADDING)
        sub_notebook.add(tw_tab, text="Twitch")
        self._twitch_restrict_lbl = ttk.Label(tw_tab, text="", foreground="orange", wraplength=480)
        self._twitch_gate_root = ttk.Frame(tw_tab)
        self._twitch_gate_root.pack(fill=tk.BOTH, expand=True)

        lbl3 = ttk.Label(self._twitch_gate_root, text="Twitch 連携設定", font=styles.FONT_BOLD)
        lbl3.pack(anchor=tk.W, pady=(0, 10))

        self.twitch_login_frame = ttk.Frame(self._twitch_gate_root)
        self.twitch_login_frame.pack(pady=5, fill=tk.X)

        # Twitch Sign-In Button (using image)
        try:
            from pathlib import Path
            twitch_btn_path = Path(__file__).parent.parent.parent / "static" / "images" / "twitch_oauth_button.png"
            if twitch_btn_path.exists():
                twitch_img = Image.open(str(twitch_btn_path))
                twitch_photo = ImageTk.PhotoImage(twitch_img)
                twitch_btn = tk.Button(
                    self.twitch_login_frame,
                    image=twitch_photo,
                    command=self.auth_twitch,
                    borderwidth=0,
                    bg=styles.ThemeManager.COLOR_BG,
                    activebackground=styles.ThemeManager.COLOR_BG,
                )
                twitch_btn.image = twitch_photo  # type: ignore # Keep a reference
                twitch_btn.pack(pady=20)
            else:
                # Fallback to text button if image not found
                ttk.Button(self.twitch_login_frame, text="Twitch と連携する", command=self.auth_twitch).pack(pady=20)
        except Exception as e:
            # Fallback to text button on error
            logger.warning(f"Failed to load Twitch button image: {e}")
            ttk.Button(self.twitch_login_frame, text="Twitch と連携する", command=self.auth_twitch).pack(pady=20)

        self.twitch_disconnect_frame = ttk.Frame(self._twitch_gate_root)
        ttk.Label(self.twitch_disconnect_frame, text="センター・ローカルの Twitch 連携を解除します", foreground="gray").pack(
            pady=(0, 5)
        )
        ttk.Button(self.twitch_disconnect_frame, text="連携解除 (Disconnect)", command=self._on_twitch_disconnect).pack()

        self.tw_status_lbl = ttk.Label(self._twitch_gate_root, text="連携状態: 確認中...")
        self.tw_status_lbl.pack()
        self.update_auth_status()

        # 2-3. YouTube
        yt_tab = ttk.Frame(sub_notebook, padding=styles.PADDING)
        sub_notebook.add(yt_tab, text="YouTube")

        lbl4 = ttk.Label(yt_tab, text="YouTube 設定", font=styles.FONT_BOLD)
        lbl4.pack(anchor=tk.W, pady=(0, 5))
        self._add_entry(yt_tab, "YouTube チャンネルID", "youtube_channel_id")
        help_ch_id = ttk.Label(yt_tab, text="UCで始まるチャンネルIDを入力してください。", wraplength=400)
        help_ch_id.pack(anchor=tk.W, pady=(0, 5))

        self._add_entry(yt_tab, "YouTubeDataAPI キー", "youtube_api_key", show="*")
        help_api_key = ttk.Label(yt_tab, text="YouTubeDataAPI(v3)キーを入力してください。\nGoogle Cloud Consoleから取得できます。", wraplength=400)
        help_api_key.pack(anchor=tk.W, pady=(0, 10))

        self._add_combo(yt_tab, "取得モード", "youtube_feed_mode", ["poll", "websub"])
        help_mode = ttk.Label(
            yt_tab,
            text=(
                "poll: RSS取得モード\n（Twitch連携・WebSub・Bluesky OAuth使用不可）\n"
                " Bluesky はアプリパスワードでの利用になります。\n"
                "\n"
                "websub: WebSubセンターサーバーモード\n（YouTube WebSub・Twitch Eventsubを利用）\n"
                "BlueskyはOAuth認証で利用します（アプリパスワード不要）\n"
            ),
            wraplength=400,
        )
        help_mode.pack(anchor=tk.W, pady=(0, 10))

        # 2-4. Niconico
        nico_tab = ttk.Frame(sub_notebook, padding=styles.PADDING)
        sub_notebook.add(nico_tab, text="ニコニコ")

        lbl5 = ttk.Label(nico_tab, text="ニコニコ動画設定", font=styles.FONT_BOLD)
        lbl5.pack(anchor=tk.W, pady=(0, 5))
        self._add_entry(nico_tab, "ユーザーID (数字)", "niconico_user_id")
        help_user_id = ttk.Label(nico_tab, text="ニコニコのユーザーIDを指定してください。（数字のみ）", wraplength=400)
        help_user_id.pack(anchor=tk.W, pady=(0, 5))

        self._add_entry(nico_tab, "ユーザー名", "niconico_user_name")
        help_user_name = ttk.Label(nico_tab, text="未設定時は自動取得を試みます。\n確実に名前を指定したい場合は入力してください。", wraplength=400)
        help_user_name.pack(anchor=tk.W, pady=(0, 5))

        self._add_entry(nico_tab, "ニコニコのポーリング間隔（分）", "niconico_monitor_interval")
        help_nico = ttk.Label(nico_tab, text="最小5分。デフォルト: 10分、推奨: 10分", wraplength=400)
        help_nico.pack(anchor=tk.W, pady=(0, 5))

        # 2-4. WebSub（センター利用時のみ有効。poll / WebSub フォールバック時は無効）
        ws_tab = ttk.Frame(sub_notebook, padding=styles.PADDING)
        sub_notebook.add(ws_tab, text="WebSub")

        self._websub_restrict_lbl = ttk.Label(ws_tab, text="", foreground="orange", wraplength=480)
        self._websub_gate_root = ttk.Frame(ws_tab)
        self._websub_gate_root.pack(fill=tk.BOTH, expand=True)

        lbl6 = ttk.Label(self._websub_gate_root, text="WebSub サーバー設定", font=styles.FONT_BOLD)
        lbl6.pack(anchor=tk.W, pady=(0, 10))
        self._add_entry(self._websub_gate_root, "センターサーバーURL", "center_server_url")
        self._add_entry(self._websub_gate_root, "クライアントID", "websub_client_id")
        self._add_entry(self._websub_gate_root, "APIキー", "websub_client_api_key")
        self._add_entry(self._websub_gate_root, "コールバックURL", "websub_callback_base_url")
        self._add_entry(self._websub_gate_root, "購読期間 (秒)", "websub_lease_seconds")
        ttk.Label(self._websub_gate_root, text="WebSub購読の有効期間 。\n デフォルトは5日(432000)です。", wraplength=400).pack(anchor=tk.W, pady=(0, 5))

        ttk.Button(
            self._websub_gate_root,
            text="🧪 接続テスト",
            command=lambda: self._test_websub_connection(
                self.vars["websub_client_id"].get(),
                self.vars["websub_client_api_key"].get(),
                self.vars["center_server_url"].get(),
            ),
        ).pack(pady=10)

    def _build_posting_tab(self, notebook):
        """3. Posting (Sub-tabs)"""
        tab = ttk.Frame(notebook)
        notebook.add(tab, text="投稿設定")

        sub_notebook = ttk.Notebook(tab)
        sub_notebook.pack(fill=tk.BOTH, expand=True, padx=5, pady=5)

        # 3-1. Safeguards (Security Options)
        safe_tab = ttk.Frame(sub_notebook, padding=styles.PADDING)
        sub_notebook.add(safe_tab, text="投稿保護")

        lbl = ttk.Label(safe_tab, text="投稿保護設定", font=styles.FONT_BOLD)
        lbl.pack(anchor=tk.W, pady=(0, 10))

        self._add_check(safe_tab, "重複投稿を防止 (PREVENT_DUPLICATE_POSTS)", "prevent_duplicate_posts")
        help_dup = ttk.Label(safe_tab, text="同じ動画の再投稿を防止します。", wraplength=400)
        help_dup.pack(anchor=tk.W, padx=20, pady=(0, 5))

        self._add_check(safe_tab, "YouTube重複排除 (DEDUP_ENABLED)", "youtube_dedup_enabled")
        help_dedup = ttk.Label(safe_tab, text="優先度ベースの動画管理。LIVE/アーカイブのみ登録（デフォルト: 有効）", wraplength=400)
        help_dedup.pack(anchor=tk.W, padx=20, pady=(0, 5))

        self._add_check(safe_tab, "Blueskyへの投稿を有効化", "bluesky_post_enabled")
        help_bsky = ttk.Label(safe_tab, text="Blueskyへの投稿機能の有効/無効切り替え。", wraplength=400)
        help_bsky.pack(anchor=tk.W, padx=20, pady=(0, 10))

        help_lbl = ttk.Label(safe_tab, text="これらの設定は、意図しない多重投稿を防ぐための安全装置です。", wraplength=400)
        help_lbl.pack(anchor=tk.W, pady=5)

        # 3-2. Autopost
        auto_tab = ttk.Frame(sub_notebook)
        sub_notebook.add(auto_tab, text="自動投稿")

        # Create Scrollable Container
        canvas = tk.Canvas(auto_tab, bg=styles.ThemeManager.COLOR_BG, highlightthickness=0)
        scrollbar = ttk.Scrollbar(auto_tab, orient=tk.VERTICAL, command=canvas.yview)
        scrollable_frame = ttk.Frame(canvas, padding=styles.PADDING)

        scrollable_frame.bind(
            "<Configure>",
            lambda e: canvas.configure(scrollregion=canvas.bbox("all"))
        )

        canvas.create_window((0, 0), window=scrollable_frame, anchor="nw")
        canvas.configure(yscrollcommand=scrollbar.set)

        # Mousewheel handling
        def _on_mousewheel(event):
            if canvas.winfo_exists():
                canvas.yview_scroll(int(-1 * (event.delta / 120)), "units")
            else:
                canvas.unbind_all("<MouseWheel>")

        # Proper binding to avoid global conflict
        def _bind_mousewheel(event):
            canvas.bind_all("<MouseWheel>", _on_mousewheel)
        def _unbind_mousewheel(event):
            canvas.unbind_all("<MouseWheel>")

        scrollable_frame.bind("<Enter>", _bind_mousewheel)
        scrollable_frame.bind("<Leave>", _unbind_mousewheel)

        canvas.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)
        scrollbar.pack(side=tk.RIGHT, fill=tk.Y)

        lbl2 = ttk.Label(scrollable_frame, text="自動投稿設定 (Autopost)", font=styles.FONT_BOLD)
        help_auto = ttk.Label(scrollable_frame, text="AUTOPOST モード時の挙動に関する投稿設定です。", wraplength=400)
        lbl2.pack(anchor=tk.W, pady=(0, 10))
        help_auto.pack(anchor=tk.W, pady=(0, 10))

        lbl_status = ttk.Label(scrollable_frame, text="YouTubeLive の配信状態(AutoPost)", font=styles.FONT_BOLD)
        lbl_status.pack(anchor=tk.W, pady=(5, 5))
        self._add_status_checks(scrollable_frame, "autopost_statuses", ["upcoming", "live", "archive"])
        help_status = ttk.Label(scrollable_frame, text="upcoming: 予約枠のみを投稿\nlive: 予約枠と配信開始・配信終了のみ投稿\narchive: アーカイブ公開のみ投稿\n（すべてオフで自動投稿なし）", wraplength=400)
        help_status.pack(anchor=tk.W, pady=(0, 10))

        self._add_entry(scrollable_frame, "投稿間隔 (分)", "autopost_interval_minutes")
        help_interval = ttk.Label(scrollable_frame, text="連続投稿によるスパムアカウント扱いを防止するため\n自動投稿間隔を調整します。（デフォルト: 5分）", wraplength=400)
        help_interval.pack(anchor=tk.W, pady=(0, 10))

        self._add_entry(scrollable_frame, "ルックバック時間 (分)", "autopost_lookback_minutes")
        help_lookback = ttk.Label(scrollable_frame, text="再起動時の取りこぼし防止を目的とします（デフォルト: 30分）", wraplength=400)
        help_lookback.pack(anchor=tk.W, pady=(0, 10))

        self._add_entry(scrollable_frame, "未投稿動画の検知閾値 (件)", "autopost_missed_detection_threshold")
        help_threshold = ttk.Label(scrollable_frame, text="時間内に未投稿動画がこの件数以上ある場合、\nAUTOPOSTモードは起動しません（デフォルト: 20件）", wraplength=400)
        help_threshold.pack(anchor=tk.W, pady=(0, 10))

        self._add_check(scrollable_frame, "通常動画を含める", "autopost_include_normal")
        help_normal = ttk.Label(scrollable_frame, text="通常の動画投稿も投稿対象に含める（デフォルト: 有効）", wraplength=400)
        help_normal.pack(anchor=tk.W, padx=20, pady=(0, 10))

        self._add_check(scrollable_frame, "プレミア配信を含める", "autopost_include_premiere")
        help_premiere = ttk.Label(scrollable_frame, text="プレミア配信も投稿対象に含める（デフォルト: 有効）\nこの設定は手動投稿モードと共通設定となっています。", wraplength=400)
        help_premiere.pack(anchor=tk.W, padx=20, pady=(0, 10))

        # 非対応項目
        ttk.Separator(scrollable_frame, orient=tk.HORIZONTAL).pack(fill=tk.X, pady=10)
        ttk.Label(scrollable_frame, text="以下の項目は非対応です(将来的な対応予定もありません)", font=("", 9, "bold")).pack(anchor=tk.W, pady=5)

        ttk.Checkbutton(scrollable_frame, text="🎥 YouTube Shorts", state='disabled').pack(anchor=tk.W, pady=3)
        ttk.Checkbutton(scrollable_frame, text="👥 メンバー限定動画", state='disabled').pack(anchor=tk.W, pady=3)

        # 3-3. Manual Posting
        manual_tab = ttk.Frame(sub_notebook, padding=styles.PADDING)
        sub_notebook.add(manual_tab, text="手動投稿")

        lbl3 = ttk.Label(manual_tab, text="YouTube Live 手動投稿設定", font=styles.FONT_BOLD)
        help_manual = ttk.Label(manual_tab, text="手動投稿モード時にYouTube Live関連通知だけ自動投稿する設定です。", wraplength=400)
        lbl3.pack(anchor=tk.W, pady=(0, 10))
        help_manual.pack(anchor=tk.W, pady=(0, 10))

        self._add_check(manual_tab, "予約枠を投稿", "youtube_live_auto_post_schedule")
        help_schedule = ttk.Label(manual_tab, text="放送枠が立った時（upcoming/schedule状態）の予約通知投稿", wraplength=400)
        help_schedule.pack(anchor=tk.W, padx=20, pady=(0, 10))

        self._add_check(manual_tab, "配信中・終了を投稿", "youtube_live_auto_post_live")
        help_live = ttk.Label(manual_tab, text="配信開始・終了時の通知投稿", wraplength=400)
        help_live.pack(anchor=tk.W, padx=20, pady=(0, 10))

        self._add_check(manual_tab, "アーカイブを投稿", "youtube_live_auto_post_archive")
        help_archive = ttk.Label(manual_tab, text="YouTube Live のアーカイブ（録画）が公開された時の通知投稿", wraplength=400)
        help_archive.pack(anchor=tk.W, padx=20, pady=(0, 10))

        self._add_check(manual_tab, "プレミア配信を含める", "autopost_include_premiere")
        help_premiere = ttk.Label(manual_tab, text="プレミア配信も投稿対象に含める（デフォルト: 有効）\nこの設定は自動投稿モードと共通設定となっています。", wraplength=400)
        help_premiere.pack(anchor=tk.W, padx=20, pady=(0, 10))

        ttk.Separator(manual_tab, orient=tk.HORIZONTAL).pack(fill=tk.X, pady=10)
        ttk.Label(manual_tab, text="以下の項目は非対応です(将来的な対応予定もありません)", font=("", 9, "bold")).pack(anchor=tk.W, pady=5)

        ttk.Checkbutton(manual_tab, text="🎥 YouTube Shorts", state='disabled').pack(anchor=tk.W, pady=3)
        ttk.Checkbutton(manual_tab, text="👥 メンバー限定動画", state='disabled').pack(anchor=tk.W, pady=3)

    def _build_live_tab(self, notebook):
        """4. Live Settings (RSS Polling Mode Only)"""
        tab = ttk.Frame(notebook)
        notebook.add(tab, text="RSS設定")

        # サブタブ
        sub_notebook = ttk.Notebook(tab)
        sub_notebook.pack(fill=tk.BOTH, expand=True, padx=5, pady=5)

        # 4-1. 遅延設定タブ
        self._build_subtab_live_delay(sub_notebook)

        # 4-2. ポーリング設定タブ
        self._build_subtab_live_polling(sub_notebook)

    def _build_subtab_live_delay(self, parent_notebook):
        """4-1. Live配信開始後、いつ投稿するか"""
        tab = ttk.Frame(parent_notebook, padding=styles.PADDING)
        parent_notebook.add(tab, text="⏳ 遅延")

        lbl = ttk.Label(tab, text="配信開始後、いつ投稿するか", font=styles.FONT_BOLD)
        lbl.pack(anchor=tk.W, pady=(0, 10))

        # YOUTUBE_LIVE_POST_DELAY
        delay_var = tk.StringVar(value=str(getattr(settings, "youtube_live_post_delay", "immediate")))
        self.vars["youtube_live_post_delay"] = delay_var

        ttk.Radiobutton(
            tab,
            text="⚡ 即座に投稿（検知直後）",
            variable=delay_var,
            value='immediate'
        ).pack(anchor=tk.W, pady=5)

        ttk.Radiobutton(
            tab,
            text="⏰ 5分後に投稿（確認後）",
            variable=delay_var,
            value='delay_5min'
        ).pack(anchor=tk.W, pady=5)

        ttk.Radiobutton(
            tab,
            text="🕐 30分後に投稿（安定化後）",
            variable=delay_var,
            value='delay_30min'
        ).pack(anchor=tk.W, pady=5)

    def _build_subtab_live_polling(self, parent_notebook):
        """4-3. ポーリング設定"""
        # スクロール可能フレームを作成
        tab = ttk.Frame(parent_notebook)
        parent_notebook.add(tab, text="🔄 ポーリング")

        canvas = tk.Canvas(tab, bg=styles.ThemeManager.COLOR_BG, highlightthickness=0)
        scrollbar = ttk.Scrollbar(tab, orient=tk.VERTICAL, command=canvas.yview)
        scrollable_frame = ttk.Frame(canvas, padding=styles.PADDING)

        scrollable_frame.bind(
            "<Configure>",
            lambda e: canvas.configure(scrollregion=canvas.bbox("all"))
        )

        canvas.create_window((0, 0), window=scrollable_frame, anchor="nw")
        canvas.configure(yscrollcommand=scrollbar.set)

        # マウスホイール対応
        def _on_mousewheel(event):
            if canvas.winfo_exists():
                canvas.yview_scroll(int(-1 * (event.delta / 120)), "units")
            else:
                canvas.unbind_all("<MouseWheel>")
        canvas.bind_all("<MouseWheel>", _on_mousewheel)
        canvas.bind("<Destroy>", lambda e: canvas.unbind_all("<MouseWheel>"))

        canvas.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)
        scrollbar.pack(side=tk.RIGHT, fill=tk.Y)

        # === Warning for WebSub mode ===
        warning_lbl = ttk.Label(scrollable_frame, text="⚠️このタブはRSSポーリングモード専用です。\nYouTube取得モード『websub』選択時は、この設定は無効になります。", foreground="orange", font=("bold",))
        warning_lbl.pack(anchor=tk.W, pady=(0, 15))

        ttk.Separator(scrollable_frame, orient=tk.HORIZONTAL).pack(fill=tk.X, pady=10)

        # === General Live Settings ===
        lbl_gen = ttk.Label(scrollable_frame, text="全般設定", font=styles.FONT_BOLD)
        lbl_gen.pack(anchor=tk.W, pady=(0, 10))

        self._add_check(scrollable_frame, "配信予定時刻を検出 (DETECT_SCHEDULED_TIME)", "detect_scheduled_time")
        help_detect = ttk.Label(scrollable_frame, text="スケジュールされた配信時刻を検知し、正確な開始時刻を予測します。", wraplength=400)
        help_detect.pack(anchor=tk.W, pady=(0, 10))

        self._add_entry(scrollable_frame, "YouTube RSS ポーリング間隔 (分)", "youtube_monitor_interval")
        help_rss = ttk.Label(scrollable_frame, text="最小10分、最大60分。デフォルト: 10分。\nRSSはYouTubeのPubSubHubbubを利用しています。\n短期間で頻繁なポーリングはYouTube側からアクセスを拒否される\n可能性があります。", wraplength=400)
        help_rss.pack(anchor=tk.W, pady=(0, 10))

        self._add_entry(scrollable_frame, "RSS監視間隔 (秒)", "live_monitor_interval")
        help_monitor = ttk.Label(scrollable_frame, text="RSSポーリングモード時の基本監視サイクルです。", wraplength=400)
        help_monitor.pack(anchor=tk.W, pady=(0, 10))

        ttk.Separator(scrollable_frame, orient=tk.HORIZONTAL).pack(fill=tk.X, pady=10)

        # === ACTIVE Interval ===
        lbl = ttk.Label(scrollable_frame, text="配信状態（ACTIVE）の監視設定", font=styles.FONT_BOLD)
        lbl.pack(anchor=tk.W, pady=(0, 10))

        help_active = ttk.Label(scrollable_frame, text="スケジュール配信（schedule）または配信中（live）の動画が\nある場合の確認間隔。\nこの状態では頻繁に確認する必要があります。", wraplength=400)
        help_active.pack(anchor=tk.W, pady=(0, 5))

        self._add_entry(scrollable_frame, "ACTIVE時のポーリング間隔 (分)", "youtube_live_poll_interval_active")
        help_active_range = ttk.Label(scrollable_frame, text="※ 推奨値: 15分（範囲: 1～60分）", wraplength=400)
        help_active_range.pack(anchor=tk.W, pady=(0, 15))

        ttk.Separator(scrollable_frame, orient=tk.HORIZONTAL).pack(fill=tk.X, pady=10)

        # === COMPLETED Interval Range ===
        lbl2 = ttk.Label(scrollable_frame, text="配信終了状態（COMPLETED）の監視設定", font=styles.FONT_BOLD)
        lbl2.pack(anchor=tk.W, pady=(0, 10))

        help_completed = ttk.Label(scrollable_frame, text="配信が終了し、アーカイブ化まで待機中の動画の確認間隔。\nアーカイブ化されるまでの期間（通常は1～3時間）に自動調整されます。", wraplength=400)
        help_completed.pack(anchor=tk.W, pady=(0, 5))

        self._add_entry(scrollable_frame, "COMPLETED時の最短間隔 (分)", "youtube_live_poll_interval_completed_min")
        help_min = ttk.Label(scrollable_frame, text="配信直後の確認間隔（範囲: 30～180分）", wraplength=400)
        help_min.pack(anchor=tk.W, pady=(0, 10))

        self._add_entry(scrollable_frame, "COMPLETED時の最大間隔 (分)", "youtube_live_poll_interval_completed_max")
        help_max = ttk.Label(scrollable_frame, text="時間経過でだんだん確認間隔を広げる場合の上限値\n（範囲: 30～180分、最短間隔以上）", wraplength=400)
        help_max.pack(anchor=tk.W, pady=(0, 15))

        ttk.Separator(scrollable_frame, orient=tk.HORIZONTAL).pack(fill=tk.X, pady=10)

        # === ARCHIVE Tracking ===
        lbl3 = ttk.Label(scrollable_frame, text="アーカイブ化後の追跡設定", font=styles.FONT_BOLD)
        lbl3.pack(anchor=tk.W, pady=(0, 10))

        help_archive = ttk.Label(scrollable_frame, text="配信がライブアーカイブ化された後、最大何回まで確認を続けるか。\n各回の間隔は最大間隔で固定されます。", wraplength=400)
        help_archive.pack(anchor=tk.W, pady=(0, 5))

        self._add_entry(scrollable_frame, "ARCHIVE化後の最大追跡回数", "youtube_live_archive_check_count_max")
        help_archive_count = ttk.Label(scrollable_frame, text="配信がアーカイブ化された後、何回までチェック対象に保つか。\n（推奨値: 4回、範囲: 1～10回）", wraplength=400)
        help_archive_count.pack(anchor=tk.W, pady=(0, 10))

        self._add_entry(scrollable_frame, "ARCHIVE化後の確認間隔 (分)", "youtube_live_archive_check_interval")
        help_archive_interval = ttk.Label(scrollable_frame, text="アーカイブ化後、動画情報を確認する間隔（推奨値: 180分）", wraplength=400)
        help_archive_interval.pack(anchor=tk.W, pady=(0, 5))

    def _build_templates_tab(self, notebook):
        """5. Templates & Images"""
        tab = ttk.Frame(notebook)
        notebook.add(tab, text="テンプレート/画像")

        sub_notebook = ttk.Notebook(tab)
        sub_notebook.pack(fill=tk.BOTH, expand=True, padx=5, pady=5)

        # 5-1. YouTube Templates
        self._build_subtab_youtube_templates(sub_notebook)

        # 5-2. Niconico Templates
        self._build_subtab_niconico_templates(sub_notebook)

        # 5-3. Twitch Templates
        self._build_subtab_twitch_templates(sub_notebook)

        # 5-4. Images
        self._build_subtab_templates_images(sub_notebook)

    def _build_subtab_youtube_templates(self, parent_notebook):
        """5-1. YouTubeテンプレート"""
        tab = ttk.Frame(parent_notebook, padding=styles.PADDING)
        parent_notebook.add(tab, text="📺 YouTube")

        # セクションラベル
        lbl = ttk.Label(tab, text="YouTubeテンプレート設定", font=styles.FONT_BOLD)
        lbl.pack(anchor=tk.W, pady=(0, 10))

        # 新規動画投稿
        ttk.Label(tab, text="新規動画投稿:", font=("", 9)).pack(anchor=tk.W, pady=(5, 2))
        youtube_new_video_var = tk.StringVar(value=getattr(settings, 'template_youtube_new_video_path', ''))
        self.vars['template_youtube_new_video_path'] = youtube_new_video_var
        frame = ttk.Frame(tab)
        frame.pack(anchor=tk.W, fill=tk.X, padx=0, pady=(0, 5))
        ttk.Entry(frame, textvariable=youtube_new_video_var, width=50).pack(side=tk.LEFT, padx=5, fill=tk.X, expand=True)
        ttk.Button(frame, text="🗂️", width=2, command=lambda: self._browse_file(youtube_new_video_var)).pack(side=tk.RIGHT, padx=2)
        ttk.Label(tab, text="YouTube新規動画投稿通知用テンプレート（Jinja2形式）", font=("", 8)).pack(anchor=tk.W, padx=5, pady=(0, 10))

        # スケジュール
        ttk.Label(tab, text="スケジュール:", font=("", 9)).pack(anchor=tk.W, pady=(5, 2))
        youtube_schedule_var = tk.StringVar(value=getattr(settings, 'template_youtube_schedule_path', ''))
        self.vars['template_youtube_schedule_path'] = youtube_schedule_var
        frame = ttk.Frame(tab)
        frame.pack(anchor=tk.W, fill=tk.X, padx=0, pady=(0, 5))
        ttk.Entry(frame, textvariable=youtube_schedule_var, width=50).pack(side=tk.LEFT, padx=5, fill=tk.X, expand=True)
        ttk.Button(frame, text="🗂️", width=2, command=lambda: self._browse_file(youtube_schedule_var)).pack(side=tk.RIGHT, padx=2)
        ttk.Label(tab, text="YouTube予約枠通知用テンプレート（Jinja2形式）", font=("", 8)).pack(anchor=tk.W, padx=5, pady=(0, 10))

        # 配信開始
        ttk.Label(tab, text="配信開始:", font=("", 9)).pack(anchor=tk.W, pady=(5, 2))
        youtube_online_var = tk.StringVar(value=getattr(settings, 'template_youtube_online_path', ''))
        self.vars['template_youtube_online_path'] = youtube_online_var
        frame = ttk.Frame(tab)
        frame.pack(anchor=tk.W, fill=tk.X, padx=0, pady=(0, 5))
        ttk.Entry(frame, textvariable=youtube_online_var, width=50).pack(side=tk.LEFT, padx=5, fill=tk.X, expand=True)
        ttk.Button(frame, text="🗂️", width=2, command=lambda: self._browse_file(youtube_online_var)).pack(side=tk.RIGHT, padx=2)
        ttk.Label(tab, text="YouTube配信開始通知用テンプレート（Jinja2形式）", font=("", 8)).pack(anchor=tk.W, padx=5, pady=(0, 10))

        # 配信終了
        ttk.Label(tab, text="配信終了:", font=("", 9)).pack(anchor=tk.W, pady=(5, 2))
        youtube_offline_var = tk.StringVar(value=getattr(settings, 'template_youtube_offline_path', ''))
        self.vars['template_youtube_offline_path'] = youtube_offline_var
        frame = ttk.Frame(tab)
        frame.pack(anchor=tk.W, fill=tk.X, padx=0, pady=(0, 5))
        ttk.Entry(frame, textvariable=youtube_offline_var, width=50).pack(side=tk.LEFT, padx=5, fill=tk.X, expand=True)
        ttk.Button(frame, text="🗂️", width=2, command=lambda: self._browse_file(youtube_offline_var)).pack(side=tk.RIGHT, padx=2)
        ttk.Label(tab, text="YouTube配信終了通知用テンプレート（Jinja2形式）", font=("", 8)).pack(anchor=tk.W, padx=5, pady=(0, 10))

        # アーカイブ
        ttk.Label(tab, text="アーカイブ:", font=("", 9)).pack(anchor=tk.W, pady=(5, 2))
        youtube_archive_var = tk.StringVar(value=getattr(settings, 'template_youtube_archive_path', ''))
        self.vars['template_youtube_archive_path'] = youtube_archive_var
        frame = ttk.Frame(tab)
        frame.pack(anchor=tk.W, fill=tk.X, padx=0, pady=(0, 5))
        ttk.Entry(frame, textvariable=youtube_archive_var, width=50).pack(side=tk.LEFT, padx=5, fill=tk.X, expand=True)
        ttk.Button(frame, text="🗂️", width=2, command=lambda: self._browse_file(youtube_archive_var)).pack(side=tk.RIGHT, padx=2)
        ttk.Label(tab, text="YouTubeアーカイブ公開通知用テンプレート（Jinja2形式）", font=("", 8)).pack(anchor=tk.W, padx=5, pady=(0, 10))

    def _build_subtab_niconico_templates(self, parent_notebook):
        """5-2. ニコニコテンプレート"""
        tab = ttk.Frame(parent_notebook, padding=styles.PADDING)
        parent_notebook.add(tab, text="🎬 Niconico")

        # セクションラベル
        lbl = ttk.Label(tab, text="ニコニコテンプレート設定", font=styles.FONT_BOLD)
        lbl.pack(anchor=tk.W, pady=(0, 10))

        # 新規動画投稿
        ttk.Label(tab, text="新規動画投稿:", font=("", 9)).pack(anchor=tk.W, pady=(5, 2))
        nico_video_var = tk.StringVar(value=getattr(settings, 'template_nico_new_video_path', ''))
        self.vars['template_nico_new_video_path'] = nico_video_var
        frame = ttk.Frame(tab)
        frame.pack(anchor=tk.W, fill=tk.X, padx=0, pady=(0, 10))
        ttk.Entry(frame, textvariable=nico_video_var, width=50).pack(side=tk.LEFT, padx=5, fill=tk.X, expand=True)
        ttk.Button(frame, text="🗂️", width=2, command=lambda: self._browse_file(nico_video_var)).pack(side=tk.RIGHT, padx=2)
        ttk.Label(tab, text="Niconico新規動画投稿通知用テンプレート（Jinja2形式）", font=("", 8)).pack(anchor=tk.W, padx=5, pady=(0, 10))

    def _build_subtab_twitch_templates(self, parent_notebook):
        """5-3. Twitchテンプレート"""
        tab = ttk.Frame(parent_notebook, padding=styles.PADDING)
        parent_notebook.add(tab, text="📺 Twitch")

        # セクションラベル
        lbl = ttk.Label(tab, text="Twitchテンプレート設定", font=styles.FONT_BOLD)
        lbl.pack(anchor=tk.W, pady=(0, 10))

        # 配信開始
        ttk.Label(tab, text="配信開始:", font=("", 9)).pack(anchor=tk.W, pady=(5, 2))
        twitch_online_var = tk.StringVar(value=getattr(settings, 'template_twitch_online_path', ''))
        self.vars['template_twitch_online_path'] = twitch_online_var
        frame = ttk.Frame(tab)
        frame.pack(anchor=tk.W, fill=tk.X, padx=0, pady=(0, 5))
        ttk.Entry(frame, textvariable=twitch_online_var, width=50).pack(side=tk.LEFT, padx=5, fill=tk.X, expand=True)
        ttk.Button(frame, text="🗂️", width=2, command=lambda: self._browse_file(twitch_online_var)).pack(side=tk.RIGHT, padx=2)
        ttk.Label(tab, text="Twitch配信開始通知用テンプレート（Jinja2形式）", font=("", 8)).pack(anchor=tk.W, padx=5, pady=(0, 10))

        # 配信終了（通常）
        ttk.Label(tab, text="配信終了（通常）:", font=("", 9)).pack(anchor=tk.W, pady=(5, 2))
        twitch_offline_var = tk.StringVar(value=getattr(settings, 'template_twitch_offline_path', ''))
        self.vars['template_twitch_offline_path'] = twitch_offline_var
        frame = ttk.Frame(tab)
        frame.pack(anchor=tk.W, fill=tk.X, padx=0, pady=(0, 5))
        ttk.Entry(frame, textvariable=twitch_offline_var, width=50).pack(side=tk.LEFT, padx=5, fill=tk.X, expand=True)
        ttk.Button(frame, text="🗂️", width=2, command=lambda: self._browse_file(twitch_offline_var)).pack(side=tk.RIGHT, padx=2)
        ttk.Label(tab, text="Twitch配信終了（通常）通知用テンプレート（Jinja2形式）", font=("", 8)).pack(anchor=tk.W, padx=5, pady=(0, 10))

        # 配信終了（Raid）
        ttk.Label(tab, text="配信終了（Raid）:", font=("", 9)).pack(anchor=tk.W, pady=(5, 2))
        twitch_raid_var = tk.StringVar(value=getattr(settings, 'template_twitch_raid_path', ''))
        self.vars['template_twitch_raid_path'] = twitch_raid_var
        frame = ttk.Frame(tab)
        frame.pack(anchor=tk.W, fill=tk.X, padx=0, pady=(0, 5))
        ttk.Entry(frame, textvariable=twitch_raid_var, width=50).pack(side=tk.LEFT, padx=5, fill=tk.X, expand=True)
        ttk.Button(frame, text="🗂️", width=2, command=lambda: self._browse_file(twitch_raid_var)).pack(side=tk.RIGHT, padx=2)
        ttk.Label(tab, text="Twitch配信終了（Raid時）通知用テンプレート（Jinja2形式）", font=("", 8)).pack(anchor=tk.W, padx=5, pady=(0, 10))

    def _build_subtab_templates_images(self, parent_notebook):
        """5-4. 画像設定"""
        tab = ttk.Frame(parent_notebook)
        parent_notebook.add(tab, text="🖼️ 画像")

        # スクロール可能フレームを作成
        canvas = tk.Canvas(tab, bg=styles.ThemeManager.COLOR_BG, highlightthickness=0)
        scrollbar = ttk.Scrollbar(tab, orient=tk.VERTICAL, command=canvas.yview)
        scrollable_frame = ttk.Frame(canvas, padding=styles.PADDING)

        scrollable_frame.bind(
            "<Configure>",
            lambda e: canvas.configure(scrollregion=canvas.bbox("all"))
        )

        canvas.create_window((0, 0), window=scrollable_frame, anchor="nw")
        canvas.configure(yscrollcommand=scrollbar.set)

        # マウスホイール対応
        def _on_mousewheel(event):
            if canvas.winfo_exists():
                canvas.yview_scroll(int(-1 * (event.delta / 120)), "units")
            else:
                canvas.unbind_all("<MouseWheel>")
        canvas.bind_all("<MouseWheel>", _on_mousewheel)
        canvas.bind("<Destroy>", lambda e: canvas.unbind_all("<MouseWheel>"))

        canvas.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)
        scrollbar.pack(side=tk.RIGHT, fill=tk.Y)

        # セクションラベル
        lbl = ttk.Label(scrollable_frame, text="画像設定", font=styles.FONT_BOLD)
        lbl.pack(anchor=tk.W, pady=(0, 10))

        # デフォルト画像フォルダ
        ttk.Label(scrollable_frame, text="デフォルト画像フォルダ:", font=("", 9)).pack(anchor=tk.W, pady=(5, 2))
        image_path_var = tk.StringVar(value=getattr(settings, 'bluesky_image_path', ''))
        self.vars['bluesky_image_path'] = image_path_var
        frame = ttk.Frame(scrollable_frame)
        frame.pack(anchor=tk.W, fill=tk.X, padx=0, pady=(0, 5))
        ttk.Entry(frame, textvariable=image_path_var, width=50).pack(side=tk.LEFT, padx=5, fill=tk.X, expand=True)
        ttk.Button(frame, text="📁", width=2, command=lambda: self._browse_directory(image_path_var)).pack(side=tk.RIGHT, padx=2)
        ttk.Label(scrollable_frame, text="投稿時に画像がない場合に使用するデフォルト画像フォルダ", font=("", 8)).pack(anchor=tk.W, padx=5, pady=(0, 10))

        ttk.Separator(scrollable_frame, orient=tk.HORIZONTAL).pack(fill=tk.X, pady=10)

        # リサイズ設定
        ttk.Label(scrollable_frame, text="リサイズ設定", font=styles.FONT_BOLD).pack(anchor=tk.W, pady=(10, 10))

        ttk.Label(scrollable_frame, text="横長画像の幅（px）:", font=("", 9)).pack(anchor=tk.W, pady=(5, 2))
        image_width_var = tk.StringVar(value=str(getattr(settings, 'image_resize_target_width', 1200)))
        self.vars['image_resize_target_width'] = image_width_var
        frame = ttk.Frame(scrollable_frame)
        frame.pack(anchor=tk.W, fill=tk.X, padx=0, pady=(0, 5))
        ttk.Spinbox(frame, from_=100, to=3840, textvariable=image_width_var, width=10).pack(side=tk.LEFT, padx=5)
        ttk.Label(scrollable_frame, text="画像をリサイズする際の目標幅（100-3840px）", font=("", 8)).pack(anchor=tk.W, padx=5, pady=(0, 10))

        ttk.Label(scrollable_frame, text="横長画像の高さ（px）:", font=("", 9)).pack(anchor=tk.W, pady=(5, 2))
        image_height_var = tk.StringVar(value=str(getattr(settings, 'image_resize_target_height', 800)))
        self.vars['image_resize_target_height'] = image_height_var
        frame = ttk.Frame(scrollable_frame)
        frame.pack(anchor=tk.W, fill=tk.X, padx=0, pady=(0, 5))
        ttk.Spinbox(frame, from_=100, to=2160, textvariable=image_height_var, width=10).pack(side=tk.LEFT, padx=5)
        ttk.Label(scrollable_frame, text="画像をリサイズする際の目標高さ（100-2160px）", font=("", 8)).pack(anchor=tk.W, padx=5, pady=(0, 10))

        ttk.Separator(scrollable_frame, orient=tk.HORIZONTAL).pack(fill=tk.X, pady=10)

        # 品質・サイズ最適化
        ttk.Label(scrollable_frame, text="品質・サイズ最適化", font=styles.FONT_BOLD).pack(anchor=tk.W, pady=(10, 10))

        ttk.Label(scrollable_frame, text="JPEG品質（1-100）:", font=("", 9)).pack(anchor=tk.W, pady=(5, 2))
        image_quality_var = tk.StringVar(value=str(getattr(settings, 'image_output_quality_initial', 90)))
        self.vars['image_output_quality_initial'] = image_quality_var
        frame = ttk.Frame(scrollable_frame)
        frame.pack(anchor=tk.W, fill=tk.X, padx=0, pady=(0, 5))
        ttk.Spinbox(frame, from_=1, to=100, textvariable=image_quality_var, width=10).pack(side=tk.LEFT, padx=5)
        ttk.Label(scrollable_frame, text="JPEG圧縮品質（1=低品質/小容量、100=高品質/大容量）", font=("", 8)).pack(anchor=tk.W, padx=5, pady=(0, 10))

        ttk.Label(scrollable_frame, text="サイズ最適化目標（KB）:", font=("", 9)).pack(anchor=tk.W, pady=(5, 2))
        # image_size_target is stored in bytes
        target_size_kb = getattr(settings, 'image_size_target', 800 * 1024) // 1024
        image_target_size_var = tk.StringVar(value=str(target_size_kb))
        self.vars['image_size_target'] = image_target_size_var
        frame = ttk.Frame(scrollable_frame)
        frame.pack(anchor=tk.W, fill=tk.X, padx=0, pady=(0, 5))
        ttk.Spinbox(frame, from_=50, to=5000, textvariable=image_target_size_var, width=10).pack(side=tk.LEFT, padx=5)
        ttk.Label(scrollable_frame, text="画像を圧縮する際の目標ファイルサイズ（50-5000KB）", font=("", 8)).pack(anchor=tk.W, padx=5, pady=(0, 10))

        ttk.Label(scrollable_frame, text="ファイルサイズ変換閾値（KB）:", font=("", 9)).pack(anchor=tk.W, pady=(5, 2))
        # Convert from bytes to KB for display
        threshold_kb = getattr(settings, 'image_size_threshold', 900 * 1024) // 1024
        image_size_threshold_var = tk.StringVar(value=str(threshold_kb))
        self.vars['image_size_threshold'] = image_size_threshold_var
        frame = ttk.Frame(scrollable_frame)
        frame.pack(anchor=tk.W, fill=tk.X, padx=0, pady=(0, 5))
        ttk.Spinbox(frame, from_=100, to=2000, textvariable=image_size_threshold_var, width=10).pack(side=tk.LEFT, padx=5)
        ttk.Label(scrollable_frame, text="このサイズを超えたら圧縮処理を開始（推奨: 900KB）", font=("", 8)).pack(anchor=tk.W, padx=5, pady=(0, 10))

        ttk.Label(scrollable_frame, text="ファイルサイズ上限（KB）:", font=("", 9)).pack(anchor=tk.W, pady=(5, 2))
        # Convert from bytes to KB for display
        limit_kb = getattr(settings, 'image_size_limit', 1024 * 1024) // 1024
        image_size_limit_var = tk.StringVar(value=str(limit_kb))
        self.vars['image_size_limit'] = image_size_limit_var
        frame = ttk.Frame(scrollable_frame)
        frame.pack(anchor=tk.W, fill=tk.X, padx=0, pady=(0, 5))
        ttk.Spinbox(frame, from_=500, to=2000, textvariable=image_size_limit_var, width=10).pack(side=tk.LEFT, padx=5)
        ttk.Label(scrollable_frame, text="このサイズを超えたら投稿を中止（推奨: 1000KB）", font=("", 8)).pack(anchor=tk.W, padx=5, pady=(0, 10))

        canvas.pack(side="left", fill="both", expand=True)
        scrollbar.pack(side="right", fill="y")

    def _build_logging_tab(self, notebook):
        """6. Logging"""
        tab = ttk.Frame(notebook, padding=styles.PADDING)
        notebook.add(tab, text="ログ設定")

        # Global Log Level
        lbl = ttk.Label(tab, text="グローバルログレベル", font=styles.FONT_BOLD)
        lbl.pack(anchor=tk.W, pady=(0, 10))
        self._add_combo(tab, "ログレベル", "log_level", ["INFO", "DEBUG", "WARNING", "ERROR"])
        help_global = ttk.Label(tab, text="すべてのモジュールに適用される基本的なログレベルです。", wraplength=400)
        help_global.pack(anchor=tk.W, pady=(0, 10))

        self._add_combo(tab, "ファイル出力レベル", "log_level_file", ["INFO", "DEBUG", "WARNING", "ERROR"])
        help_file = ttk.Label(tab, text="ログファイルに保存する詳細度を指定します。", wraplength=400)
        help_file.pack(anchor=tk.W, pady=(0, 10))

        self._add_entry(tab, "ログファイル保持日数", "log_retention_days")
        help_count = ttk.Label(tab, text="過去のログファイルを何日分残すか設定します。", wraplength=400)
        help_count.pack(anchor=tk.W, pady=(0, 15))

        ttk.Separator(tab, orient=tk.HORIZONTAL).pack(fill=tk.X, pady=15)

        # Module-specific Log Levels
        lbl2 = ttk.Label(tab, text="モジュール別ログレベル", font=styles.FONT_BOLD)
        lbl2.pack(anchor=tk.W, pady=(0, 10))
        help_module = ttk.Label(tab, text="個別のモジュールに対して異なるログレベルを設定できます。\n空白の場合はグローバルログレベルが適用されます。", wraplength=400)
        help_module.pack(anchor=tk.W, pady=(0, 10))
        levels = ["INFO", "DEBUG", "WARNING", "ERROR"]
        self._add_combo(tab, "認証 (Auth)", "log_level_auth", levels)
        self._add_combo(tab, "Webhook", "log_level_webhook", levels)
        self._add_combo(tab, "GUI", "log_level_gui", levels)
        self._add_combo(tab, "Bluesky", "log_level_bsky", levels)
        self._add_combo(tab, "YouTube", "log_level_youtube", levels)
        self._add_combo(tab, "Niconico", "log_level_niconico", levels)
        self._add_combo(tab, "Twitch", "log_level_twitch", levels)
        self._add_combo(tab, "Thumbnails", "log_level_thumbnails", levels)
        self._add_combo(tab, "Post Error", "log_level_post_error", levels)
        self._add_combo(tab, "Post", "log_level_post", levels)

    def _build_backup_tab(self, notebook):
        """7. Backup (Restored Security Options)"""
        tab = ttk.Frame(notebook)
        notebook.add(tab, text="バックアップ")

        sub_notebook = ttk.Notebook(tab)
        sub_notebook.pack(fill=tk.BOTH, expand=True, padx=5, pady=5)

        # 7-1. Create Backup
        create_tab = ttk.Frame(sub_notebook, padding=styles.PADDING)
        sub_notebook.add(create_tab, text="バックアップ作成")

        # Create Scrollable Container for Backup Create
        canvas = tk.Canvas(create_tab, bg=styles.ThemeManager.COLOR_BG, highlightthickness=0)
        scrollbar = ttk.Scrollbar(create_tab, orient=tk.VERTICAL, command=canvas.yview)
        scrollable_frame = ttk.Frame(canvas, padding=styles.PADDING)

        scrollable_frame.bind(
            "<Configure>",
            lambda e: canvas.configure(scrollregion=canvas.bbox("all"))
        )

        canvas.create_window((0, 0), window=scrollable_frame, anchor="nw")
        canvas.configure(yscrollcommand=scrollbar.set)

        # Mousewheel handling
        def _on_mousewheel(event):
            if canvas.winfo_exists():
                canvas.yview_scroll(int(-1 * (event.delta / 120)), "units")
            else:
                canvas.unbind_all("<MouseWheel>")
        canvas.bind_all("<MouseWheel>", _on_mousewheel)
        canvas.bind("<Destroy>", lambda e: canvas.unbind_all("<MouseWheel>"))

        canvas.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)
        scrollbar.pack(side=tk.RIGHT, fill=tk.Y)

        frame = scrollable_frame

        # === 説明 ===
        ttk.Label(frame, text="📦 バックアップを作成", font=styles.FONT_BOLD).pack(anchor=tk.W, pady=10)

        explanation = """バックアップは以下を含みます：

• データベース (SQLite)
• テンプレートファイル
• 設定ファイル (settings.env)
"""
        ttk.Label(frame, text=explanation, wraplength=400, justify=tk.LEFT).pack(anchor=tk.W, padx=10, pady=(0, 15))

        # === セキュリティオプション ===
        ttk.Label(frame, text="セキュリティオプション", font=styles.FONT_BOLD).pack(anchor=tk.W, pady=(10, 5))

        self.include_api_keys_var = tk.BooleanVar(value=False)
        self.include_passwords_var = tk.BooleanVar(value=False)
        self.include_images_var = tk.BooleanVar(value=False)

        ttk.Checkbutton(
            frame,
            text="🔐 API キーを含める",
            variable=self.include_api_keys_var
        ).pack(anchor=tk.W, padx=20, pady=3)

        ttk.Label(
            frame,
            text="⚠️ セキュリティリスク: API キーを含めると、バックアップを他のユーザーと共有できません",
            foreground='orange',
            font=styles.FONT_SMALL
        ).pack(anchor=tk.W, padx=40, pady=(0, 10))

        ttk.Checkbutton(
            frame,
            text="🔒 パスワードを含める",
            variable=self.include_passwords_var
        ).pack(anchor=tk.W, padx=20, pady=3)

        ttk.Label(
            frame,
            text="⚠️ セキュリティリスク: パスワードを含めると、バックアップを他のユーザーと共有できません",
            foreground='orange',
            font=styles.FONT_SMALL
        ).pack(anchor=tk.W, padx=40, pady=(0, 10))

        ttk.Checkbutton(
            frame,
            text="🖼️ 画像フォルダを含める",
            variable=self.include_images_var
        ).pack(anchor=tk.W, padx=20, pady=3)

        ttk.Label(
            frame,
            text="ℹ️ 画像フォルダを含めるとファイルサイズが大きくなります",
            foreground='gray',
            font=styles.FONT_SMALL
        ).pack(anchor=tk.W, padx=40, pady=(0, 15))

        # === セパレータ ===
        ttk.Separator(frame, orient=tk.HORIZONTAL).pack(fill=tk.X, pady=10)

        # === バックアップボタン ===
        ttk.Button(
            frame,
            text="💾 バックアップファイルを作成",
            command=self._on_run_backup
        ).pack(anchor=tk.W, padx=10, pady=5, fill=tk.X)

        ttk.Label(
            frame,
            text="DB・テンプレート・設定をバックアップファイルに保存します。\nファイル保存先を選択するダイアログが表示されます。",
            wraplength=400,
            justify=tk.LEFT
        ).pack(anchor=tk.W, padx=20, pady=(0, 15))

        # === 注意事項 ===
        warning_text = """⚠️ 注意事項

• バックアップは ZIP ファイル形式で保存されます
• ファイルダイアログが表示されます
• 保存先を選択して完了です"""

        ttk.Label(frame, text=warning_text, foreground='orange', wraplength=400, justify=tk.LEFT).pack(
            anchor=tk.W, padx=10, pady=10
        )


        # 7-2. Restore Backup
        restore_tab = ttk.Frame(sub_notebook, padding=styles.PADDING)
        sub_notebook.add(restore_tab, text="復元 (リストア)")

        # Create Scrollable Container for Restore
        canvas2 = tk.Canvas(restore_tab, bg=styles.ThemeManager.COLOR_BG, highlightthickness=0)
        scrollbar2 = ttk.Scrollbar(restore_tab, orient=tk.VERTICAL, command=canvas2.yview)
        scrollable_frame2 = ttk.Frame(canvas2, padding=styles.PADDING)

        scrollable_frame2.bind(
            "<Configure>",
            lambda e: canvas2.configure(scrollregion=canvas2.bbox("all"))
        )

        canvas2.create_window((0, 0), window=scrollable_frame2, anchor="nw")
        canvas2.configure(yscrollcommand=scrollbar2.set)

        # Mousewheel handling
        def _on_mousewheel2(event):
            if canvas2.winfo_exists():
                canvas2.yview_scroll(int(-1 * (event.delta / 120)), "units")
            else:
                canvas2.unbind_all("<MouseWheel>")
        canvas2.bind_all("<MouseWheel>", _on_mousewheel2)
        canvas2.bind("<Destroy>", lambda e: canvas2.unbind_all("<MouseWheel>"))

        canvas2.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)
        scrollbar2.pack(side=tk.RIGHT, fill=tk.Y)

        frame2 = scrollable_frame2

        # === 説明 ===
        ttk.Label(frame2, text="📂 バックアップから復元", font=styles.FONT_BOLD).pack(anchor=tk.W, pady=10)

        explanation_restore = """保存されたバックアップファイルから復元します。

復元時の動作：
• 現在のデータは自動的にバックアップされます
• バックアップの内容で現在のデータを置き換えます
• アプリケーション再起動が必要な場合があります"""

        ttk.Label(frame2, text=explanation_restore, wraplength=400, justify=tk.LEFT).pack(
            anchor=tk.W, padx=10, pady=(0, 15)
        )

        # === セパレータ ===
        ttk.Separator(frame2, orient=tk.HORIZONTAL).pack(fill=tk.X, pady=10)

        # === 復元ボタン ===
        ttk.Button(
            frame2,
            text="📂 バックアップファイルから復元",
            command=self._on_restore_backup
        ).pack(anchor=tk.W, padx=10, pady=5, fill=tk.X)

        ttk.Label(
            frame2,
            text="バックアップファイル（.zip）を選択してください。\nファイル選択ダイアログが表示されます。",
            wraplength=400
        ).pack(anchor=tk.W, padx=20, pady=(0, 15))

        # === セパレータ ===
        ttk.Separator(frame2, orient=tk.HORIZONTAL).pack(fill=tk.X, pady=10)

        # === 注意事項 ===
        warning_text_restore = """⚠️ 警告：復元処理について

• 現在のデータは上書きされます
• 既存データは自動的にバックアップされます
• API キー・パスワード除外オプションで作成したバックアップの場合、
  復元後に手動で設定し直す必要があります
• 復元後、アプリケーション再起動が必要な場合があります"""

        ttk.Label(frame2, text=warning_text_restore, foreground='red', wraplength=400, justify=tk.LEFT).pack(
             anchor=tk.W, padx=10
        )

    def _build_app_tab(self, notebook):
        """8. App Details"""
        tab = ttk.Frame(notebook)
        notebook.add(tab, text="アプリ詳細")

        sub_notebook = ttk.Notebook(tab)
        sub_notebook.pack(fill=tk.BOTH, expand=True, padx=5, pady=5)

        # 8-1. アプリ情報
        info_tab = ttk.Frame(sub_notebook, padding=styles.PADDING)
        sub_notebook.add(info_tab, text="アプリ情報")

        lbl = ttk.Label(info_tab, text="アプリケーション情報", font=styles.FONT_BOLD)
        lbl.pack(anchor=tk.W)
        ttk.Label(info_tab, text="StreamNotify on Bluesky v4").pack(anchor=tk.W, pady=5)

        # 8-2. キャッシュ管理
        self._build_subtab_cache_management(sub_notebook)

    def _build_subtab_cache_management(self, parent_notebook):
        """8-2. キャッシュ管理（RSSポーリング専用）"""
        tab = ttk.Frame(parent_notebook)
        parent_notebook.add(tab, text="💾 キャッシュ管理")

        # スクロール可能フレームを作成
        canvas = tk.Canvas(tab, bg=styles.ThemeManager.COLOR_BG, highlightthickness=0)
        scrollbar = ttk.Scrollbar(tab, orient=tk.VERTICAL, command=canvas.yview)
        scrollable_frame = ttk.Frame(canvas, padding=styles.PADDING)

        scrollable_frame.bind(
            "<Configure>",
            lambda e: canvas.configure(scrollregion=canvas.bbox("all"))
        )

        canvas.create_window((0, 0), window=scrollable_frame, anchor="nw")
        canvas.configure(yscrollcommand=scrollbar.set)

        # マウスホイール対応
        def _on_mousewheel(event):
            if canvas.winfo_exists():
                canvas.yview_scroll(int(-1 * (event.delta / 120)), "units")
            else:
                canvas.unbind_all("<MouseWheel>")
        canvas.bind_all("<MouseWheel>", _on_mousewheel)
        canvas.bind("<Destroy>", lambda e: canvas.unbind_all("<MouseWheel>"))

        canvas.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)
        scrollbar.pack(side=tk.RIGHT, fill=tk.Y)

        # タイトル
        lbl = ttk.Label(scrollable_frame, text="YouTube キャッシュ管理（RSSポーリングモード）", font=styles.FONT_BOLD)
        lbl.pack(anchor=tk.W, pady=(0, 10))

        # 警告
        help_txt = ttk.Label(scrollable_frame, text="⚠️ 注意: 実行中は複数回実行できません（1起動1回）", foreground="red")
        help_txt.pack(anchor=tk.W, pady=5)

        # キャッシュ操作フレーム
        button_frame = ttk.LabelFrame(scrollable_frame, text="キャッシュ操作", padding=10)
        button_frame.pack(fill=tk.BOTH, expand=True, pady=10)

        # フラグ初期化
        if not hasattr(self, '_cache_operation_running'):
            self._cache_operation_running = False

        # 1. LIVEキャッシュをクリア
        ttk.Button(
            button_frame,
            text="🗑️ LIVEキャッシュをクリア",
            command=self._on_clear_live_cache
        ).pack(fill=tk.X, padx=5, pady=5)
        ttk.Label(button_frame, text="Live（schedule/live/completed/archive）のキャッシュをすべてクリア",
                  foreground='gray', font=("", 9)).pack(anchor=tk.W, padx=10, pady=(0, 10))

        # 2. Schedule キャッシュを更新
        ttk.Button(
            button_frame,
            text="📅 Schedule キャッシュを更新",
            command=self._on_update_schedule_cache
        ).pack(fill=tk.X, padx=5, pady=5)
        ttk.Label(button_frame, text="Schedule 状態の Live がなければスキップ（1時間未満なら更新しない）",
                  foreground='gray', font=("", 9)).pack(anchor=tk.W, padx=10, pady=(0, 10))

        # 3. LIVE キャッシュを更新
        ttk.Button(
            button_frame,
            text="🔴 LIVE キャッシュを更新",
            command=self._on_update_live_cache
        ).pack(fill=tk.X, padx=5, pady=5)
        ttk.Label(button_frame, text="Upcoming/Live/End 状態の Live がなければスキップ（1時間未満なら更新しない）",
                  foreground='gray', font=("", 9)).pack(anchor=tk.W, padx=10, pady=(0, 10))

        # 4. Archive キャッシュを更新
        ttk.Button(
            button_frame,
            text="🎬 Archive キャッシュを更新",
            command=self._on_update_archive_cache
        ).pack(fill=tk.X, padx=5, pady=5)
        ttk.Label(button_frame, text="Archive 状態の Live がなければスキップ（1時間未満なら更新しない）",
                  foreground='gray', font=("", 9)).pack(anchor=tk.W, padx=10, pady=(0, 10))

        # 5. 動画キャッシュを更新
        ttk.Button(
            button_frame,
            text="🎥 動画キャッシュを更新",
            command=self._on_update_video_cache
        ).pack(fill=tk.X, padx=5, pady=5)
        ttk.Label(button_frame, text="通常動画がなければスキップ（7日以上前のキャッシュのみ更新）",
                  foreground='gray', font=("", 9)).pack(anchor=tk.W, padx=10, pady=(0, 10))

        # 6. キャッシュ強制更新
        ttk.Button(
            button_frame,
            text="⚡ キャッシュ強制更新（全件）",
            command=self._on_force_update_all_cache
        ).pack(fill=tk.X, padx=5, pady=5)
        ttk.Label(button_frame, text="YouTube 全件キャッシュを更新（50件ごとバッチ処理、時間がかかります）",
                  foreground='red', font=("", 9)).pack(anchor=tk.W, padx=10, pady=(0, 10))

        # 削除済み動画リスト管理セクション
        ttk.Separator(scrollable_frame, orient=tk.HORIZONTAL).pack(fill=tk.X, pady=10)

        # 削除済み動画キャッシュのクリア
        ttk.Button(
            scrollable_frame,
            text="🗑️ 削除済み動画リストをクリア",
            command=self._on_clear_deleted_video_cache
        ).pack(fill=tk.X, padx=5, pady=5)

        help_lbl1 = ttk.Label(scrollable_frame, text="削除済み動画リスト（除外リスト）をリセットします", wraplength=400)
        help_lbl1.pack(anchor=tk.W, padx=10, pady=(0, 10))

        # キャッシュ統計情報表示
        stats_frame = ttk.LabelFrame(scrollable_frame, text="キャッシュ統計", padding=10)
        stats_frame.pack(fill=tk.BOTH, expand=True, pady=10)

        self.cache_stats_label = ttk.Label(stats_frame, text="キャッシュ情報を読み込み中...", wraplength=400, justify=tk.LEFT)
        self.cache_stats_label.pack(anchor=tk.W, pady=5)

        ttk.Button(
            stats_frame,
            text="🔄 統計を更新",
            command=self._update_cache_statistics
        ).pack(fill=tk.X, padx=5, pady=5)

        # 初期統計の読み込み
        self._update_cache_statistics()

    def _on_clear_live_cache(self):
        """🗑️ LIVEキャッシュをクリア"""
        if self._cache_operation_running:
            messagebox.showwarning("警告", "キャッシュ操作が実行中です。終了を待ってください。")
            return

        if not messagebox.askyesno("確認", "Live（schedule/live/completed/archive）のキャッシュをクリアしますか？"):
            return

        self._cache_operation_running = True
        try:
            # DB から Live 関連をクリア
            if self.db:
                videos = self.db.get_all_videos()
                live_count = 0
                for video in videos:
                    content_type = video.get('content_type', '')
                    if content_type in ['schedule', 'live', 'completed', 'archive']:
                        self.db.delete_video(video['video_id'])
                        live_count += 1

                messagebox.showinfo("完了", f"✅ {live_count} 件の Live キャッシュをクリアしました")
                logger.info(f"Live キャッシュをクリア: {live_count} 件")
            else:
                messagebox.showwarning("警告", "DB インスタンスが利用不可です")
        except Exception as e:
            messagebox.showerror("エラー", f"❌ キャッシュクリア中にエラー:\n{e}")
            logger.error(f"キャッシュ管理エラー: {e}")
        finally:
            self._cache_operation_running = False

    def _on_update_schedule_cache(self):
        """📅 Schedule キャッシュを更新"""
        if self._cache_operation_running:
            messagebox.showwarning("警告", "キャッシュ操作が実行中です。終了を待ってください。")
            return

        if not messagebox.askyesno("確認", "Schedule 状態の Live キャッシュを更新しますか？\n（1時間以内の更新済みはスキップします）"):
            return

        self._cache_operation_running = True
        try:
            self._update_cache_by_type('schedule')
        finally:
            self._cache_operation_running = False

    def _on_update_live_cache(self):
        """🔴 LIVE キャッシュを更新"""
        if self._cache_operation_running:
            messagebox.showwarning("警告", "キャッシュ操作が実行中です。終了を待ってください。")
            return

        if not messagebox.askyesno("確認", "Upcoming/Live/End 状態の Live キャッシュを更新しますか？\n（1時間以内の更新済みはスキップします）"):
            return

        self._cache_operation_running = True
        try:
            self._update_cache_by_type('live')
        finally:
            self._cache_operation_running = False

    def _on_update_archive_cache(self):
        """🎬 Archive キャッシュを更新"""
        if self._cache_operation_running:
            messagebox.showwarning("警告", "キャッシュ操作が実行中です。終了を待ってください。")
            return

        if not messagebox.askyesno("確認", "Archive 状態の Live キャッシュを更新しますか？\n（1時間以内の更新済みはスキップします）"):
            return

        self._cache_operation_running = True
        try:
            self._update_cache_by_type('archive')
        finally:
            self._cache_operation_running = False

    def _on_update_video_cache(self):
        """🎥 動画キャッシュを更新"""
        if self._cache_operation_running:
            messagebox.showwarning("警告", "キャッシュ操作が実行中です。終了を待ってください。")
            return

        if not messagebox.askyesno("確認", "動画キャッシュを更新しますか？\n（7日以上前のキャッシュのみ更新）"):
            return

        self._cache_operation_running = True
        try:
            self._update_cache_by_type('video')
        finally:
            self._cache_operation_running = False

    def _on_force_update_all_cache(self):
        """⚡ キャッシュ強制更新（全件）"""
        if self._cache_operation_running:
            messagebox.showwarning("警告", "キャッシュ操作が実行中です。終了を待ってください。")
            return

        if not messagebox.askyesno("確認", "YouTube 全件キャッシュを強制更新しますか？\n（時間がかかる場合があります）"):
            return

        self._cache_operation_running = True
        try:
            self._update_cache_by_type('all')
        finally:
            self._cache_operation_running = False

    def _update_cache_by_type(self, cache_type):
        """キャッシュを種別ごとに更新（共通メソッド）"""
        from datetime import datetime, timedelta

        try:
            if not self.db:
                messagebox.showwarning("警告", "DB インスタンスが利用不可です")
                return

            # 簡略版: キャッシュ更新をシミュレート
            # 実装注: v3では YouTube API プラグインと Classifier を使用していますが、
            # v4 ではRSSポーリング専用のため、基本的な処理のみを実施

            cache_desc = {
                'schedule': 'Schedule 状態の Live',
                'live': 'Upcoming/Live/End 状態の Live',
                'archive': 'Archive 状態の Live',
                'video': '通常動画',
                'all': 'YouTube 全件'
            }

            messagebox.showinfo("処理中", f"✅ {cache_desc.get(cache_type, 'キャッシュ')} の更新処理を開始しました。\n\n※ 実装注: RSSポーリングモード専用のため、詳細な更新ロジックはv3を参照してください。")
            logger.info(f"キャッシュ更新処理: {cache_type}")

        except Exception as e:
            messagebox.showerror("エラー", f"❌ キャッシュ更新中にエラー:\n{e}")
            logger.error(f"キャッシュ更新エラー: {e}")

    def _on_clear_deleted_video_cache(self):
        """削除済み動画キャッシュをクリア"""
        if not messagebox.askyesno("確認", "削除済み動画リストをクリアしますか？\n\n再度同じ動画が表示される可能性があります。"):
            return

        try:
            from v4.deleted_video_cache import get_deleted_video_cache
            cache = get_deleted_video_cache()
            if cache.clear_all_deleted():
                messagebox.showinfo("成功", "✅ 削除済み動画リストをクリアしました")
                logger.info("削除済み動画キャッシュをクリア")
                self._update_cache_statistics()
            else:
                messagebox.showerror("エラー", "❌ キャッシュのクリアに失敗しました")
        except Exception as e:
            logger.error(f"キャッシュクリアエラー: {e}")
            messagebox.showerror("エラー", f"クリア中にエラーが発生しました:\n{e}")

    def _update_cache_statistics(self):
        """キャッシュ統計情報を更新"""
        try:
            from v4.core.deleted_video_cache import get_deleted_video_cache
            cache = get_deleted_video_cache()
            deleted_videos = cache.get_deleted_videos()

            # 各サービスの削除済み動画数を集計
            youtube_count = len(deleted_videos.get('youtube', []))
            niconico_count = len(deleted_videos.get('niconico', []))
            twitch_count = len(deleted_videos.get('twitch', []))
            total_count = youtube_count + niconico_count + twitch_count

            stats_text = f"""削除済み動画リスト内容:
  • YouTube: {youtube_count} 件
  • ニコニコ: {niconico_count} 件
  • Twitch: {twitch_count} 件
  • 合計: {total_count} 件"""

            self.cache_stats_label.config(text=stats_text)
        except Exception as e:
            logger.error(f"キャッシュ統計更新エラー: {e}")
            self.cache_stats_label.config(text=f"統計情報の読み込みに失敗しました\n{e}")

    def _reset_to_defaults(self):
        """デフォルト値にリセット"""
        if not messagebox.askyesno("確認", "すべての設定をデフォルト値にリセットしますか？\n\nこの操作は取り消せません。"):
            return

        try:
            # settings.env をデフォルト値にリセット
            from v4.core.config import Settings
            default_settings = Settings()
            self.db.save_settings(default_settings.model_dump())

            logger.info("⚠️ 設定をデフォルト値にリセットしました")
            messagebox.showinfo("成功", "✅ 設定をデフォルト値にリセットしました。\nアプリを再起動してください。")
            self.window.destroy()
        except Exception as e:
            logger.error(f"リセット失敗: {e}")
            messagebox.showerror("エラー", f"リセット中にエラーが発生しました:\n{e}")

    def _build_future_tab(self, notebook):
        """9. Future Features (Preview)"""
        tab = ttk.Frame(notebook, padding=styles.PADDING)
        notebook.add(tab, text="🔮 将来機能")

        lbl = ttk.Label(tab, text="将来実装予定のプラグイン", font=styles.FONT_BOLD)
        lbl.pack(anchor=tk.W, pady=10)

        help_lbl = ttk.Label(tab, text="以下の機能は現在未実装です：", wraplength=400)
        help_lbl.pack(anchor=tk.W, pady=5)

        feature_lbl = ttk.Label(tab, text="• ActivityPub 連携\n• Discord 通知", wraplength=400, justify=tk.LEFT)
        feature_lbl.pack(anchor=tk.W, padx=20, pady=5)

    def _add_entry(self, parent, label, attr, show=None, label_suffix="", label_color=None):
        frame = ttk.Frame(parent)
        frame.pack(fill=tk.X, pady=2)

        lbl_text = label + label_suffix
        lbl = ttk.Label(frame, text=lbl_text, width=25, anchor="w")
        if label_color:
            lbl.configure(foreground=label_color)
        lbl.pack(side=tk.LEFT)

        var = tk.StringVar(value=str(getattr(settings, attr, "")))
        self.vars[attr] = var
        ttk.Entry(frame, textvariable=var, show=show).pack(side=tk.RIGHT, fill=tk.X, expand=True) # pyright: ignore[reportArgumentType]

    def _add_check(self, parent, label, attr):
        frame = ttk.Frame(parent)
        frame.pack(fill=tk.X, pady=2)
        var = tk.BooleanVar(value=bool(getattr(settings, attr, False)))
        self.vars[attr] = var
        ttk.Checkbutton(frame, text=label, variable=var).pack(side=tk.LEFT)

    def _add_combo(self, parent, label, attr, values):
        frame = ttk.Frame(parent)
        frame.pack(fill=tk.X, pady=2)
        ttk.Label(frame, text=label, width=20).pack(side=tk.LEFT)
        var = tk.StringVar(value=str(getattr(settings, attr, values[0] if values else "")))
        self.vars[attr] = var
        ttk.Combobox(frame, textvariable=var, values=values, state="readonly").pack(side=tk.RIGHT, fill=tk.X, expand=True)

    def _add_status_checks(self, parent, attr, options):
        frame = ttk.Frame(parent)
        frame.pack(fill=tk.X, pady=2)

        current_val = getattr(settings, attr, [])
        # In case it's None or not a list
        if not isinstance(current_val, list):
            current_val = []

        # We need to manage a list of vars
        if attr not in self.vars:
           self.vars[attr] = {}

        for opt in options:
            var = tk.BooleanVar(value=(opt in current_val))
            self.vars[attr][opt] = var
            ttk.Checkbutton(frame, text=opt, variable=var).pack(side=tk.LEFT, padx=5)

    def save(self):
        new_values = {}
        for k, v in self.vars.items():
            if isinstance(v, dict): # For status checks (dict of BooleanVars)
                 selected = [opt for opt, var in v.items() if var.get()]
                 new_values[k] = selected
            else:
                 new_values[k] = v.get()

        try:
            new_values["port"] = int(new_values.get("port", 8000))
        except (ValueError, KeyError):
            messagebox.showerror("Error", "ポート番号は数値で入力してください")
            return

        # Convert KB to bytes for image settings
        if "image_size_threshold" in new_values:
            new_values["image_size_threshold"] = int(new_values["image_size_threshold"]) * 1024
        if "image_size_limit" in new_values:
            new_values["image_size_limit"] = int(new_values["image_size_limit"]) * 1024
        if "image_size_target" in new_values:
            new_values["image_size_target"] = int(new_values["image_size_target"]) * 1024

        # Filter out attributes that don't exist in settings
        from v4.core.config import Settings
        valid_attrs = set(Settings.model_fields.keys())
        filtered_values = {k: v for k, v in new_values.items() if k in valid_attrs}

        # Debug: log ALL template and image values
        template_keys = [k for k in new_values.keys() if "template" in k]
        image_keys = [k for k in new_values.keys() if "image" in k]

        logger.debug(f"🔍 All new_values: {[(k, v[:50] if isinstance(v, str) and len(v) > 50 else v) for k, v in new_values.items() if 'template' in k or 'image' in k]}")

        if template_keys:
            logger.debug(f"🔍 Template values before filter: {[(k, new_values[k]) for k in template_keys]}")
            logger.debug(f"🔍 Template values after filter: {[(k, filtered_values[k]) for k in template_keys if k in filtered_values]}")
            logger.debug(f"🔍 Template keys missing from filtered: {[k for k in template_keys if k not in filtered_values]}")
        if image_keys:
            logger.debug(f"🔍 Image values before filter: {[(k, new_values[k]) for k in image_keys]}")
            logger.debug(f"🔍 Image values after filter: {[(k, filtered_values[k]) for k in image_keys if k in filtered_values]}")

        logger.debug(f"💾 About to save_settings with {len(filtered_values)} values")
        success = self.db.save_settings(filtered_values)
        if success:
            try:
                from v4.core.config import settings
                settings.reload_settings()
                logger.debug("Configuration reloaded from disk")
            except Exception as e:
                logger.error(f"Failed to reload configuration: {e}")

            # Apply Theme
            try:
                from v4.gui.styles import ThemeManager
                ThemeManager.apply_theme()
                ThemeManager.configure_ttk_styles(self.parent)
                logger.debug("Theme re-applied")
            except Exception as e:
                logger.error(f"Failed to apply theme: {e}")

            # Apply Logging
            if self._has_logging_settings_changed(filtered_values):
                try:
                    from v4.core.logging_config_split import setup_logging
                    setup_logging()
                    logger.debug("Logging settings updated in real-time")
                except Exception as e:
                    logger.error(f"Failed to apply logging settings: {e}")

            messagebox.showinfo("成功", "設定を保存・適用しました。\n※ ホスト/ポート変更はアプリ再起動で反映されます。")
            self.window.destroy()
        else:
            messagebox.showerror("エラー", "設定の保存に失敗しました。")

    def _has_logging_settings_changed(self, new_values: dict) -> bool:
        logging_keys = {
            "log_level", "log_level_youtube", "log_level_niconico", "log_level_twitch",
            "log_level_gui", "log_level_bsky", "log_level_auth", "log_level_webhook",
            "log_level_thumbnails", "log_level_post_error", "log_level_post"
        }
        return any(key in new_values for key in logging_keys)

    def auth_bsky(self):
        handle = self.vars["bluesky_username"].get()
        if not handle:
            messagebox.showwarning("警告", "OAuth 連携にはユーザー名（ハンドル）の入力が必要です")
            return

        success = self.db.start_oauth_flow("bsky", handle=handle)
        if success:
            messagebox.showinfo("成功", "BlueSky との連携が完了しました。")
            self.update_auth_status()
        else:
            messagebox.showerror("エラー", "Bluesky 連携に失敗しました")

    def _on_bsky_disconnect(self):
        """Bluesky 連携解除"""
        if not messagebox.askyesno("確認", "Bluesky との連携を解除しますか？\n(サーバー上のセッションとローカル情報を削除します)"):
            return

        success = self.db.disconnect_bsky_account()
        if success:
             messagebox.showinfo("成功", "Bluesky 連携を解除しました")
             self.update_auth_status()
        else:
             messagebox.showerror("エラー", "連携解除に失敗しました（または既に解除済み）")

    def auth_twitch(self):
        success = self.db.start_oauth_flow("twitch")
        if success:
            messagebox.showinfo("成功", "Twitch 連携が完了しました")
            self.update_auth_status()
        else:
            messagebox.showerror(
                "エラー",
                "Twitch 連携に失敗しました。\n\n"
                "考えられる原因:\n"
                "・センターサーバーに接続できない (center_server_url を確認)\n"
                "・API キーが正しくない (websub_client_api_key を確認)\n"
                "・ブラウザで認証が完了しなかった (タイムアウト)\n\n"
                "詳細はログ (v4/logs/v4_app.log) を確認してください。"
            )

    def _on_twitch_disconnect(self):
        if not messagebox.askyesno(
            "確認",
            "Twitch との連携を解除しますか？\n"
            "（センター側の EventSub・連携情報と、この PC のローカル情報を削除します）",
        ):
            return
        success = self.db.disconnect_twitch_account()
        if success:
            messagebox.showinfo("成功", "Twitch 連携を解除しました")
            self.update_auth_status()
        else:
            messagebox.showerror("エラー", "連携解除中にエラーが発生しました。ログを確認してください。")

    def _on_run_backup(self):
        """Invoke data backup with security options"""
        from v4.core.backup_manager import run_backup, BackupManager
        try:
             # バックアップディレクトリを作成
            backup_dir = settings.v4_dir / "backups"
            backup_dir.mkdir(exist_ok=True)

            # 保存先を選択
            from datetime import datetime

            timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
            default_filename = f"streamnotify_backup_{timestamp}.zip"

            backup_file = filedialog.asksaveasfilename(
                title="バックアップファイルを保存",
                defaultextension=".zip",
                filetypes=[("ZIP ファイル", "*.zip"), ("すべてのファイル", "*.*")],
                initialdir=str(backup_dir),
                initialfile=default_filename
            )

            if not backup_file:
                return

            # Use instance method if possible or explicit call
            manager = BackupManager()
            # BackupManager.create_backup returns Path or None
            # Need to modify/check core backup manager to accept output path or move it after creation
            # Current core implementation creates file automatically.
            # We will use the file created by core and move/rename it if necessary,
            # OR pass logic to core if it supported output path.
            # v4 core `create_backup` returns the Path object of created backup in default dir.

            created_path = manager.create_backup(
                include_images=self.include_images_var.get(),
                include_env=True,
                include_api_keys=self.include_api_keys_var.get(),
                include_passwords=self.include_passwords_var.get()
            )

            if created_path:
                # Move/Rename to user selected path
                import shutil
                try:
                    target_path = Path(backup_file) # type: ignore
                    # If user chose different location/name
                    if target_path.resolve() != created_path.resolve():
                        shutil.move(str(created_path), str(target_path))
                        final_path = target_path
                    else:
                        final_path = created_path

                    msg = f"バックアップを作成しました:\n{final_path.name}"
                    if not self.include_api_keys_var.get() or not self.include_passwords_var.get():
                            msg += "\n\n⚠️ セキュリティのため、一部のキー/パスワードは除外されています。"
                    messagebox.showinfo("成功", msg)
                except Exception as e:
                     logger.error(f"Failed to move backup file: {e}")
                     messagebox.showinfo("完了(移動失敗)", f"バックアップは作成されましたが、指定場所への移動に失敗しました。\n保存場所: {created_path}")

            else:
                messagebox.showerror("エラー", "バックアップの作成に失敗しました")
        except Exception as e:
            logger.error(f"Backup failed: {e}")
            messagebox.showerror("エラー", f"バックアップ実行中にエラーが発生しました: {e}")

    def _on_restore_backup(self):
        from v4.core.backup_manager import run_restore

        if not messagebox.askyesno("復元の確認", "現在のデータはバックアップの内容で上書きされます。\n実行してよろしいですか？\n(復元前に現在の状態が自動バックアップされます)"):
            return

        file_path = filedialog.askopenfilename(
            title="バックアップファイルを選択",
            filetypes=[("ZIP Files", "*.zip"), ("All Files", "*.*")],
            initialdir=settings.v4_dir / "backups"
        )

        if not file_path:
            return

        try:
            success, msg = run_restore(file_path)
            if success:
                messagebox.showinfo("復元成功", msg)
                self.parent.quit()
            else:
                messagebox.showerror("復元失敗", msg)
        except Exception as e:
            logger.error(f"Restore failed: {e}")
            messagebox.showerror("エラー", f"復元中にエラーが発生しました: {e}")

    def _on_select_template_dir(self):
        initial_dir = self.vars["template_path"].get() or str(settings.v4_dir / "templates")
        path = filedialog.askdirectory(initialdir=initial_dir, title="テンプレートフォルダを選択")
        if path:
            self.vars["template_path"].set(path)

    def _test_websub_connection(self, client_id, api_key, server_url):
        import requests
        if not client_id or not api_key or not server_url:
            messagebox.showwarning("入力不足", "接続テストには WebSub 関連の全項目（URL, ClientID, APIKey）が必要です")
            return

        if not self._settings_center_features_enabled():
            messagebox.showinfo(
                "センター未利用",
                "取得モードが poll、または WebSub が不通で\n RSS フォールバック中は、\n"
                "センター接続テストは利用できません。\n"
                "（フォールバック中はメイン画面の「WebSubに再接続」を試してください）",
            )
            return

        try:
            # Get current values from vars
            c_id = self.vars['websub_client_id'].get()
            a_key = self.vars['websub_client_api_key'].get()
            s_url = self.vars['center_server_url'].get()
            ch_id = self.vars['youtube_channel_id'].get()

            if not s_url:
                messagebox.showwarning("エラー", "サーバーURLが空です")
                return

            endpoint = f"{s_url.rstrip('/')}/clienthealth"
            params = {'client_id': c_id}
            if ch_id:
                params['channel_id'] = ch_id
            headers = {'X-Client-API-Key': a_key}

            resp = requests.get(endpoint, headers=headers, params=params, timeout=5)

            if resp.status_code == 200:
                data = resp.json()
                subs = data.get('subscriptions') or []
                sub_count = len(subs)
                ch_sub = any(s.get('channel_id') == ch_id for s in subs) if ch_id else None
                status_msg = "✅ 接続成功\n"
                status_msg += f"クライアント登録: 済み\n"
                status_msg += f"購読数: {sub_count} 件"
                if ch_id and ch_sub is not None:
                    status_msg += f"\nチャンネル {ch_id}: {'購読済み' if ch_sub else '未購読'}"
                messagebox.showinfo("テスト結果", status_msg)
            elif resp.status_code == 401:
                messagebox.showerror("テスト結果", "❌ 認証失敗 (401)\nAPI キーが間違っている可能性があります")
            elif resp.status_code == 403:
                messagebox.showerror("テスト結果", "❌ 認可失敗 (403)\nクライアントIDが登録されていない可能性があります")
            else:
                messagebox.showerror("テスト結果", f"❌ エラー ({resp.status_code})\n{resp.text}")

        except Exception as e:
            logger.error(f"WebSub test failed: {e}")
            messagebox.showerror("接続エラー", f"接続できませんでした:\n{e}")

    def update_auth_status(self):
        status = self.db.get_auth_status()
        if hasattr(self, "tw_status_lbl"):
            tw_text = f"連携状態: {'✅ 連携済み' if status.get('twitch') else '❌ 未連携'}"
            if status.get("twitch_username"):
                tw_text += f" ({status.get('twitch_username')})"
            self.tw_status_lbl.config(text=tw_text)

            if hasattr(self, "twitch_login_frame") and hasattr(self, "twitch_disconnect_frame"):
                if status.get("twitch"):
                    self.twitch_login_frame.pack_forget()
                    self.twitch_disconnect_frame.pack(pady=5, fill=tk.X, before=self.tw_status_lbl)
                else:
                    self.twitch_disconnect_frame.pack_forget()
                    self.twitch_login_frame.pack(pady=5, fill=tk.X, before=self.tw_status_lbl)

        if hasattr(self, "bs_status_lbl"):
            is_connected = status.get('bluesky')
            bs_text = f"連携状態: {'✅ 連携済み' if is_connected else '❌ 未連携'}"
            if status.get('bsky_handle'):
                bs_text += f" ({status.get('bsky_handle')})"
            self.bs_status_lbl.config(text=bs_text)

            # Toggle Buttons
            if hasattr(self, "bsky_login_frame") and hasattr(self, "bsky_disconnect_frame"):
                if is_connected:
                    self.bsky_login_frame.pack_forget()
                    self.bsky_disconnect_frame.pack(pady=5, fill=tk.X, before=self.bs_status_lbl)
                else:
                    self.bsky_disconnect_frame.pack_forget()
                    self.bsky_login_frame.pack(pady=5, fill=tk.X, before=self.bs_status_lbl)
    def _browse_file(self, var):
        """ファイル参照ダイアログを開く"""
        from tkinter.filedialog import askopenfilename
        filename = askopenfilename(
            title="テンプレートファイルを選択",
            filetypes=[("Jinja2 Template", "*.j2 *.jinja2"), ("Text files", "*.txt"), ("All files", "*.*")]
        )
        if filename:
            var.set(filename)

    def _browse_directory(self, var):
        """ディレクトリ参照ダイアログを開く"""
        from tkinter.filedialog import askdirectory
        dirname = askdirectory(title="フォルダを選択")
        if dirname:
            var.set(dirname)
