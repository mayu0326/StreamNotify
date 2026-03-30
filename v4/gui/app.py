import tkinter as tk
from tkinter import ttk, messagebox
import logging
from datetime import datetime
from . import styles
from .components.footer import Footer
from .adapter import V3DatabaseAdapter
from v4.core.config import settings

from .components.toolbar import Toolbar
from .components.video_table import VideoTable

logger = logging.getLogger("v4.gui")

class StreamNotifyApp:
    """Main Application Window (v4 Modular)"""
    def __init__(
        self,
        root,
        db: V3DatabaseAdapter,
        show_rss_controls: bool = False,
        show_websub_retry: bool = False,
    ):
        self.root = root
        self.db = db
        self.show_rss_controls = show_rss_controls
        self.show_websub_retry = show_websub_retry
        self.root.title("StreamNotify for Bluesky v4")
        self.root.geometry("1400x800")

        # Apply Theme (resolve and apply current theme setting)
        styles.ThemeManager.apply_theme()
        styles.ThemeManager.configure_ttk_styles(self.root)
        self.root.configure(bg=styles.ThemeManager.COLOR_BG)

        # BatchScheduleManager (lazy-initialized on first use)
        self._schedule_mgr = None

        # Initialize Main Layout
        self.setup_ui()

    def _get_schedule_mgr(self):
        """BatchScheduleManager をシングルトンとして取得"""
        if self._schedule_mgr is None:
            from v4.core.schedule_manager import BatchScheduleManager
            self._schedule_mgr = BatchScheduleManager(self.db)
        return self._schedule_mgr

    def setup_ui(self):
        # 1. Toolbar
        self.toolbar = Toolbar(
            self.root,
            on_refresh=self.refresh_data,
            on_post=self.handle_post,
            on_settings=self.handle_settings,
            on_template_edit=self.handle_template_edit,
            on_bulk_delete=self.handle_bulk_delete,
            on_batch_schedule=self.handle_batch_schedule,
            on_fetch_feed=self.handle_fetch_feed,
            on_classify_live=self.handle_classify_live,
            on_schedule_view=self.handle_schedule_view,
            on_image_assign=self.handle_image_assign,
            on_websub_retry=self.handle_websub_retry,
            show_rss_controls=self.show_rss_controls,
            show_websub_retry=self.show_websub_retry,
        )

        # 2. Main content area (Table)
        self.video_table = VideoTable(
            self.root,
            db=self.db,
            on_selection_change=self.update_button_states,
            on_refresh=self.refresh_data,
        )

        # 3. Footer
        self.footer = Footer(self.root)

        # Initial Data Refresh
        self.refresh_data()

    def refresh_data(self):
        self.footer.set_status("データを読み込み中...")
        self.root.update_idletasks()
        try:
            # Sync with server
            self.db.sync_with_server()
            # Get local videos
            videos = self.db.get_all_videos()
            self.video_table.update_data(videos)
            self.footer.set_status(f"読み込み完了: {len(videos)} 件表示中")
            self.update_button_states()
        except Exception as e:
            logger.error(f"Failed to refresh data: {e}", exc_info=True)
            self.footer.set_status(f"エラー: {e}", is_error=True)

    def handle_post(self):
        selected_ids = self.video_table.get_selected_ids()
        if not selected_ids:
            from tkinter import messagebox
            messagebox.showwarning("警告", "投稿する動画を選択してください")
            return

        if len(selected_ids) == 1:
            from .views.post_dialog import PostDialog
            PostDialog(self.root, selected_ids[0], self.db, on_refresh=self.refresh_data)
        else:
            # Batch posting for multiple selection
            self.footer.set_status(f"一括投稿開始: {len(selected_ids)} 件...")
            for vid_id in selected_ids:
                if self.db.post_to_bluesky(vid_id):
                    self.db.mark_as_posted(vid_id)
            self.footer.set_status(f"一括投稿完了")
            self.refresh_data()

    def handle_bulk_delete(self):
        selected_ids = self.video_table.get_selected_ids()
        if not selected_ids:
            return

        from tkinter import messagebox
        if messagebox.askyesno("確認", f"選択された {len(selected_ids)} 件の動画を削除しますか？"):
            self.footer.set_status(f"一括削除中...")
            for vid_id in selected_ids:
                self.db.delete_video(vid_id)
            self.video_table.selected_ids.clear()
            self.refresh_data()
            self.footer.set_status(f"一括削除が完了しました")

    def handle_batch_schedule(self):
        from tkinter import messagebox
        selected_ids = self.video_table.get_selected_ids()
        if not selected_ids:
            messagebox.showwarning("警告", "スケジュールを設定する動画を選択してください")
            return
        if len(selected_ids) < 2:
            messagebox.showwarning("警告", "一括スケジュールには 2 件以上の動画を選択してください")
            return

        from .dialogs.batch_schedule_dialog import BatchScheduleDialog
        BatchScheduleDialog(self.root, selected_ids, self.db, self._get_schedule_mgr())

    def update_button_states(self):
        selected_ids = self.video_table.get_selected_ids()
        is_selected = len(selected_ids) > 0
        self.toolbar.set_post_state(is_selected)
        self.toolbar.set_schedule_state(is_selected)
        self.toolbar.del_btn.config(state=tk.NORMAL if is_selected else tk.DISABLED)
        # 画像設定は 1 件だけ選択時のみ有効（チェック☑が1つのとき）
        self.toolbar.set_image_assign_state(len(selected_ids) == 1)

    def handle_settings(self):
        from .views.settings_view import SettingsView
        SettingsView(self.root, self.db)

    def handle_template_edit(self):
        from .views.template_editor_view import TemplateEditorView
        TemplateEditorView(self.root, self.db)

    def handle_schedule_view(self):
        """投稿予定一覧を別ウィンドウ表示する。"""
        schedule_window = tk.Toplevel(self.root)
        schedule_window.title("📅 投稿予定一覧")
        schedule_window.geometry("980x620")
        from .views.schedule_view_tab import ScheduleViewTab
        tab = ScheduleViewTab(schedule_window, self.db, self._get_schedule_mgr())
        tab.get_frame().pack(fill=tk.BOTH, expand=True)

    def handle_websub_retry(self):
        """WebSub 不通からの復帰（センター再接続・フォールバック解除）。"""
        self.footer.set_status("WebSub に再接続中...")
        self.root.update_idletasks()
        try:
            ok, err = self.db.retry_websub_and_lift_fallback()
            if ok:
                self.show_rss_controls = False
                self.show_websub_retry = False
                self.toolbar.set_rss_controls_visible(False)
                self.toolbar.set_websub_retry_visible(False)
                messagebox.showinfo(
                    "WebSub",
                    "センターへの接続に成功しました。\n"
                    "Twitch / WebSub / Bluesky OAuth などセンター経由の機能が有効になりました。",
                )
                self.refresh_data()
            else:
                messagebox.showerror("WebSub", f"再接続に失敗しました:\n{err}")
        except Exception as e:
            logger.error("WebSub retry handler failed: %s", e, exc_info=True)
            messagebox.showerror("エラー", str(e))
        finally:
            self.footer.set_status("待機中")

    def handle_fetch_feed(self):
        """RSS/WebSub 設定に応じて手動で最新動画を取得する。"""
        channel_id = getattr(settings, "youtube_channel_id", "")
        if not channel_id:
            messagebox.showerror("エラー", "YouTube チャンネル ID が設定されていません。")
            return
        self.footer.set_status("新着取得中...")
        try:
            added = self.db.fetch_rss_manually()
            self.refresh_data()
            messagebox.showinfo("完了", f"新規追加: {added} 件")
        except Exception as e:
            logger.error("Manual feed fetch failed: %s", e, exc_info=True)
            messagebox.showerror("エラー", f"新着取得に失敗しました: {e}")
        finally:
            self.footer.set_status("待機中")

    def handle_classify_live(self):
        """
        YouTube 動画の手動 Live 判定。
        選択行がある場合は選択対象のみ、なければ最新 YouTube 30 件を対象にする。
        """
        selected_ids = self.video_table.get_selected_ids()
        if not selected_ids:
            youtube_videos = [v for v in self.video_table.all_videos if (v.get("service") or "").lower() == "youtube"]
            selected_ids = [v.get("video_id") for v in youtube_videos[:30] if v.get("video_id")]
        if not selected_ids:
            messagebox.showinfo("情報", "判定対象の YouTube 動画がありません。")
            return
        self.footer.set_status(f"Live判定中... ({len(selected_ids)} 件)")
        try:
            updated = self.db.classify_youtube_live_manually(selected_ids)
            self.refresh_data()
            messagebox.showinfo("完了", f"判定更新: {updated} 件")
        except Exception as e:
            logger.error("Manual live classification failed: %s", e, exc_info=True)
            messagebox.showerror("エラー", f"Live判定に失敗しました: {e}")
        finally:
            self.footer.set_status("待機中")

    def handle_image_assign(self):
        """選択中 1 件の行に画像情報を割り当てる（専用ダイアログを表示）。"""
        selected_ids = self.video_table.get_selected_ids()
        if len(selected_ids) != 1:
            messagebox.showwarning("警告", "画像設定は 1 件だけ選択して実行してください。")
            return
        video_id = selected_ids[0]
        try:
            from .views.image_assign_dialog import ImageAssignDialog
            # on_refresh に refresh_data を渡す
            ImageAssignDialog(self.root, video_id, self.db, on_refresh=self.refresh_data)
        except Exception as e:
            logger.error("Image assignment failed: %s", e, exc_info=True)
            messagebox.showerror("エラー", f"画像設定に失敗しました: {e}")

if __name__ == "__main__":
    # Test execution
    logging.basicConfig(level=logging.INFO)
    root = tk.Tk()
    db = V3DatabaseAdapter()
    app = StreamNotifyApp(root, db)
    root.mainloop()
