# -*- coding: utf-8 -*-

"""
StreamNotify - v3 テンプレート編集ダイアログ

Jinja2ベースのテンプレート編集ダイアログ（tkinter）。
- テンプレートテキスト編集
- テンプレート引数ボタン群（変数挿入）
- ライブプレビュー
- サンプル context でレンダリング

対応テンプレート種別:
- YouTube: new_video, online (将来), offline (将来)
- ニコニコ: new_video, online (将来), offline (将来)
- Twitch: online, offline, raid (将来)

注意: Vanilla 環境では Bluesky プラグイン無効のため、このダイアログは
       テンプレート編集可能（将来の機能フック用）ですが、実行時には投稿されません。
"""

import logging
import tkinter as tk
from pathlib import Path
from tkinter import filedialog, messagebox, ttk
from typing import Callable, Optional

# v3 テンプレートユーティリティをインポート
from template_utils import (
    get_sample_context,
    get_template_args_for_dialog,
    get_template_path,
    preview_template,
)

logger = logging.getLogger("GUILogger")

__author__ = "mayuneco(mayunya)"
__copyright__ = "Copyright (C) 2025 mayuneco(mayunya)"
__license__ = "GPLv2"

# ============ UI定義 ============

DEFAULT_FONT = ("Yu Gothic UI", 11)
BUTTON_FONT = ("Yu Gothic UI", 10)
PREVIEW_FONT = ("Courier New", 10)
TITLE_FONT = ("Yu Gothic UI", 12, "bold")

# ============ カラーテーマ ============
BG_DARK = "#2B2B2B"
BG_DARKER = "#1E1E1E"
BG_PREVIEW = "#0D1117"
FG_LIGHT = "#FFFFFF"
FG_MUTED = "#D4D4D4"
FG_PREVIEW = "#C9D1D9"
FG_ERROR = "#FF6B6B"
COLOR_PRIMARY = "#0078D7"
COLOR_PRIMARY_HOVER = "#005A9E"
COLOR_SUCCESS = "#00AA00"
COLOR_SUCCESS_HOVER = "#008800"
COLOR_ERROR = "#AA0000"
COLOR_ERROR_HOVER = "#880000"

# ============ テンプレート編集ダイアログ ============


