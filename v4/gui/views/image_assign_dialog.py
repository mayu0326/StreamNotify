"""
ImageAssignDialog - 行単位の画像設定ダイアログ（v3互換）

v3 の edit_image_file() に相当する機能を v4 向けに移植。
  - ファイル参照 → images/{Site}/import/{video_id}.jpg にコピー＋画像処理
  - URL から直接ダウンロード
  - YouTube サムネイル / ニコニコ OGP の自動取得
  - 登録済み画像のプレビュー
  - 登録済み画像のクリア
"""

import os
import shutil
import logging
import tkinter as tk
from tkinter import ttk, messagebox, filedialog
from pathlib import Path
from typing import Optional

from v4.gui import styles

logger = logging.getLogger("v4.gui.image_assign")

try:
    from PIL import Image, ImageTk
    PIL_AVAILABLE = True
except ImportError:
    PIL_AVAILABLE = False


class ImageAssignDialog:
    """行単位の画像設定ダイアログ"""

    def __init__(self, parent, video_id: str, db, on_refresh=None, on_success_callback=None):
        self.parent = parent
        self.video_id = video_id
        self.db = db
        self.on_refresh = on_refresh
        self.on_success_callback = on_success_callback  # 画像登録成功時の追加コールバック

        # 動画情報を取得
        self.video = db.get_video_by_id(video_id)
        if not self.video:
            messagebox.showerror("エラー", f"動画情報が見つかりません: {video_id}")
            return

        self.service = (self.video.get("service") or "youtube").lower()
        self.site_dir = self._normalize_site_dir(self.service)

        # Import ディレクトリ（v4/images/{Site}/import/）
        try:
            from v4.core.assets.images import image_manager
            self.import_dir: Path = image_manager.base_dir / self.site_dir / "import"
        except Exception:
            self.import_dir = Path("v4") / "images" / self.site_dir / "import"
        self.import_dir.mkdir(parents=True, exist_ok=True)

        self._build_window()

    # ------------------------------------------------------------------ #
    # helpers
    # ------------------------------------------------------------------ #

    @staticmethod
    def _normalize_site_dir(service: str) -> str:
        mapping = {"youtube": "YouTube", "niconico": "Niconico", "twitch": "Twitch"}
        return mapping.get(service.lower(), "YouTube")

    def _get_current_image_path(self) -> Optional[Path]:
        """DB に登録済みの画像ファイルパスを返す。見つからなければ None。"""
        filename = self.video.get("image_filename")
        if not filename:
            return None
        # import → autopost の順で探す
        for mode in ("import", "autopost"):
            p = self.import_dir.parent / mode / filename
            if p.exists():
                return p
        return None

    # ------------------------------------------------------------------ #
    # UI
    # ------------------------------------------------------------------ #

    def _build_window(self):
        win = tk.Toplevel(self.parent)
        win.title(f"🖼️ 画像ファイル設定 - {self.video_id}")
        win.geometry("580x520")
        win.resizable(False, False)
        win.transient(self.parent)
        win.grab_set()
        self.window = win

        styles.ThemeManager.apply_theme()
        win.configure(bg=styles.ThemeManager.COLOR_BG)

        # --- ヘッダー ---
        hdr = ttk.Frame(win, padding=(10, 8, 10, 0))
        hdr.pack(fill=tk.X)
        ttk.Label(hdr, text=f"動画ID: {self.video_id}", font=styles.FONT_BOLD).pack(anchor=tk.W)
        title = (self.video.get("title") or "")[:55]
        ttk.Label(
            hdr,
            text=f"タイトル: {title}",
            font=styles.FONT_MAIN,
            foreground=styles.ThemeManager.COLOR_TEXT_SECONDARY,
        ).pack(anchor=tk.W)
        ttk.Label(
            hdr,
            text=f"サービス: {self.site_dir}  |  保存先: {self.import_dir}",
            font=styles.FONT_MAIN,
            foreground=styles.ThemeManager.COLOR_TEXT_SECONDARY,
        ).pack(anchor=tk.W)
        ttk.Separator(win).pack(fill=tk.X, padx=10, pady=6)

        # --- 登録済み画像 ---
        cur_frame = ttk.LabelFrame(win, text="登録済み画像", padding=8)
        cur_frame.pack(fill=tk.X, padx=10, pady=(0, 4))

        cur_file = self.video.get("image_filename") or "（未登録）"
        self.cur_image_var = tk.StringVar(value=cur_file)
        ttk.Label(cur_frame, textvariable=self.cur_image_var,
                  foreground="blue", font=styles.FONT_MAIN).pack(side=tk.LEFT, anchor=tk.W)
        ttk.Button(cur_frame, text="プレビュー", command=self._preview_image).pack(
            side=tk.RIGHT, padx=4
        )

        # --- ファイル参照 ---
        file_frame = ttk.LabelFrame(
            win, text=f"ファイルから選択（{self.site_dir}/import に保存）", padding=8
        )
        file_frame.pack(fill=tk.X, padx=10, pady=4)

        row1 = ttk.Frame(file_frame)
        row1.pack(fill=tk.X)
        self.file_var = tk.StringVar()
        ttk.Entry(row1, textvariable=self.file_var, width=42).pack(side=tk.LEFT)
        ttk.Button(row1, text="📂 参照", command=self._browse_file).pack(side=tk.LEFT, padx=4)

        # --- URL ダウンロード ---
        url_frame = ttk.LabelFrame(win, text="URL から画像をダウンロード", padding=8)
        url_frame.pack(fill=tk.X, padx=10, pady=4)

        row2 = ttk.Frame(url_frame)
        row2.pack(fill=tk.X)
        thumb_url = self.video.get("thumbnail_url") or ""
        self.url_var = tk.StringVar(value=thumb_url)
        ttk.Entry(row2, textvariable=self.url_var, width=42).pack(side=tk.LEFT)
        ttk.Button(row2, text="⬇️ DL", command=self._download_from_url).pack(side=tk.LEFT, padx=4)

        # --- 自動取得 ---
        auto_frame = ttk.LabelFrame(win, text="自動取得", padding=8)
        auto_frame.pack(fill=tk.X, padx=10, pady=4)

        if self.service == "youtube":
            ttk.Button(
                auto_frame, text="YouTube サムネイルを自動取得", command=self._fetch_youtube
            ).pack(side=tk.LEFT, padx=4)
        elif self.service == "niconico":
            ttk.Button(
                auto_frame, text="OGP からニコニコサムネイルを取得", command=self._fetch_niconico
            ).pack(side=tk.LEFT, padx=4)

        # --- ボタン行 ---
        ttk.Separator(win).pack(fill=tk.X, padx=10, pady=6)
        btn_row = ttk.Frame(win, padding=(10, 0))
        btn_row.pack(fill=tk.X)

        ttk.Button(btn_row, text="✅ 保存", command=self._save).pack(side=tk.LEFT, padx=4)
        ttk.Button(btn_row, text="🗑️ 画像をクリア", command=self._clear_image).pack(side=tk.LEFT, padx=4)
        ttk.Button(btn_row, text="❌ キャンセル", command=win.destroy).pack(side=tk.RIGHT, padx=4)

    # ------------------------------------------------------------------ #
    # actions
    # ------------------------------------------------------------------ #

    def _browse_file(self):
        """任意フォルダからファイルを選択し、import ディレクトリへコピー＋リネーム＋処理。"""
        filetypes = [("画像ファイル", "*.png;*.jpg;*.jpeg;*.gif;*.webp"), ("すべて", "*")]
        path = filedialog.askopenfilename(
            parent=self.window,
            title="画像を選択",
            initialdir=os.path.expanduser("~"),
            filetypes=filetypes,
        )
        if not path or not os.path.isfile(path):
            return

        # ファイル名を {video_id}.jpg に統一（v3互換）
        standardized = f"{self.video_id}.jpg"
        dest = self.import_dir / standardized

        try:
            shutil.copy2(path, dest)
            logger.info(f"画像コピー: {path} → {dest}")
        except Exception as e:
            messagebox.showerror("エラー", f"ファイルのコピーに失敗しました:\n{e}")
            return

        # 画像処理（リサイズ・JPG変換）
        self._process_image(dest)

        # DB に登録
        if self.db.update_image_info(self.video_id, image_mode="import", image_filename=standardized):
            self.video["image_filename"] = standardized
            self.cur_image_var.set(standardized)
            self.file_var.set(standardized)
            logger.info(f"✅ 画像をコピーして登録しました: {self.video_id} -> {standardized}")
            # 成功コールバック（親ダイアログの表示更新など）
            if self.on_success_callback:
                self.on_success_callback(standardized)
            messagebox.showinfo("成功", f"画像を登録しました:\n{standardized}")
            if self.on_refresh:
                self.on_refresh()
            self.window.destroy()
        else:
            messagebox.showerror("エラー", "DB への登録に失敗しました。")

    def _download_from_url(self):
        url = self.url_var.get().strip()
        if not url:
            messagebox.showwarning("警告", "URL を入力してください。")
            return
        self._download_and_register(url)

    def _fetch_youtube(self):
        try:
            from v4.core.assets.image_manager import get_youtube_thumbnail_url
            url = get_youtube_thumbnail_url(self.video_id)
        except Exception as e:
            messagebox.showerror("エラー", f"サムネイル URL の取得に失敗しました:\n{e}")
            return
        if not url:
            messagebox.showwarning("警告", "YouTube サムネイル URL を取得できませんでした。")
            return
        self._download_and_register(url)

    def _fetch_niconico(self):
        try:
            from v4.thumbnails_v4.niconico_ogp_utils import get_niconico_ogp_url
            url = get_niconico_ogp_url(self.video_id)
        except Exception as e:
            messagebox.showerror("エラー", f"OGP 取得に失敗しました:\n{e}")
            return
        if not url:
            messagebox.showwarning("警告", "OGP からサムネイル URL を取得できませんでした。")
            return
        self._download_and_register(url)

    def _download_and_register(self, url: str):
        """URL からサムネイルをダウンロードして import ディレクトリに保存・DB 登録。"""
        try:
            from v4.core.assets.image_manager import get_image_manager
            mgr = get_image_manager()
            filename = mgr.download_and_save_thumbnail(
                thumbnail_url=url,
                site=self.site_dir,
                video_id=self.video_id,
                mode="import",
            )
        except Exception as e:
            messagebox.showerror("エラー", f"ダウンロードに失敗しました:\n{e}")
            return

        if not filename:
            messagebox.showerror("エラー", "画像のダウンロードに失敗しました。")
            return

        if self.db.update_image_info(self.video_id, image_mode="import", image_filename=filename):
            self.video["image_filename"] = filename
            self.cur_image_var.set(filename)
            logger.info(f"✅ 画像を登録しました: {self.video_id} -> {filename}")
            # 成功コールバック（親ダイアログの表示更新など）
            if self.on_success_callback:
                self.on_success_callback(filename)
            messagebox.showinfo("成功", f"画像を取得・登録しました:\n{filename}")
            if self.on_refresh:
                self.on_refresh()
            self.window.destroy()
        else:
            messagebox.showerror("エラー", "DB への登録に失敗しました。")

    def _save(self):
        """ファイル名テキスト入力から手動保存。"""
        filename = self.file_var.get().strip()
        if not filename:
            messagebox.showwarning("警告", "ファイル名を入力してください。")
            return

        dest = self.import_dir / filename
        if not dest.exists():
            if not messagebox.askyesno(
                "確認",
                f"画像ファイル '{filename}' が見つかりません。\nそれでも設定しますか？",
            ):
                return

        if self.db.update_image_info(self.video_id, image_mode="import", image_filename=filename):
            self.cur_image_var.set(filename)
            messagebox.showinfo("成功", f"画像情報を保存しました:\n{filename}")
            if self.on_refresh:
                self.on_refresh()
            self.window.destroy()
        else:
            messagebox.showerror("エラー", "DB への保存に失敗しました。")

    def _clear_image(self):
        if not messagebox.askyesno("確認", "登録済みの画像情報をクリアしますか？"):
            return
        if self.db.update_image_info(self.video_id, image_mode=None, image_filename=None):
            self.cur_image_var.set("（未登録）")
            self.file_var.set("")
            messagebox.showinfo("成功", "画像情報をクリアしました。")
            if self.on_refresh:
                self.on_refresh()
            self.window.destroy()
        else:
            messagebox.showerror("エラー", "クリアに失敗しました。")

    def _preview_image(self):
        """登録済み画像をプレビューウィンドウに表示。"""
        path = self._get_current_image_path()
        if not path:
            messagebox.showinfo("情報", "登録済みの画像ファイルが見つかりません。")
            return

        if not PIL_AVAILABLE:
            messagebox.showinfo("情報", f"画像パス:\n{path}\n\n(Pillow 未インストールのためプレビュー不可)")
            return

        try:
            img = Image.open(path)
            img.thumbnail((400, 300), Image.LANCZOS)
            photo = ImageTk.PhotoImage(img)

            prev_win = tk.Toplevel(self.window)
            prev_win.title(f"プレビュー - {path.name}")
            prev_win.resizable(False, False)
            prev_win.configure(bg=styles.ThemeManager.COLOR_BG)

            lbl = ttk.Label(prev_win, image=photo)
            lbl.image = photo  # GC防止
            lbl.pack(padx=10, pady=10)
            ttk.Label(prev_win, text=str(path), font=styles.FONT_MAIN,
                      foreground=styles.ThemeManager.COLOR_TEXT_SECONDARY).pack(padx=10, pady=(0, 8))
            ttk.Button(prev_win, text="閉じる", command=prev_win.destroy).pack(pady=(0, 8))
        except Exception as e:
            messagebox.showerror("エラー", f"プレビューの表示に失敗しました:\n{e}")

    @staticmethod
    def _process_image(path: Path):
        """PIL で画像をリサイズ・JPG 変換する（失敗しても続行）。"""
        if not PIL_AVAILABLE:
            return
        try:
            img = Image.open(path).convert("RGB")
            # 最大 1280×720 にリサイズ（大きい場合のみ）
            img.thumbnail((1280, 720), Image.LANCZOS)
            img.save(path, "JPEG", quality=85, optimize=True)
            logger.info(f"画像処理完了: {path}")
        except Exception as e:
            logger.warning(f"画像処理スキップ（元ファイルを使用）: {e}")
