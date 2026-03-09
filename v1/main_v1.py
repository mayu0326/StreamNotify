# -*- coding: utf-8 -*-

"""
StreamNotify on Bluesky- v1 メインスクリプト（GUI 統合版）

特定の YouTube チャンネルの新着動画を RSS で監視し、
DB に蓄積。投稿対象は GUI で選択。
蓄積モード時は投稿なし。

GUI はマルチスレッドで動作（メインループは継続）
"""

import logging
import os
import signal
import sys
import threading
import time
import tkinter as tk
from datetime import datetime
from logging.handlers import RotatingFileHandler
from tkinter import messagebox, ttk


# ロギング設定
def setup_logging():
    """ロギングを設定"""
    os.makedirs("logs", exist_ok=True)

    logger = logging.getLogger("AppLogger")
    logger.setLevel(logging.DEBUG)

    # ファイルハンドラ
    fh = RotatingFileHandler(
        "logs/app.log",
        maxBytes=10*1024*1024,
        backupCount=5,
        encoding="utf-8"
    )
    fh.setLevel(logging.DEBUG)

    # コンソールハンドラ
    ch = logging.StreamHandler()
    ch.setLevel(logging.INFO)

    formatter = logging.Formatter(
        "%(asctime)s - %(name)s - %(levelname)s - %(message)s"
    )
    fh.setFormatter(formatter)
    ch.setFormatter(formatter)

    logger.addHandler(fh)
    logger.addHandler(ch)

    return logger

logger = setup_logging()

__author__ = "mayuneco(mayunya)"
__copyright__ = "Copyright (C) 2025 mayuneco(mayunya)"
__license__ = "GPLv2"


