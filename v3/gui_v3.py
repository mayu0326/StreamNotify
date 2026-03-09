# -*- coding: utf-8 -*-

"""
Stream notify on Bluesky - v3 GUI（改善版）

DB の動画一覧を表示し、投稿対象をチェックボックスで選択・スケジュール管理。
tkinter を使用（標準ライブラリのみ）
"""

import tkinter as tk
from tkinter import ttk, messagebox, filedialog
from datetime import datetime, timedelta
import logging
import os
import calendar
from image_manager import get_image_manager
from pathlib import Path
from template_editor_dialog import TemplateEditorDialog
from backup_manager import BackupManager
from unified_settings_window import UnifiedSettingsWindow  # Restored
from schedule_manager import BatchScheduleManager  # Restored
from batch_schedule_dialog import BatchScheduleDialog  # Restored
from schedule_view_tab import ScheduleViewTab  # Restored

try:
    from PIL import Image

    PIL_AVAILABLE = True
except ImportError:
    PIL_AVAILABLE = False

logger = logging.getLogger("GUILogger")

__author__ = "mayuneco(mayunya)"
__copyright__ = "Copyright (C) 2025 mayuneco(mayunya)"
__license__ = "GPLv2"


class CreateToolTip:
    """ウィジェットにツールチップを作成する"""

    def __init__(self, widget, text):
        self.widget = widget
        self.text = text
        self.widget.bind("<Enter>", self.enter)
        self.widget.bind("<Leave>", self.leave)
        self.id = None
        self.tw = None

    def enter(self, event=None):
        self.schedule()

    def leave(self, event=None):
        self.unschedule()
        self.hidetip()

    def schedule(self):
        self.unschedule()
        self.id = self.widget.after(500, self.showtip)

    def unschedule(self):
        id = self.id
        self.id = None
        if id:
            self.widget.after_cancel(id)

    def showtip(self, event=None):
        x = y = 0
        x, y, cx, cy = self.widget.bbox("insert")
        x += self.widget.winfo_rootx() + 25
        y += self.widget.winfo_rooty() + 20
        # creates a toplevel window
        self.tw = tk.Toplevel(self.widget)
        # Leaves only the label and removes the app window
        self.tw.wm_overrideredirect(True)
        self.tw.wm_geometry(f"+{x}+{y}")
        label = tk.Label(
            self.tw,
            text=self.text,
            justify="left",
            background="#ffffe0",
            relief="solid",
            borderwidth=1,
            font=("tahoma", "8", "normal"),
        )
        label.pack(ipadx=1)

    def hidetip(self):
        tw = self.tw
        self.tw = None
        if tw:
            tw.destroy()


