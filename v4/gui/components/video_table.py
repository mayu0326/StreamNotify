import tkinter as tk
from tkinter import ttk
import threading
import logging
from typing import Optional
from pathlib import Path
from .. import styles

try:
    from PIL import Image
    PIL_AVAILABLE = True
except ImportError:
    PIL_AVAILABLE = False

logger = logging.getLogger("v4.gui.video_table")

class VideoTable(ttk.Frame):
    """Main video list component using Treeview with Filtering and Selection"""
    def __init__(self, parent, db=None, on_selection_change=None, on_refresh=None):
        super().__init__(parent)
        self.pack(fill=tk.BOTH, expand=True, padx=styles.PADDING, pady=styles.MARGIN)
        self.db = db
        self.on_selection_change = on_selection_change
        self.on_refresh = on_refresh
        self.all_videos = [] # Full list for filtering
        self.selected_ids = set()
        self._thumb_cache: dict = {}  # url → PhotoImage
        self._thumb_load_id: Optional[str] = None  # currently loading video_id

        # 1. Filter Panel
        self.setup_filter_panel()

        # 2. Table Area
        self.table_frame = ttk.Frame(self)
        self.table_frame.pack(fill=tk.BOTH, expand=True)

        # Columns
        columns = ("Select", "Service", "ID", "Title", "Channel", "Status", "Posted", "Published")
        self.tree = ttk.Treeview(self.table_frame, columns=columns, show="headings")

        # Set Headings & Widths
        self.tree.heading("Select", text="☑")
        self.tree.column("Select", width=40, anchor=tk.CENTER)

        self.tree.heading("Service", text="サービス")
        self.tree.column("Service", width=75, anchor=tk.CENTER)

        self.tree.heading("ID", text="Video ID")
        self.tree.column("ID", width=100)

        self.tree.heading("Title", text="タイトル")
        self.tree.column("Title", width=390)

        self.tree.heading("Channel", text="チャンネル")
        self.tree.column("Channel", width=150)

        self.tree.heading("Status", text="タイプ")
        self.tree.column("Status", width=80, anchor=tk.CENTER)

        self.tree.heading("Posted", text="投稿済み")
        self.tree.column("Posted", width=70, anchor=tk.CENTER)

        self.tree.heading("Published", text="公開日時")
        self.tree.column("Published", width=150)

        # Scrollbar
        self.scrollbar = ttk.Scrollbar(self, orient=tk.VERTICAL, command=self.tree.yview)
        self.tree.configure(yscroll=self.scrollbar.set)

        self.tree.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)
        self.scrollbar.pack(side=tk.RIGHT, fill=tk.Y)

        self.tree.bind("<Button-1>", self.on_click)
        self.tree.bind("<Double-Button-1>", self._on_double_click)
        self.tree.bind("<Button-3>", self.show_context_menu)
        self.tree.bind("<Button-2>", self.show_context_menu)
        self.tree.bind("<<TreeviewSelect>>", self._on_row_select)

        # 3. Context Menu
        self.context_menu = tk.Menu(self, tearoff=0)
        styles.ThemeManager.apply_tk_menu_styles(self.context_menu)
        self.context_menu.add_command(label="📋 動画詳細を表示", command=self._menu_detail)
        self.context_menu.add_separator()
        self.context_menu.add_command(label="📤 この動画を投稿", command=self._menu_post)
        self.context_menu.add_separator()
        self.context_menu.add_command(label="🗓️ スケジュール設定", command=self._menu_schedule)
        self.context_menu.add_command(label="🖼️ 画像を設定", command=self._menu_image_assign)
        self.context_menu.add_command(label="🔗 ブラウザで開く", command=self._menu_open_browser)
        self.context_menu.add_separator()
        self.context_menu.add_command(label="❌ 削除", command=self._menu_delete)

        # 4. Thumbnail Preview Panel
        self.setup_thumbnail_panel()

    def setup_filter_panel(self):
        filter_frame = ttk.Frame(self, padding=(0, 0, 0, styles.MARGIN))
        filter_frame.pack(fill=tk.X)

        ttk.Label(filter_frame, text="🔍").pack(side=tk.LEFT)
        self.filter_var = tk.StringVar()
        self.filter_var.trace_add("write", lambda *args: self.apply_filter())
        self.ent_filter = ttk.Entry(filter_frame, textvariable=self.filter_var, width=28)
        self.ent_filter.pack(side=tk.LEFT, padx=styles.MARGIN)

        ttk.Label(filter_frame, text="サービス:").pack(side=tk.LEFT, padx=(styles.MARGIN, 0))
        self.service_var = tk.StringVar(value="すべて")
        self.cmb_service = ttk.Combobox(
            filter_frame, textvariable=self.service_var,
            values=["すべて", "youtube", "niconico", "twitch"],
            width=9, state="readonly"
        )
        self.cmb_service.pack(side=tk.LEFT, padx=styles.MARGIN)
        self.cmb_service.bind("<<ComboboxSelected>>", self.apply_filter)

        # タイプフィルタ（v3 種類・表現に合わせる）
        ttk.Label(filter_frame, text="タイプ:").pack(side=tk.LEFT, padx=(styles.MARGIN, 0))
        self.status_var = tk.StringVar(value="すべて")
        self._status_display_to_internal = {
            "すべて":       None,
            "動画":         "upload",
            "プレミア":     "premiere",
            "配信中":       "live",
            "アーカイブ":   "archive",
            "予約配信":     "schedule",
        }
        self._status_internal_to_display = {v: k for k, v in self._status_display_to_internal.items() if v}
        # 複数の内部値が同じ表示名になりえる補足（video もアップロードとして扱う）
        self._status_internal_to_display["video"] = "動画"
        self._status_internal_to_display["completed"] = "アーカイブ"
        status_values = list(self._status_display_to_internal.keys())
        self.cmb_status = ttk.Combobox(filter_frame, textvariable=self.status_var,
                                       values=status_values,
                                       width=10, state="readonly")
        self.cmb_status.pack(side=tk.LEFT, padx=styles.MARGIN)
        self.cmb_status.bind("<<ComboboxSelected>>", self.apply_filter)

        # 投稿済み/未投稿フィルタ
        ttk.Label(filter_frame, text="投稿状態:").pack(side=tk.LEFT, padx=(styles.MARGIN, 0))
        self.posted_var = tk.StringVar(value="すべて")
        self.cmb_posted = ttk.Combobox(
            filter_frame, textvariable=self.posted_var,
            values=["すべて", "投稿済み", "未投稿"],
            width=8, state="readonly",
        )
        self.cmb_posted.pack(side=tk.LEFT, padx=styles.MARGIN)
        self.cmb_posted.bind("<<ComboboxSelected>>", self.apply_filter)

        ttk.Label(filter_frame, text="並び順:").pack(side=tk.LEFT, padx=(styles.MARGIN, 0))
        self.sort_var = tk.StringVar(value="公開日時（新しい順）")
        self.cmb_sort = ttk.Combobox(
            filter_frame, textvariable=self.sort_var,
            values=["公開日時（新しい順）", "公開日時（古い順）", "タイトル", "チャンネル"],
            width=18, state="readonly"
        )
        self.cmb_sort.pack(side=tk.LEFT, padx=styles.MARGIN)
        self.cmb_sort.bind("<<ComboboxSelected>>", self.apply_filter)

        ttk.Button(filter_frame, text="フィルタリセット", command=self._reset_filters).pack(side=tk.RIGHT, padx=styles.MARGIN)
        ttk.Button(filter_frame, text="すべて選択", command=self.select_all).pack(side=tk.RIGHT, padx=styles.MARGIN)
        ttk.Button(filter_frame, text="解除", command=self.deselect_all).pack(side=tk.RIGHT)

    def setup_thumbnail_panel(self):
        """サムネイルプレビューパネルをテーブル下部に作成する。"""
        self.preview_frame = ttk.LabelFrame(self, text="📸 サムネイルプレビュー", padding=4)
        self.preview_frame.pack(fill=tk.X, pady=(styles.MARGIN, 0))

        self.thumb_label = ttk.Label(self.preview_frame, text="動画を選択するとサムネイルが表示されます")
        self.thumb_label.pack(side=tk.LEFT, padx=8)

        self.preview_info = ttk.Label(self.preview_frame, text="", font=styles.FONT_MAIN,
                                      wraplength=500, justify=tk.LEFT)
        self.preview_info.pack(side=tk.LEFT, padx=8, fill=tk.X, expand=True)

    def update_data(self, videos):
        self.all_videos = videos
        self.apply_filter()

    def _sort_videos(self, videos: list) -> list:
        """並び順に従って動画リストをソートする。"""
        key = self.sort_var.get()
        if key == "公開日時（新しい順）":
            return sorted(videos, key=lambda v: (v.get("published_at") or ""), reverse=True)
        if key == "公開日時（古い順）":
            return sorted(videos, key=lambda v: (v.get("published_at") or ""))
        if key == "タイトル":
            return sorted(videos, key=lambda v: (v.get("title") or "").lower())
        if key == "チャンネル":
            return sorted(videos, key=lambda v: (v.get("channel_name") or "").lower())
        return videos

    def apply_filter(self, *args):
        # Clear existing
        for item in self.tree.get_children():
            self.tree.delete(item)

        search_q = self.filter_var.get().lower()
        status_filter = self.status_var.get()
        service_filter = self.service_var.get()
        posted_filter = self.posted_var.get()
        status_internal = self._status_display_to_internal.get(status_filter, status_filter)

        filtered = []
        for video in self.all_videos:
            title = (video.get("title") or "").lower()
            channel = (video.get("channel_name") or "").lower()
            status = (video.get("video_status") or "").lower()
            service = (video.get("service") or "").lower()
            is_posted = bool(video.get("posted_to_bluesky"))

            if search_q and search_q not in title and search_q not in channel:
                continue
            if status_internal is not None and status_internal != status:
                continue
            if service_filter != "すべて" and service_filter.lower() != service:
                continue
            if posted_filter == "投稿済み" and not is_posted:
                continue
            if posted_filter == "未投稿" and is_posted:
                continue
            filtered.append(video)

        for video in self._sort_videos(filtered):
            checked = "☑" if video.get("video_id") in self.selected_ids else "☐"
            status_display = self._status_internal_to_display.get(
                (video.get("video_status") or "").lower(),
                video.get("video_status") or ""
            )
            posted_mark = "✅" if video.get("posted_to_bluesky") else "–"
            self.tree.insert("", tk.END, values=(
                checked,
                (video.get("service") or "").lower() or "unknown",
                video["video_id"],
                video["title"],
                video["channel_name"],
                status_display,
                posted_mark,
                video["published_at"]
            ), iid=video["video_id"])

    def _on_double_click(self, event):
        """行ダブルクリックで動画詳細ウィンドウを開く。"""
        item_id = self.tree.identify_row(event.y)
        col = self.tree.identify_column(event.x)
        # チェックボックス列のダブルクリックは通常クリックと同じ動作
        if not item_id or col == "#1":
            return
        from ..views.video_detail_dialog import VideoDetailDialog
        VideoDetailDialog(
            self.winfo_toplevel(), item_id, self.db,
            on_refresh=self.on_refresh,
        )

    def on_click(self, event):
        item_id = self.tree.identify_row(event.y)
        col = self.tree.identify_column(event.x)
        if item_id and col == "#1":
            if item_id in self.selected_ids:
                self.selected_ids.remove(item_id)
                new_val = "☐"
            else:
                self.selected_ids.add(item_id)
                new_val = "☑"

            vals = list(self.tree.item(item_id, "values"))
            vals[0] = new_val
            self.tree.item(item_id, values=vals)

            if self.on_selection_change:
                self.on_selection_change()

    def _on_row_select(self, event):
        """行選択時にサムネイルプレビューを更新する。"""
        selected = self.tree.selection()
        if not selected:
            return
        item_id = selected[0]
        video = next((v for v in self.all_videos if v.get("video_id") == item_id), None)
        if not video:
            return

        service = (video.get("service") or "youtube").strip().lower()
        title = video.get("title", "")[:60]
        channel = video.get("channel_name", "")
        status_raw = (video.get("video_status") or "").lower()
        status_display = self._status_internal_to_display.get(status_raw, status_raw or "–")
        info_text = f"{title}\n{channel} / {service} / {status_display}"
        self.preview_info.config(text=info_text)

        # まずはダウンロード済みキャッシュを探す（v4/images/{Site}/autopost または import）
        cached_path = self._find_cached_thumbnail(service, item_id)
        if cached_path:
            self._thumb_load_id = item_id
            self._load_thumbnail_from_path(cached_path, item_id)
            return

        # キャッシュがない場合、thumbnail_url からダウンロード
        thumb_url = video.get("thumbnail_url")
        # ニコニコは adapter で URL を返さないため、OGP 取得をバックグラウンドで試行
        if not thumb_url and service == "niconico":
            self.thumb_label.config(image="", text="取得中...（OGP）")
            self._thumb_load_id = item_id
            threading.Thread(target=self._fetch_thumbnail, args=(None, item_id, "niconico"), daemon=True).start()
            return
        if not thumb_url:
            self.thumb_label.config(image="", text="サムネイルなし")
            return

        if thumb_url in self._thumb_cache:
            self.thumb_label.config(image=self._thumb_cache[thumb_url], text="")
            return

        self.thumb_label.config(image="", text="読み込み中...")
        self._thumb_load_id = item_id
        threading.Thread(
            target=self._fetch_thumbnail,
            args=(thumb_url, item_id, service),
            daemon=True
        ).start()

    def _find_cached_thumbnail(self, service: str, video_id: str) -> Optional[Path]:
        """ダウンロード済みのサムネイルキャッシュを探す（autopost / import）。"""
        try:
            from v4.core.assets.images import image_manager
            site_map = {"youtube": "YouTube", "niconico": "Niconico", "twitch": "Twitch"}
            site = site_map.get(service, "YouTube")
            base = image_manager.base_dir
            # autopost 優先、次に import
            for mode in ("autopost", "import"):
                mode_dir = base / site / mode
                if not mode_dir.exists():
                    continue
                # {video_id}.{ext} の形で探す
                for ext in ("jpg", "jpeg", "png", "webp", "gif"):
                    candidate = mode_dir / f"{video_id}.{ext}"
                    if candidate.exists():
                        logger.debug(f"✅ キャッシュ発見: {candidate}")
                        return candidate
        except Exception as e:
            logger.debug(f"Cache search failed: {e}")
        return None

    def _load_thumbnail_from_path(self, path: Path, video_id: str):
        """ローカルキャッシュパスからサムネイルを読み込む。"""
        if not PIL_AVAILABLE:
            self.thumb_label.config(image="", text="(Pillow不可)")
            return
        try:
            img = Image.open(path)
            img.thumbnail((160, 90), Image.LANCZOS)
            from PIL import ImageTk
            photo = ImageTk.PhotoImage(img)
            self._thumb_cache[str(path)] = photo  # GC 防止
            if self._thumb_load_id == video_id:
                self.thumb_label.config(image=photo, text="")
        except Exception as e:
            logger.debug(f"Failed to load cached thumbnail: {e}")
            self.thumb_label.config(image="", text="読み込み失敗")

    def _fetch_thumbnail(self, url: Optional[str], video_id: str, service: str = "youtube"):
        """バックグラウンドスレッドでサムネイルを取得し、メモリキャッシュと v4/images への保存を行う。
        url が None で service が niconico の場合は OGP（watch ページの og:image）を取得してからダウンロード。
        """
        try:
            import httpx
            from PIL import Image
            import io

            if url is None and service == "niconico":
                try:
                    from v4.thumbnails_v4.niconico_ogp_utils import get_niconico_ogp_url
                    url = get_niconico_ogp_url(video_id)
                except Exception as e:
                    logger.debug("Niconico OGP thumbnail URL failed: %s", e)
                if not url:
                    if self._thumb_load_id == video_id:
                        self.after(0, lambda: self.thumb_label.config(image="", text="サムネイルなし（OGP取得不可）"))
                    return

            if not url:
                return

            with httpx.Client(timeout=8.0, follow_redirects=True) as client:
                resp = client.get(url)
                resp.raise_for_status()

            data = resp.content
            img = Image.open(io.BytesIO(data))
            img.thumbnail((160, 90), Image.LANCZOS)

            # プラットフォーム別に v4/images/{YouTube|Niconico|Twitch}/autopost へキャッシュ保存（二重取得しないよう取得済み bytes を保存）
            try:
                from v4.core.assets.images import image_manager
                site = (service or "youtube").capitalize()
                if site not in ("YouTube", "Niconico", "Twitch"):
                    site = "YouTube"
                ext = image_manager._detect_extension(data)
                save_path = image_manager.base_dir / site / "autopost" / f"{video_id}.{ext}"
                save_path.parent.mkdir(parents=True, exist_ok=True)
                save_path.write_bytes(data)
                logger.debug("Thumbnail cached: %s", save_path)
            except Exception as save_err:
                logger.debug("Thumbnail save to cache failed: %s", save_err)

            # tkinter PhotoImage は PIL ImageTk を使う
            from PIL import ImageTk
            photo = ImageTk.PhotoImage(img)
            self._thumb_cache[url] = photo

            # メインスレッドで UI 更新
            if self._thumb_load_id == video_id:
                self.after(0, lambda: self.thumb_label.config(image=photo, text=""))
        except Exception as e:
            logger.debug(f"Thumbnail load failed for {url}: {e}")
            if self._thumb_load_id == video_id:
                self.after(0, lambda: self.thumb_label.config(image="", text="取得失敗"))

    def _reset_filters(self):
        """検索・フィルタ・並び順を初期値に戻す"""
        self.filter_var.set("")
        self.service_var.set("すべて")
        self.status_var.set("すべて")
        self.posted_var.set("すべて")
        self.sort_var.set("公開日時（新しい順）")
        self.apply_filter()
        # ttk.Entry にフォーカスが残っていると、リセット後も入力テキストが選択状態のまま見える。
        # そのため選択ハイライトを明示的に解除し、フォーカスを Treeview 側へ移す。
        try:
            self.ent_filter.selection_clear()
            self.ent_filter.icursor(0)
        except Exception:
            pass
        try:
            self.tree.focus_set()
        except Exception:
            pass

    def select_all(self):
        for item in self.tree.get_children():
            if item not in self.selected_ids:
                self.selected_ids.add(item)
                vals = list(self.tree.item(item, "values"))
                vals[0] = "☑"
                self.tree.item(item, values=vals)
        if self.on_selection_change:
            self.on_selection_change()

    def deselect_all(self):
        for item in list(self.selected_ids):
            if self.tree.exists(item):
                self.selected_ids.remove(item)
                vals = list(self.tree.item(item, "values"))
                vals[0] = "☐"
                self.tree.item(item, values=vals)
        if self.on_selection_change:
            self.on_selection_change()

    def show_context_menu(self, event):
        item_id = self.tree.identify_row(event.y)
        if item_id:
            self.tree.selection_set(item_id)
            self.context_menu.post(event.x_root, event.y_root)

    def _menu_detail(self):
        item_id = self.tree.selection()[0]
        from ..views.video_detail_dialog import VideoDetailDialog
        VideoDetailDialog(
            self.winfo_toplevel(), item_id, self.db,
            on_refresh=self.on_refresh,
        )

    def _menu_image_assign(self):
        item_id = self.tree.selection()[0]
        from ..views.image_assign_dialog import ImageAssignDialog
        ImageAssignDialog(
            self.winfo_toplevel(), item_id, self.db,
            on_refresh=self.on_refresh
        )

    def _menu_post(self):
        item_id = self.tree.selection()[0]
        from ..views.post_dialog import PostDialog
        PostDialog(self.winfo_toplevel(), item_id, self.db, on_refresh=self.on_refresh)

    def _menu_schedule(self):
        item_id = self.tree.selection()[0]
        video = next((v for v in self.all_videos if v["video_id"] == item_id), None)
        initial_time = video.get("scheduled_start_time") if video else None

        from ..views.schedule_dialog import ScheduleDialog
        ScheduleDialog(
            self.winfo_toplevel(),
            item_id,
            initial_time,
            on_save=self._on_schedule_save
        )

    def _on_schedule_save(self, video_id, new_dt):
        if not self.db:
            return
        success = self.db.update_scheduled_time(video_id, new_dt)
        if success:
            from tkinter import messagebox
            messagebox.showinfo("成功", f"予約投稿時間を設定しました: {new_dt}")
            if self.on_refresh:
                self.on_refresh()
        else:
            from tkinter import messagebox
            messagebox.showerror("エラー", "予約時間の更新に失敗しました")

    def _menu_open_browser(self):
        """サービスに応じた正しいURLでブラウザを開く。"""
        item_id = self.tree.selection()[0]
        video = next((v for v in self.all_videos if v.get("video_id") == item_id), None)
        import webbrowser

        if video and video.get("video_url"):
            webbrowser.open(video["video_url"])
            return

        service = (video.get("service", "") if video else "").lower()
        if service == "niconico":
            webbrowser.open(f"https://www.nicovideo.jp/watch/{item_id}")
        elif service == "twitch":
            channel = (video.get("channel_name", "") if video else "").lower()
            webbrowser.open(f"https://www.twitch.tv/{channel}")
        else:
            webbrowser.open(f"https://www.youtube.com/watch?v={item_id}")

    def _menu_delete(self):
        item_id = self.tree.selection()[0]
        if not self.db:
            return
        from tkinter import messagebox
        if messagebox.askyesno("確認", f"動画 {item_id} をリストから削除しますか？"):
            self.db.delete_video(item_id)
            if self.on_refresh:
                self.on_refresh()

    def get_selected_ids(self):
        return list(self.selected_ids)
