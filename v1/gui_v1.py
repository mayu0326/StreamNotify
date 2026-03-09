# -*- coding: utf-8 -*-

"""
StreamNotify on Bluesky- v1 GUI（改善版）

DB の動画一覧を表示し、投稿対象をチェックボックスで選択・スケジュール管理。
tkinter を使用（標準ライブラリのみ）
"""

import logging
import tkinter as tk
from datetime import datetime, timedelta
from tkinter import messagebox, ttk

from database import get_database

logger = logging.getLogger("AppLogger")

__author__ = "mayuneco(mayunya)"
__copyright__ = "Copyright (C) 2025 mayuneco(mayunya)"
__license__ = "GPLv2"


class YouTubeNotifierGUI:
    """YouTube Notifier GUI"""

    def __init__(self, root):
        self.root = root
        self.root.title("YouTube → Bluesky Notifier - DB 管理")
        self.root.geometry("1300x700")

        self.db = get_database()
        self.selected_rows = set()  # チェック状態を保持

        self.setup_ui()
        self.refresh_data()

    def setup_ui(self):
        """UI を構築"""

        # === 上部: ツールバー ===
        toolbar = ttk.Frame(self.root)
        toolbar.pack(side=tk.TOP, fill=tk.X, padx=5, pady=5)

        ttk.Button(toolbar, text="🔄 再読込", command=self.refresh_data).pack(side=tk.LEFT, padx=2)
        ttk.Separator(toolbar, orient=tk.VERTICAL).pack(side=tk.LEFT, fill=tk.Y, padx=2)
        ttk.Button(toolbar, text="☑️ すべて選択", command=self.select_all).pack(side=tk.LEFT, padx=2)
        ttk.Button(toolbar, text="☐ すべて解除", command=self.deselect_all).pack(side=tk.LEFT, padx=2)
        ttk.Separator(toolbar, orient=tk.VERTICAL).pack(side=tk.LEFT, fill=tk.Y, padx=2)
        ttk.Button(toolbar, text="💾 選択を保存", command=self.save_selection).pack(side=tk.LEFT, padx=2)
        ttk.Button(toolbar, text="ℹ️ 統計", command=self.show_stats).pack(side=tk.LEFT, padx=2)

        # === 中央: Treeview（一覧表） ===
        table_frame = ttk.Frame(self.root)
        table_frame.pack(fill=tk.BOTH, expand=True, padx=5, pady=5)

        # Treeview 定義
        columns = ("Select", "Video ID", "Published", "Title", "Posted", "Scheduled")
        self.tree = ttk.Treeview(table_frame, columns=columns, height=20, show="headings")

        self.tree.column("Select", width=50, anchor=tk.CENTER)
        self.tree.column("Video ID", width=110)
        self.tree.column("Published", width=130)
        self.tree.column("Title", width=600)
        self.tree.column("Posted", width=60, anchor=tk.CENTER)
        self.tree.column("Scheduled", width=150)

        self.tree.heading("Select", text="☑️")
        self.tree.heading("Video ID", text="Video ID")
        self.tree.heading("Published", text="公開日時")
        self.tree.heading("Title", text="タイトル")
        self.tree.heading("Posted", text="投稿済み")
        self.tree.heading("Scheduled", text="予約日時")

        # スクロールバー
        scrollbar = ttk.Scrollbar(table_frame, orient=tk.VERTICAL, command=self.tree.yview)
        self.tree.configure(yscroll=scrollbar.set)

        self.tree.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)
        scrollbar.pack(side=tk.RIGHT, fill=tk.Y)

        # イベント
        self.tree.bind("<Button-1>", self.on_tree_click)
        self.tree.bind("<Double-1>", self.on_tree_double_click)

        # === 下部: ステータスバー ===
        status_frame = ttk.Frame(self.root)
        status_frame.pack(side=tk.BOTTOM, fill=tk.X, padx=5, pady=5)

        self.status_label = ttk.Label(status_frame, text="準備完了", relief=tk.SUNKEN)
        self.status_label.pack(fill=tk.X)

    def refresh_data(self):
        """DB から最新データを取得して表示"""
        # 既存の行をクリア
        for item in self.tree.get_children():
            self.tree.delete(item)

        videos = self.db.get_all_videos()
        self.selected_rows.clear()

        for video in videos:
            checked = "☑️" if video["selected_for_post"] else "☐"
            posted = "✓" if video["posted_to_bluesky"] else "–"
            scheduled = video["scheduled_at"] or "（未設定）"

            self.tree.insert("", tk.END, values=(
                checked,
                video["video_id"],
                video["published_at"][:10],
                video["title"][:100],
                posted,
                scheduled[:16] if scheduled != "（未設定）" else scheduled
            ), iid=video["video_id"], tags=("even" if len(self.tree.get_children()) % 2 == 0 else "odd",))

            if video["selected_for_post"]:
                self.selected_rows.add(video["video_id"])

        # 行の背景色を交互に
        self.tree.tag_configure("even", background="#f0f0f0")
        self.tree.tag_configure("odd", background="white")

        self.status_label.config(text=f"読み込み完了: {len(videos)} 件の動画（選択: {len(self.selected_rows)} 件）")

    def on_tree_click(self, event):
        """Treeview の「選択」列をクリックしてチェック状態をトグル"""
        item_id = self.tree.identify_row(event.y)
        col = self.tree.identify_column(event.x)

        if not item_id or col != "#1":  # 「Select」列
            return

        # チェック状態をトグル
        if item_id in self.selected_rows:
            self.selected_rows.remove(item_id)
            new_checked = "☐"
        else:
            self.selected_rows.add(item_id)
            new_checked = "☑️"

        # Treeview を更新
        values = list(self.tree.item(item_id, "values"))
        values[0] = new_checked
        self.tree.item(item_id, values=values)

    def on_tree_double_click(self, event):
        """Treeview の「予約日時」列をダブルクリックして編集"""
        item_id = self.tree.identify_row(event.y)
        col = self.tree.identify_column(event.x)

        if not item_id or col != "#6":  # 「Scheduled」列
            return

        self.edit_scheduled_time(item_id)

    def select_all(self):
        """すべての動画を選択"""
        for item_id in self.tree.get_children():
            self.selected_rows.add(item_id)
            values = list(self.tree.item(item_id, "values"))
            values[0] = "☑️"
            self.tree.item(item_id, values=values)

        self.status_label.config(text=f"すべて選択しました（{len(self.selected_rows)} 件）")

    def deselect_all(self):
        """すべての選択を解除"""
        for item_id in self.tree.get_children():
            self.selected_rows.discard(item_id)
            values = list(self.tree.item(item_id, "values"))
            values[0] = "☐"
            self.tree.item(item_id, values=values)

        self.status_label.config(text="すべての選択を解除しました")

    def save_selection(self):
        """現在の選択状態を DB に保存"""
        videos = self.db.get_all_videos()

        for video in videos:
            is_selected = video["video_id"] in self.selected_rows
            self.db.update_selection(video["video_id"], selected=is_selected)

        messagebox.showinfo("成功", f"{len(self.selected_rows)} 件の選択状態を保存しました。\n\nmain_v1.py が実行中なら、5分ごとに1件ずつ投稿されます。")
        self.refresh_data()

    def edit_scheduled_time(self, video_id):
        """予約日時をダイアログで編集"""
        edit_window = tk.Toplevel(self.root)
        edit_window.title(f"予約日時設定 - {video_id}")
        edit_window.geometry("350x200")
        edit_window.resizable(False, False)

        # ラベルと説明
        ttk.Label(edit_window, text=f"動画: {video_id}", font=("Arial", 10, "bold")).pack(pady=5)
        ttk.Label(edit_window, text="予約投稿日時を設定します", foreground="gray").pack(pady=5)

        # 入力フィールド
        ttk.Label(edit_window, text="日時 (YYYY-MM-DD HH:MM):").pack(pady=5)

        entry = ttk.Entry(edit_window, width=35)
        entry.pack(pady=5, padx=10)

        # デフォルト値：今から5分後
        default_time = (datetime.now() + timedelta(minutes=5)).strftime("%Y-%m-%d %H:%M")
        entry.insert(0, default_time)
        entry.selection_range(0, tk.END)
        entry.focus()

        # クイックボタン
        quick_frame = ttk.LabelFrame(edit_window, text="クイック設定", padding=10)
        quick_frame.pack(pady=10, padx=10, fill=tk.X)

        def set_quick_time(minutes):
            quick_time = (datetime.now() + timedelta(minutes=minutes)).strftime("%Y-%m-%d %H:%M")
            entry.delete(0, tk.END)
            entry.insert(0, quick_time)

        ttk.Button(quick_frame, text="5分後", command=lambda: set_quick_time(5)).pack(side=tk.LEFT, padx=2)
        ttk.Button(quick_frame, text="15分後", command=lambda: set_quick_time(15)).pack(side=tk.LEFT, padx=2)
        ttk.Button(quick_frame, text="30分後", command=lambda: set_quick_time(30)).pack(side=tk.LEFT, padx=2)
        ttk.Button(quick_frame, text="1時間後", command=lambda: set_quick_time(60)).pack(side=tk.LEFT, padx=2)

        # ボタン
        button_frame = ttk.Frame(edit_window)
        button_frame.pack(pady=10)

        def save_time():
            scheduled = entry.get().strip()

            try:
                datetime.fromisoformat(scheduled)
            except ValueError:
                messagebox.showerror("エラー", "無効な日時形式です。\n形式: YYYY-MM-DD HH:MM\n例: 2025-12-05 08:45")
                return

            self.db.update_selection(video_id, selected=True, scheduled_at=scheduled)
            self.selected_rows.add(video_id)

            messagebox.showinfo("成功", f"予約日時を設定しました。\n{scheduled}\n\n「選択を保存」ボタンで確定してください。")
            edit_window.destroy()
            self.refresh_data()

        def clear_selection():
            self.db.update_selection(video_id, selected=False, scheduled_at=None)
            self.selected_rows.discard(video_id)
            messagebox.showinfo("成功", "この動画の選択を解除しました。")
            edit_window.destroy()
            self.refresh_data()

        ttk.Button(button_frame, text="保存", command=save_time).pack(side=tk.LEFT, padx=5)
        ttk.Button(button_frame, text="選択解除", command=clear_selection).pack(side=tk.LEFT, padx=5)
        ttk.Button(button_frame, text="キャンセル", command=edit_window.destroy).pack(side=tk.LEFT, padx=5)

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

📌 次のステップ
━━━━━━━━━━━━━━━━━
1. 動画を選択（☑️ をクリック）
2. 「予約日時」をダブルクリックで投稿日時を設定
3. 「💾 選択を保存」をクリック
4. main_v1.py が実行中なら、自動投稿されます
        """

        messagebox.showinfo("統計情報", stats)


def main():
    """GUI メイン"""
    root = tk.Tk()
    gui = YouTubeNotifierGUI(root)
    root.mainloop()


if __name__ == "__main__":
    main()
