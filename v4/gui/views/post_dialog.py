import tkinter as tk
from tkinter import ttk, messagebox
import logging
import os
from pathlib import Path
from typing import Optional
from .. import styles

logger = logging.getLogger("v4.gui.views")

try:
    from PIL import Image
    PIL_AVAILABLE = True
except ImportError:
    PIL_AVAILABLE = False


class PostDialog:
    """投稿設定ウィンドウ - v3 PostSettingsWindow に内容を寄せた動画の投稿設定"""
    def __init__(self, parent, video_id, db_adapter, on_refresh=None):
        self.parent = parent
        self.video_id = video_id
        self.db = db_adapter
        self.on_refresh = on_refresh  # 投稿成功後に一覧を再読込するコールバック
        self.image_path: Optional[str] = None  # setup_ui で上書き
        self._preview_photo = None  # GC防止

        # Window setup
        self.window = tk.Toplevel(parent)
        self.window.title("📤 投稿設定")
        self.window.geometry("700x680")
        self.window.resizable(False, False)
        self.window.transient(parent)
        self.window.grab_set()
        self.window.configure(bg=styles.ThemeManager.COLOR_BG)

        self.video = self._fetch_video()
        if not self.video:
            messagebox.showerror("エラー", "動画情報が見つかりません")
            self.window.destroy()
            return

        self.setup_ui()
        # タイトルを動画名で更新
        title = (self.video.get("title") or self.video_id)[:50]
        if len(self.video.get("title") or "") > 50:
            title += "..."
        self.window.title(f"📤 投稿設定 - {title}")

    def _fetch_video(self):
        return self.db.get_video_by_id(self.video_id)

    def setup_ui(self):
        pad = 10
        main_frame = ttk.Frame(self.window)
        main_frame.pack(fill=tk.X, expand=False, padx=pad, pady=pad, side=tk.TOP)

        # === 1. 動画情報 (v3 同様 grid) ===
        info_frame = ttk.LabelFrame(main_frame, text="📹 動画情報", padding=pad)
        info_frame.pack(fill=tk.X, pady=(0, 10))

        ttk.Label(info_frame, text="タイトル:", font=("", 10, "bold")).grid(row=0, column=0, sticky=tk.W)
        title_text = (self.video.get("title") or "")[:80]
        if len(self.video.get("title") or "") > 80:
            title_text += "..."
        tm = styles.ThemeManager
        ttk.Label(info_frame, text=title_text, foreground=tm.COLOR_LABEL_ACCENT, wraplength=550).grid(row=0, column=1, sticky=tk.W, columnspan=2)

        ttk.Label(info_frame, text="ソース:", font=("", 10, "bold")).grid(row=1, column=0, sticky=tk.W)
        source_text = (self.video.get("service") or self.video.get("source") or "youtube").upper()
        ttk.Label(info_frame, text=source_text, foreground=tm.COLOR_LABEL_SUCCESS).grid(row=1, column=1, sticky=tk.W)

        ttk.Label(info_frame, text="公開日時:", font=("", 10, "bold")).grid(row=2, column=0, sticky=tk.W)
        ttk.Label(info_frame, text=self.video.get("published_at") or "不明").grid(row=2, column=1, sticky=tk.W)

        # === 2. 投稿状況 (v3 同様) ===
        status_frame = ttk.LabelFrame(main_frame, text="📊 投稿状況", padding=pad)
        status_frame.pack(fill=tk.X, pady=(0, 10))

        posted = self.video.get("posted_to_bluesky")
        posted_status = "✅ 投稿済み" if posted else "❌ 未投稿"
        posted_date = self.video.get("posted_at") or "—"
        ttk.Label(status_frame, text=f"投稿実績: {posted_status} ({posted_date})", font=("", 10)).pack(anchor=tk.W, pady=(0, 5))

        scheduled_at = self.video.get("scheduled_at") or self.video.get("scheduled_start_time")
        if scheduled_at:
            schedule_text = f"投稿予約: 予約あり ({scheduled_at})"
            schedule_color = tm.COLOR_LABEL_SUCCESS
        else:
            schedule_text = "投稿予約: 予約なし"
            schedule_color = tm.COLOR_LABEL_MUTED
        ttk.Label(status_frame, text=schedule_text, foreground=schedule_color, font=("", 10)).pack(anchor=tk.W)

        # === 3. DB画像の設定 + プレビュー (v3 同様) ===
        image_frame = ttk.LabelFrame(main_frame, text="🖼️ DB画像の設定", padding=pad)
        image_frame.pack(fill=tk.X, pady=(0, 5))

        db_image_path = self._resolve_db_image()
        if db_image_path:
            self.image_path = str(db_image_path)
            image_filename = db_image_path.name
        else:
            self.image_path = None
            image_filename = self.video.get("image_filename")

        image_info_frame = ttk.Frame(image_frame)
        image_info_frame.pack(fill=tk.X, expand=True)

        if image_filename:
            image_text = f"✅ ファイル: {image_filename}"
            image_color = tm.COLOR_LABEL_ACCENT
        else:
            image_text = "❌ なし"
            image_color = tm.COLOR_LABEL_MUTED
        ttk.Label(image_info_frame, text=image_text, foreground=image_color, font=("", 10, "bold")).pack(anchor=tk.W)

        if image_filename and db_image_path:
            self._display_image_preview(image_info_frame, db_image_path)

        thumb_url = self.video.get("thumbnail_url")
        if thumb_url:
            self.use_thumb_var = tk.BooleanVar(value=False)
            ttk.Checkbutton(
                image_frame,
                text="サムネイルを自動取得して添付",
                variable=self.use_thumb_var,
                command=self._toggle_auto_thumb,
            ).pack(anchor=tk.W, pady=(4, 0))

        # === 4. 投稿方法 (v3 同様 ラジオ) ===
        post_method_frame = ttk.LabelFrame(main_frame, text="📋 投稿方法", padding=pad)
        post_method_frame.pack(fill=tk.X, pady=(0, 10))

        has_image = bool(self.image_path)
        self.use_image_var = tk.BooleanVar(value=has_image)
        self._radio_attach = None
        if not has_image:
            self.use_image_var.set(False)
            self._radio_attach = ttk.Radiobutton(
                post_method_frame,
                text="🖼️ 画像を添付",
                variable=self.use_image_var,
                value=True,
                state=tk.DISABLED,
            )
            self._radio_attach.pack(anchor=tk.W, pady=5)
            ttk.Radiobutton(
                post_method_frame,
                text="🔗 URLリンクカード（画像なし）",
                variable=self.use_image_var,
                value=False,
                state=tk.DISABLED,
            ).pack(anchor=tk.W, pady=5)
            ttk.Label(
                post_method_frame,
                text="⚠️ DB画像がないため、URLリンクカードのみ利用可能（画像を選択すると画像添付が選べます）",
                foreground=tm.COLOR_LABEL_WARNING,
            ).pack(anchor=tk.W, padx=20)
        else:
            self._radio_attach = ttk.Radiobutton(
                post_method_frame,
                text="🖼️ 画像を添付",
                variable=self.use_image_var,
                value=True,
            )
            self._radio_attach.pack(anchor=tk.W, pady=5)
            ttk.Radiobutton(
                post_method_frame,
                text="🔗 URLリンクカード",
                variable=self.use_image_var,
                value=False,
            ).pack(anchor=tk.W, pady=5)

        # === 5. 小さい画像の加工 (v3 同様) ===
        small_image_frame = ttk.LabelFrame(main_frame, text="🎨 小さい画像の加工", padding=pad)
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
            foreground=tm.COLOR_LABEL_MUTED,
            font=("", 9),
        ).pack(anchor=tk.W, padx=5)

        # === ボタン (v3 同様) ===
        btn_frame = ttk.Frame(self.window)
        btn_frame.pack(fill=tk.X, padx=pad, pady=pad, side=tk.BOTTOM)

        ttk.Button(btn_frame, text="✅ 確定して投稿", command=lambda: self.execute_post(dry_run=False)).pack(side=tk.RIGHT, padx=5)
        ttk.Button(btn_frame, text="❌ キャンセル", command=self.window.destroy).pack(side=tk.RIGHT, padx=5)
        ttk.Button(btn_frame, text="🧪 投稿テスト", command=lambda: self.execute_post(dry_run=True)).pack(side=tk.RIGHT, padx=5)

    def _display_image_preview(self, parent_frame: ttk.Frame, image_path: Path):
        """画像プレビューを表示（解像度・サイズ・サムネイル）- v3 同様"""
        tm = styles.ThemeManager
        if not PIL_AVAILABLE:
            ttk.Label(parent_frame, text="⚠️ PIL (Pillow) がインストールされていないため、プレビューは表示できません", foreground=tm.COLOR_LABEL_WARNING).pack(anchor=tk.W, pady=5)
            return
        try:
            if not image_path.exists():
                ttk.Label(parent_frame, text=f"⚠️ 画像ファイルが見つかりません: {image_path.name}", foreground=tm.COLOR_LABEL_WARNING).pack(anchor=tk.W, pady=5)
                return
            preview_container = ttk.Frame(parent_frame)
            preview_container.pack(fill=tk.X, pady=5)
            info_frame = ttk.Frame(preview_container)
            info_frame.pack(side=tk.LEFT, fill=tk.BOTH, expand=True, padx=(0, 10))
            with Image.open(image_path) as img_info:
                w, h = img_info.size
                size_kb = image_path.stat().st_size / 1024
                ttk.Label(info_frame, text=f"解像度: {w}×{h} px\nサイズ: {size_kb:.1f} KB", foreground=tm.COLOR_LABEL_MUTED, font=("", 9), justify=tk.LEFT).pack(anchor=tk.W)
            preview_frame = ttk.Frame(preview_container)
            preview_frame.pack(side=tk.RIGHT)
            with Image.open(image_path) as img:
                img.thumbnail((100, 67), Image.Resampling.LANCZOS)
                from PIL import ImageTk
                photo = ImageTk.PhotoImage(img)
                self._preview_photo = photo
                lbl = tk.Label(preview_frame, image=photo, bg=styles.ThemeManager.COLOR_BG_SECONDARY, relief=tk.SUNKEN)
                lbl.image = photo
                lbl.pack()
        except Exception as e:
            logger.warning("画像プレビュー表示エラー: %s", e)
            ttk.Label(parent_frame, text=f"⚠️ 画像の読み込みに失敗: {str(e)[:50]}", foreground=tm.COLOR_LABEL_WARNING).pack(anchor=tk.W, pady=5)

    def _clear_image(self):
        """添付画像をクリアする。"""
        self.image_path = None
        if hasattr(self, "use_thumb_var"):
            self.use_thumb_var.set(False)
        if hasattr(self, "use_image_var"):
            self.use_image_var.set(False)

    def _toggle_auto_thumb(self):
        """サムネイル自動取得チェックボックスの切り替え。"""
        if not hasattr(self, "use_thumb_var"):
            return
        if self.use_thumb_var.get():
            thumb_url = self.video.get("thumbnail_url")
            cached = self._try_get_cached_thumbnail(thumb_url)
            if cached:
                self.image_path = cached
                if getattr(self, "_radio_attach", None) is not None:
                    self._radio_attach.config(state=tk.NORMAL)
                    self.use_image_var.set(True)
            else:
                messagebox.showinfo(
                    "サムネイル",
                    "ローカルキャッシュが見つかりません。\n"
                    "「画像を選択」で手動指定するか、設定画面でサムネイルを事前取得してください。"
                )
                self.use_thumb_var.set(False)
        else:
            self._clear_image()

    def _resolve_db_image(self) -> Optional[Path]:
        """DB に登録済みの image_filename からローカルパスを解決する。"""
        filename = self.video.get("image_filename")
        if not filename:
            return None
        try:
            from v4.core.assets.images import image_manager
            service = (self.video.get("service") or "youtube").lower()
            site_map = {"youtube": "YouTube", "niconico": "Niconico", "twitch": "Twitch"}
            site = site_map.get(service, "YouTube")
            for mode in ("import", "autopost"):
                p = image_manager.base_dir / site / mode / filename
                if p.exists():
                    return p
        except Exception as e:
            logger.debug("resolve_db_image failed: %s", e)
        return None

    def _try_get_cached_thumbnail(self, thumb_url: Optional[str]) -> Optional[str]:
        """ローカルキャッシュ（v4/images/{サイト}/autopost）からサムネイルを探す。無ければダウンロード。ニコニコは OGP で URL 取得。"""
        try:
            from v4.core.assets.images import image_manager
            service_raw = self.video.get("service", "youtube")
            site = (service_raw.capitalize() if service_raw else "YouTube")
            if site not in ("YouTube", "Niconico", "Twitch"):
                site = "YouTube"
            video_id = self.video_id
            cache_dir = image_manager.base_dir / site / "autopost"

            # 既存キャッシュを探す
            for ext in ("jpg", "jpeg", "png", "webp", "gif"):
                candidate = cache_dir / f"{video_id}.{ext}"
                if candidate.exists():
                    return str(candidate)

            # ニコニコは CDN URL が使えないため OGP で URL 取得してからダウンロード
            if site == "Niconico":
                try:
                    from v4.thumbnails_v4.niconico_ogp_utils import get_niconico_ogp_url
                    thumb_url = get_niconico_ogp_url(video_id)
                except Exception as e:
                    logger.debug("Niconico OGP thumbnail failed: %s", e)
                    return None

            if not thumb_url:
                return None

            filename = image_manager.download_thumbnail(thumb_url, site, video_id)
            if filename:
                path = cache_dir / filename
                if path.exists():
                    return str(path)
        except Exception as e:
            logger.debug(f"Thumbnail cache lookup failed: {e}")
        return None

    def execute_post(self, dry_run=False):
        content = (self.db.render_video_text(self.video_id) or "").strip()
        if not content:
            messagebox.showwarning("警告", "テンプレートのレンダリングに失敗したか、投稿内容が空です。")
            return

        use_image = self.use_image_var.get()
        resize_small = self.resize_small_var.get()
        image_path = self.image_path if use_image and self.image_path else None

        image_info = f"\n添付画像: {os.path.basename(image_path)}" if image_path else ""
        confirm_msg = (
            f"テスト投稿を実行しますか？{image_info}" if dry_run
            else f"本当に投稿しますか？{image_info}"
        )
        if not messagebox.askyesno("確認", confirm_msg):
            return

        try:
            success = self.db.post_text_to_bluesky(
                content, dry_run=dry_run, image_path=image_path, resize_small_images=resize_small
            )

            if success:
                msg = "投稿テストが完了しました (ログを確認してください)" if dry_run else "正常に投稿されました"
                messagebox.showinfo("成功", msg)
                if not dry_run:
                    self.db.mark_as_posted(self.video_id)
                    if self.on_refresh:
                        self.on_refresh()
                    self.window.destroy()
            else:
                messagebox.showerror("エラー", "投稿に失敗しました。詳細はログを確認してください。")
        except Exception as e:
            logger.error("Post execution failed: %s", e)
            messagebox.showerror("エラー", f"致命的なエラーが発生しました: {e}")