class TemplateEditorDialog(tk.Toplevel):
    """v3 テンプレート編集ダイアログ（tkinter版）

    テンプレート種別を指定して開く、カスタマイズ可能なモーダルダイアログ。

    Args:
        master: 親ウィンドウ
        template_type: テンプレート種別（例: "youtube_new_video"）
        initial_text: 初期テンプレートテキスト
        on_save: 保存ボタン押下時のコールバック (text: str, template_type: str) -> None

    例:
        def on_save(text, template_type):
            print(f"Saved {template_type}: {text[:50]}...")

        dialog = TemplateEditorDialog(
            master=root,
            template_type="youtube_new_video",
            initial_text="{{ title }} | {{ channel_name }}",
            on_save=on_save
        )
    """

    def __init__(
        self,
        master,
        template_type: str,
        initial_text: str = "",
        on_save: Optional[Callable[[str, str], None]] = None,
        initial_file_path: Optional[str] = None,
        **kwargs,
    ):
        super().__init__(master, **kwargs)

        self.title(f"テンプレート編集: {template_type}")
        self.geometry("1000x700")
        self.configure(bg=BG_DARK)

        # プロパティ
        self.template_type = template_type
        self.on_save_callback = on_save
        self.sample_context = get_sample_context(template_type)
        self.last_preview_text = ""
        self.loaded_file_path = initial_file_path  # 読み込み済みファイルパスを記憶

        # UI を構築
        self._build_ui()

        # 初期テキストをセット
        if initial_text:
            self.text_editor.insert("1.0", initial_text)
            self._on_text_changed(None)  # 初期プレビュー更新

        # モーダルダイアログにする
        self.transient(master)
        self.grab_set()
        self.focus()

    def _build_ui(self):
        """UI要素を構築"""

        # ========== ツールバー ==========
        toolbar = tk.Frame(self, bg=BG_DARK, height=60)
        toolbar.pack(side="top", fill="x", padx=5, pady=5)

        # テンプレート種別ラベル
        type_label = tk.Label(
            toolbar,
            text=f"📄 種別: {self.template_type}",
            font=TITLE_FONT,
            fg=FG_LIGHT,
            bg=BG_DARK,
        )
        type_label.pack(side="left", padx=10, pady=5)

        # ボタングループ
        button_group = tk.Frame(toolbar, bg=BG_DARK)
        button_group.pack(side="right", padx=10)

        open_btn = tk.Button(
            button_group,
            text="📂 開く",
            font=BUTTON_FONT,
            command=self._on_open_file,
            width=10,
            bg="#4A90E2",
            fg=FG_LIGHT,
            activebackground="#3B7BC8",
            relief="flat",
            padx=10,
            pady=5,
        )
        open_btn.pack(side="left", padx=5)

        new_btn = tk.Button(
            button_group,
            text="🆕 新規作成",
            font=BUTTON_FONT,
            command=self._on_new_template,
            width=12,
            bg="#2EC844",
            fg=FG_LIGHT,
            activebackground="#25A439",
            relief="flat",
            padx=10,
            pady=5,
        )
        new_btn.pack(side="left", padx=5)

        refresh_btn = tk.Button(
            button_group,
            text="🔄 プレビュー更新",
            font=BUTTON_FONT,
            command=self._on_preview_refresh,
            width=20,
            bg=COLOR_PRIMARY,
            fg=FG_LIGHT,
            activebackground=COLOR_PRIMARY_HOVER,
            relief="flat",
            padx=10,
            pady=5,
        )
        refresh_btn.pack(side="left", padx=5)

        save_btn = tk.Button(
            button_group,
            text="💾 保存",
            font=BUTTON_FONT,
            command=self._on_save,
            width=12,
            bg=COLOR_SUCCESS,
            fg=FG_LIGHT,
            activebackground=COLOR_SUCCESS_HOVER,
            relief="flat",
            padx=10,
            pady=5,
        )
        save_btn.pack(side="left", padx=5)

        close_btn = tk.Button(
            button_group,
            text="❌ キャンセル",
            font=BUTTON_FONT,
            command=self.destroy,
            width=12,
            bg=COLOR_ERROR,
            fg=FG_LIGHT,
            activebackground=COLOR_ERROR_HOVER,
            relief="flat",
            padx=10,
            pady=5,
        )
        close_btn.pack(side="left", padx=5)

        # ========== メインエリア ==========
        main_frame = tk.Frame(self, bg=BG_DARK)
        main_frame.pack(fill="both", expand=True, padx=5, pady=5)

        # 左側: テンプレートエディタ + 引数ボタン
        left_frame = tk.Frame(main_frame, bg=BG_DARK)
        left_frame.pack(side="left", fill="both", expand=True, padx=(0, 5))

        # エディタラベル
        editor_label = tk.Label(
            left_frame,
            text="📝 テンプレートテキスト",
            font=("Yu Gothic UI", 10, "bold"),
            fg=FG_LIGHT,
            bg=BG_DARK,
        )
        editor_label.pack(anchor="w", pady=(0, 5))

        # テキストエディタ（Tkinter Text + スクロールバー）
        editor_frame = tk.Frame(left_frame, bg=BG_DARKER)
        editor_frame.pack(fill="both", expand=True)

        scrollbar = ttk.Scrollbar(editor_frame)
        scrollbar.pack(side="right", fill="y")

        self.text_editor = tk.Text(
            editor_frame,
            font=PREVIEW_FONT,
            wrap="word",
            yscrollcommand=scrollbar.set,
            bg=BG_DARKER,
            fg=FG_MUTED,
            insertbackground=FG_LIGHT,
            selectbackground=COLOR_PRIMARY,
            relief="flat",
            borderwidth=0,
        )
        self.text_editor.pack(side="left", fill="both", expand=True)
        self.text_editor.bind("<KeyRelease>", self._on_text_changed)

        scrollbar.configure(command=self.text_editor.yview)

        # ========== テンプレート引数ボタングループ ==========
        args_label = tk.Label(
            left_frame,
            text="🔧 利用可能な変数（クリックで挿入）",
            font=("Yu Gothic UI", 10, "bold"),
            fg=FG_LIGHT,
            bg=BG_DARK,
        )
        args_label.pack(anchor="w", pady=(10, 5))

        # ボタンフレーム（4列グリッド配置）
        args_frame = tk.Frame(left_frame, bg=BG_DARK)
        args_frame.pack(fill="x", padx=0, pady=(0, 5))

        # 変数ボタンを作成（4列グリッド）
        args_with_dialog = get_template_args_for_dialog(
            self.template_type, blacklist=True
        )
        if args_with_dialog:
            for idx, (display_name, var_key) in enumerate(args_with_dialog):
                row = idx // 4  # 4つごとに行を進める
                col = idx % 4  # 4列サイクル
                self._create_arg_button(args_frame, display_name, var_key, row, col)
        else:
            no_args_label = tk.Label(
                args_frame,
                text="利用可能な変数がありません",
                font=BUTTON_FONT,
                fg="#888888",
                bg=BG_DARK,
            )
            no_args_label.pack(pady=10)

        # ========== 右側: プレビューエリア ==========
        right_frame = tk.Frame(main_frame, bg=BG_DARK)
        right_frame.pack(side="right", fill="both", expand=True, padx=(5, 0))

        preview_label = tk.Label(
            right_frame,
            text="👁️ プレビュー",
            font=("Yu Gothic UI", 10, "bold"),
            fg=FG_LIGHT,
            bg=BG_DARK,
        )
        preview_label.pack(anchor="w", pady=(0, 5))

        preview_frame = tk.Frame(right_frame, bg=BG_PREVIEW)
        preview_frame.pack(fill="both", expand=True)

        preview_scrollbar = ttk.Scrollbar(preview_frame)
        preview_scrollbar.pack(side="right", fill="y")

        self.preview_text = tk.Text(
            preview_frame,
            font=PREVIEW_FONT,
            wrap="word",
            yscrollcommand=preview_scrollbar.set,
            bg=BG_PREVIEW,
            fg=FG_PREVIEW,
            state="disabled",
            selectbackground="#238636",
            relief="flat",
            borderwidth=0,
        )
        self.preview_text.pack(side="left", fill="both", expand=True)
        preview_scrollbar.configure(command=self.preview_text.yview)

        # ステータスバー
        status_frame = tk.Frame(self, bg=BG_DARK, height=40)
        status_frame.pack(side="bottom", fill="x", padx=5, pady=5)

        self.status_label = tk.Label(
            status_frame,
            text="✅ 準備完了",
            font=("Yu Gothic UI", 9),
            fg=COLOR_SUCCESS,
            bg=BG_DARK,
        )
        self.status_label.pack(anchor="w", padx=10, pady=5)

    def _create_arg_button(
        self, parent, display_name: str, var_key: str, row: int, col: int
    ):
        """テンプレート引数ボタンを作成（grid配置）"""

        def on_click():
            # カーソル位置に {{ var_key }} を挿入
            cursor_pos = self.text_editor.index(tk.INSERT)
            self.text_editor.insert(cursor_pos, f"{{{{ {var_key} }}}}")
            self.text_editor.focus()
            self._on_text_changed(None)

        btn = tk.Button(
            parent,
            text=display_name,
            font=BUTTON_FONT,
            command=on_click,
            bg=COLOR_PRIMARY,
            fg=FG_LIGHT,
            activebackground=COLOR_PRIMARY_HOVER,
            relief="flat",
            padx=5,
            pady=5,
        )
        btn.grid(row=row, column=col, padx=3, pady=3, sticky="ew")

        # 列の幅を均等にする
        parent.grid_columnconfigure(col, weight=1)

    def _on_text_changed(self, event):
        """テキスト変更時のコールバック（自動プレビュー更新）"""
        self._update_preview()

    def _on_open_file(self):
        """ファイルから開くボタンのコールバック"""
        file_path = filedialog.askopenfilename(
            title="テンプレートファイルを開く",
            filetypes=[
                ("テンプレートファイル", "*.txt *.jinja2"),
                ("すべてのファイル", "*.*"),
            ],
            initialdir="templates",
        )

        if not file_path:
            return

        try:
            with open(file_path, "r", encoding="utf-8") as f:
                content = f.read()

            # エディタにテキストを挿入
            self.text_editor.delete("1.0", "end")
            self.text_editor.insert("1.0", content)
            self._on_text_changed(None)

            # ファイルパスを記憶（保存時に直接上書きするため）
            self.loaded_file_path = file_path

            self._set_status(
                f"✅ ファイルを開きました: {Path(file_path).name}", color=COLOR_SUCCESS
            )
            logger.info(f"✅ テンプレートファイルを開きました: {file_path}")

        except Exception as e:
            logger.error(f"❌ ファイル読み込みエラー: {e}")
            messagebox.showerror("エラー", f"ファイルを開けませんでした:\n{str(e)}")
            self._set_status(f"❌ ファイル読み込みエラー", color=COLOR_ERROR)
            self._set_status(f"❌ ファイル読み込みエラー", color=COLOR_ERROR)

    def _on_preview_refresh(self):
        """プレビュー更新ボタンのコールバック"""
        self._update_preview()

    def _update_preview(self):
        """プレビューテキストを更新"""
        template_text = self.text_editor.get("1.0", "end-1c")

        if not template_text.strip():
            # テンプレートが空の場合
            self._set_preview("（テンプレートが空です）", is_error=False)
            self._set_status("ℹ️ テンプレートが空です", color="#888888")
            return
        # プレビューレンダリング実行
        success, result = preview_template(
            self.template_type, template_text, event_context=self.sample_context
        )

        if success:
            self._set_preview(result, is_error=False)
            self._set_status(f"✅ プレビュー成功", color=COLOR_SUCCESS)
        else:
            # エラー表示
            self._set_preview(result, is_error=True)
            self._set_status(f"❌ エラー", color=COLOR_ERROR)

        self.last_preview_text = result

    def _set_preview(self, text: str, is_error: bool = False):
        """プレビューテキストを設定"""
        self.preview_text.config(state="normal")
        self.preview_text.delete("1.0", "end")

        if is_error:
            self.preview_text.config(fg=FG_ERROR)
        else:
            self.preview_text.config(fg=FG_PREVIEW)

        self.preview_text.insert("1.0", text)
        self.preview_text.config(state="disabled")

    def _set_status(self, message: str, color: str = FG_LIGHT):
        """ステータスバーを設定"""
        self.status_label.configure(text=message, fg=color)

    def _on_save(self):
        """保存ボタンのコールバック"""
        template_text = self.text_editor.get("1.0", "end-1c")

        if not template_text.strip():
            messagebox.showwarning("警告", "テンプレートが空です。保存できません。")
            return

        # 最終検証
        success, result = preview_template(
            self.template_type, template_text, event_context=self.sample_context
        )

        if not success:
            response = messagebox.askyesno(
                "確認",
                f"テンプレートに問題があります:\n{result}\n\nそれでも保存しますか？",
            )
            if not response:
                return

        # 保存先を選択
        try:
            # 読み込み済みファイルパスがあれば、ダイアログ無しで直接上書き保存
            if self.loaded_file_path:
                save_path = Path(self.loaded_file_path)
                save_path.parent.mkdir(parents=True, exist_ok=True)

                with open(save_path, "w", encoding="utf-8") as f:
                    f.write(template_text)

                logger.info(f"✅ テンプレート保存完了（上書き）: {save_path}")
                messagebox.showinfo(
                    "成功", f"テンプレートを保存しました。\n{save_path}"
                )

                # コールバック実行
                if self.on_save_callback:
                    try:
                        self.on_save_callback(template_text, self.template_type)
                    except Exception as e:
                        logger.error(f"❌ コールバック実行エラー: {e}")

                self.destroy()
                return

            # 読み込み済みファイルパスがない場合は、保存ダイアログを表示
            default_path = get_template_path(self.template_type)
            initial_file = (
                Path(default_path).name if default_path else f"{self.template_type}.txt"
            )
            initial_dir = (
                str(Path(default_path).parent) if default_path else "templates"
            )

            save_file = filedialog.asksaveasfilename(
                title="テンプレートを保存",
                defaultextension=".txt",
                filetypes=[
                    ("テキストファイル", "*.txt"),
                    ("Jinja2テンプレート", "*.jinja2"),
                    ("すべてのファイル", "*.*"),
                ],
                initialfile=initial_file,
                initialdir=initial_dir,
            )

            if not save_file:
                return

            # ファイルに保存
            save_path = Path(save_file)
            save_path.parent.mkdir(parents=True, exist_ok=True)

            with open(save_path, "w", encoding="utf-8") as f:
                f.write(template_text)

            # 保存したファイルパスを記憶
            self.loaded_file_path = str(save_path)

            logger.info(f"✅ テンプレート保存完了: {save_path}")
            messagebox.showinfo("成功", f"テンプレートを保存しました。\n{save_path}")

            # コールバック実行
            if self.on_save_callback:
                try:
                    self.on_save_callback(template_text, self.template_type)
                except Exception as e:
                    logger.error(f"❌ コールバック実行エラー: {e}")

            self.destroy()

        except Exception as e:
            logger.error(f"❌ テンプレート保存エラー: {e}")
            messagebox.showerror("エラー", f"保存中にエラーが発生しました:\n{str(e)}")

    def _on_new_template(self):
        """新規テンプレートを作成"""
        # 確認ダイアログ
        if self.text_editor.get("1.0", "end-1c").strip():
            # テンプレートが空でない場合、確認を取る
            result = messagebox.askyesno(
                "新規作成確認",
                "現在のテンプレートテキストが削除されます。\nよろしいですか？",
            )
            if not result:
                return

        # テンプレートテキストをクリア
        self.text_editor.delete("1.0", "end")

        # 読み込み済みファイルパスをリセット（新規作成状態に）
        self.loaded_file_path = None

        # プレビューもクリア
        self.preview_text.config(state="normal")
        self.preview_text.delete("1.0", "end")
        self.preview_text.config(state="disabled")

        # ステータスバーを更新
        self._set_status("✨ 新規テンプレートを作成しています...")

        # フォーカスをエディタに設定
        self.text_editor.focus()

        logger.info(f"✨ 新規テンプレート作成開始（種別: {self.template_type}）")


