# -*- coding: utf-8 -*-

"""
Stream notify on Bluesky - v2 GUI（改善版）

DB の動画一覧を表示し、投稿対象をチェックボックスで選択・スケジュール管理。
tkinter を使用（標準ライブラリのみ）
"""

import calendar
import logging
import os
import sys
import tkinter as tk
from datetime import datetime, timedelta
from tkinter import filedialog, messagebox, ttk

from database import get_database
from image_manager import get_image_manager
from app_version import __version__

logger = logging.getLogger("GUILogger")

__author__ = "mayuneco(mayunya)"
__copyright__ = "Copyright (C) 2025 mayuneco(mayunya)"
__license__ = "GPLv2"


class StreamNotifyGUI:
    """Stream notify GUI（統合版, プラグイン対応）"""

    def __init__(self, root, db, plugin_manager=None):
        self.root = root
        self.root.title(f"StreamNotify on Bluesky v{__version__} - DB 管理")
        self.root.geometry("1400x750")

        self.db = db
        self.plugin_manager = plugin_manager
        self.image_manager = get_image_manager()  # 画像管理クラスを初期化
        self.selected_rows = set()

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
        ttk.Button(toolbar, text="📤 投稿実行", command=self.execute_post).pack(
            side=tk.LEFT, padx=2
        )
        ttk.Separator(toolbar, orient=tk.VERTICAL).pack(side=tk.LEFT, fill=tk.Y, padx=2)
        ttk.Button(toolbar, text="ℹ️ 統計", command=self.show_stats).pack(
            side=tk.LEFT, padx=2
        )
        ttk.Button(toolbar, text="🔧 プラグイン", command=self.show_plugins).pack(
            side=tk.LEFT, padx=2
        )

        table_frame = ttk.Frame(self.root)
        table_frame.pack(fill=tk.BOTH, expand=True, padx=5, pady=5)

        columns = (
            "Select",
            "Video ID",
            "Published",
            "Source",
            "Title",
            "Date",
            "Posted",
        )
        self.tree = ttk.Treeview(
            table_frame, columns=columns, height=20, show="headings"
        )

        self.tree.column("Select", width=50, anchor=tk.CENTER)
        self.tree.column("Video ID", width=110)
        self.tree.column("Published", width=130)
        self.tree.column("Source", width=120, anchor=tk.CENTER)
        self.tree.column("Title", width=400)
        self.tree.column("Date", width=150)
        self.tree.column("Posted", width=60, anchor=tk.CENTER)

        self.tree.heading("Select", text="☑️")
        self.tree.heading("Video ID", text="Video ID")
        self.tree.heading("Published", text="公開日時")
        self.tree.heading("Source", text="配信元")
        self.tree.heading("Title", text="タイトル")
        self.tree.heading("Date", text="投稿予定/投稿日時")
        self.tree.heading("Posted", text="投稿実績")

        scrollbar = ttk.Scrollbar(
            table_frame, orient=tk.VERTICAL, command=self.tree.yview
        )
        self.tree.configure(yscrollcommand=scrollbar.set)

        self.tree.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)
        scrollbar.pack(side=tk.RIGHT, fill=tk.Y)

        self.tree.bind("<Button-1>", self.on_tree_click)
        self.tree.bind("<Double-1>", self.on_tree_double_click)

        # 右クリックメニュー
        self.context_menu = tk.Menu(self.root, tearoff=0)
        self.context_menu.add_command(
            label="⏰ 予約日時を設定", command=self.context_edit_scheduled
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

    def refresh_data(self):
        """DB から最新データを取得して表示"""
        for item in self.tree.get_children():
            self.tree.delete(item)

        videos = self.db.get_all_videos()
        self.selected_rows.clear()

        for video in videos:
            checked = "☑️" if video.get("selected_for_post") else "☐"
            # 投稿済みの場合は投稿日時を表示、未投稿の場合は予約日時を表示
            if video.get("posted_to_bluesky"):
                # 新しい方式: posted_at がある場合はそれを表示
                if video.get("posted_at"):
                    date_info = video.get("posted_at")
                else:
                    # 古いデータベース: posted_at がない場合は "不明" と表示
                    date_info = "不明"
            else:
                # 未投稿の場合は予約日時を表示
                date_info = video.get("scheduled_at") or "（未設定）"
            source = video.get("source") or ""
            image_mode = video.get("image_mode") or ""
            image_filename = video.get("image_filename") or ""

            self.tree.insert(
                "",
                tk.END,
                values=(
                    checked,  # Select
                    video["video_id"],  # Video ID
                    video["published_at"][:10],  # Published
                    source,  # Source
                    video["title"][:100],  # Title
                    (
                        date_info[:16] if date_info != "（未設定）" else date_info
                    ),  # Date (Posted or Scheduled)
                    "✓" if video.get("posted_to_bluesky") else "–",  # Posted
                ),
                iid=video["video_id"],
                tags=("even" if len(self.tree.get_children()) % 2 == 0 else "odd",),
            )

            if video.get("selected_for_post"):
                self.selected_rows.add(video["video_id"])

        self.tree.tag_configure("even", background="#f0f0f0")
        self.tree.tag_configure("odd", background="white")

        self.status_label.config(
            text=f"読み込み完了: {len(videos)} 件の動画（選択: {len(self.selected_rows)} 件）"
        )

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

        # 予約日時列
        if col == "#6":
            self.edit_scheduled_time(item_id)

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
            except Exception:
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

    def execute_post(self):
        """投稿実行：選択された動画をすべての有効プラグインで投稿"""
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

        msg = f"""
📤 投稿実行 - 確認

以下の {len(selected)} 件を有効な全プラグインで投稿します：
"""
        for v in selected[:5]:
            msg += f"  ✓ {v['title'][:50]}...\n"
        if len(selected) > 5:
            msg += f"  ... ほか {len(selected) - 5} 件\n"
        msg += """
※ この操作は取り消せません。
※ 投稿済みフラグの有無に関わらず投稿します。
        """
        if not messagebox.askyesno("確認", msg):
            return

        success_count = 0
        fail_count = 0
        for video in selected:
            try:
                logger.info(f"📤 投稿実行（GUI）: {video['title']}")
                results = self.plugin_manager.post_video_with_all_enabled(video)
                if any(results.values()):
                    self.db.mark_as_posted(video["video_id"])
                    self.db.update_selection(
                        video["video_id"], selected=False, scheduled_at=None
                    )
                    logger.info(
                        f"動画の選択状態を更新: {video['video_id']} (selected=False, scheduled=None)"
                    )
                    success_count += 1
                    logger.info(f"✅ 投稿成功（GUI）: {video['title']}")
                else:
                    fail_count += 1
                    logger.warning(f"❌ 投稿失敗（GUI）: {video['title']}")
            except Exception as e:
                fail_count += 1
                logger.error(f"❌ 投稿エラー（GUI）: {video['title']} - {e}")

        result_msg = f"""
📊 投稿結果

成功: {success_count} 件
失敗: {fail_count} 件
合計: {len(selected)} 件

詳細はコンソールログを確認してください。
        """
        messagebox.showinfo("完了", result_msg)
        self.refresh_data()

    def show_stats(self):
        """統計情報を表示"""
        videos = self.db.get_all_videos()

        total = len(videos)
        posted = sum(1 for v in videos if v["posted_to_bluesky"])
        selected = sum(1 for v in videos if v["selected_for_post"])
        unposted = total - posted

        stats = f"""
📊 統計情報
━━━━━━━━━━━━━━━━━
総動画数:     {total}
投稿済み:     {posted}
投稿予定:     {selected}
未処理:       {unposted}

📌 操作方法
━━━━━━━━━━━━━━━━━
1. 「☑️」をクリック → 投稿対象を選択
2. 「投稿予定/投稿日時」をダブルクリック → 投稿日時を設定
3. 「💾 選択を保存」 → DB に反映
4. 「🧪 ドライラン」 → テスト実行
5. 「📤 投稿実行」 → 実投稿

⚠️ 注意
━━━━━━━━━━━━━━━━━
投稿済みフラグに関わらず投稿できます。
重複投稿にご注意ください。
        """
        messagebox.showinfo("統計情報", stats)

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
        text_widget.configure(yscrollcommand=scrollbar.set)

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
この操作は取り消せません。
本当に削除してもよろしいですか？
        """

        if not messagebox.askyesno("確認", msg, icon=messagebox.WARNING):
            logger.info(f"❌ 削除操作をキャンセルしました（{len(selected)}件選択中）")
            return

        # 削除実行
        logger.info(f"🗑️ {len(selected)} 件の動画削除を開始します")
        deleted_count = self.db.delete_videos_batch([v["video_id"] for v in selected])

        if deleted_count > 0:
            logger.info(f"✅ {deleted_count} 件の動画を削除しました（GUI操作）")
            self.selected_rows.clear()
            self.refresh_data()
            messagebox.showinfo("成功", f"{deleted_count} 件の動画を削除しました。")
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

この操作は取り消せません。
削除してもよろしいですか？
        """

        if not messagebox.askyesno("確認", msg, icon=messagebox.WARNING):
            logger.info(f"❌ 削除操作をキャンセルしました: {item_id}")
            return

        # 削除実行
        logger.info(f"🗑️ 動画削除を実行: {item_id} ({video['title'][:40]}...)")
        if self.db.delete_video(item_id):
            logger.info(f"✅ 動画を削除しました: {item_id}（右クリックメニュー操作）")
            self.selected_rows.discard(item_id)
            self.refresh_data()
            messagebox.showinfo("成功", f"動画を削除しました。\n{item_id}")
        else:
            logger.error(f"❌ 動画削除に失敗: {item_id}")
            messagebox.showerror("エラー", "動画の削除に失敗しました。")