class YouTubeNotifierGUI:
    """YouTube Notifier GUI（統合版）"""

    def __init__(self, root, db, bluesky_plugin=None):
        self.root = root
        self.root.title("YouTube → Bluesky Notifier - DB 管理")
        self.root.geometry("1400x750")

        self.db = db
        self.bluesky_plugin = bluesky_plugin
        self.selected_rows = set()

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
        ttk.Separator(toolbar, orient=tk.VERTICAL).pack(side=tk.LEFT, fill=tk.Y, padx=2)
        ttk.Button(toolbar, text="🧪 ドライラン", command=self.dry_run_post).pack(side=tk.LEFT, padx=2)
        ttk.Button(toolbar, text="📤 投稿実行", command=self.execute_post).pack(side=tk.LEFT, padx=2)
        ttk.Separator(toolbar, orient=tk.VERTICAL).pack(side=tk.LEFT, fill=tk.Y, padx=2)
        ttk.Button(toolbar, text="ℹ️ 統計", command=self.show_stats).pack(side=tk.LEFT, padx=2)

        table_frame = ttk.Frame(self.root)
        table_frame.pack(fill=tk.BOTH, expand=True, padx=5, pady=5)

        columns = ("Select", "Video ID", "Published", "Title", "Posted", "Scheduled")
        self.tree = ttk.Treeview(table_frame, columns=columns, height=20, show="headings")

        self.tree.column("Select", width=50, anchor=tk.CENTER)
        self.tree.column("Video ID", width=110)
        self.tree.column("Published", width=130)
        self.tree.column("Title", width=700)
        self.tree.column("Posted", width=60, anchor=tk.CENTER)
        self.tree.column("Scheduled", width=150)

        self.tree.heading("Select", text="☑️")
        self.tree.heading("Video ID", text="Video ID")
        self.tree.heading("Published", text="公開日時")
        self.tree.heading("Title", text="タイトル")
        self.tree.heading("Posted", text="投稿済み")
        self.tree.heading("Scheduled", text="予約日時")

        scrollbar = ttk.Scrollbar(table_frame, orient=tk.VERTICAL, command=self.tree.yview)
        self.tree.configure(yscroll=scrollbar.set)

        self.tree.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)
        scrollbar.pack(side=tk.RIGHT, fill=tk.Y)

        self.tree.bind("<Button-1>", self.on_tree_click)
        self.tree.bind("<Double-1>", self.on_tree_double_click)

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

        self.tree.tag_configure("even", background="#f0f0f0")
        self.tree.tag_configure("odd", background="white")

        self.status_label.config(text=f"読み込み完了: {len(videos)} 件の動画（選択: {len(self.selected_rows)} 件）")

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
        """Treeview の「予約日時」列をダブルクリックして編集"""
        item_id = self.tree.identify_row(event.y)
        col = self.tree.identify_column(event.x)

        if not item_id or col != "#6":
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

        messagebox.showinfo("成功", f"{len(self.selected_rows)} 件の選択状態を保存しました。")
        self.refresh_data()

    def edit_scheduled_time(self, video_id):
        """予約日時をダイアログで編集"""
        edit_window = tk.Toplevel(self.root)
        edit_window.title(f"予約日時設定 - {video_id}")
        edit_window.geometry("350x200")
        edit_window.resizable(False, False)

        ttk.Label(edit_window, text=f"動画: {video_id}", font=("Arial", 10, "bold")).pack(pady=5)
        ttk.Label(edit_window, text="予約投稿日時を設定します", foreground="gray").pack(pady=5)

        ttk.Label(edit_window, text="日時 (YYYY-MM-DD HH:MM):").pack(pady=5)

        entry = ttk.Entry(edit_window, width=35)
        entry.pack(pady=5, padx=10)

        from datetime import timedelta
        default_time = (datetime.now() + timedelta(minutes=5)).strftime("%Y-%m-%d %H:%M")
        entry.insert(0, default_time)
        entry.selection_range(0, tk.END)
        entry.focus()

        quick_frame = ttk.LabelFrame(edit_window, text="クイック設定", padding=10)
        quick_frame.pack(pady=10, padx=10, fill=tk.X)

        def set_quick_time(minutes):
            from datetime import timedelta
            quick_time = (datetime.now() + timedelta(minutes=minutes)).strftime("%Y-%m-%d %H:%M")
            entry.delete(0, tk.END)
            entry.insert(0, quick_time)

        ttk.Button(quick_frame, text="5分後", command=lambda: set_quick_time(5)).pack(side=tk.LEFT, padx=2)
        ttk.Button(quick_frame, text="15分後", command=lambda: set_quick_time(15)).pack(side=tk.LEFT, padx=2)
        ttk.Button(quick_frame, text="30分後", command=lambda: set_quick_time(30)).pack(side=tk.LEFT, padx=2)

        button_frame = ttk.Frame(edit_window)
        button_frame.pack(pady=10)

        def save_time():
            scheduled = entry.get().strip()

            try:
                datetime.fromisoformat(scheduled)
            except ValueError:
                messagebox.showerror("エラー", "無効な日時形式です。\nYYYY-MM-DD HH:MM")
                return

            self.db.update_selection(video_id, selected=True, scheduled_at=scheduled)
            self.selected_rows.add(video_id)

            messagebox.showinfo("成功", f"予約日時を設定しました。\n{scheduled}")
            edit_window.destroy()
            self.refresh_data()

        ttk.Button(button_frame, text="保存", command=save_time).pack(side=tk.LEFT, padx=5)
        ttk.Button(button_frame, text="キャンセル", command=edit_window.destroy).pack(side=tk.LEFT, padx=5)

    def dry_run_post(self):
        """ドライラン：選択された動画をログ出力のみ（実際には投稿しない）"""
        # GUI の selected_rows から直接取得（DB ではなく）
        if not self.selected_rows:
            messagebox.showwarning("警告", "投稿対象の動画がありません。\n\n☑️ をクリックして選択してください。")
            return

        videos = self.db.get_all_videos()
        selected = [v for v in videos if v["video_id"] in self.selected_rows]

        if not selected:
            messagebox.showwarning("警告", "投稿対象の動画がありません。\n\n選択して保存してから実行してください。")
            return

        # ドライランメッセージ
        msg = f"""
🧪 ドライラン モード

以下の {len(selected)} 件をテスト投稿（ログ出力のみ）します：

"""
        for v in selected[:5]:  # 最初の 5 件表示
            msg += f"  ✓ {v['title'][:50]}...\n"

        if len(selected) > 5:
            msg += f"  ... ほか {len(selected) - 5} 件\n"

        msg += f"""
メインログに [DRY RUN] と表示されます。
実際には投稿されません。
        """

        if messagebox.askyesno("確認", msg):
            for video in selected:
                logger.info(f"[DRY RUN - GUI] 投稿予定: {video['title']}")

            messagebox.showinfo("完了", f"{len(selected)} 件のドライラン実行をログに出力しました。\nコンソールログを確認してください。")

    def execute_post(self):
        """投稿実行：選択された動画を実際に Bluesky に投稿（投稿済みフラグをスルー）"""
        if not self.bluesky_plugin:
            messagebox.showerror("エラー", "Bluesky プラグインが初期化されていません。\nBLUESKY_POST_ENABLED=true で再起動してください。")
            return

        # GUI の selected_rows から直接取得（DB ではなく）
        if not self.selected_rows:
            messagebox.showwarning("警告", "投稿対象の動画がありません。\n\n☑️ をクリックして選択してください。")
            return

        videos = self.db.get_all_videos()
        # 投稿済みフラグをスルー（posted_to_bluesky チェックを削除）
        selected = [v for v in videos if v["video_id"] in self.selected_rows]

        if not selected:
            messagebox.showwarning("警告", "投稿対象の動画がありません。\n\n選択して保存してから実行してください。")
            return

        # 確認ダイアログ
        msg = f"""
📤 投稿実行 - 確認

以下の {len(selected)} 件を Bluesky に投稿します：

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

        # 投稿実行
        success_count = 0
        fail_count = 0

        for video in selected:
            try:
                logger.info(f"📤 投稿実行（GUI）: {video['title']}")
                if self.bluesky_plugin.post_video(video):
                    self.db.mark_as_posted(video["video_id"])
                    self.db.update_selection(video["video_id"], selected=False, scheduled_at=None)
                    success_count += 1
                    logger.info(f"✅ 投稿成功（GUI）: {video['title']}")
                else:
                    fail_count += 1
                    logger.warning(f"❌ 投稿失敗（GUI）: {video['title']}")
            except Exception as e:
                fail_count += 1
                logger.error(f"❌ 投稿エラー（GUI）: {video['title']} - {e}")

        # 結果表示
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
2. 「予約日時」をダブルクリック → 投稿日時を設定
3. 「💾 選択を保存」 → DB に反映
4. 「🧪 ドライラン」 → テスト実行
5. 「📤 投稿実行」 → 実投稿

⚠️ 注意
━━━━━━━━━━━━━━━━━
投稿済みフラグに関わらず投稿できます。
重複投稿にご注意ください。
        """

        messagebox.showinfo("統計情報", stats)