class StreamNotifyGUI:
    """Stream notify GUI（統合版, プラグイン対応）"""

    def __init__(self, root, db, plugin_manager=None, bluesky_core=None):
        self.root = root
        self.root.title("StreamNotify on Bluesky - DB 管理")
        self.root.geometry("1520x750")

        self.db = db
        self.plugin_manager = plugin_manager
        self.bluesky_core = bluesky_core  # コア機能へのアクセス
        self.image_manager = get_image_manager()  # 画像管理クラスを初期化
        self.schedule_mgr = BatchScheduleManager(db)  # Restored
        self.selected_rows = set()

        # 設定を読み込み（AUTOPOST モード判定用）
        from config import get_config

        self.config = get_config("settings.env")
        self.operation_mode = self.config.operation_mode

        # フィルタ用の変数
        self.all_videos = []  # フィルタ前のすべての動画
        self.filtered_videos = []  # フィルタ後の動画

        self.setup_ui()
        self.refresh_data()

    def setup_ui(self):
        """UI を構築"""

        # === 上部: ツールバー ===
        toolbar = ttk.Frame(self.root)
        toolbar.pack(side=tk.TOP, fill=tk.X, padx=5, pady=5)

        ttk.Button(toolbar, text="🔄 再読込", command=self.refresh_data).pack(
            side=tk.LEFT, padx=2
        )

        # ★ フィード取得ボタン：websubモード時は「新着取得」、それ以外は「RSS更新」
        feed_button_text = (
            "📡 新着取得" if self.config.youtube_feed_mode == "websub" else "🌐 RSS更新"
        )
        ttk.Button(
            toolbar, text=feed_button_text, command=self.fetch_rss_manually
        ).pack(side=tk.LEFT, padx=2)

        ttk.Button(
            toolbar, text="🎬 Live判定", command=self.classify_youtube_live_manually
        ).pack(side=tk.LEFT, padx=2)
        ttk.Button(toolbar, text="➕ 動画追加", command=self.add_video_dialog).pack(
            side=tk.LEFT, padx=2
        )
        ttk.Separator(toolbar, orient=tk.VERTICAL).pack(side=tk.LEFT, fill=tk.Y, padx=2)
        ttk.Button(toolbar, text="☑️ すべて選択", command=self.select_all).pack(
            side=tk.LEFT, padx=2
        )
        ttk.Button(toolbar, text="☐ すべて解除", command=self.deselect_all).pack(
            side=tk.LEFT, padx=2
        )
        ttk.Separator(toolbar, orient=tk.VERTICAL).pack(side=tk.LEFT, fill=tk.Y, padx=2)

        ttk.Button(toolbar, text="💾 選択を保存", command=self.save_selection).pack(
            side=tk.LEFT, padx=2
        )
        ttk.Button(toolbar, text="🗑️ 削除", command=self.delete_selected).pack(
            side=tk.LEFT, padx=2
        )
        ttk.Separator(toolbar, orient=tk.VERTICAL).pack(side=tk.LEFT, fill=tk.Y, padx=2)

        # 投稿ボタン（AUTOPOST モード時は無効化）
        self.dry_run_button = ttk.Button(
            toolbar, text="🧪 投稿テスト", command=self.dry_run_post
        )
        self.dry_run_button.pack(side=tk.LEFT, padx=2)
        self.execute_post_button = ttk.Button(
            toolbar, text="📤 投稿設定", command=self.execute_post
        )
        self.execute_post_button.pack(side=tk.LEFT, padx=2)
        self.batch_schedule_button = ttk.Button(
            toolbar, text="📅 一括投稿予約", command=self.batch_schedule
        )
        self.batch_schedule_button.pack(side=tk.LEFT, padx=2)
        self.schedule_view_button = ttk.Button(
            toolbar, text="📅 投稿予定一覧", command=self.show_schedule_view
        )
        self.schedule_view_button.pack(side=tk.LEFT, padx=2)
        ttk.Separator(toolbar, orient=tk.VERTICAL).pack(side=tk.LEFT, fill=tk.Y, padx=2)

        # AUTOPOST モード時は投稿ボタンを無効化
        from config import OperationMode

        if self.operation_mode == OperationMode.AUTOPOST:
            self.dry_run_button.config(state=tk.DISABLED)
            self.execute_post_button.config(state=tk.DISABLED)
        ttk.Separator(toolbar, orient=tk.VERTICAL).pack(side=tk.LEFT, fill=tk.Y, padx=2)
        ttk.Button(toolbar, text="ℹ️ 統計", command=self.show_stats).pack(
            side=tk.LEFT, padx=2
        )
        ttk.Button(
            toolbar, text="💾 バックアップ", command=self.open_backup_dialog
        ).pack(side=tk.LEFT, padx=2)
        ttk.Separator(toolbar, orient=tk.VERTICAL).pack(side=tk.LEFT, fill=tk.Y, padx=2)

        ttk.Button(toolbar, text="⚙️ 全体設定", command=self.show_app_settings).pack(
            side=tk.LEFT, padx=2
        )
        ttk.Button(toolbar, text="🔧 プラグイン", command=self.show_plugins).pack(
            side=tk.LEFT, padx=2
        )
        ttk.Button(
            toolbar, text="📝 テンプレート編集", command=self.show_template_editor
        ).pack(side=tk.LEFT, padx=2)
        ttk.Separator(toolbar, orient=tk.VERTICAL).pack(side=tk.LEFT, fill=tk.Y, padx=2)

        # === フィルタパネル ===
        filter_frame = ttk.LabelFrame(self.root, text="🔍 フィルタ設定")
        filter_frame.pack(side=tk.TOP, fill=tk.X, padx=5, pady=5)

        # 第1行: タイトル検索
        ttk.Label(filter_frame, text="タイトル検索:").grid(
            row=0, column=0, sticky=tk.W, padx=5, pady=5
        )
        self.filter_title_entry = ttk.Entry(filter_frame, width=30)
        self.filter_title_entry.grid(row=0, column=1, sticky=tk.W, padx=5, pady=5)
        self.filter_title_entry.bind("<KeyRelease>", lambda e: self.apply_filters())

        # 投稿状態フィルタ
        ttk.Label(filter_frame, text="投稿状態:").grid(
            row=0, column=2, sticky=tk.W, padx=5, pady=5
        )
        self.filter_status_var = tk.StringVar(value="全て")
        status_combo = ttk.Combobox(
            filter_frame,
            textvariable=self.filter_status_var,
            values=["全て", "投稿済み", "未投稿"],
            state="readonly",
            width=12,
        )
        status_combo.grid(row=0, column=3, sticky=tk.W, padx=5, pady=5)
        status_combo.bind("<<ComboboxSelected>>", lambda e: self.apply_filters())

        # 配信元フィルタ
        ttk.Label(filter_frame, text="配信元:").grid(
            row=0, column=4, sticky=tk.W, padx=5, pady=5
        )
        self.filter_source_var = tk.StringVar(value="全て")
        source_combo = ttk.Combobox(
            filter_frame,
            textvariable=self.filter_source_var,
            values=["全て", "YouTube", "Niconico"],
            state="readonly",
            width=12,
        )
        source_combo.grid(row=0, column=5, sticky=tk.W, padx=5, pady=5)
        source_combo.bind("<<ComboboxSelected>>", lambda e: self.apply_filters())

        # タイプフィルタ（5カテゴリ対応: 動画/アーカイブ/放送予約/放送中/放送終了/プレミア）
        ttk.Label(filter_frame, text="タイプ:").grid(
            row=0, column=6, sticky=tk.W, padx=5, pady=5
        )
        self.filter_type_var = tk.StringVar(value="全て")
        type_combo = ttk.Combobox(
            filter_frame,
            textvariable=self.filter_type_var,
            values=[
                "全て",
                "🎬 動画",
                "📹 アーカイブ",
                "📅 放送予約",
                "🔴 放送中",
                "⏹️ 放送終了",
                "🎆 プレミア",
            ],
            state="readonly",
            width=20,
        )
        type_combo.grid(row=0, column=7, sticky=tk.W, padx=5, pady=5)
        type_combo.bind("<<ComboboxSelected>>", lambda e: self.apply_filters())

        # ボタン
        ttk.Button(filter_frame, text="🔄 リセット", command=self.reset_filters).grid(
            row=0, column=8, padx=5, pady=5
        )

        table_frame = ttk.Frame(self.root)
        table_frame.pack(fill=tk.BOTH, expand=True, padx=5, pady=5)

        columns = (
            "Select",
            "Video ID",
            "Published",
            "Source",
            "Type",
            "Title",
            "Date",
            "Posted",
            "Image Mode",
            "Image File",
        )
        self.tree = ttk.Treeview(
            table_frame, columns=columns, height=20, show="headings"
        )

        self.tree.column("Select", width=50, anchor=tk.CENTER)
        self.tree.column("Video ID", width=110)
        self.tree.column("Published", width=150)
        self.tree.column("Source", width=100, anchor=tk.CENTER)
        self.tree.column("Type", width=80, anchor=tk.CENTER)
        self.tree.column("Title", width=350)
        self.tree.column("Date", width=150)
        self.tree.column("Posted", width=60, anchor=tk.CENTER)
        self.tree.column("Image Mode", width=80, anchor=tk.CENTER)
        self.tree.column("Image File", width=180)

        self.tree.heading("Select", text="☑️")
        self.tree.heading("Video ID", text="Video ID")
        self.tree.heading("Published", text="公開日時")
        self.tree.heading("Source", text="配信元")
        self.tree.heading("Type", text="タイプ")
        self.tree.heading("Title", text="タイトル")
        self.tree.heading("Date", text="投稿予定/投稿日時")
        self.tree.heading("Posted", text="投稿実績")
        self.tree.heading("Image Mode", text="画像モード")
        self.tree.heading("Image File", text="画像ファイル")

        scrollbar = ttk.Scrollbar(
            table_frame, orient=tk.VERTICAL, command=self.tree.yview
        )
        self.tree.configure(yscroll=scrollbar.set)

        self.tree.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)
        scrollbar.pack(side=tk.RIGHT, fill=tk.Y)

        self.tree.bind("<Button-1>", self.on_tree_click)
        self.tree.bind("<Double-1>", self.on_tree_double_click)

        # 右クリックメニュー
        self.context_menu = tk.Menu(self.root, tearoff=0)
        self.context_menu.add_command(
            label="⏰ 予約日時を設定", command=self.context_edit_scheduled
        )
        self.context_menu.add_command(
            label="🖼️ 画像を設定", command=self.context_edit_image
        )
        self.context_menu.add_separator()
        self.context_menu.add_command(label="🗑️ 削除", command=self.context_delete)
        self.context_menu.add_command(
            label="❌ 選択解除", command=self.context_deselect
        )

        self.tree.bind("<Button-3>", self.show_context_menu)

        status_frame = ttk.Frame(self.root)
        status_frame.pack(side=tk.BOTTOM, fill=tk.X, padx=5, pady=5)

        self.status_label = ttk.Label(status_frame, text="準備完了", relief=tk.SUNKEN)
        self.status_label.pack(fill=tk.X)

    def cleanup(self):
        """GUI クローズ時のクリーンアップ処理"""
        try:
            # tkinter Variable の明示的な破棄
            for var_name in [
                "filter_status_var",
                "filter_source_var",
                "filter_type_var",
                "filter_title_entry",
            ]:
                try:
                    var = getattr(self, var_name, None)
                    if var and hasattr(var, "set"):
                        var.set("")  # 内容をクリア
                except:
                    pass

            # その他のオブジェクト参照をクリア
            self.all_videos = []
            self.filtered_videos = []
            self.selected_rows = set()
        except Exception as e:
            pass

    def refresh_data(self):
        """DB から最新データを取得して表示"""
        # すべての動画をキャッシュ
        self.all_videos = self.db.get_all_videos()
        self.selected_rows.clear()

        # フィルタをリセット
        if hasattr(self, "filter_title_entry"):
            self.filter_title_entry.delete(0, tk.END)
        if hasattr(self, "filter_status_var"):
            self.filter_status_var.set("全て")
        if hasattr(self, "filter_source_var"):
            self.filter_source_var.set("全て")

        # フィルタを適用して表示
        self.apply_filters()

    def fetch_rss_manually(self):
        """RSS フィードを手動で今すぐ取得・更新"""
        try:
            from youtube_core.youtube_rss import YouTubeRSS
            from youtube_core.youtube_websub import YouTubeWebSub
            from config import Config

            config = Config("settings.env")
            channel_id = config.youtube_channel_id

            if not channel_id:
                messagebox.showerror(
                    "エラー", "YouTube チャンネル ID が設定されていません。"
                )
                return

            # フィード取得モード判定
            feed_mode = config.youtube_feed_mode

            if feed_mode == "websub":
                # WebSub モード時はWebSubサーバーから新着確認
                messagebox.showinfo(
                    "RSS更新",
                    "WebSub サーバーから新着を確認中...\n（ウィンドウを閉じないでください）",
                )
                fetcher = YouTubeWebSub(channel_id)
            else:
                # ポーリングモード（デフォルト）：RSS フィードを取得
                messagebox.showinfo(
                    "RSS更新",
                    "YouTube RSS フィードを取得中...\n（ウィンドウを閉じないでください）",
                )
                fetcher = YouTubeRSS(channel_id)

            # ★ 重要: save_to_db メソッドを使用してDB保存（重複防止・API確認・YouTube Live自動分類を含む）
            # save_to_db は fetch_feed を内部で呼び出して、重複防止ロジックを正しく適用します
            added_count = fetcher.save_to_db(self.db)

            if added_count == 0:
                messagebox.showinfo("RSS更新完了", "新着動画は検出されませんでした。")
                return

            # DB を再読込して表示更新
            self.refresh_data()
            logger.info(
                f"✅ フィード手動更新完了: {added_count} 件追加（{feed_mode} モード）"
            )

        except ImportError as e:
            logger.error(f"❌ インポートエラー: {e}")
            messagebox.showerror("エラー", f"必要なモジュールが見つかりません:\n{e}")

        except Exception as e:
            logger.error(f"❌ RSS更新中にエラー: {e}")
            messagebox.showerror("エラー", f"RSS更新中にエラーが発生しました:\n{e}")

    def classify_youtube_live_manually(self):
        """YouTube Live キャッシュ更新・分類を手動で実行

        処理フロー：
        1. DB から Live 関連動画を取得
        2. ★【修正】ボタン押下時刻から24時間以内の動画のみ対象
        3. 各動画について API から最新情報を取得してキャッシュ更新
        4. 分類・DB更新を実行
        5. 動画取得と自動投稿はしない
        """
        try:
            # YouTube API プラグインを取得
            youtube_api_plugin = self.plugin_manager.get_plugin("youtube_api_plugin")

            if not youtube_api_plugin:
                messagebox.showinfo(
                    "情報",
                    "YouTube API プラグインが導入されていません。\n"
                    "YOUTUBE_API_KEY を settings.env に設定してください。",
                )
                logger.info("ℹ️ YouTube API プラグインは導入されていません")
                return

            if not youtube_api_plugin.is_available():
                messagebox.showwarning(
                    "警告",
                    "YouTube API プラグインが利用不可です。\n"
                    "YOUTUBE_API_KEY が正しく設定されていることを確認してください。",
                )
                return

            # 判定開始を通知
            messagebox.showinfo(
                "YouTube Live 判定",
                "Live キャッシュ確認・更新を実行中...\n"
                "（ウィンドウを閉じないでください）",
            )

            # 実行処理
            import time
            from datetime import datetime, timedelta
            from database import get_database
            from youtube_core.youtube_video_classifier import get_video_classifier

            db = get_database()
            classifier = get_video_classifier(api_key=os.getenv("YOUTUBE_API_KEY"))

            # DB から Live 関連動画を取得
            all_videos = db.get_all_videos()
            live_videos = [
                v
                for v in all_videos
                if v.get("content_type") in ["schedule", "live", "completed", "archive"]
            ]

            if not live_videos:
                messagebox.showinfo("YouTube Live 判定", "Live 関連動画がありません。")
                logger.info("ℹ️ Live 関連動画なし")
                return

            # ★【新】24時間以内の動画のみを対象に絞り込む
            now = datetime.now()
            time_threshold = now - timedelta(hours=24)
            current_timestamp = time.time()

            filtered_videos = []
            for video in live_videos:
                video_id = video.get("video_id")
                if not video_id:
                    continue

                # representative_time_jst から時刻を解析
                # フォーマット例: "2026-01-05 23:45:00"
                representative_time_str = video.get(
                    "representative_time_jst"
                ) or video.get("published_at")
                if not representative_time_str:
                    continue

                try:
                    # datetime オブジェクトに変換
                    video_time = datetime.strptime(
                        representative_time_str.split("+")[0].strip(),
                        "%Y-%m-%d %H:%M:%S",
                    )

                    # 24時間以内かチェック
                    if video_time >= time_threshold:
                        filtered_videos.append(video)
                    else:
                        logger.debug(
                            f"⏭️ 24時間以上前（スキップ）: {video_id} ({representative_time_str})"
                        )
                except ValueError as e:
                    logger.debug(f"⏭️ 時刻解析失敗（スキップ）: {video_id} - {e}")
                    continue

            if not filtered_videos:
                messagebox.showinfo(
                    "YouTube Live 判定", "24時間以内の Live 関連動画がありません。"
                )
                logger.info("ℹ️ 24時間以内の Live 関連動画なし")
                return

            logger.info(f"🎬 {len(filtered_videos)} 件の Live 動画を API から更新中...")

            updated_count = 0
            api_fetched_count = 0

            for video in filtered_videos:
                video_id = video.get("video_id")
                if not video_id:
                    continue

                # ★【新】24時間以内の動画は常に API から最新情報を取得
                logger.debug(f"📡 API から取得（24時間以内）: {video_id}")
                classification_result = classifier.classify_video(video_id)
                api_fetched_count += 1

                if not classification_result.get("success"):
                    logger.debug(f"⏭️ 分類失敗（スキップ）: {video_id}")
                    continue

                # ★ 分類結果を DB に反映（投稿なし）
                from plugins.youtube.live_module import get_live_module

                live_module = get_live_module()

                content_type = classification_result.get("type", "video")
                live_status = classification_result.get("live_status")

                # ★ DB を更新（ただし投稿はしない）
                success = db.update_video_status(video_id, content_type, live_status)
                if success:
                    updated_count += 1
                    logger.info(
                        f"✅ 更新: {video_id} (type={content_type}, status={live_status})"
                    )

            # 結果をメッセージボックスで表示
            result_msg = f"""✅ YouTube Live 判定完了

対象期間: 過去24時間以内
対象動画: {len(filtered_videos)} 件
API 取得: {api_fetched_count} 件
DB 更新: {updated_count} 件

※ 動画取得と自動投稿はしていません。
DB を再読込みします。"""
            messagebox.showinfo("YouTube Live 判定完了", result_msg)

            # DB を再読込して表示更新
            self.refresh_data()
            logger.info(
                f"✅ YouTube Live 判定完了: 対象 {len(filtered_videos)} 件、API 取得 {api_fetched_count} 件、DB 更新 {updated_count} 件"
            )

        except ImportError as ie:
            logger.error(f"❌ インポートエラー: {ie}")
            messagebox.showwarning(
                "警告",
                f"必要なモジュールが見つかりません。\nv3 の plugins/youtube/ ディレクトリを確認してください。\n\nエラー: {ie}",
            )

        except Exception as e:
            logger.error(f"❌ YouTube Live 判定中にエラー: {e}")
            messagebox.showerror(
                "エラー", f"YouTube Live 判定中にエラーが発生しました:\n{e}"
            )

    def apply_filters(self):
        """現在のフィルタ条件をツリーに適用"""
        # フィルタ条件を取得
        title_filter = self.filter_title_entry.get().lower()
        status_filter = self.filter_status_var.get()
        source_filter = self.filter_source_var.get()
        type_filter = self.filter_type_var.get()

        # Treeview をクリア
        for item in self.tree.get_children():
            self.tree.delete(item)

        # フィルタを適用
        self.filtered_videos = []
        for video in self.all_videos:
            # タイトル検索
            if title_filter and title_filter not in video.get("title", "").lower():
                continue

            # 投稿状態フィルタ
            is_posted = video.get("posted_to_bluesky", 0)
            if status_filter == "投稿済み" and not is_posted:
                continue
            elif status_filter == "未投稿" and is_posted:
                continue

            # 配信元フィルタ
            # DBには小文字で保存されているため、フィルタ値を小文字に変換して比較
            source = video.get("source", "").lower()
            source_filter_lower = source_filter.lower()
            if source_filter_lower != "全て" and source != source_filter_lower:
                continue

            # タイプフィルタ（5カテゴリ: 動画/アーカイブ/放送予約/放送中/放送終了/プレミア）
            if type_filter != "全て":
                # 表示用のタイプを計算（新分類対応）
                content_type = video.get("content_type", "video")
                is_premiere = video.get("is_premiere", 0)
                source_for_display = video.get("source", "").lower()

                if is_premiere:
                    display_type = "🎆 プレミア"
                elif source_for_display == "niconico":
                    display_type = "🎬 動画"
                elif content_type == "archive":
                    display_type = "📹 アーカイブ"
                elif content_type == "schedule":
                    display_type = "📅 放送予約"
                elif content_type == "live":
                    display_type = "🔴 放送中"
                elif content_type == "completed":
                    display_type = "⏹️ 放送終了"
                else:
                    display_type = "🎬 動画"

                # フィルタと比較
                if display_type != type_filter:
                    continue

            # フィルタを通った動画を表示
            self.filtered_videos.append(video)
            checked = "☑️" if video.get("selected_for_post") else "☐"

            # 投稿済みの場合は投稿日時を表示、未投稿の場合は予約日時を表示
            if video.get("posted_to_bluesky"):
                if video.get("posted_at"):
                    date_info = video.get("posted_at")
                else:
                    date_info = "不明"
            else:
                date_info = video.get("scheduled_at") or "（未設定）"

            source = video.get("source") or ""
            image_mode = video.get("image_mode") or ""
            image_filename = video.get("image_filename") or ""

            # 分類情報を取得（5カテゴリ対応）
            content_type = video.get("content_type", "video")
            is_premiere = video.get("is_premiere", 0)
            if is_premiere:
                display_type = "🎆 プレミア"
            elif source == "Niconico":
                display_type = "🎬 動画"
            elif content_type == "archive":
                display_type = "📹 アーカイブ"
            elif content_type == "schedule":
                display_type = "📅 放送予約"
            elif content_type == "live":
                display_type = "🔴 放送中"
            elif content_type == "completed":
                display_type = "⏹️ 放送終了"
            else:
                display_type = "🎬 動画"

            self.tree.insert(
                "",
                tk.END,
                values=(
                    checked,  # Select
                    video["video_id"],  # Video ID
                    video["published_at"][:16].replace(
                        "T", " "
                    ),  # Published (with time)
                    source,  # Source
                    display_type,  # Type (video/live/archive)
                    video["title"][:100],  # Title
                    date_info[:16] if date_info != "（未設定）" else date_info,  # Date
                    "✓" if video.get("posted_to_bluesky") else "–",  # Posted
                    image_mode,  # Image Mode
                    image_filename,  # Image File
                ),
                iid=video["video_id"],
                tags=("even" if len(self.tree.get_children()) % 2 == 0 else "odd",),
            )

            if video.get("selected_for_post"):
                self.selected_rows.add(video["video_id"])

        self.tree.tag_configure("even", background="#f0f0f0")
        self.tree.tag_configure("odd", background="white")

        # ステータスを更新
        total = len(self.all_videos)
        filtered = len(self.filtered_videos)
        selected = len(self.selected_rows)
        if filtered < total:
            status_text = (
                f"読み込み完了: {total} 件中 {filtered} 件を表示（選択: {selected} 件）"
            )
        else:
            status_text = f"読み込み完了: {total} 件の動画（選択: {selected} 件）"
        self.status_label.config(text=status_text)

    def reset_filters(self):
        """フィルタをリセット"""
        self.filter_title_entry.delete(0, tk.END)
        self.filter_status_var.set("全て")
        self.filter_source_var.set("全て")
        self.filter_type_var.set("全て")
        self.apply_filters()
        logger.info("✅ フィルタをリセットしました")

    def on_tree_click(self, event):
        """Treeview の「選択」列をクリックしてチェック状態をトグル"""
        item_id = self.tree.identify_row(event.y)
        col = self.tree.identify_column(event.x)

        if not item_id or col != "#1":
            return

        if item_id in self.selected_rows:
            self.selected_rows.remove(item_id)
            new_checked = "☐"
        else:
            self.selected_rows.add(item_id)
            new_checked = "☑️"

        values = list(self.tree.item(item_id, "values"))
        values[0] = new_checked
        self.tree.item(item_id, values=values)

    def on_tree_double_click(self, event):
        """Treeview の列をダブルクリックして編集"""
        item_id = self.tree.identify_row(event.y)
        col = self.tree.identify_column(event.x)

        if not item_id:
            return

        # 予約日時列（#7 に変更）
        if col == "#7":
            self.edit_scheduled_time(item_id)
        # 画像モード列または画像ファイル列（#9, #10 に変更）
        elif col in ("#9", "#10"):
            self.edit_image_file(item_id)

    def select_all(self):
        """すべてを選択"""
        self.selected_rows.clear()
        for item in self.tree.get_children():
            self.selected_rows.add(item)
            values = list(self.tree.item(item, "values"))
            values[0] = "☑️"
            self.tree.item(item, values=values)

    def deselect_all(self):
        """すべてを解除"""
        self.selected_rows.clear()
        for item in self.tree.get_children():
            values = list(self.tree.item(item, "values"))
            values[0] = "☐"
            self.tree.item(item, values=values)

    def save_selection(self):
        """選択状態を DB に保存"""
        try:
            for video_id in self.selected_rows:
                self.db.update_selection(video_id, selected=True)
                logger.info(f"動画の選択状態を更新: {video_id} (selected=True)")
            for item in self.tree.get_children():
                if item not in self.selected_rows:
                    self.db.update_selection(item, selected=False)
                    logger.info(f"動画の選択状態を更新: {item} (selected=False)")
            messagebox.showinfo("成功", "選択状態を保存しました。")
            self.refresh_data()
        except Exception as e:
            messagebox.showerror("エラー", f"保存中にエラーが発生しました:\n{e}")

    def edit_scheduled_time(self, item_id):
        """予約日時をダイアログで編集"""
        videos = self.db.get_all_videos()
        video = next((v for v in videos if v["video_id"] == item_id), None)
        if not video:
            messagebox.showerror("エラー", "動画情報が見つかりません。")
            return

        edit_window = tk.Toplevel(self.root)
        edit_window.title(f"投稿日時設定 - {item_id}")
        edit_window.geometry("480x400")
        edit_window.resizable(False, False)

        ttk.Label(
            edit_window, text=f"動画: {item_id}", font=("Arial", 10, "bold")
        ).pack(pady=4)
        ttk.Label(edit_window, text="予約投稿日時を設定します", foreground="gray").pack(
            pady=1
        )

        # 前回投稿日時情報を表示
        if video.get("posted_to_bluesky"):
            if video.get("posted_at"):
                prev_post_info = f"前回投稿日時: {video.get('posted_at')}"
            else:
                prev_post_info = "前回投稿日時: 不明"
        else:
            prev_post_info = "前回投稿日時: 投稿されていません"

        ttk.Label(
            edit_window, text=prev_post_info, foreground="blue", font=("Arial", 9)
        ).pack(pady=2)

        # メインフレーム（スクロール対応）
        main_frame = ttk.Frame(edit_window)
        main_frame.pack(fill=tk.BOTH, padx=8, pady=4)

        # === 日付選択 ===
        date_frame = ttk.LabelFrame(main_frame, text="📅 日付を選択", padding=8)
        date_frame.pack(fill=tk.X, pady=3)

        # 現在の予約日時またはデフォルト値を取得
        if video.get("scheduled_at"):
            try:
                selected_date = datetime.fromisoformat(video.get("scheduled_at")).date()
            except:
                selected_date = datetime.now().date()
        else:
            selected_date = datetime.now().date()

        year_var = tk.StringVar(value=str(selected_date.year))
        month_var = tk.StringVar(value=str(selected_date.month))
        day_var = tk.StringVar(value=str(selected_date.day))

        # 日付Spinbox
        date_control_frame = ttk.Frame(date_frame)
        date_control_frame.pack(pady=4, fill=tk.X)

        year_spin = ttk.Spinbox(
            date_control_frame,
            from_=2024,
            to=2030,
            width=4,
            textvariable=year_var,
            font=("Arial", 11),
        )
        year_spin.pack(side=tk.LEFT, padx=3, fill=tk.X, expand=True)
        ttk.Label(date_control_frame, text="年", width=2).pack(side=tk.LEFT, padx=2)

        month_spin = ttk.Spinbox(
            date_control_frame,
            from_=1,
            to=12,
            width=4,
            textvariable=month_var,
            font=("Arial", 11),
        )
        month_spin.pack(side=tk.LEFT, padx=3, fill=tk.X, expand=True)
        ttk.Label(date_control_frame, text="月", width=2).pack(side=tk.LEFT, padx=2)

        day_spin = ttk.Spinbox(
            date_control_frame,
            from_=1,
            to=31,
            width=4,
            textvariable=day_var,
            font=("Arial", 11),
        )
        day_spin.pack(side=tk.LEFT, padx=3, fill=tk.X, expand=True)
        ttk.Label(date_control_frame, text="日", width=2).pack(side=tk.LEFT, padx=2)

        def update_calendar(*args):
            """日の妥当性をチェック"""
            try:
                year = int(year_var.get())
                month = int(month_var.get())
                day = int(day_var.get())

                # 日の妥当性チェック
                if day > calendar.monthrange(year, month)[1]:
                    day = calendar.monthrange(year, month)[1]
                    day_var.set(str(day))
            except Exception:
                return

        year_spin.bind("<KeyRelease>", update_calendar)
        month_spin.bind("<KeyRelease>", update_calendar)
        day_spin.bind("<KeyRelease>", update_calendar)

        # === 時間選択 ===
        time_frame = ttk.LabelFrame(main_frame, text="🕐 時間を選択", padding=8)
        time_frame.pack(fill=tk.X, pady=3)

        # 現在の時間またはデフォルト値を取得
        if video.get("scheduled_at"):
            try:
                selected_time = datetime.fromisoformat(video.get("scheduled_at")).time()
            except Exception:
                selected_time = (datetime.now() + timedelta(minutes=5)).time()
        else:
            selected_time = (datetime.now() + timedelta(minutes=5)).time()

        hour_var = tk.StringVar(value=f"{selected_time.hour:02d}")
        minute_var = tk.StringVar(value=f"{selected_time.minute:02d}")

        time_control_frame = ttk.Frame(time_frame)
        time_control_frame.pack(pady=4, fill=tk.X)

        hour_spin = ttk.Spinbox(
            time_control_frame,
            from_=0,
            to=23,
            width=4,
            textvariable=hour_var,
            format="%02.0f",
            font=("Arial", 11),
        )
        hour_spin.pack(side=tk.LEFT, padx=3, fill=tk.X, expand=True)
        ttk.Label(time_control_frame, text="時", width=2).pack(side=tk.LEFT, padx=2)

        minute_spin = ttk.Spinbox(
            time_control_frame,
            from_=0,
            to=59,
            width=4,
            textvariable=minute_var,
            format="%02.0f",
            font=("Arial", 11),
        )
        minute_spin.pack(side=tk.LEFT, padx=3, fill=tk.X, expand=True)
        ttk.Label(time_control_frame, text="分", width=2).pack(side=tk.LEFT, padx=2)

        # クイック設定
        quick_frame = ttk.LabelFrame(main_frame, text="⚡ クイック設定", padding=8)
        quick_frame.pack(fill=tk.X, pady=3)

        def set_quick_time(minutes_offset):
            """クイック設定で時刻を更新"""
            quick_dt = datetime.now() + timedelta(minutes=minutes_offset)
            year_var.set(str(quick_dt.year))
            month_var.set(str(quick_dt.month))
            day_var.set(str(quick_dt.day))
            hour_var.set(f"{quick_dt.hour:02d}")
            minute_var.set(f"{quick_dt.minute:02d}")

        quick_btn_frame1 = ttk.Frame(quick_frame)
        quick_btn_frame1.pack(fill=tk.X, pady=2)
        ttk.Button(
            quick_btn_frame1, text="5分後", width=18, command=lambda: set_quick_time(5)
        ).pack(side=tk.LEFT, padx=1, expand=True)
        ttk.Button(
            quick_btn_frame1,
            text="15分後",
            width=18,
            command=lambda: set_quick_time(15),
        ).pack(side=tk.LEFT, padx=1, expand=True)

        quick_btn_frame2 = ttk.Frame(quick_frame)
        quick_btn_frame2.pack(fill=tk.X, pady=2)
        ttk.Button(
            quick_btn_frame2,
            text="30分後",
            width=18,
            command=lambda: set_quick_time(30),
        ).pack(side=tk.LEFT, padx=1, expand=True)
        ttk.Button(
            quick_btn_frame2,
            text="1時間後",
            width=18,
            command=lambda: set_quick_time(60),
        ).pack(side=tk.LEFT, padx=1, expand=True)

        # ボタン
        button_frame = ttk.Frame(edit_window)
        button_frame.pack(fill=tk.X, pady=6, padx=8)

        def save_time():
            """保存"""
            try:
                year = int(year_var.get())
                month = int(month_var.get())
                day = int(day_var.get())
                hour = int(hour_var.get())
                minute = int(minute_var.get())

                scheduled = datetime(year, month, day, hour, minute).strftime(
                    "%Y-%m-%d %H:%M"
                )
                self.db.update_selection(item_id, selected=True, scheduled_at=scheduled)
                logger.info(
                    f"動画の選択状態を更新: {item_id} (selected=True, scheduled={scheduled})"
                )
                self.selected_rows.add(item_id)
                messagebox.showinfo(
                    "成功",
                    f"予約日時を設定しました。\n{scheduled}\n\n「選択を保存」ボタンで確定してください。",
                )
                edit_window.destroy()
                # 画像設定ダイアログを開くか確認
                if messagebox.askyesno("次のステップ", "画像を設定しますか？"):
                    self.edit_image_file(item_id)
            except Exception as e:
                messagebox.showerror("エラー", f"無効な日時です:\n{e}")

        def clear_selection():
            """選択解除"""
            self.db.update_selection(
                item_id,
                selected=False,
                scheduled_at=None,
                image_mode=None,
                image_filename=None,
            )
            logger.info(
                f"動画の選択状態を更新: {item_id} (selected=False, scheduled=None)"
            )
            self.selected_rows.discard(item_id)
            messagebox.showinfo("成功", "この動画の選択を解除しました。")
            edit_window.destroy()
            self.refresh_data()

        ttk.Button(button_frame, text="✅ 保存", command=save_time).pack(
            side=tk.LEFT, padx=4, expand=True, fill=tk.X
        )
        ttk.Button(button_frame, text="❌ 選択解除", command=clear_selection).pack(
            side=tk.LEFT, padx=4, expand=True, fill=tk.X
        )
        ttk.Button(button_frame, text="✕ キャンセル", command=edit_window.destroy).pack(
            side=tk.LEFT, padx=4, expand=True, fill=tk.X
        )

    def show_context_menu(self, event):
        """右クリックメニューを表示"""
        item_id = self.tree.identify_row(event.y)
        if item_id:
            self.tree.selection_set(item_id)
            self.current_context_item = item_id
            self.context_menu.post(event.x_root, event.y_root)

    def context_edit_scheduled(self):
        """コンテキストメニューから予約日時を編集"""
        if hasattr(self, "current_context_item"):
            self.edit_scheduled_time(self.current_context_item)

    def context_edit_image(self):
        """コンテキストメニューから画像を設定"""
        if hasattr(self, "current_context_item"):
            self.edit_image_file(self.current_context_item)

    def context_deselect(self):
        """コンテキストメニューから選択解除"""
        if hasattr(self, "current_context_item"):
            item_id = self.current_context_item
            self.db.update_selection(
                item_id,
                selected=False,
                scheduled_at=None,
                image_mode=None,
                image_filename=None,
            )
            logger.info(
                f"動画の選択状態を更新: {item_id} (selected=False, scheduled=None)"
            )
            self.selected_rows.discard(item_id)
            messagebox.showinfo("成功", "この動画の選択を解除しました。")
            self.refresh_data()

    def edit_image_file(self, item_id):
        """画像ファイルをダイアログで編集（コンパクト版）"""
        videos = self.db.get_all_videos()
        video = next((v for v in videos if v["video_id"] == item_id), None)
        if not video:
            messagebox.showerror("エラー", "動画情報が見つかりません。")
            return

        site = video.get("source", "YouTube")  # デフォルトはYouTube
        site_dir = self._normalize_site_dir(site)

        image_window = tk.Toplevel(self.root)
        image_window.title(f"画像ファイル設定 - {item_id}")
        image_window.geometry("550x450")
        image_window.resizable(False, False)

        ttk.Label(
            image_window, text=f"動画ID: {item_id}", font=("Arial", 10, "bold")
        ).pack(pady=5)
        ttk.Label(
            image_window,
            text=f"配信元: {site} | タイトル: {video['title'][:40]}...",
            foreground="gray",
        ).pack(pady=2)

        # 画像ファイル選択フレーム
        image_frame = ttk.LabelFrame(
            image_window, text=f"画像ファイル指定 ({site_dir}/import)", padding=10
        )
        image_frame.pack(pady=5, padx=10, fill=tk.BOTH, expand=True)

        image_path_var = tk.StringVar(value=video.get("image_filename") or "")

        # ファイル名入力
        file_select_frame = ttk.Frame(image_frame)
        file_select_frame.pack(fill=tk.X, pady=5)

        ttk.Label(file_select_frame, text="ファイル名:").pack(side=tk.LEFT, padx=5)
        image_entry = ttk.Entry(
            file_select_frame, textvariable=image_path_var, width=35
        )
        image_entry.pack(side=tk.LEFT, padx=5, fill=tk.X, expand=True)

        def browse_image():
            """ファイルブラウザで画像を選択（任意のフォルダから）"""
            # ★ 修正: 初期ディレクトリをユーザーのホームディレクトリに（制限なし）
            try:
                initialdir = os.path.expanduser("~")  # ユーザーのホームディレクトリ
            except Exception:
                initialdir = os.getcwd()  # 失敗時はカレントディレクトリ

            filetypes = [
                ("画像ファイル", "*.png;*.jpg;*.jpeg;*.gif;*.webp"),
                ("すべて", "*"),
            ]
            path = filedialog.askopenfilename(
                title="画像を選択", initialdir=initialdir, filetypes=filetypes
            )

            if path:
                # ★ 修正: パス検証を撤廃し、任意のフォルダから選択可能に
                # ファイルが実在するかのみチェック
                if os.path.isfile(path):
                    original_filename = os.path.basename(path)

                    # ★ 【新規】ファイル名を video_id.jpg に統一（自動取得と同じ形式）
                    standardized_filename = f"{item_id}.jpg"
                    image_path_var.set(standardized_filename)

                    # ★ 選択されたファイルを images/{site}/import にコピー
                    import shutil

                    import_dir = os.path.abspath(f"images/{site_dir}/import")
                    os.makedirs(import_dir, exist_ok=True)
                    dest_path = os.path.join(import_dir, standardized_filename)

                    try:
                        shutil.copy2(path, dest_path)
                        logger.info(
                            f"✅ 画像ファイルをコピーしました: {path} → {dest_path}"
                        )
                        logger.info(
                            f"   ファイル名を統一: {original_filename} → {standardized_filename}"
                        )

                        # ★ 【新規】コピーしたファイルに画像処理を実行（リサイズ・JPG変換）
                        from image_processor import resize_image

                        try:
                            logger.info(f"🔄 画像処理を実行中: {standardized_filename}")
                            processed_data = resize_image(dest_path)
                            if processed_data:
                                # 処理済みバイナリを上書き保存
                                with open(dest_path, "wb") as f:
                                    f.write(processed_data)
                                logger.info(
                                    f"✅ 画像処理完了（リサイズ・JPG変換）: {standardized_filename}"
                                )
                            else:
                                logger.warning(
                                    f"⚠️ 画像処理に失敗しました（元ファイルを使用）: {standardized_filename}"
                                )
                        except Exception as e:
                            logger.warning(
                                f"⚠️ 画像処理エラー（元ファイルを使用、続行）: {e}"
                            )

                        # DB に登録（統一されたファイル名で登録）
                        self.db.update_image_info(
                            item_id,
                            image_mode="import",
                            image_filename=standardized_filename,
                        )
                        logger.info(
                            f"✅ DB に画像ファイルを登録しました: {item_id} → {standardized_filename}"
                        )
                        messagebox.showinfo(
                            "成功",
                            f"画像ファイルを登録しました。\n{standardized_filename}",
                        )
                        image_window.destroy()  # 自動的にダイアログを閉じる
                    except Exception as e:
                        logger.error(f"❌ ファイルコピーエラー: {e}")
                        messagebox.showerror(
                            "エラー", f"ファイルのコピーに失敗しました。\n{e}"
                        )
                else:
                    messagebox.showerror("エラー", "選択されたファイルが見つかりません")

        ttk.Button(file_select_frame, text="📂 参照", command=browse_image).pack(
            side=tk.LEFT, padx=2
        )

        # 登録済み画像表示
        current_image_var = tk.StringVar(
            value=video.get("image_filename") or "（未登録）"
        )
        current_frame = ttk.LabelFrame(
            image_frame, text="登録されている画像", padding=5
        )
        current_frame.pack(fill=tk.X, pady=5)
        ttk.Label(
            current_frame, textvariable=current_image_var, foreground="blue"
        ).pack(anchor=tk.W)

        # URLからダウンロードフレーム
        url_frame = ttk.LabelFrame(
            image_frame, text="URLから画像をダウンロード", padding=5
        )
        url_frame.pack(fill=tk.X, pady=5)

        url_var = tk.StringVar(value=video.get("thumbnail_url") or "")

        url_input_frame = ttk.Frame(url_frame)
        url_input_frame.pack(fill=tk.X)

        ttk.Label(url_input_frame, text="URL:").pack(side=tk.LEFT, padx=2)
        url_entry = ttk.Entry(url_input_frame, textvariable=url_var, width=35)
        url_entry.pack(side=tk.LEFT, padx=2, fill=tk.X, expand=True)

        def download_from_url():
            """URLから画像をダウンロード"""
            url = url_var.get().strip()
            if not url:
                messagebox.showwarning("警告", "URLを入力してください。")
                return

            # YouTube動画の場合、ロガーを切り替え
            import image_manager as im_module
            import logging

            original_logger = im_module.logger
            if site_dir == "YouTube":
                im_module.logger = logging.getLogger("YouTubeLogger")

            try:
                # ダウンロード
                filename = self.image_manager.download_and_save_thumbnail(
                    thumbnail_url=url, site=site_dir, video_id=item_id, mode="import"
                )
            finally:
                im_module.logger = original_logger

            if filename:
                image_path_var.set(filename)
                current_image_var.set(filename)
                image_window.destroy()  # ダイアログを先に閉じる
                messagebox.showinfo("成功", f"画像をダウンロードしました。\n{filename}")
            else:
                messagebox.showerror("エラー", "画像のダウンロードに失敗しました。")

        ttk.Button(
            url_input_frame, text="⬇️ ダウンロード", command=download_from_url
        ).pack(side=tk.LEFT, padx=2)

        # 自動取得／バックフィルフレーム
        auto_frame = ttk.LabelFrame(
            image_frame, text="自動取得/バックフィル", padding=5
        )
        auto_frame.pack(fill=tk.X, pady=5)

        def run_youtube_thumbnail_fetch():
            """YouTube動画の場合、高品質サムネイルを取得してDB反映"""
            if site_dir != "YouTube":
                messagebox.showinfo("情報", "YouTube動画のみ対応の機能です。")
                return
            try:
                from image_manager import get_youtube_thumbnail_url
            except Exception as e:
                messagebox.showerror("エラー", f"モジュール読み込みに失敗しました: {e}")
                return

            thumb_url = get_youtube_thumbnail_url(item_id)
            if not thumb_url:
                messagebox.showwarning(
                    "警告", "YouTubeサムネイルURLを取得できませんでした。"
                )
                return

            # ロガーを一時的に切り替え
            import image_manager as im_module
            import logging

            original_logger = im_module.logger
            im_module.logger = logging.getLogger("YouTubeLogger")

            try:
                filename = self.image_manager.download_and_save_thumbnail(
                    thumbnail_url=thumb_url,
                    site=site_dir,
                    video_id=item_id,
                    mode="import",
                )
            finally:
                im_module.logger = original_logger

            if filename:
                # DB更新時のロガーも切り替え
                import database as db_module

                db_original_logger = db_module.logger
                db_module.logger = logging.getLogger("YouTubeLogger")

                try:
                    self.db.update_thumbnail_url(item_id, thumb_url)
                    self.db.update_image_info(
                        item_id, image_mode="import", image_filename=filename
                    )
                finally:
                    db_module.logger = db_original_logger

                image_path_var.set(filename)
                current_image_var.set(filename)
                image_window.destroy()  # ダイアログを先に閉じる
                messagebox.showinfo(
                    "成功", f"YouTubeサムネイルを取得しました。\n{filename}"
                )
            else:
                messagebox.showerror("エラー", "画像のダウンロードに失敗しました。")

        def run_niconico_ogp_fetch():
            """ニコニコ動画の場合、OGPから即時取得してDB反映"""
            if site_dir != "Niconico":
                messagebox.showinfo("情報", "ニコニコ動画のみ対応の機能です。")
                return
            try:
                from thumbnails.niconico_ogp_backfill import fetch_thumbnail_url
            except Exception as e:
                messagebox.showerror("エラー", f"モジュール読み込みに失敗しました: {e}")
                return

            thumb_url = fetch_thumbnail_url(item_id)
            if not thumb_url:
                messagebox.showwarning(
                    "警告", "OGPからサムネイルURLを取得できませんでした。"
                )
                return

            filename = self.image_manager.download_and_save_thumbnail(
                thumbnail_url=thumb_url,
                site=site_dir,
                video_id=item_id,
                mode="import",
            )
            if filename:
                self.db.update_thumbnail_url(item_id, thumb_url)
                self.db.update_image_info(
                    item_id, image_mode="import", image_filename=filename
                )
                image_path_var.set(filename)
                current_image_var.set(filename)
                image_window.destroy()  # ダイアログを先に閉じる
                messagebox.showinfo("成功", f"OGPから画像を取得しました。\n{filename}")
            else:
                messagebox.showerror("エラー", "画像のダウンロードに失敗しました。")

        def run_redownload_all():
            """画像未設定の動画を再ダウンロード（全体）"""
            if not messagebox.askyesno(
                "確認", "画像未設定の動画をまとめて再ダウンロードしますか？"
            ):
                return
            try:
                from thumbnails.image_re_fetch_module import redownload_missing_images

                redownload_missing_images(dry_run=False)
                messagebox.showinfo(
                    "完了", "再ダウンロードを実行しました。ログを確認してください。"
                )
            except Exception as e:
                messagebox.showerror("エラー", f"再ダウンロードに失敗しました: {e}")

        # 動画ソースに応じて適切なボタンを表示
        if site_dir == "YouTube":
            ttk.Button(
                auto_frame,
                text="YouTubeサムネイル取得",
                command=run_youtube_thumbnail_fetch,
            ).pack(side=tk.LEFT, padx=3, expand=True, fill=tk.X)
        elif site_dir == "Niconico":
            ttk.Button(
                auto_frame,
                text="OGPから取得 (ニコニコ)",
                command=run_niconico_ogp_fetch,
            ).pack(side=tk.LEFT, padx=3, expand=True, fill=tk.X)

        ttk.Button(
            auto_frame, text="未設定画像を再ダウンロード", command=run_redownload_all
        ).pack(side=tk.LEFT, padx=3, expand=True, fill=tk.X)

        # ボタン
        button_frame = ttk.Frame(image_window)
        button_frame.pack(pady=10, padx=10, fill=tk.X)

        def save_image():
            """画像設定を保存"""
            image_filename = image_path_var.get().strip() or None
            image_mode = "import" if image_filename else None

            # 画像ファイルの存在確認
            if image_filename:
                image_path = os.path.join("images", site_dir, "import", image_filename)
                if not os.path.exists(image_path):
                    if not messagebox.askyesno(
                        "確認",
                        f"画像ファイル '{image_filename}' が見つかりません。\nそれでも設定しますか？",
                    ):
                        return

            self.db.update_image_info(
                item_id, image_mode=image_mode, image_filename=image_filename
            )
            messagebox.showinfo(
                "成功",
                f"画像ファイルを設定しました。\n画像: {image_filename or '（指定なし）'}\n\n「選択を保存」ボタンで確定してください。",
            )
            image_window.destroy()
            self.refresh_data()

        def clear_image():
            """画像設定をクリア"""
            image_path_var.set("")
            current_image_var.set("（未登録）")
            self.db.update_image_info(item_id, image_mode=None, image_filename=None)
            messagebox.showinfo("成功", "画像ファイルを削除しました。")
            image_window.destroy()
            self.refresh_data()

        def preview_image():
            """画像をプレビュー（別ウィンドウ）"""
            filename = image_path_var.get().strip()
            if not filename:
                messagebox.showinfo("情報", "画像が登録されていません。")
                return

            image_info = self.image_manager.get_image_info(site_dir, "import", filename)
            if not image_info:
                messagebox.showerror(
                    "エラー", f"画像ファイル '{filename}' が見つかりません。"
                )
                return

            # プレビューウィンドウを作成（画像表示 + 情報）
            preview_window = tk.Toplevel(image_window)
            preview_window.title(f"画像プレビュー - {filename}")
            preview_window.geometry("520x520")
            preview_window.resizable(False, False)

            # 画像表示
            image_path = image_info["path"]
            has_pillow = True
            try:
                from PIL import Image, ImageTk, ImageOps  # type: ignore
            except ImportError:
                has_pillow = False

            img_label = ttk.Label(preview_window)
            img_label.pack(pady=10)

            if has_pillow:
                try:
                    with Image.open(image_path) as img_obj:
                        img_obj = ImageOps.exif_transpose(img_obj)
                        img_obj.thumbnail((480, 320), Image.Resampling.LANCZOS)
                        photo = ImageTk.PhotoImage(img_obj)
                        img_label.configure(image=photo)
                        img_label.image = photo  # GC防止
                except Exception as e:
                    ttk.Label(
                        preview_window,
                        text=f"画像の読み込みに失敗しました: {e}",
                        foreground="red",
                    ).pack(pady=5)
            else:
                ttk.Label(
                    preview_window,
                    text="Pillow が未インストールのため画像表示できません。\n`pip install Pillow` を実行してください。",
                    foreground="red",
                    wraplength=480,
                ).pack(pady=5)

            ttk.Label(preview_window, text="画像情報", font=("Arial", 12, "bold")).pack(
                pady=5
            )

            info_frame = ttk.Frame(preview_window, padding=10)
            info_frame.pack(fill=tk.BOTH, expand=True)

            # 情報を表示
            ttk.Label(info_frame, text="ファイル名:", font=("Arial", 9, "bold")).grid(
                row=0, column=0, sticky=tk.W, pady=3
            )
            ttk.Label(info_frame, text=image_info["filename"]).grid(
                row=0, column=1, sticky=tk.W, pady=3, padx=10
            )

            ttk.Label(info_frame, text="形式:", font=("Arial", 9, "bold")).grid(
                row=1, column=0, sticky=tk.W, pady=3
            )
            ttk.Label(info_frame, text=image_info["format"]).grid(
                row=1, column=1, sticky=tk.W, pady=3, padx=10
            )

            ttk.Label(
                info_frame, text="ファイルサイズ:", font=("Arial", 9, "bold")
            ).grid(row=2, column=0, sticky=tk.W, pady=3)
            ttk.Label(info_frame, text=f"{image_info['file_size_mb']} MB").grid(
                row=2, column=1, sticky=tk.W, pady=3, padx=10
            )

            if image_info.get("width") and image_info.get("height"):
                ttk.Label(info_frame, text="解像度:", font=("Arial", 9, "bold")).grid(
                    row=3, column=0, sticky=tk.W, pady=3
                )
                ttk.Label(
                    info_frame, text=f"{image_info['width']} x {image_info['height']}"
                ).grid(row=3, column=1, sticky=tk.W, pady=3, padx=10)

                ttk.Label(info_frame, text="モード:", font=("Arial", 9, "bold")).grid(
                    row=4, column=0, sticky=tk.W, pady=3
                )
                ttk.Label(info_frame, text=image_info.get("mode", "N/A")).grid(
                    row=4, column=1, sticky=tk.W, pady=3, padx=10
                )
            else:
                ttk.Label(
                    info_frame,
                    text="※ Pillow未インストールのため解像度情報は取得できません",
                    foreground="gray",
                    wraplength=350,
                ).grid(row=3, column=0, columnspan=2, pady=10)

            ttk.Label(info_frame, text="パス:", font=("Arial", 9, "bold")).grid(
                row=5, column=0, sticky=tk.W, pady=3
            )
            path_label = ttk.Label(
                info_frame,
                text=image_info["path"],
                foreground="blue",
                cursor="hand2",
                wraplength=320,
            )
            path_label.grid(row=5, column=1, sticky=tk.W, pady=3, padx=10)

            def open_folder():
                """フォルダを開く"""
                import subprocess

                folder_path = os.path.dirname(image_info["path"])
                subprocess.Popen(f'explorer "{folder_path}"')

            path_label.bind("<Button-1>", lambda e: open_folder())

            ttk.Button(
                preview_window, text="閉じる", command=preview_window.destroy
            ).pack(pady=10)

        ttk.Button(button_frame, text="✅ 保存", command=save_image).pack(
            side=tk.LEFT, padx=3, expand=True, fill=tk.X
        )
        ttk.Button(button_frame, text="🔍 プレビュー", command=preview_image).pack(
            side=tk.LEFT, padx=3, expand=True, fill=tk.X
        )
        ttk.Button(button_frame, text="❌ クリア", command=clear_image).pack(
            side=tk.LEFT, padx=3, expand=True, fill=tk.X
        )
        ttk.Button(
            button_frame, text="✕ キャンセル", command=image_window.destroy
        ).pack(side=tk.LEFT, padx=3, expand=True, fill=tk.X)

    def _normalize_site_dir(self, site: str) -> str:
        """サイト名をディレクトリ表記に正規化"""
        if not site:
            return "YouTube"
        s = site.lower()
        if s == "youtube":
            return "YouTube"
        if s == "niconico" or s == "nico" or s.startswith("nico"):
            return "Niconico"
        if s == "twitch":
            return "Twitch"
        return site

    def dry_run_post(self):
        """ドライラン：投稿設定ウィンドウを表示（ドライランモード）"""
        # AUTOPOST / COLLECT モード時は実行禁止
        from config import OperationMode

        if self.operation_mode == OperationMode.AUTOPOST:
            messagebox.showerror(
                "エラー",
                "🤖 AUTOPOST モード では手動投稿操作は禁止されています。\n\n"
                "投稿はすべて自動制御されます。\n"
                "手動投稿を実行するには、settings.env で APP_MODE を\n"
                "'selfpost' に変更して、アプリを再起動してください。",
            )
            return

        if self.operation_mode == OperationMode.COLLECT:
            messagebox.showerror(
                "エラー",
                "📦 COLLECT モード では投稿機能が無効化されています。\n\n"
                "投稿を実行するには、settings.env で APP_MODE を\n"
                "'selfpost' に変更して、アプリを再起動してください。",
            )
            return

        if not self.selected_rows:
            messagebox.showwarning(
                "警告",
                "投稿対象の動画がありません。\n\n☑️ をクリックして選択してください。",
            )
            return

        videos = self.db.get_all_videos()
        selected = [v for v in videos if v["video_id"] in self.selected_rows]

        if not selected:
            messagebox.showwarning(
                "警告",
                "投稿対象の動画がありません。\n\n選択して保存してから実行してください。",
            )
            return

        msg = f"""
🧪 投稿テスト モード

以下の {len(selected)} 件をテスト実行します：

"""
        for v in selected[:5]:
            msg += f"  ✓ {v['title'][:50]}...\n"

        if len(selected) > 5:
            msg += f"  ... ほか {len(selected) - 5} 件\n"

        msg += """
投稿設定ウィンドウで「投稿テスト」をクリックすると、
ログ出力のみで実際には投稿されません。
        """

        if messagebox.askyesno("確認", msg):
            for video in selected:
                post_window = PostSettingsWindow(
                    self.root,
                    video,
                    self.db,
                    self.plugin_manager,
                    self.bluesky_core,
                    operation_mode=self.operation_mode,
                    is_dry_run=True,
                )
                self.root.wait_window(post_window.window)

    def execute_post(self):
        """投稿設定：投稿設定ウィンドウを表示"""
        # AUTOPOST / COLLECT モード時は実行禁止
        from config import OperationMode

        if self.operation_mode == OperationMode.AUTOPOST:
            messagebox.showerror(
                "エラー",
                "🤖 AUTOPOST モード では手動投稿操作は禁止されています。\n\n"
                "投稿はすべて自動制御されます。\n"
                "手動投稿を実行するには、settings.env で APP_MODE を\n"
                "'selfpost' に変更して、アプリを再起動してください。",
            )
            return

        if self.operation_mode == OperationMode.COLLECT:
            messagebox.showerror(
                "エラー",
                "📦 COLLECT モード では投稿機能が無効化されています。\n\n"
                "投稿を実行するには、settings.env で APP_MODE を\n"
                "'selfpost' に変更して、アプリを再起動してください。",
            )
            return

        # 🔧 DRY_RUN モード時は自動的にドライランモードに切り替え
        if self.operation_mode == OperationMode.DRY_RUN:
            logger.info(
                "🧪 DRY_RUN モード：投稿操作を自動的にドライランモードで実行します"
            )
            self.dry_run_post()
            return

        if not self.plugin_manager:
            messagebox.showerror(
                "エラー",
                "プラグインマネージャが初期化されていません。再起動してください。",
            )
            return

        if not self.selected_rows:
            messagebox.showwarning(
                "警告",
                "投稿対象の動画がありません。\n\n☑️ をクリックして選択してください。",
            )
            return

        videos = self.db.get_all_videos()
        selected = [v for v in videos if v["video_id"] in self.selected_rows]

        if not selected:
            messagebox.showwarning(
                "警告",
                "投稿対象の動画がありません。\n\n選択して保存してから実行してください。",
            )
            return

        # 各動画について投稿設定ウィンドウを表示
        for video in selected:
            post_window = PostSettingsWindow(
                self.root,
                video,
                self.db,
                self.plugin_manager,
                self.bluesky_core,
                operation_mode=self.operation_mode,
            )
            self.root.wait_window(post_window.window)

    def show_stats(self):
        """統計情報を表示（拡張版：日別・配信元別統計）"""
        videos = self.db.get_all_videos()

        total = len(videos)
        posted = sum(1 for v in videos if v["posted_to_bluesky"])
        selected = sum(1 for v in videos if v["selected_for_post"])
        unposted = total - posted

        # v3.2.0: 配信元別集計
        youtube_count = sum(
            1 for v in videos if v.get("source", "youtube") == "youtube"
        )
        niconico_count = sum(1 for v in videos if v.get("source") == "niconico")

        # v3.2.0: 配信元別投稿状況
        youtube_posted = sum(
            1
            for v in videos
            if v.get("source", "youtube") == "youtube" and v["posted_to_bluesky"]
        )
        niconico_posted = sum(
            1
            for v in videos
            if v.get("source") == "niconico" and v["posted_to_bluesky"]
        )

        # v3.2.0: 日別集計（過去7日間）
        from datetime import timedelta, datetime as dt

        today = dt.now().date()
        daily_stats = {}

        for i in range(7):
            date = today - timedelta(days=i)
            daily_stats[date] = {"total": 0, "posted": 0}

        for video in videos:
            try:
                if video.get("published_at"):
                    pub_date = dt.fromisoformat(video["published_at"]).date()
                    if pub_date in daily_stats:
                        daily_stats[pub_date]["total"] += 1
                        if video["posted_to_bluesky"]:
                            daily_stats[pub_date]["posted"] += 1
            except:
                pass

        stats = f"""
📊 統計情報（v3.2.0拡張版）
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

【 全体統計 】
総動画数:     {total}
投稿済み:     {posted} ({int(posted*100/total) if total > 0 else 0}%)
投稿予定:     {selected}
未処理:       {unposted}

【 配信元別統計 】
YouTube:      {youtube_count} 件 (投稿済み: {youtube_posted})
ニコニコ:     {niconico_count} 件 (投稿済み: {niconico_posted})

【 過去7日間の投稿状況 】
"""
        for i in range(7):
            date = today - timedelta(days=i)
            day_stats = daily_stats.get(date, {"total": 0, "posted": 0})
            date_str = (
                date.strftime("%m/%d（%a）")
                .replace("Mon", "月")
                .replace("Tue", "火")
                .replace("Wed", "水")
                .replace("Thu", "木")
                .replace("Fri", "金")
                .replace("Sat", "土")
                .replace("Sun", "日")
            )
            stats += f"  {date_str}: 全 {day_stats['total']} 件 | 投稿済み {day_stats['posted']} 件\n"

        stats += """
📌 操作方法
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
1. 「☑️」をクリック → 投稿対象を選択
2. 「投稿予定/投稿日時」をダブルクリック → 投稿日時を設定
3. 「💾 選択を保存」 → DB に反映
4. 「🧪 投稿テスト」 → テスト実行
5. 「📤 投稿設定」 → 投稿設定

⚠️ 注意
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
投稿済みフラグに関わらず投稿できます。
重複投稿にご注意ください。
        """
        messagebox.showinfo("統計情報", stats)

    def show_app_settings(self):
        """統合設定ウィンドウを表示"""
        UnifiedSettingsWindow(self.root, db=self.db)

    def batch_schedule(self):
        """複数動画の一括スケジュール設定（★ Phase 2 新機能）"""
        if not self.selected_rows:
            messagebox.showwarning("警告", "動画を選択してください")
            return

        selected_ids = list(self.selected_rows)
        logger.info(f"📅 一括スケジュール開始: {len(selected_ids)} 件")

        # ダイアログを開く
        dialog = BatchScheduleDialog(
            self.root, selected_ids, self.db, self.schedule_mgr
        )
        self.root.wait_window(dialog)

        # ダイアログクローズ後に表示を更新
        self.refresh_data()

    def show_schedule_view(self):
        """投稿予定一覧を確認・管理（★ Phase 2 新機能）"""
        logger.info("📅 投稿予定一覧を表示します")

        # 別ウィンドウで投稿予定タブを開く
        schedule_window = tk.Toplevel(self.root)
        schedule_window.title("📅 投稿スケジュール管理")
        schedule_window.geometry("900x600")

        tab = ScheduleViewTab(schedule_window, self.db, self.schedule_mgr)
        tab.get_frame().pack(fill=tk.BOTH, expand=True)

        self.root.wait_window(schedule_window)

    def open_backup_dialog(self):
        """バックアップ・復元ダイアログを表示"""
        backup_win = tk.Toplevel(self.root)
        backup_win.title("バックアップ・復元 (v3.2.0)")
        backup_win.geometry("400x300")

        ttk.Label(backup_win, text="バックアップと復元", font=("", 12, "bold")).pack(
            pady=10
        )

        bm = BackupManager()

        def do_backup():
            filename = filedialog.asksaveasfilename(
                defaultextension=".zip",
                filetypes=[("ZIP files", "*.zip")],
                initialfile=f"backup_{datetime.now().strftime('%Y%m%d_%H%M%S')}.zip",
                title="バックアップを保存",
            )
            if filename:
                success, msg = bm.create_backup(
                    filename, include_api_keys=True, include_passwords=True
                )
                if success:
                    messagebox.showinfo("成功", msg)
                else:
                    messagebox.showerror("失敗", msg)

        def do_restore():
            filename = filedialog.askopenfilename(
                defaultextension=".zip",
                filetypes=[("ZIP files", "*.zip")],
                title="バックアップファイルを選択",
            )
            if filename:
                if messagebox.askyesno(
                    "確認",
                    "復元を実行すると現在のデータは上書きされます。\n実行しますか？",
                ):
                    success, msg = bm.restore_backup(filename)
                    if success:
                        messagebox.showinfo("成功", msg)
                    else:
                        messagebox.showerror("失敗", msg)

        ttk.Button(backup_win, text="📥 バックアップ作成", command=do_backup).pack(
            pady=10, fill=tk.X, padx=20
        )
        ttk.Button(backup_win, text="📤 バックアップから復元", command=do_restore).pack(
            pady=10, fill=tk.X, padx=20
        )

        ttk.Separator(backup_win, orient=tk.HORIZONTAL).pack(
            fill=tk.X, padx=10, pady=10
        )
        ttk.Button(backup_win, text="閉じる", command=backup_win.destroy).pack(pady=5)

    def youtube_live_settings(self):
        """統合設定ウィンドウを Live タブをアクティブにして開く（v3.3.0+）"""
        UnifiedSettingsWindow(self.root, initial_tab="live", db=self.db)

    def show_plugins(self):
        """導入プラグイン情報を表示"""
        if not self.plugin_manager:
            messagebox.showinfo(
                "プラグイン情報", "プラグインマネージャーが初期化されていません。"
            )
            return

        loaded = self.plugin_manager.get_loaded_plugins()
        enabled = self.plugin_manager.get_enabled_plugins()

        if not loaded:
            messagebox.showinfo(
                "プラグイン情報", "導入されているプラグインがありません。"
            )
            return

        # プラグイン情報を整形（固定幅で見やすく）
        info_lines = ["🔧 導入プラグイン一覧"]
        info_lines.append("-" * 65)
        info_lines.append("")

        for plugin_name, plugin in loaded.items():
            is_enabled = plugin_name in enabled
            status = "✅有効" if is_enabled else "⚪無効"
            name = plugin.get_name()
            version = plugin.get_version()
            description = plugin.get_description()

            # 説明文が長い場合は折り返す
            desc_lines = []
            desc = description
            max_width = 58
            while len(desc) > max_width:
                # 最後のスペースで分割
                idx = desc.rfind(" ", 0, max_width)
                if idx == -1:
                    idx = max_width
                desc_lines.append(desc[:idx])
                desc = desc[idx:].lstrip()
            if desc:
                desc_lines.append(desc)

            info_lines.append(f"【{name}】 {status}")
            info_lines.append(f"  バージョン: v{version}")
            for i, desc_line in enumerate(desc_lines):
                if i == 0:
                    info_lines.append(f"  説明: {desc_line}")
                else:
                    info_lines.append(f"         {desc_line}")
            info_lines.append("")

        info_text = "\n".join(info_lines)

        # Toplevel ウィンドウで表示（スクロール機能付き）
        info_window = tk.Toplevel(self.root)
        info_window.title("プラグイン情報")
        info_window.geometry("700x500")

        # テキストウィジェット
        text_frame = ttk.Frame(info_window)
        text_frame.pack(fill=tk.BOTH, expand=True, padx=10, pady=10)

        text_widget = tk.Text(
            text_frame, wrap=tk.WORD, font=("Courier New", 9), height=25, width=80
        )
        scrollbar = ttk.Scrollbar(
            text_frame, orient=tk.VERTICAL, command=text_widget.yview
        )
        text_widget.configure(yscroll=scrollbar.set)

        text_widget.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)
        scrollbar.pack(side=tk.RIGHT, fill=tk.Y)

        text_widget.insert(tk.END, info_text)
        text_widget.config(state=tk.DISABLED)

        # 閉じるボタン
        button_frame = ttk.Frame(info_window)
        button_frame.pack(fill=tk.X, padx=10, pady=5)
        ttk.Button(button_frame, text="閉じる", command=info_window.destroy).pack(
            side=tk.RIGHT
        )

    def show_template_editor(self):
        """テンプレート編集ダイアログを表示（2階層構造）"""
        try:
            from template_utils import get_template_path

            # ========== メインダイアログ（配信元選択） ==========
            main_dialog = tk.Toplevel(self.root)
            main_dialog.title("テンプレート編集")
            main_dialog.geometry("400x300")
            main_dialog.resizable(False, False)
            main_dialog.transient(self.root)
            main_dialog.grab_set()

            ttk.Label(
                main_dialog,
                text="編集するテンプレートを選択してください",
                font=("Arial", 12, "bold"),
            ).pack(pady=15)

            # フレーム
            frame = ttk.Frame(main_dialog)
            frame.pack(fill=tk.BOTH, expand=True, padx=20, pady=10)

            def _open_template_editor(template_type):
                """テンプレートエディタを開く共通処理"""
                try:
                    # テンプレートパスを自動的に取得
                    template_path = get_template_path(template_type)

                    initial_text = ""
                    if template_path:
                        try:
                            from pathlib import Path

                            path_obj = Path(template_path)
                            if path_obj.exists():
                                with open(path_obj, "r", encoding="utf-8") as f:
                                    initial_text = f.read()
                                logger.info(
                                    f"✅ テンプレートを読み込みました: {template_path}"
                                )
                        except Exception as e:
                            logger.warning(f"⚠️ テンプレート読み込みエラー: {e}")

                    def on_save(text, ttype):
                        """テンプレート保存コールバック"""
                        try:
                            from pathlib import Path

                            # テンプレートパスを取得
                            save_path = get_template_path(ttype)
                            if save_path:
                                path_obj = Path(save_path)
                            else:
                                # デフォルト保存先を決定
                                path_obj = Path("templates") / f"{ttype}.txt"

                            path_obj.parent.mkdir(parents=True, exist_ok=True)
                            with open(path_obj, "w", encoding="utf-8") as f:
                                f.write(text)
                            logger.info(f"✅ テンプレート保存完了: {path_obj}")
                            messagebox.showinfo(
                                "成功", f"テンプレートを保存しました。\n{path_obj}"
                            )
                        except Exception as e:
                            logger.error(f"❌ テンプレート保存エラー: {e}")
                            messagebox.showerror(
                                "エラー", f"保存中にエラーが発生しました:\n{str(e)}"
                            )

                    # テンプレート編集ダイアログを開く（main_dialog ではなく root を parent とする）
                    editor = TemplateEditorDialog(
                        master=self.root,
                        template_type=template_type,
                        initial_text=initial_text,
                        on_save=on_save,
                    )
                    # ダイアログを閉じたら詳細ダイアログとメインダイアログも閉じる
                    main_dialog.wait_window(editor)
                    main_dialog.destroy()

                except Exception as e:
                    logger.error(f"❌ テンプレートエディタエラー: {e}")
                    messagebox.showerror(
                        "エラー", f"テンプレートエディタの起動に失敗しました:\n{str(e)}"
                    )

            def _show_youtube_selector():
                """YouTube テンプレート選択画面を表示"""
                main_dialog.withdraw()

                youtube_dialog = tk.Toplevel(self.root)
                youtube_dialog.title("YouTube テンプレート選択")
                youtube_dialog.geometry("400x350")
                youtube_dialog.resizable(False, False)
                youtube_dialog.transient(self.root)
                youtube_dialog.grab_set()

                ttk.Label(
                    youtube_dialog,
                    text="YouTube テンプレート種別を選択",
                    font=("Arial", 11, "bold"),
                ).pack(pady=10)

                # YouTube テンプレートタイプ
                youtube_types = [
                    ("🎬 新着動画", "youtube_new_video"),
                    ("🔴 配信開始", "youtube_online"),
                    ("📅 スケジュール枠", "youtube_schedule"),
                    ("⏹️ 配信終了", "youtube_offline"),
                    ("📹 アーカイブ", "youtube_archive"),
                ]

                youtube_frame = ttk.Frame(youtube_dialog)
                youtube_frame.pack(fill=tk.BOTH, expand=True, padx=15, pady=10)

                for display_name, template_type in youtube_types:

                    def on_youtube_select(tt=template_type):
                        """YouTube テンプレート選択後の処理"""
                        youtube_dialog.destroy()
                        _open_template_editor(tt)

                    btn = ttk.Button(
                        youtube_frame, text=display_name, command=on_youtube_select
                    )
                    btn.pack(fill=tk.X, pady=8)

                # 戻るボタン
                def go_back():
                    youtube_dialog.destroy()
                    main_dialog.deiconify()

                ttk.Button(youtube_dialog, text="← 戻る", command=go_back).pack(pady=10)

            def _show_twitch_selector():
                """Twitch テンプレート選択画面を表示（まだ無効）"""
                main_dialog.withdraw()

                twitch_dialog = tk.Toplevel(self.root)
                twitch_dialog.title("Twitch テンプレート選択")
                twitch_dialog.geometry("400x250")
                twitch_dialog.resizable(False, False)
                twitch_dialog.transient(self.root)
                twitch_dialog.grab_set()

                ttk.Label(
                    twitch_dialog,
                    text="Twitch テンプレート種別を選択",
                    font=("Arial", 11, "bold"),
                ).pack(pady=10)

                # Twitch テンプレートタイプ
                twitch_types = [
                    ("🔴 配信開始", "twitch_online"),
                    ("⏹️ 配信終了", "twitch_offline"),
                ]

                twitch_frame = ttk.Frame(twitch_dialog)
                twitch_frame.pack(fill=tk.BOTH, expand=True, padx=15, pady=10)

                for display_name, template_type in twitch_types:

                    def on_twitch_select(tt=template_type):
                        """Twitch テンプレート選択後の処理"""
                        twitch_dialog.destroy()
                        _open_template_editor(tt)

                    btn = ttk.Button(
                        twitch_frame, text=display_name, command=on_twitch_select
                    )
                    btn.pack(fill=tk.X, pady=8)

                # 戻るボタン
                def go_back():
                    twitch_dialog.destroy()
                    main_dialog.deiconify()

                ttk.Button(twitch_dialog, text="← 戻る", command=go_back).pack(pady=10)

            # メインボタン（配信元選択）
            button_configs = [
                ("▶️ YouTube", _show_youtube_selector, False),
                ("🎵 ニコニコ", lambda: _open_template_editor("nico_new_video"), False),
                ("🎮 Twitch", _show_twitch_selector, True),  # 無効状態
            ]

            for btn_text, btn_cmd, is_disabled in button_configs:
                btn = ttk.Button(
                    frame,
                    text=btn_text,
                    command=btn_cmd,
                    state=tk.DISABLED if is_disabled else tk.NORMAL,
                )
                btn.pack(fill=tk.X, pady=12)

            # キャンセルボタン
            ttk.Button(
                main_dialog, text="キャンセル", command=main_dialog.destroy
            ).pack(pady=10)

        except Exception as e:
            logger.error(f"❌ テンプレート選択ダイアログエラー: {e}")
            messagebox.showerror(
                "エラー", f"テンプレート選択ダイアログの起動に失敗しました:\n{str(e)}"
            )

    def backup_data(self):
        """データベース・テンプレート・設定をバックアップ"""
        try:
            from backup_manager import get_backup_manager

            # 保存先を選択
            backup_file = filedialog.asksaveasfilename(
                title="バックアップファイルを保存",
                defaultextension=".zip",
                filetypes=[("ZIP ファイル", "*.zip"), ("すべてのファイル", "*.*")],
                initialfile=f"streamnotify_backup_{datetime.now().strftime('%Y%m%d_%H%M%S')}.zip",
            )

            if not backup_file:
                return

            # バックアップ作成ダイアログ
            dialog = tk.Toplevel(self.root)
            dialog.title("バックアップオプション")
            dialog.geometry("400x300")
            dialog.resizable(False, False)

            ttk.Label(
                dialog, text="バックアップオプション", font=("Arial", 12, "bold")
            ).pack(pady=10)

            # API キー・パスワード包含オプション
            include_api_keys_var = tk.BooleanVar(value=False)
            include_passwords_var = tk.BooleanVar(value=False)
            include_images_var = tk.BooleanVar(value=False)

            ttk.Checkbutton(
                dialog,
                text="🔐 API キーを含める（セキュリティリスク）",
                variable=include_api_keys_var,
            ).pack(anchor=tk.W, padx=20, pady=5)

            ttk.Checkbutton(
                dialog,
                text="🔒 パスワードを含める（セキュリティリスク）",
                variable=include_passwords_var,
            ).pack(anchor=tk.W, padx=20, pady=5)

            ttk.Checkbutton(
                dialog, text="🖼️ 画像フォルダを含める", variable=include_images_var
            ).pack(anchor=tk.W, padx=20, pady=5)

            ttk.Label(
                dialog,
                text="⚠️ 機密情報を含めることはお勧めしません。\n\n推奨: 公開環境でのバックアップ共有時は\nAPI キー・パスワード除外オプションを推奨します。",
                justify=tk.LEFT,
                foreground="red",
            ).pack(padx=20, pady=10)

            def do_backup():
                backup_manager = get_backup_manager()
                success, msg = backup_manager.create_backup(
                    backup_file,
                    include_api_keys=include_api_keys_var.get(),
                    include_passwords=include_passwords_var.get(),
                    include_images=include_images_var.get(),
                )

                if success:
                    logger.info(f"✅ バックアップ作成完了: {backup_file}")
                    messagebox.showinfo("バックアップ完了", msg)
                else:
                    logger.error(f"❌ バックアップ作成失敗: {msg}")
                    messagebox.showerror("バックアップ失敗", msg)

            # ボタン
            button_frame = ttk.Frame(dialog)
            button_frame.pack(fill=tk.X, padx=20, pady=10)

            ttk.Button(
                button_frame, text="✅ バックアップ作成", command=do_backup
            ).pack(side=tk.LEFT, padx=5)
            ttk.Button(button_frame, text="キャンセル", command=dialog.destroy).pack(
                side=tk.LEFT, padx=5
            )

        except ImportError:
            logger.error("❌ backup_manager モジュールが見つかりません")
            messagebox.showerror("エラー", "バックアップマネージャーが見つかりません")
        except Exception as e:
            logger.error(f"❌ バックアップ処理エラー: {e}")
            messagebox.showerror("エラー", f"バックアップ処理に失敗しました:\n{e}")

    def restore_data(self):
        """バックアップから復元"""
        try:
            from backup_manager import get_backup_manager

            # 復元ファイルを選択
            backup_file = filedialog.askopenfilename(
                title="バックアップファイルを選択",
                filetypes=[("ZIP ファイル", "*.zip"), ("すべてのファイル", "*.*")],
            )

            if not backup_file:
                return

            # 確認ダイアログ
            result = messagebox.askyesno(
                "復元確認",
                f"このバックアップから復元しますか？\n\n{backup_file}\n\n⚠️ 現在のデータは上書きされます。\n既存データは自動的にバックアップされます。",
            )

            if not result:
                return

            # 復元実行
            backup_manager = get_backup_manager()
            success, msg = backup_manager.restore_backup(backup_file)

            if success:
                logger.info(f"✅ 復元完了: {backup_file}")
                messagebox.showinfo("復元完了", msg)
                # 復元後はアプリケーション再起動が必要なため、GUI を再読込
                self.refresh_data()
            else:
                logger.error(f"❌ 復元失敗: {msg}")
                messagebox.showerror("復元失敗", msg)

        except ImportError:
            logger.error("❌ backup_manager モジュールが見つかりません")
            messagebox.showerror("エラー", "バックアップマネージャーが見つかりません")
        except Exception as e:
            logger.error(f"❌ 復元処理エラー: {e}")
            messagebox.showerror("エラー", f"復元処理に失敗しました:\n{e}")

    def validate_datetime(self, date_string):
        """日時形式をバリデーション"""
        try:
            datetime.fromisoformat(date_string)
            return True
        except ValueError:
            return False

    def delete_selected(self):
        """ツールバーから選択した動画をDBから削除"""
        if not self.selected_rows:
            messagebox.showwarning(
                "警告",
                "削除対象の動画がありません。\n\n☑️ をクリックして選択してください。",
            )
            return

        videos = self.db.get_all_videos()
        selected = [v for v in videos if v["video_id"] in self.selected_rows]

        if not selected:
            messagebox.showwarning("警告", "削除対象の動画がありません。")
            return

        # 確認ダイアログ
        msg = f"""
🗑️ 削除確認

以下の {len(selected)} 件の動画をDBから完全削除します：

"""
        for v in selected[:5]:
            msg += f"  × {v['title'][:50]}...\n"

        if len(selected) > 5:
            msg += f"  ... ほか {len(selected) - 5} 件\n"

        msg += """
⚠️ 関連する画像ファイルも削除されます
この操作は取り消せません。
本当に削除してもよろしいですか？
        """

        if not messagebox.askyesno("確認", msg, icon=messagebox.WARNING):
            logger.info(f"❌ 削除操作をキャンセルしました（{len(selected)}件選択中）")
            return

        # 削除実行
        logger.info(f"🗑️ {len(selected)} 件の動画削除を開始します")
        result = self.db.delete_videos_batch([v["video_id"] for v in selected])
        deleted_count = result.get("deleted_count", 0)
        deleted_videos = result.get("deleted_videos", [])

        if deleted_count > 0:
            # 画像ファイルも削除
            images_deleted = 0
            for del_video in deleted_videos:
                if del_video.get("image_filename"):
                    try:
                        site = self._normalize_site_dir(
                            del_video.get("source", "YouTube")
                        )
                        if self.image_manager.delete_images_by_video_id(
                            site, del_video["image_filename"]
                        ):
                            images_deleted += 1
                    except Exception as e:
                        logger.warning(
                            f"⚠️ 画像削除に失敗: {del_video['video_id']} - {e}"
                        )

            logger.info(
                f"✅ {deleted_count} 件の動画を削除しました（画像ファイル {images_deleted} 件も削除）"
            )
            self.selected_rows.clear()
            self.refresh_data()
            messagebox.showinfo(
                "成功",
                f"{deleted_count} 件の動画を削除しました。\n（画像ファイル {images_deleted} 件も削除）",
            )
        else:
            logger.error(f"❌ 動画の削除に失敗しました（{len(selected)}件リクエスト）")
            messagebox.showerror("エラー", "動画の削除に失敗しました。")

    def context_delete(self):
        """右クリックメニューから動画を削除"""
        if not hasattr(self, "current_context_item"):
            messagebox.showerror("エラー", "削除対象が見つかりません。")
            return

        item_id = self.current_context_item
        videos = self.db.get_all_videos()
        video = next((v for v in videos if v["video_id"] == item_id), None)

        if not video:
            messagebox.showerror("エラー", "動画情報が見つかりません。")
            return

        # 確認ダイアログ
        msg = f"""
🗑️ 削除確認

以下の動画をDBから完全削除します：

タイトル: {video['title'][:60]}...
動画ID: {item_id}

⚠️ 関連する画像ファイルも削除されます
この操作は取り消せません。
削除してもよろしいですか？
        """

        if not messagebox.askyesno("確認", msg, icon=messagebox.WARNING):
            logger.info(f"❌ 削除操作をキャンセルしました: {item_id}")
            return

        # 削除実行
        logger.info(f"🗑️ 動画削除を実行: {item_id} ({video['title'][:40]}...)")
        result = self.db.delete_video(item_id)

        if result.get("success"):
            # 画像ファイルも削除
            images_deleted = False
            if result.get("image_filename"):
                try:
                    site = self._normalize_site_dir(result.get("source", "YouTube"))
                    if self.image_manager.delete_images_by_video_id(
                        site, result["image_filename"]
                    ):
                        images_deleted = True
                except Exception as e:
                    logger.warning(f"⚠️ 画像削除に失敗: {item_id} - {e}")

            logger.info(f"✅ 動画を削除しました: {item_id}（右クリックメニュー操作）")
            self.selected_rows.discard(item_id)
            self.refresh_data()

            if images_deleted:
                messagebox.showinfo(
                    "成功", f"動画を削除しました。\n{item_id}\n（画像ファイルも削除）"
                )
            else:
                messagebox.showinfo("成功", f"動画を削除しました。\n{item_id}")
        else:
            logger.error(f"❌ 動画削除に失敗: {item_id}")
            messagebox.showerror("エラー", "動画の削除に失敗しました。")

    def add_video_dialog(self):
        """動画追加ダイアログを表示"""
        dialog = tk.Toplevel(self.root)
        dialog.title("➕ 動画を追加")
        dialog.geometry("500x380")
        dialog.transient(self.root)
        dialog.grab_set()

        # === タイトル ===
        ttk.Label(dialog, text="動画を手動で追加", font=("", 12, "bold")).pack(
            padx=10, pady=10
        )

        # === プラットフォーム選択 ===
        ttk.Label(dialog, text="プラットフォーム:").pack(
            padx=10, pady=(10, 5), anchor=tk.W
        )
        platform_var = tk.StringVar(value="YouTube")
        platform_frame = ttk.Frame(dialog)
        platform_frame.pack(padx=10, pady=5, fill=tk.X)

        ttk.Radiobutton(
            platform_frame, text="YouTube", variable=platform_var, value="YouTube"
        ).pack(side=tk.LEFT, padx=5)

        # --- ニコニコプラグインのチェックとボタン生成 ---
        niconico_plugin_enabled = False
        if self.plugin_manager:
            niconico_plugin = self.plugin_manager.get_plugin("niconico_plugin")
            if niconico_plugin and niconico_plugin.is_available():
                niconico_plugin_enabled = True

        niconico_radio_button = ttk.Radiobutton(
            platform_frame, text="ニコニコ", variable=platform_var, value="Niconico"
        )
        if not niconico_plugin_enabled:
            niconico_radio_button.config(state=tk.DISABLED)
            CreateToolTip(
                niconico_radio_button,
                "ニコニコプラグインが導入されていないため無効です",
            )
        niconico_radio_button.pack(side=tk.LEFT, padx=5)

        # === 説明 ===
        description_frame = ttk.Frame(dialog)
        description_frame.pack(padx=10, pady=5, fill=tk.BOTH, expand=True)

        def update_description(*args):
            for widget in description_frame.winfo_children():
                widget.destroy()

            if platform_var.get() == "YouTube":
                desc_text = "YouTubeの動画URLまたは動画IDを入力してください。\n\n例：dQw4w9WgXcQ\nまたは：https://www.youtube.com/watch?v=dQw4w9WgXcQ"
            else:
                desc_text = "ニコニコの動画URLまたは動画IDを入力してください。\n\n例：sm123456789\nまたは：https://www.nicovideo.jp/watch/sm123456789"

            desc = ttk.Label(
                description_frame, text=desc_text, justify=tk.LEFT, foreground="gray"
            )
            desc.pack(padx=5, pady=5, anchor=tk.W)

        platform_var.trace("w", update_description)
        update_description()

        # === 入力フィールド ===
        ttk.Label(dialog, text="動画URL / 動画ID:").pack(
            padx=10, pady=(10, 5), anchor=tk.W
        )
        video_id_entry = ttk.Entry(dialog, width=50)
        video_id_entry.pack(padx=10, pady=5, fill=tk.X)
        video_id_entry.focus()

        # === ボタンフレーム ===
        button_frame = ttk.Frame(dialog)
        button_frame.pack(padx=10, pady=15, fill=tk.X)

        def on_add():
            """追加処理"""
            input_value = video_id_entry.get().strip()
            if not input_value:
                messagebox.showwarning("警告", "動画IDまたは URLを入力してください")
                return

            dialog.destroy()
            self._add_video_from_id(input_value, platform_var.get())

        ttk.Button(button_frame, text="✅ 追加", command=on_add).pack(
            side=tk.LEFT, padx=5
        )
        ttk.Button(button_frame, text="✖️ キャンセル", command=dialog.destroy).pack(
            side=tk.LEFT, padx=5
        )

    def _add_video_from_id(self, input_value: str, platform: str = "YouTube"):
        """動画IDから動画を追加"""
        logger.info(f"🔍 {platform} 動画追加を開始: {input_value}")

        if platform == "YouTube":
            self._add_youtube_video(input_value)
        elif platform == "Niconico":
            self._add_niconico_video(input_value)
        else:
            messagebox.showerror(
                "エラー", f"対応していないプラットフォーム: {platform}"
            )

    def _add_youtube_video(self, input_value: str):
        """YouTube 動画を追加"""
        # 動画ID を抽出
        video_id = self._extract_video_id(input_value)
        if not video_id:
            messagebox.showerror(
                "エラー", "有効な YouTube 動画IDが見つかりませんでした"
            )
            logger.error(f"❌ YouTube 動画ID抽出失敗: {input_value}")
            return

        logger.info(f"✅ 抽出された YouTube 動画ID: {video_id}")

        # YouTube API プラグインから動画情報を取得
        if not self.plugin_manager:
            messagebox.showerror(
                "エラー", "プラグインマネージャーが初期化されていません"
            )
            return

        # YouTube API プラグインを取得
        youtube_api_plugin = None
        try:
            plugins = self.plugin_manager.get_enabled_plugins()
            for plugin_name, plugin_instance in plugins.items():
                if "youtube_api" in plugin_name.lower():
                    youtube_api_plugin = plugin_instance
                    break

            if not youtube_api_plugin:
                logger.warning("⚠️ YouTube API プラグインが有効化されていません")
                messagebox.showwarning(
                    "警告",
                    "YouTube API プラグインが有効化されていません\n\n手動で動画情報を入力してください",
                )
                self._add_video_manual(video_id)
                return

            # 動画情報を取得
            logger.info(f"🌐 YouTube API から動画情報を取得: {video_id}")
            video_details = youtube_api_plugin._fetch_video_detail(video_id)

            if not video_details:
                logger.warning(f"⚠️ YouTube API での取得に失敗しました: {video_id}")
                messagebox.showinfo(
                    "情報",
                    "YouTube API での取得に失敗しました\n\n手動で動画情報を入力してください",
                )
                self._add_video_manual(video_id)
                return

            # 動画情報から video dict を構築
            snippet = video_details.get("snippet", {})

            # ★ ライブ判定を実行（API データから）
            from plugins.youtube.youtube_api_plugin import YouTubeAPIPlugin

            api_plugin = YouTubeAPIPlugin()
            content_type, live_status, is_premiere = api_plugin._classify_video_core(
                video_details
            )

            # サムネイル URL を取得
            thumbnail_url = snippet.get("thumbnails", {}).get("high", {}).get("url", "")

            # 公開日時を取得・変換
            published_at = snippet.get("publishedAt", datetime.now().isoformat())
            try:
                dt = datetime.fromisoformat(published_at.replace("Z", "+00:00"))
                published_at = dt.strftime("%Y-%m-%d %H:%M:%S")
            except:
                pass

            video_dict = {
                "video_id": video_id,
                "title": snippet.get("title", "【新着動画】"),
                "video_url": f"https://www.youtube.com/watch?v={video_id}",
                "published_at": published_at,
                "channel_name": snippet.get("channelTitle", ""),
                "thumbnail_url": thumbnail_url,
                "content_type": content_type,
                "live_status": live_status,
                "is_premiere": is_premiere,
                "source": "youtube",
            }

            # ★ 直接 DB に保存（プラグインではなく）
            # ★ skip_dedup=True: 手動追加なので重複排除をスキップして強制挿入
            success = self.db.insert_video(
                video_id=video_dict["video_id"],
                title=video_dict["title"],
                video_url=video_dict["video_url"],
                published_at=video_dict["published_at"],
                channel_name=video_dict["channel_name"],
                thumbnail_url=thumbnail_url,
                content_type=content_type,
                live_status=live_status,
                is_premiere=is_premiere,
                source=video_dict["source"],
                skip_dedup=True,  # ★ 手動追加は重複排除をスキップ
            )

            if success:
                # ★ 手動追加後にサムネイルをダウンロード
                if thumbnail_url and self.image_manager:
                    try:
                        logger.info(
                            f"📥 手動追加後、サムネイル画像をダウンロード中: {video_id}"
                        )
                        image_filename = self.image_manager.download_and_save_thumbnail(
                            thumbnail_url=thumbnail_url,
                            site="YouTube",
                            video_id=video_id,
                            mode="autopost",
                        )
                        # ★ ダウンロード成功時、DB に画像情報を登録
                        if image_filename:
                            self.db.update_image_info(
                                video_id=video_id,
                                image_mode="autopost",
                                image_filename=image_filename,
                            )
                            logger.info(
                                f"✅ DB に画像情報を登録しました: {video_id} → {image_filename}"
                            )
                    except Exception as e:
                        logger.warning(f"⚠️ サムネイルダウンロード失敗（継続）: {e}")

                logger.info(
                    f"✅ YouTube 動画を追加しました: {video_id} (content_type={content_type}, live_status={live_status})"
                )
                messagebox.showinfo(
                    "成功", f"YouTube 動画を追加しました:\n{video_dict['title']}"
                )
                self.refresh_data()
            else:
                logger.warning(f"⚠️ DB 保存に失敗しました: {video_id}")
                messagebox.showerror("エラー", "動画情報の保存に失敗しました")

        except Exception as e:
            logger.error(f"❌ YouTube 動画追加エラー: {e}", exc_info=True)
            messagebox.showerror("エラー", f"エラーが発生しました:\n{e}")

    def _add_niconico_video(self, input_value: str):
        """ニコニコ動画を追加"""
        # ニコニコ動画ID を抽出
        video_id = self._extract_niconico_video_id(input_value)
        if not video_id:
            messagebox.showerror(
                "エラー",
                "有効なニコニコ動画IDが見つかりませんでした\n(例: sm123456789)",
            )
            logger.error(f"❌ ニコニコ 動画ID抽出失敗: {input_value}")
            return

        logger.info(f"✅ 抽出されたニコニコ動画ID: {video_id}")

        # ニコニコプラグインを取得
        if not self.plugin_manager:
            messagebox.showerror(
                "エラー", "プラグインマネージャーが初期化されていません"
            )
            return

        niconico_plugin = None
        try:
            plugins = self.plugin_manager.get_enabled_plugins()
            for plugin_name, plugin_instance in plugins.items():
                if "niconico" in plugin_name.lower():
                    niconico_plugin = plugin_instance
                    break

            if not niconico_plugin:
                logger.warning("⚠️ ニコニコプラグインが有効化されていません")
                messagebox.showwarning(
                    "警告",
                    "ニコニコプラグインが有効化されていません\n\nニコニコユーザーIDを設定.envで設定してください",
                )
                return

            # 動画情報を取得
            logger.info(f"🌐 ニコニコ API から動画情報を取得: {video_id}")

            # ニコニコプラグインから動画情報を取得
            video_details = niconico_plugin.get_video_details(video_id)

            if not video_details:
                logger.warning(f"⚠️ ニコニコ API での取得に失敗しました: {video_id}")
                messagebox.showerror(
                    "エラー", f"ニコニコ動画情報の取得に失敗しました:\n{video_id}"
                )
                return

            # 動画情報を構築
            video_id_clean = (
                video_id
                if video_id.startswith("sm") or video_id.startswith("so")
                else f"sm{video_id}"
            )

            published_at = video_details.get(
                "published_at", datetime.now().strftime("%Y-%m-%d %H:%M:%S")
            )

            video_dict = {
                "video_id": video_id_clean,
                "title": video_details.get("title", f"【ニコニコ】{video_id_clean}"),
                "video_url": f"https://www.nicovideo.jp/watch/{video_id_clean}",
                "published_at": published_at,
                "channel_name": video_details.get(
                    "channel_name", video_details.get("user_name", "")
                ),
                "thumbnail_url": video_details.get("thumbnail_url", ""),
                "source": "niconico",
            }

            # DB に保存
            success = self.db.insert_video(
                video_id=video_dict["video_id"],
                title=video_dict["title"],
                video_url=video_dict["video_url"],
                published_at=video_dict["published_at"],
                channel_name=video_dict["channel_name"],
                thumbnail_url=video_dict.get("thumbnail_url", ""),
                source=video_dict["source"],
                skip_dedup=True,  # ★ 手動追加は重複排除をスキップ
            )

            if success:
                # ★ 手動追加後にサムネイルをダウンロード
                if video_dict.get("thumbnail_url") and self.image_manager:
                    try:
                        logger.info(
                            f"📥 手動追加後、サムネイル画像をダウンロード中: {video_id_clean}"
                        )
                        image_filename = self.image_manager.download_and_save_thumbnail(
                            thumbnail_url=video_dict["thumbnail_url"],
                            site="Niconico",
                            video_id=video_id_clean,
                            mode="autopost",
                        )
                        # ★ ダウンロード成功時、DB に画像情報を登録
                        if image_filename:
                            self.db.update_image_info(
                                video_id=video_id_clean,
                                image_mode="autopost",
                                image_filename=image_filename,
                            )
                            logger.info(
                                f"✅ DB に画像情報を登録しました: {video_id_clean} → {image_filename}"
                            )
                    except Exception as e:
                        logger.warning(f"⚠️ サムネイルダウンロード失敗（継続）: {e}")

                logger.info(f"✅ ニコニコ動画を追加しました: {video_id_clean}")
                messagebox.showinfo(
                    "成功", f"ニコニコ動画を追加しました:\n{video_dict['title']}"
                )
                self.refresh_data()
            else:
                logger.warning(f"⚠️ DB 保存に失敗しました: {video_id_clean}")
                messagebox.showerror("エラー", "動画情報の保存に失敗しました")

        except Exception as e:
            logger.error(f"❌ ニコニコ動画追加エラー: {e}", exc_info=True)
            messagebox.showerror("エラー", f"エラーが発生しました:\n{e}")

    def _video_exists(self, video_id: str) -> bool:
        """動画がDBに存在するか確認"""
        try:
            all_videos = self.db.get_all_videos()
            for video in all_videos:
                if video.get("video_id") == video_id:
                    return True
            return False
        except Exception:
            return False

    def _extract_video_id(self, input_value: str) -> str:
        """URLまたは ID から YouTube 動画IDを抽出"""
        input_value = input_value.strip()

        # パターンマッチング（複数の URL 形式に対応）
        import re

        # youtube.com/watch?v=XXXXX
        match = re.search(r"watch\?v=([a-zA-Z0-9_-]{11})", input_value)
        if match:
            return match.group(1)

        # youtu.be/XXXXX
        match = re.search(r"youtu\.be/([a-zA-Z0-9_-]{11})", input_value)
        if match:
            return match.group(1)

        # www.youtube.com/embed/XXXXX
        match = re.search(r"/embed/([a-zA-Z0-9_-]{11})", input_value)
        if match:
            return match.group(1)

        # 11文字の動画ID の場合はそのまま
        if len(input_value) == 11 and re.match(r"^[a-zA-Z0-9_-]{11}$", input_value):
            return input_value

        return None

    def _extract_niconico_video_id(self, input_value: str) -> str:
        """URLまたは ID からニコニコ動画IDを抽出"""
        input_value = input_value.strip()

        # パターンマッチング
        import re

        # nicovideo.jp/watch/sm123456789 または so123456789
        match = re.search(r"watch/((?:sm|so)\d+)", input_value)
        if match:
            return match.group(1)

        # sm123456789 または so123456789 の直接入力
        if re.match(r"^(?:sm|so)\d+$", input_value):
            return input_value

        return None

    def _add_video_manual(self, video_id: str):
        """手動で動画情報を入力するダイアログを表示"""
        dialog = tk.Toplevel(self.root)
        dialog.title("✏️ 動画情報を手動入力")
        dialog.geometry("600x500")
        dialog.transient(self.root)
        dialog.grab_set()

        # === 動画情報入力フォーム ===
        header_frame = ttk.Frame(dialog)
        header_frame.pack(padx=10, pady=10, fill=tk.X)
        ttk.Label(
            header_frame, text="動画情報を入力してください", font=("", 12, "bold")
        ).pack(side=tk.LEFT)

        # API から自動取得ボタン
        def on_fetch_from_api():
            """API からメタデータを取得して自動入力"""
            try:
                from plugins.youtube.youtube_api_plugin import YouTubeAPIPlugin

                api_plugin = YouTubeAPIPlugin()
                if not api_plugin.is_available():
                    messagebox.showwarning(
                        "警告", "YouTube API が利用不可です。手動入力してください。"
                    )
                    return

                # API から詳細取得
                details = api_plugin._fetch_video_detail(video_id)
                if not details:
                    messagebox.showerror(
                        "エラー", f"API から動画詳細を取得できませんでした: {video_id}"
                    )
                    return

                # 詳細から必要情報を抽出
                snippet = details.get("snippet", {})
                title = snippet.get("title", "")
                channel = snippet.get("channelTitle", "")
                published_at = snippet.get("publishedAt", "")

                # ISO 8601 → YYYY-MM-DD HH:MM:SS に変換
                try:
                    from datetime import datetime

                    if published_at:
                        dt = datetime.fromisoformat(published_at.replace("Z", "+00:00"))
                        published_at = dt.strftime("%Y-%m-%d %H:%M:%S")
                except:
                    pass

                # ライブ判定
                from plugins.youtube.youtube_api_plugin import YouTubeAPIPlugin

                api_plugin = YouTubeAPIPlugin()
                content_type, live_status, is_premiere = (
                    api_plugin._classify_video_core(details)
                )

                # サムネイル URL
                thumbnail_url = (
                    snippet.get("thumbnails", {}).get("high", {}).get("url", "")
                )

                # UI に設定
                title_entry.delete(0, tk.END)
                title_entry.insert(0, title)

                channel_entry.delete(0, tk.END)
                channel_entry.insert(0, channel)

                published_entry.delete(0, tk.END)
                published_entry.insert(0, published_at)

                content_type_var.set(content_type)

                live_status_var.set(live_status or "none")

                thumbnail_url_entry.delete(0, tk.END)
                thumbnail_url_entry.insert(0, thumbnail_url)

                is_premiere_var.set(1 if is_premiere else 0)

                logger.info(
                    f"✅ API からメタデータを取得しました: {video_id} (content_type={content_type}, live_status={live_status})"
                )
                messagebox.showinfo("成功", "✅ API からメタデータを取得しました")

            except Exception as e:
                logger.error(f"❌ API 取得エラー: {e}", exc_info=True)
                messagebox.showerror("エラー", f"API 取得に失敗しました:\n{str(e)}")

        ttk.Button(
            header_frame, text="🔍 API から自動取得", command=on_fetch_from_api
        ).pack(side=tk.RIGHT, padx=5)

        # フォーム
        form_frame = ttk.Frame(dialog)
        form_frame.pack(padx=10, pady=10, fill=tk.BOTH, expand=True)

        # 動画ID（読み取り専用）
        ttk.Label(form_frame, text="動画ID:").grid(row=0, column=0, sticky=tk.W, pady=5)
        id_entry = ttk.Entry(form_frame, width=50)
        id_entry.grid(row=0, column=1, sticky=tk.EW, padx=5, pady=5)
        id_entry.insert(0, video_id)
        id_entry.config(state=tk.DISABLED)

        # タイトル
        ttk.Label(form_frame, text="タイトル*:").grid(
            row=1, column=0, sticky=tk.W, pady=5
        )
        title_entry = ttk.Entry(form_frame, width=50)
        title_entry.grid(row=1, column=1, sticky=tk.EW, padx=5, pady=5)

        # チャンネル名
        ttk.Label(form_frame, text="チャンネル名:").grid(
            row=2, column=0, sticky=tk.W, pady=5
        )
        channel_entry = ttk.Entry(form_frame, width=50)
        channel_entry.grid(row=2, column=1, sticky=tk.EW, padx=5, pady=5)

        # 公開日時
        ttk.Label(form_frame, text="公開日時*:").grid(
            row=3, column=0, sticky=tk.W, pady=5
        )
        published_entry = ttk.Entry(form_frame, width=50)
        published_entry.grid(row=3, column=1, sticky=tk.EW, padx=5, pady=5)
        published_entry.insert(0, datetime.now().strftime("%Y-%m-%d %H:%M:%S"))

        # コンテンツタイプ（5カテゴリ対応）
        ttk.Label(form_frame, text="コンテンツ種別:").grid(
            row=4, column=0, sticky=tk.W, pady=5
        )
        content_type_var = tk.StringVar(value="video")
        content_combo = ttk.Combobox(
            form_frame, textvariable=content_type_var, state="readonly", width=47
        )
        content_combo["values"] = ("video", "archive", "schedule", "live", "completed")
        content_combo.grid(row=4, column=1, sticky=tk.EW, padx=5, pady=5)

        # ライブ配信状態
        ttk.Label(form_frame, text="配信状態:").grid(
            row=5, column=0, sticky=tk.W, pady=5
        )
        live_status_var = tk.StringVar(value="none")
        live_status_combo = ttk.Combobox(
            form_frame, textvariable=live_status_var, state="readonly", width=47
        )
        live_status_combo["values"] = ("none", "upcoming", "live", "completed")
        live_status_combo.grid(row=5, column=1, sticky=tk.EW, padx=5, pady=5)

        # サムネイル URL
        ttk.Label(form_frame, text="サムネイルURL:").grid(
            row=6, column=0, sticky=tk.W, pady=5
        )
        thumbnail_url_entry = ttk.Entry(form_frame, width=50)
        thumbnail_url_entry.grid(row=6, column=1, sticky=tk.EW, padx=5, pady=5)

        # プレミア配信フラグ
        ttk.Label(form_frame, text="プレミア配信:").grid(
            row=7, column=0, sticky=tk.W, pady=5
        )
        is_premiere_var = tk.IntVar(value=0)
        ttk.Checkbutton(form_frame, variable=is_premiere_var).grid(
            row=7, column=1, sticky=tk.W, padx=5, pady=5
        )

        form_frame.columnconfigure(1, weight=1)

        # === ボタン ===
        button_frame = ttk.Frame(dialog)
        button_frame.pack(padx=10, pady=10, fill=tk.X)

        def on_save():
            """保存処理"""
            title = title_entry.get().strip()
            channel = channel_entry.get().strip()
            published_at = published_entry.get().strip()
            content_type = content_type_var.get()
            live_status = live_status_var.get()
            thumbnail_url = thumbnail_url_entry.get().strip()
            is_premiere = bool(is_premiere_var.get())

            if not title or not published_at:
                messagebox.showwarning("警告", "タイトルと公開日時は必須です")
                return

            # DB に保存
            try:
                video_url = f"https://www.youtube.com/watch?v={video_id}"
                success = self.db.insert_video(
                    video_id=video_id,
                    title=title,
                    video_url=video_url,
                    published_at=published_at,
                    channel_name=channel,
                    thumbnail_url=thumbnail_url,
                    content_type=content_type,
                    live_status=live_status if live_status != "none" else None,
                    is_premiere=is_premiere,
                    source="youtube",
                    skip_dedup=True,  # ★ 手動追加は重複排除をスキップ
                )

                if success:
                    # ★ 手動追加後にサムネイルをダウンロード
                    if thumbnail_url and self.image_manager:
                        try:
                            logger.info(
                                f"📥 手動追加後、サムネイル画像をダウンロード中: {video_id}"
                            )
                            image_filename = (
                                self.image_manager.download_and_save_thumbnail(
                                    thumbnail_url=thumbnail_url,
                                    site="YouTube",
                                    video_id=video_id,
                                    mode="autopost",
                                )
                            )
                            # ★ ダウンロード成功時、DB に画像情報を登録
                            if image_filename:
                                self.db.update_image_info(
                                    video_id=video_id,
                                    image_mode="autopost",
                                    image_filename=image_filename,
                                )
                                logger.info(
                                    f"✅ DB に画像情報を登録しました: {video_id} → {image_filename}"
                                )
                        except Exception as e:
                            logger.warning(
                                f"⚠️ サムネイルダウンロード失敗（継続）: {e}"
                            )

                    logger.info(
                        f"✅ 動画を手動追加しました: {video_id} (content_type={content_type}, live_status={live_status})"
                    )
                    messagebox.showinfo(
                        "成功", f"✅ 動画を追加しました\n\n{title[:60]}..."
                    )
                    dialog.destroy()
                    self.refresh_data()
                else:
                    logger.warning(f"⚠️ 動画は既に存在します: {video_id}")
                    messagebox.showwarning("警告", f"この動画は既に登録されています")

            except Exception as e:
                logger.error(f"❌ 手動追加エラー: {e}", exc_info=True)
                messagebox.showerror("エラー", f"保存に失敗しました:\n{str(e)}")

        ttk.Button(button_frame, text="💾 保存", command=on_save).pack(
            side=tk.LEFT, padx=5
        )
        ttk.Button(button_frame, text="✖️ キャンセル", command=dialog.destroy).pack(
            side=tk.LEFT, padx=5
        )