# ============ スタンドアロンテスト ============


if __name__ == "__main__":
    """テンプレート編集ダイアログのスタンドアロンテスト"""

    def test_on_save(text, template_type):
        print(f"\n{'='*50}")
        print(f"保存されたテンプレート ({template_type}):")
        print(f"{'='*50}")
        print(text)
        print(f"{'='*50}")

    # メインウィンドウ
    root = tk.Tk()
    root.title("テンプレート編集ダイアログ テスト")
    root.geometry("1200x100")
    root.configure(bg=BG_DARK)

    # テストボタン
    def open_editor():
        dialog = TemplateEditorDialog(
            master=root,
            template_type="youtube_new_video",
            initial_text="🎬 {{ channel_name }}\n\n📹 {{ title }}\n\n{{ video_url }}",
            on_save=test_on_save,
        )

    test_btn = tk.Button(
        root,
        text="📝 テンプレート編集ダイアログを開く",
        command=open_editor,
        font=("Yu Gothic UI", 12),
        bg=COLOR_PRIMARY,
        fg=FG_LIGHT,
        activebackground=COLOR_PRIMARY_HOVER,
        relief="flat",
        padx=20,
        pady=20,
    )
    test_btn.pack(padx=20, pady=20, fill="x")

    root.mainloop()
