# -*- coding: utf-8 -*-

"""
Schedule View Tab - 投稿スケジュール確認・管理タブ

スケジュール済みの動画一覧を表示し、編集・キャンセル機能を提供します。
"""

import tkinter as tk
from tkinter import ttk, messagebox
from datetime import datetime
from typing import Optional
import logging

logger = logging.getLogger("GUILogger")

__author__ = "mayuneco(mayunya)"
__copyright__ = "Copyright (C) 2025 mayuneco(mayunya)"
__license__ = "GPLv2"


class ScheduleViewTab:
    """投稿スケジュール確認・管理タブ"""

    def __init__(self, parent, db, schedule_mgr):
        """
        初期化

        Args:
            parent: 親ウィンドウ（ノートブック）
            db: Database インスタンス
            schedule_mgr: BatchScheduleManager インスタンス
        """
        self.db = db
        self.schedule_mgr = schedule_mgr
        self.current_context_item = None

        # フレーム作成
        self.frame = ttk.Frame(parent)
        self._build_ui()

    def get_frame(self) -> ttk.Frame:
        """フレームを取得"""
        return self.frame

    def _build_ui(self):
        """UI 構築"""
        # ===== ツールバー =====
        toolbar = ttk.Frame(self.frame)
        toolbar.pack(fill=tk.X, padx=5, pady=5)

        ttk.Button(toolbar, text="🔄 更新", command=self._refresh_schedule).pack(
            side=tk.LEFT, padx=2
        )
        ttk.Button(toolbar, text="❌ 全て取消", command=self._on_cancel_all).pack(
            side=tk.LEFT, padx=2
        )

        # ステータス表示
        self.status_label = ttk.Label(
            toolbar,
            text="読み込み中...",
            relief=tk.SUNKEN,
        )
        self.status_label.pack(side=tk.RIGHT, fill=tk.X, expand=True, padx=5)

        # ===== ツリービュー =====
        tree_frame = ttk.Frame(self.frame)
        tree_frame.pack(fill=tk.BOTH, expand=True, padx=5, pady=5)

        columns = ("Video ID", "Title", "Scheduled", "Status", "Remaining")
        self.tree = ttk.Treeview(
            tree_frame,
            columns=columns,
            height=20,
            show="headings",
        )

        self.tree.column("Video ID", width=100, anchor=tk.W)
        self.tree.column("Title", width=250, anchor=tk.W)
        self.tree.column("Scheduled", width=150, anchor=tk.CENTER)
        self.tree.column("Status", width=80, anchor=tk.CENTER)
        self.tree.column("Remaining", width=100, anchor=tk.CENTER)

        self.tree.heading("Video ID", text="📹 Video ID")
        self.tree.heading("Title", text="📝 Title")
        self.tree.heading("Scheduled", text="⏰ Scheduled Time")
        self.tree.heading("Status", text="✅ Status")
        self.tree.heading("Remaining", text="⏱️  Remaining")

        scrollbar = ttk.Scrollbar(tree_frame, orient=tk.VERTICAL, command=self.tree.yview)
        self.tree.configure(yscroll=scrollbar.set)

        self.tree.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)
        scrollbar.pack(side=tk.RIGHT, fill=tk.Y)

        # コンテキストメニュー
        self.context_menu = tk.Menu(self.frame, tearoff=False)
        self.context_menu.add_command(
            label="✏️  編集", command=self._on_edit_schedule
        )
        self.context_menu.add_command(
            label="❌ 取消", command=self._on_cancel_schedule
        )
        self.context_menu.add_separator()
        self.context_menu.add_command(
            label="📋 詳細表示", command=self._on_show_details
        )

        self.tree.bind("<Button-3>", self._on_right_click)

        # 初期読込
        self._refresh_schedule()

    def _refresh_schedule(self):
        """スケジュール一覧を再読込"""
        try:
            # 既存アイテムを削除
            for item in self.tree.get_children():
                self.tree.delete(item)

            # スケジュール統計取得
            stats = self.schedule_mgr.get_schedule_stats()
            scheduled_videos = self.schedule_mgr.get_scheduled_videos()

            # リストに追加
            for i, video in enumerate(scheduled_videos, 1):
                video_id = video.get("video_id", "N/A")[:20]
                title = video.get("title", "N/A")[:50]
                scheduled_at_str = video.get("scheduled_at", "N/A")

                # ステータス判定
                if scheduled_at_str:
                    try:
                        scheduled_at = datetime.fromisoformat(scheduled_at_str)
                        now = datetime.now()
                        status = "⏳ Pending" if scheduled_at > now else "🔴 Overdue"
                        remaining = self._calc_remaining(scheduled_at)
                    except:
                        status = "❓ Invalid"
                        remaining = "N/A"
                else:
                    status = "❌ No Schedule"
                    remaining = "N/A"

                self.tree.insert(
                    "",
                    tk.END,
                    values=(
                        video_id,
                        title,
                        scheduled_at_str,
                        status,
                        remaining,
                    ),
                )

            # ステータス更新
            total = stats["total_scheduled"]
            pending = stats["pending"]
            overdue = stats["overdue"]

            status_text = f"📊 総数: {total} | ⏳ 待機中: {pending} | 🔴 超過: {overdue}"
            self.status_label.config(text=status_text)

            logger.info(f"✅ スケジュール一覧更新: {total} 件")

        except Exception as e:
            logger.error(f"❌ スケジュール一覧更新失敗: {e}")
            self.status_label.config(text="❌ 読込失敗")

    def _calc_remaining(self, scheduled_at: datetime) -> str:
        """予定時刻までの残り時間を計算"""
        try:
            now = datetime.now()
            if scheduled_at > now:
                delta = scheduled_at - now
                hours = delta.total_seconds() // 3600
                minutes = (delta.total_seconds() % 3600) // 60
                return f"{int(hours)}h {int(minutes)}m"
            else:
                delta = now - scheduled_at
                hours = delta.total_seconds() // 3600
                minutes = (delta.total_seconds() % 3600) // 60
                return f"{int(hours)}h {int(minutes)}m 前"
        except:
            return "N/A"

    def _on_right_click(self, event):
        """右クリックメニュー表示"""
        item = self.tree.identify("item", event.x, event.y)
        if item:
            self.tree.selection_set(item)
            self.current_context_item = item
            self.context_menu.post(event.x_root, event.y_root)

    def _on_edit_schedule(self):
        """スケジュール編集"""
        if not self.current_context_item:
            messagebox.showwarning("警告", "動画を選択してください")
            return

        # ツリーから動画ID取得
        values = self.tree.item(self.current_context_item, "values")
        if not values:
            return

        video_id = values[0]
        video = self.db.get_video(video_id)

        if not video:
            messagebox.showerror("エラー", "動画情報が見つかりません")
            return

        # 編集ダイアログ（簡易版）
        dialog = tk.Toplevel(self.frame)
        dialog.title(f"スケジュール編集 - {video_id[:20]}")
        dialog.geometry("400x200")
        dialog.transient(self.frame)
        dialog.grab_set()

        ttk.Label(dialog, text="新しい投稿予定時刻:", font=("Arial", 11)).pack(
            anchor=tk.W, padx=10, pady=10
        )

        frame = ttk.Frame(dialog)
        frame.pack(fill=tk.X, padx=20, pady=5)

        ttk.Label(frame, text="日時:").pack(side=tk.LEFT)
        date_var = tk.StringVar(
            value=video.get("scheduled_at", datetime.now().strftime("%Y-%m-%d %H:%M:%S"))
        )
        date_entry = ttk.Entry(frame, textvariable=date_var)
        date_entry.pack(side=tk.LEFT, padx=5, expand=True, fill=tk.X)

        def save_edit():
            try:
                # バリデーション
                datetime.fromisoformat(date_var.get())
                self.db.update_selection(video_id, selected=True, scheduled_at=date_var.get())
                messagebox.showinfo("成功", "スケジュールを更新しました")
                self._refresh_schedule()
                dialog.destroy()
            except ValueError:
                messagebox.showerror("エラー", "無効な日時形式です。\n(YYYY-MM-DD HH:MM:SS)")

        ttk.Button(frame, text="✅ 保存", command=save_edit).pack(
            side=tk.LEFT, padx=5
        )
        ttk.Button(frame, text="❌ キャンセル", command=dialog.destroy).pack(
            side=tk.LEFT, padx=5
        )

    def _on_cancel_schedule(self):
        """スケジュール個別キャンセル"""
        if not self.current_context_item:
            messagebox.showwarning("警告", "動画を選択してください")
            return

        values = self.tree.item(self.current_context_item, "values")
        if not values:
            return

        video_id = values[0]
        result = messagebox.askyesno(
            "確認",
            f"動画 {video_id[:20]} のスケジュールをキャンセルしますか？",
        )

        if result:
            if self.schedule_mgr.cancel_schedule(video_id):
                messagebox.showinfo("成功", "スケジュールをキャンセルしました")
                self._refresh_schedule()
            else:
                messagebox.showerror("失敗", "キャンセルに失敗しました")

    def _on_cancel_all(self):
        """全スケジュールキャンセル"""
        count = self.schedule_mgr.get_schedule_stats()["total_scheduled"]
        if count == 0:
            messagebox.showinfo("情報", "スケジュール済みの動画がありません")
            return

        result = messagebox.askyesno(
            "確認",
            f"全 {count} 件のスケジュールをキャンセルしますか？\n\nこの操作は取り消せません。",
        )

        if result:
            cancelled = self.schedule_mgr.cancel_all_schedule()
            messagebox.showinfo("成功", f"{cancelled} 件のスケジュールをキャンセルしました")
            self._refresh_schedule()

    def _on_show_details(self):
        """詳細表示"""
        if not self.current_context_item:
            return

        values = self.tree.item(self.current_context_item, "values")
        if not values:
            return

        video_id = values[0]
        video = self.db.get_video(video_id)

        if not video:
            messagebox.showerror("エラー", "動画情報が見つかりません")
            return

        detail_text = (
            f"📹 動画ID: {video.get('video_id', 'N/A')}\n"
            f"📝 タイトル: {video.get('title', 'N/A')}\n"
            f"⏰ 投稿予定: {video.get('scheduled_at', 'N/A')}\n"
            f"✅ 投稿済み: {'はい' if video.get('posted_to_bluesky') else 'いいえ'}\n"
            f"📅 公開日時: {video.get('published_at', 'N/A')}\n"
            f"🔗 URL: {video.get('video_url', 'N/A')}"
        )

        messagebox.showinfo("詳細情報", detail_text)
