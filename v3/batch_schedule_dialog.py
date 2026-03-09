# -*- coding: utf-8 -*-

"""
Batch Schedule Dialog - 複数動画の一括スケジュール設定ダイアログ

選択した複数動画に対して、開始時刻と投稿間隔を指定して
自動的に投稿予定時刻を計算・保存します。
"""

import logging
import tkinter as tk
from datetime import datetime, timedelta
from functools import partial
from tkinter import messagebox, ttk
from typing import Any, Dict, List, Optional

logger = logging.getLogger("GUILogger")

__author__ = "mayuneco(mayunya)"
__copyright__ = "Copyright (C) 2025 mayuneco(mayunya)"
__license__ = "GPLv2"


class BatchScheduleDialog(tk.Toplevel):
    """複数動画の一括スケジュール設定ダイアログ"""

    def __init__(self, parent, selected_video_ids: List[str], db, schedule_mgr):
        """
        初期化

        Args:
            parent: 親ウィンドウ
            selected_video_ids: 選択動画のID リスト
            db: Database インスタンス
            schedule_mgr: BatchScheduleManager インスタンス
        """
        super().__init__(parent)
        self.title("📅 複数動画の一括スケジュール設定")
        self.geometry("600x700")
        self.resizable(False, False)
        self.transient(parent)
        self.grab_set()

        self.selected_video_ids = selected_video_ids
        self.db = db
        self.schedule_mgr = schedule_mgr
        self.schedule_preview: Dict[str, Any] = {}  # {video_id: scheduled_datetime}

        self._build_ui()

    def _build_ui(self):
        """UI 構築"""
        # ===== フレーム1: 動画情報表示 =====
        info_frame = ttk.LabelFrame(self, text="📋 対象動画", padding=10)
        info_frame.pack(fill=tk.X, padx=10, pady=5)

        count_label = ttk.Label(
            info_frame,
            text=f"選択動画数: {len(self.selected_video_ids)} 件",
            font=("Arial", 11, "bold"),
        )
        count_label.pack(anchor=tk.W)

        # 動画IDプレビュー（スクロール可能）
        preview_frame = ttk.Frame(info_frame)
        preview_frame.pack(fill=tk.BOTH, expand=True, pady=5)

        scrollbar = ttk.Scrollbar(preview_frame)
        scrollbar.pack(side=tk.RIGHT, fill=tk.Y)

        self.video_listbox = tk.Listbox(
            preview_frame, height=5, yscrollcommand=scrollbar.set
        )
        self.video_listbox.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)
        scrollbar.config(command=self.video_listbox.yview)

        for video_id in self.selected_video_ids:
            video = self.db.get_video(video_id)
            title = video.get("title", "N/A") if video else "N/A"
            display_text = f"{video_id[:20]}... - {title[:40]}"
            self.video_listbox.insert(tk.END, display_text)

        # ===== フレーム2: 開始時刻設定 =====
        start_frame = ttk.LabelFrame(self, text="⏰ 開始時刻設定", padding=10)
        start_frame.pack(fill=tk.X, padx=10, pady=5)

        # 日付選択
        date_frame = ttk.Frame(start_frame)
        date_frame.pack(fill=tk.X, pady=5)

        ttk.Label(date_frame, text="日付:").pack(side=tk.LEFT, padx=5)
        self.date_var = tk.StringVar(value=datetime.now().strftime("%Y-%m-%d"))
        date_entry = ttk.Entry(date_frame, textvariable=self.date_var, width=12)
        date_entry.pack(side=tk.LEFT, padx=5)
        ttk.Label(date_frame, text="(YYYY-MM-DD)").pack(side=tk.LEFT)

        # 時刻選択
        time_frame = ttk.Frame(start_frame)
        time_frame.pack(fill=tk.X, pady=5)

        ttk.Label(time_frame, text="時刻:").pack(side=tk.LEFT, padx=5)

        ttk.Label(time_frame, text="時:").pack(side=tk.LEFT, padx=5)
        self.hour_var = tk.StringVar(value="14")
        hour_spin = ttk.Spinbox(
            time_frame, from_=0, to=23, textvariable=self.hour_var, width=3
        )
        hour_spin.pack(side=tk.LEFT, padx=2)

        ttk.Label(time_frame, text="分:").pack(side=tk.LEFT, padx=5)
        self.minute_var = tk.StringVar(value="00")
        minute_spin = ttk.Spinbox(
            time_frame, from_=0, to=59, textvariable=self.minute_var, width=3
        )
        minute_spin.pack(side=tk.LEFT, padx=2)

        # 「今から〇分後」クイック設定
        quick_frame = ttk.Frame(start_frame)
        quick_frame.pack(fill=tk.X, pady=5)

        ttk.Label(quick_frame, text="クイック設定:").pack(side=tk.LEFT, padx=5)
        for minutes in [5, 10, 30, 60]:
            ttk.Button(
                quick_frame,
                text=f"+{minutes}分",
                command=partial(self._set_start_time_from_now, minutes),
                width=8,
            ).pack(side=tk.LEFT, padx=2)

        # ===== フレーム3: 投稿間隔設定 =====
        interval_frame = ttk.LabelFrame(self, text="📏 投稿間隔設定", padding=10)
        interval_frame.pack(fill=tk.X, padx=10, pady=5)

        ttk.Label(interval_frame, text="投稿間隔 (5～60分):").pack(anchor=tk.W, pady=5)

        # ラジオボタン選択
        radio_frame = ttk.Frame(interval_frame)
        radio_frame.pack(fill=tk.X, padx=20, pady=5)

        self.interval_var = tk.IntVar(value=5)
        for interval in [5, 10, 15, 30, 60]:
            ttk.Radiobutton(
                radio_frame,
                text=f"{interval} 分",
                variable=self.interval_var,
                value=interval,
                command=self._update_preview,
            ).pack(side=tk.LEFT, padx=10)

        # カスタム値入力
        custom_frame = ttk.Frame(interval_frame)
        custom_frame.pack(fill=tk.X, padx=20, pady=5)

        ttk.Label(custom_frame, text="カスタム:").pack(side=tk.LEFT, padx=5)
        self.custom_interval_var = tk.StringVar()
        custom_spin = ttk.Spinbox(
            custom_frame,
            from_=5,
            to=60,
            textvariable=self.custom_interval_var,
            width=5,
            command=self._on_custom_interval_changed,
        )
        custom_spin.pack(side=tk.LEFT, padx=2)
        ttk.Label(custom_frame, text="分").pack(side=tk.LEFT, padx=2)

        # ===== フレーム4: プレビュー表示 =====
        preview_title_frame = ttk.LabelFrame(
            self, text="👁️  投稿予定プレビュー", padding=10
        )
        preview_title_frame.pack(fill=tk.BOTH, expand=True, padx=10, pady=5)

        # ツリービュー
        columns = ("順序", "動画ID", "投稿予定時刻")
        self.preview_tree = ttk.Treeview(
            preview_title_frame, columns=columns, height=10, show="headings"
        )

        self.preview_tree.column("順序", width=50, anchor=tk.CENTER)
        self.preview_tree.column("動画ID", width=150)
        self.preview_tree.column("投稿予定時刻", width=150)

        self.preview_tree.heading("順序", text="順序")
        self.preview_tree.heading("動画ID", text="動画ID")
        self.preview_tree.heading("投稿予定時刻", text="投稿予定時刻")

        scrollbar = ttk.Scrollbar(
            preview_title_frame, orient=tk.VERTICAL, command=self.preview_tree.yview
        )
        self.preview_tree.configure(yscrollcommand=scrollbar.set)

        self.preview_tree.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)
        scrollbar.pack(side=tk.RIGHT, fill=tk.Y)

        # ===== フレーム5: 実行ボタン =====
        button_frame = ttk.Frame(self)
        button_frame.pack(fill=tk.X, padx=10, pady=10)

        ttk.Button(
            button_frame,
            text="✅ スケジュール確定",
            command=self._apply_schedule,
            width=20,
        ).pack(side=tk.LEFT, padx=5, expand=True)

        ttk.Button(
            button_frame,
            text="❌ キャンセル",
            command=self.destroy,
            width=20,
        ).pack(side=tk.LEFT, padx=5, expand=True)

        # 初期プレビュー更新
        self._update_preview()

    def _set_start_time_from_now(self, minutes: int):
        """「今から〇分後」に開始時刻を設定"""
        now = datetime.now() + timedelta(minutes=minutes)
        self.date_var.set(now.strftime("%Y-%m-%d"))
        self.hour_var.set(f"{now.hour:02d}")
        self.minute_var.set(f"{now.minute:02d}")
        self._update_preview()

    def _on_custom_interval_changed(self):
        """カスタム間隔が変更された"""
        if self.custom_interval_var.get():
            self.interval_var.set(0)  # ラジオボタン解除
            self._update_preview()

    def _get_selected_interval(self) -> int:
        """現在選択されている間隔を取得"""
        if self.interval_var.get() > 0:
            return self.interval_var.get()
        elif self.custom_interval_var.get():
            try:
                return int(self.custom_interval_var.get())
            except ValueError:
                return 5
        return 5

    def _parse_start_time(self) -> datetime:
        """開始時刻をパース"""
        try:
            date_str = self.date_var.get()
            hour = int(self.hour_var.get())
            minute = int(self.minute_var.get())
            dt = datetime.strptime(date_str, "%Y-%m-%d")
            dt = dt.replace(hour=hour, minute=minute, second=0, microsecond=0)
            return dt
        except (ValueError, AttributeError):
            logger.warning("⚠️  日時パース失敗。デフォルト値を使用")
            return datetime.now()

    def _update_preview(self):
        """プレビューを更新"""
        try:
            start_time = self._parse_start_time()
            interval = self._get_selected_interval()

            # スケジュール計算
            self.schedule_preview = self.schedule_mgr.calculate_schedule(
                self.selected_video_ids, start_time, interval
            )

            # プレビュー表示を更新
            for item in self.preview_tree.get_children():
                self.preview_tree.delete(item)

            for i, video_id in enumerate(self.selected_video_ids, 1):
                if video_id in self.schedule_preview:
                    scheduled_at = self.schedule_preview[video_id]
                    scheduled_str = scheduled_at.strftime("%Y-%m-%d %H:%M:%S")
                else:
                    scheduled_str = "計算失敗"

                self.preview_tree.insert(
                    "",
                    tk.END,
                    values=(
                        f"#{i}",
                        video_id[:20] + "..." if len(video_id) > 20 else video_id,
                        scheduled_str,
                    ),
                )

            logger.debug(f"✅ プレビュー更新: {len(self.schedule_preview)} 件")

        except Exception as e:
            logger.error(f"❌ プレビュー更新失敗: {e}")

    def _apply_schedule(self):
        """スケジュールを DB に保存"""
        if not self.schedule_preview:
            messagebox.showwarning("警告", "スケジュール計算に失敗しました。")
            return

        # 確認ダイアログ
        count = len(self.schedule_preview)
        result = messagebox.askyesno(
            "確認",
            f"{count} 件の動画のスケジュールを設定します。\n\nよろしいですか？",
        )

        if not result:
            return

        # DB に保存
        results = self.schedule_mgr.apply_schedule(
            self.schedule_preview, force_overwrite=False
        )

        success_count = sum(1 for v in results.values() if v)
        failed_count = len(results) - success_count

        if success_count > 0:
            messagebox.showinfo(
                "成功",
                f"✅ {success_count} 件のスケジュールを設定しました。"
                + (
                    f"\n⚠️  {failed_count} 件は既に予約済みのためスキップされました。"
                    if failed_count > 0
                    else ""
                ),
            )
            logger.info(f"✅ スケジュール保存完了: {success_count} 件")
            self.destroy()
        else:
            messagebox.showerror(
                "失敗",
                "スケジュール設定に失敗しました。",
            )
            logger.error("❌ スケジュール設定失敗")