class PostSettingsWindow:
    """投稿設定ウィンドウ - 動画の投稿設定を詳細に管理"""

    def __init__(
        self,
        parent,
        video,
        db,
        plugin_manager=None,
        bluesky_core=None,
        operation_mode=None,
        is_dry_run=False,
    ):
        """
        投稿設定ウィンドウを初期化

        Args:
            parent: 親ウィンドウ
            video: 選択されたビデオレコード
            db: Database インスタンス
            plugin_manager: PluginManager インスタンス
            bluesky_core: Bluesky コア機能インスタンス
            operation_mode: 動作モード（OperationMode）
            is_dry_run: dry_run メソッドから呼び出されたか
        """
        self.parent = parent
        self.video = video
        self.db = db
        self.plugin_manager = plugin_manager
        self.bluesky_core = bluesky_core
        self.operation_mode = operation_mode
        self.is_dry_run = is_dry_run  # dry_run_post() から呼ばれたフラグ
        self.result = None  # 確定時の設定結果

        # ウィンドウを作成
        self.window = tk.Toplevel(parent)
        self.window.title(f"📤 投稿設定 - {video['title'][:50]}...")
        self.window.geometry("700x620")
        self.window.resizable(False, False)

        self._build_ui()
        self.window.transient(parent)
        self.window.grab_set()

    def _build_ui(self):
        """UI を構築"""
        # === メインフレーム ===
        main_frame = ttk.Frame(self.window)
        main_frame.pack(fill=tk.X, expand=False, padx=10, pady=10, side=tk.TOP)

        # === 1. 動画情報 ===
        info_frame = ttk.LabelFrame(main_frame, text="📹 動画情報", padding=10)
        info_frame.pack(fill=tk.X, pady=(0, 10))

        ttk.Label(info_frame, text="タイトル:", font=("", 10, "bold")).grid(
            row=0, column=0, sticky=tk.W
        )
        title_label = ttk.Label(
            info_frame, text=self.video["title"], foreground="darkblue", wraplength=550
        )
        title_label.grid(row=0, column=1, sticky=tk.W, columnspan=2)

        ttk.Label(info_frame, text="ソース:", font=("", 10, "bold")).grid(
            row=1, column=0, sticky=tk.W
        )
        source_text = self.video.get("source", "youtube").upper()
        ttk.Label(info_frame, text=source_text, foreground="darkgreen").grid(
            row=1, column=1, sticky=tk.W
        )

        ttk.Label(info_frame, text="公開日時:", font=("", 10, "bold")).grid(
            row=2, column=0, sticky=tk.W
        )
        ttk.Label(info_frame, text=self.video.get("published_at", "不明")).grid(
            row=2, column=1, sticky=tk.W
        )

        # === 2. 投稿実績と投稿予約を1列に統合 ===
        status_frame = ttk.LabelFrame(main_frame, text="📊 投稿状況", padding=10)
        status_frame.pack(fill=tk.X, pady=(0, 10))

        # 投稿実績
        posted_status = (
            "✅ 投稿済み" if self.video.get("posted_to_bluesky") else "❌ 未投稿"
        )
        posted_date = self.video.get("posted_at", "—")
        posted_info = f"投稿実績: {posted_status} ({posted_date})"
        ttk.Label(status_frame, text=posted_info, font=("", 10)).pack(
            anchor=tk.W, pady=(0, 5)
        )

        # 投稿予約
        scheduled_at = self.video.get("scheduled_at")
        if scheduled_at:
            schedule_text = f"投稿予約: 予約あり ({scheduled_at})"
            schedule_color = "darkgreen"
        else:
            schedule_text = f"投稿予約: 予約なし"
            schedule_color = "gray"

        ttk.Label(
            status_frame, text=schedule_text, foreground=schedule_color, font=("", 10)
        ).pack(anchor=tk.W)

        # === 3. DB 画像の設定 + プレビュー（左右配置） ===
        image_frame = ttk.LabelFrame(main_frame, text="🖼️ DB画像の設定", padding=10)
        image_frame.pack(fill=tk.X, pady=(0, 5))

        # 画像情報フレーム（左側）
        image_info_frame = ttk.Frame(image_frame)
        image_info_frame.pack(fill=tk.X, expand=True)

        image_filename = self.video.get("image_filename")
        if image_filename:
            image_text = f"✅ ファイル: {image_filename}"
            image_color = "darkblue"
        else:
            image_text = "❌ なし"
            image_color = "gray"

        ttk.Label(
            image_info_frame,
            text=image_text,
            foreground=image_color,
            font=("", 10, "bold"),
        ).pack(anchor=tk.W)

        # 画像情報詳細（左側）
        if image_filename:
            self._display_image_preview(image_info_frame, image_filename)

        # === 4. 投稿方法の選択 ===
        post_method_frame = ttk.LabelFrame(main_frame, text="📋 投稿方法", padding=10)
        post_method_frame.pack(fill=tk.X, pady=(0, 10))

        self.use_image_var = tk.BooleanVar(value=True if image_filename else False)

        # 画像がない場合は強制的に URLリンクカード
        if not image_filename:
            self.use_image_var.set(False)
            ttk.Radiobutton(
                post_method_frame,
                text="🔗 URLリンクカード（画像なし）",
                variable=self.use_image_var,
                value=False,
                state=tk.DISABLED,
            ).pack(anchor=tk.W, pady=5)
            ttk.Label(
                post_method_frame,
                text="⚠️ DB画像がないため、URLリンクカードのみ利用可能",
                foreground="orange",
            ).pack(anchor=tk.W, padx=20)
        else:
            ttk.Radiobutton(
                post_method_frame,
                text="🖼️ 画像を添付",
                variable=self.use_image_var,
                value=True,
            ).pack(anchor=tk.W, pady=5)
            ttk.Radiobutton(
                post_method_frame,
                text="🔗 URLリンクカード",
                variable=self.use_image_var,
                value=False,
            ).pack(anchor=tk.W, pady=5)

        # === 5. 小さい画像の加工設定 ===
        small_image_frame = ttk.LabelFrame(
            main_frame, text="🎨 小さい画像の加工", padding=10
        )
        small_image_frame.pack(fill=tk.X, pady=(0, 10))

        self.resize_small_var = tk.BooleanVar(value=True)
        ttk.Checkbutton(
            small_image_frame,
            text="小さい画像も自動加工する（リサイズ・圧縮）",
            variable=self.resize_small_var,
        ).pack(anchor=tk.W, pady=5)
        ttk.Label(
            small_image_frame,
            text="✓: すべての画像を加工 / ✗: 大きい画像のみ加工",
            foreground="gray",
            font=("", 9),
        ).pack(anchor=tk.W, padx=5)

        # === ボタンフレーム（常に下部に固定） ===
        button_frame = ttk.Frame(self.window)
        button_frame.pack(fill=tk.X, padx=10, pady=10, side=tk.BOTTOM)

        # 🔧 DRY_RUN モード または dry_run_post() から呼ばれた場合
        from config import OperationMode

        is_dry_run_mode = (
            self.operation_mode == OperationMode.DRY_RUN
        ) or self.is_dry_run

        # 「確定して投稿」ボタンを条件付きで表示・無効化
        confirm_button = ttk.Button(
            button_frame,
            text="✅ 確定して投稿",
            command=self._confirm_and_post,
            state=tk.DISABLED if is_dry_run_mode else tk.NORMAL,
        )
        confirm_button.pack(side=tk.RIGHT, padx=5)

        # DRY_RUN モード時のツールチップ
        if is_dry_run_mode:
            confirm_button_label = (
                "🧪 DRY_RUN モードまたはドライランモードでは実投稿できません"
            )
        else:
            confirm_button_label = "✅ 確定して投稿"

        ttk.Button(
            button_frame, text="❌ キャンセル", command=self.window.destroy
        ).pack(side=tk.RIGHT, padx=5)
        ttk.Button(button_frame, text="🧪 投稿テスト", command=self._dry_run).pack(
            side=tk.RIGHT, padx=5
        )

    def _display_image_preview(self, parent_frame, image_filename):
        """画像プレビューを表示（右横配置）"""
        if not PIL_AVAILABLE:
            ttk.Label(
                parent_frame,
                text="⚠️ PIL (Pillow) がインストールされていないため、プレビューは表示できません",
                foreground="orange",
            ).pack(anchor=tk.W, pady=5)
            return

        try:
            # 画像ファイルの完全パスを構築
            site = self.video.get("source", "youtube").capitalize()
            image_path = Path("images") / site / "import" / image_filename

            if not image_path.exists():
                # autopost フォルダも試す
                image_path = Path("images") / site / "autopost" / image_filename

            if not image_path.exists():
                ttk.Label(
                    parent_frame,
                    text=f"⚠️ 画像ファイルが見つかりません: {image_filename}",
                    foreground="orange",
                ).pack(anchor=tk.W, pady=5)
                return

            # 画像情報と画像を左右に配置するフレーム
            preview_container = ttk.Frame(parent_frame)
            preview_container.pack(fill=tk.X, pady=5)

            # 左側：画像情報
            info_frame = ttk.Frame(preview_container)
            info_frame.pack(side=tk.LEFT, fill=tk.BOTH, expand=True, padx=(0, 10))

            with Image.open(image_path) as img_info:
                width, height = img_info.size
                size_kb = image_path.stat().st_size / 1024
                info_text = f"解像度: {width}×{height} px\nサイズ: {size_kb:.1f} KB"
                ttk.Label(
                    info_frame,
                    text=info_text,
                    foreground="gray",
                    font=("", 9),
                    justify=tk.LEFT,
                ).pack(anchor=tk.W)

            # 右側：プレビュー画像
            preview_frame = ttk.Frame(preview_container)
            preview_frame.pack(side=tk.RIGHT)

            # 画像を開く
            with Image.open(image_path) as img:
                # サムネイルサイズに縮小（最大 100x67）
                img.thumbnail((100, 67), Image.Resampling.LANCZOS)

                # PIL Image を tkinter PhotoImage に変換
                from PIL import ImageTk

                photo = ImageTk.PhotoImage(img)

                # ラベルに表示
                preview_label = tk.Label(
                    preview_frame, image=photo, bg="lightgray", relief=tk.SUNKEN
                )
                preview_label.image = photo  # ガベージコレクション対策
                preview_label.pack()

        except Exception as e:
            logger.warning(f"画像プレビュー表示エラー: {e}")
            ttk.Label(
                parent_frame,
                text=f"⚠️ 画像の読み込みに失敗: {str(e)[:50]}",
                foreground="orange",
            ).pack(anchor=tk.W, pady=5)

    def _confirm_and_post(self):
        """設定を確定して投稿を実行"""
        use_image = self.use_image_var.get()
        resize_small = self.resize_small_var.get()

        logger.info(
            f"🔍 投稿設定確定: use_image={use_image}, resize_small={resize_small}"
        )

        self.result = {
            "use_image": use_image,
            "resize_small_images": resize_small,
            "video": self.video,
        }

        # 投稿実行
        self._execute_post(dry_run=False)

    def _dry_run(self):
        """投稿テスト実行"""
        use_image = self.use_image_var.get()
        resize_small = self.resize_small_var.get()

        logger.info(
            f"🔍 投稿テスト設定: use_image={use_image}, resize_small={resize_small}"
        )

        self.result = {
            "use_image": use_image,
            "resize_small_images": resize_small,
            "video": self.video,
        }
        self._execute_post(dry_run=True)

    def _execute_post(self, dry_run=False):
        """投稿を実行"""
        try:
            video = self.video
            use_image = self.result["use_image"]
            resize_small = self.result["resize_small_images"]

            logger.info(
                f"📋 _execute_post 開始: use_image={use_image} (type={type(use_image).__name__}), resize_small={resize_small}"
            )

            # ⭐ 重複投稿チェック（設定値で有効化）
            try:
                from config import get_config

                config = get_config("settings.env")
                if config.prevent_duplicate_posts and not dry_run:
                    if self.db.is_duplicate_post(video["video_id"]):
                        messagebox.showwarning(
                            "警告: 重複投稿防止",
                            f"この動画は既に投稿済みです。\n\n{video['title'][:60]}...\n\n重複投稿を防止しました。",
                        )
                        logger.warning(
                            f"🛑 重複投稿を防止しました: {video['video_id']}"
                        )
                        return
            except Exception as e:
                logger.warning(f"重複チェック機能の読み込みエラー: {e}")

            mode_str = "画像" if use_image else "URLリンクカード"
            dry_str = "【投稿テスト】" if dry_run else ""

            logger.info(
                f"{dry_str}投稿開始: {video['title'][:40]}... (投稿方法: {mode_str})"
            )

            if use_image:
                # プラグイン経由で画像添付投稿
                if self.plugin_manager:
                    # video に投稿方法フラグを追加
                    video_with_settings = dict(video)
                    video_with_settings["use_image"] = True
                    logger.info(
                        f"📤 プラグイン経由で投稿（画像添付）: {video['title']}"
                    )
                    # ★ dry_run フラグを渡す
                    results = self.plugin_manager.post_video_with_all_enabled(
                        video_with_settings, dry_run=dry_run
                    )
                    logger.info(f"投稿結果: {results}")
                    if any(results.values()) and not dry_run:
                        self.db.mark_as_posted(video["video_id"])
                else:
                    messagebox.showerror(
                        "エラー", "プラグインマネージャが初期化されていません"
                    )
                    return
            else:
                # テキスト + URLリンク投稿（プラグイン経由でテンプレート対応）← 修正: 2025-12-18
                if self.plugin_manager:
                    logger.info(
                        f"📤 プラグイン経由で投稿（テンプレート対応）: {video['title']}"
                    )
                    video_with_settings = dict(video)
                    video_with_settings["use_image"] = False  # 画像なしモード
                    # ★ dry_run フラグを渡す
                    results = self.plugin_manager.post_video_with_all_enabled(
                        video_with_settings, dry_run=dry_run
                    )
                    logger.info(f"投稿結果: {results}")
                    success = any(results.values())  # 任意のプラグイン成功で OK
                    if success and not dry_run:
                        self.db.mark_as_posted(video["video_id"])
                elif self.bluesky_core:
                    # フォールバック：プラグインがない場合はコア機能を直接呼び出し
                    logger.info(
                        f"📤 コア機能で投稿（テンプレート非対応、シンプルテキストのみ）: {video['title']}"
                    )
                    # ★ 固定設定値を video 辞書に追加
                    video_with_settings = dict(video)
                    video_with_settings["via_plugin"] = False  # プラグイン非導入フラグ
                    video_with_settings["use_link_card"] = (
                        False  # リンクカード無効（プラグイン機能）
                    )
                    video_with_settings["embed"] = None  # 画像埋め込みなし
                    # ★ dry_run フラグを設定
                    if hasattr(self.bluesky_core, "set_dry_run"):
                        self.bluesky_core.set_dry_run(dry_run)
                    success = self.bluesky_core.post_video_minimal(video_with_settings)
                    if success and not dry_run:
                        self.db.mark_as_posted(video["video_id"])
                else:
                    messagebox.showerror(
                        "エラー", "プラグインもコア機能も初期化されていません"
                    )
                    return

            msg = f"{'✅ 投稿テスト完了' if dry_run else '✅ 投稿完了'}\n\n{video['title'][:60]}...\n\n投稿方法: {mode_str}"
            messagebox.showinfo("成功", msg)

            # ★ 投稿テスト後でも選択状態を更新（投稿テストは投稿済み扱いにしない）
            if not dry_run:
                self.db.update_selection(
                    video["video_id"], selected=False, scheduled_at=None
                )
                logger.info(f"選択状態を更新: {video['video_id']} (selected=False)")

            # 窓を閉じる
            self.window.destroy()

        except Exception as e:
            logger.error(f"投稿エラー: {e}", exc_info=True)
            messagebox.showerror("エラー", f"投稿に失敗しました:\n{str(e)}")