def run_gui(db, bluesky_plugin, stop_event):
    """GUI をスレッドで実行"""
    root = tk.Tk()
    gui = YouTubeNotifierGUI(root, db, bluesky_plugin)

    def on_closing():
        stop_event.set()
        root.destroy()

    root.protocol("WM_DELETE_WINDOW", on_closing)
    root.mainloop()


def signal_handler(signum, frame):
    """シグナルハンドラ"""
    logger.info("\n[INFO] アプリケーションを終了します...")
    sys.exit(0)


def main():
    """メインエントリポイント"""
    try:
        logger.info("設定を読み込んでいます...")
        from config import get_config
        config = get_config("settings.env")
        logger.info(f"設定を読み込みました。ポーリング間隔: {config.poll_interval_minutes} 分")

    except Exception as e:
        logger.error(f"設定の読み込みに失敗しました: {e}")
        sys.exit(1)

    try:
        logger.info("データベースを初期化しています...")
        from database import get_database
        db = get_database()

        if db.is_first_run:
            logger.info("🆕 初回起動です。蓄積モードで動作します。")

        logger.info("データベースを初期化しました")

    except Exception as e:
        logger.error(f"データベースの初期化に失敗しました: {e}")
        sys.exit(1)

    try:
        logger.info("YouTube RSS を初期化しています...")
        from youtube_rss import get_youtube_rss
        yt_rss = get_youtube_rss(config.youtube_channel_id)

        bluesky_plugin = None
        if not config.is_collect_mode:
            logger.info("Bluesky を初期化しています...")
            from bluesky_plugin import get_bluesky_plugin

            bluesky_plugin = get_bluesky_plugin(
                config.bluesky_username,
                config.bluesky_password,
                dry_run=not config.bluesky_post_enabled
            )

        logger.info("初期化完了しました")

    except Exception as e:
        logger.error(f"初期化に失敗しました: {e}")
        sys.exit(1)

    logger.info("YouTube → Bluesky Notifier v1 を起動しました")
    logger.info(f"ポーリング間隔: {config.poll_interval_minutes} 分")

    if config.is_collect_mode:
        logger.warning("📦 蓄積モード で動作します。投稿は行いません。")
    else:
        logger.info("🔄 運用モード で動作します。投稿対象は GUI で選択してください。")

    # GUI をスレッドで起動（bluesky_plugin を渡す）
    stop_event = threading.Event()
    gui_thread = threading.Thread(target=run_gui, args=(db, bluesky_plugin, stop_event), daemon=True)
    gui_thread.start()
    logger.info("✅ GUI を起動しました。別ウィンドウを確認してください。")

    # メインループ
    polling_count = 0
    last_post_time = None
    POST_INTERVAL_MINUTES = 5

    try:
        while not stop_event.is_set():
            polling_count += 1
            logger.info(f"\n=== ポーリング #{polling_count} ===")
            logger.info(f"実行時刻: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")

            logger.info("YouTube RSS を取得しています...")
            saved_count = yt_rss.save_to_db(db)
            logger.info(f"{saved_count} 個の新着動画を保存しました")

            if config.is_collect_mode:
                logger.info("蓄積モード のため、投稿処理をスキップします。")
            else:
                now = datetime.now()
                should_post = last_post_time is None or (now - last_post_time).total_seconds() >= POST_INTERVAL_MINUTES * 60

                if should_post:
                    selected_video = db.get_selected_videos()

                    if selected_video:
                        logger.info(f"投稿対象を発見しました: {selected_video['title']}")

                        if bluesky_plugin.post_video(selected_video):
                            db.mark_as_posted(selected_video['video_id'])
                            last_post_time = now
                            logger.info(f"✅ 投稿完了。次の投稿は {POST_INTERVAL_MINUTES} 分後です。")
                        else:
                            logger.warning(f"❌ 投稿に失敗しました: {selected_video['title']}")
                    else:
                        logger.info("投稿対象の動画がありません。GUI で選択してください。")
                else:
                    elapsed = (now - last_post_time).total_seconds() / 60
                    remaining = POST_INTERVAL_MINUTES - elapsed
                    logger.info(f"投稿間隔制限中。次の投稿まで約 {remaining:.1f} 分待機。")

            logger.info(f"次のポーリングまで {config.poll_interval_minutes} 分待機中...")
            time.sleep(config.poll_interval_minutes * 60)

    except KeyboardInterrupt:
        logger.info("\n[INFO] ユーザーによる中断")
        sys.exit(0)
    except Exception as e:
        logger.error(f"予期せぬエラーが発生しました: {e}", exc_info=True)
        sys.exit(1)


if __name__ == "__main__":
    signal.signal(signal.SIGINT, signal_handler)
    if sys.platform.startswith('win'):
        signal.signal(signal.SIGBREAK, signal_handler)

    main()
