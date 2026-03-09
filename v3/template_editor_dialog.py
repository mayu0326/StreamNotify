# -*- coding: utf-8 -*-

"""
Stream notify on Bluesky - v3 テンプレート編集ダイアログ

Jinja2ベースのテンプレート編集ダイアログ（customtkinter）。
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

import customtkinter as ctk
import tkinter as tk
from tkinter import messagebox, scrolledtext, filedialog
import logging
from typing import Dict, Any, Optional, Callable
from pathlib import Path
import sys

# v3 テンプレートユーティリティをインポート
from template_utils import (
    TEMPLATE_ARGS,
    TEMPLATE_VAR_BLACKLIST,
    get_sample_context,
    preview_template,
    save_template_file,
    get_template_args_for_dialog,
)

logger = logging.getLogger("AppLogger")

__author__ = "mayuneco(mayunya)"
__copyright__ = "Copyright (C) 2025 mayuneco(mayunya)"
__license__ = "GPLv3"

# ============ UI定義 ============

DEFAULT_FONT = ("Yu Gothic UI", 11, "normal")
BUTTON_FONT = ("Yu Gothic UI", 10, "normal")
PREVIEW_FONT = ("Courier New", 10, "normal")
TITLE_FONT = ("Yu Gothic UI", 12, "bold")

# ============ テンプレート編集ダイアログ ============


class TemplateEditorDialog(ctk.CTkToplevel):
    """v3 テンプレート編集ダイアログ

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
        **kwargs
    ):
        super().__init__(master, **kwargs)

        self.title(f"テンプレート編集: {template_type}")
        self.geometry("1000x700")

        # プロパティ
        self.template_type = template_type
        self.on_save_callback = on_save
        self.sample_context = get_sample_context(template_type)
        self.last_preview_text = ""

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
        toolbar = ctk.CTkFrame(self, fg_color="#2B2B2B")
        toolbar.pack(side="top", fill="x", padx=5, pady=5)

        # テンプレート種別ラベル
        type_label = ctk.CTkLabel(
            toolbar,
            text=f"📄 種別: {self.template_type}",
            font=TITLE_FONT,
            text_color="#FFFFFF"
        )
        type_label.pack(side="left", padx=10, pady=5)

        # ボタングループ
        button_group = ctk.CTkFrame(toolbar, fg_color="transparent")
        button_group.pack(side="right", padx=10)

        refresh_btn = ctk.CTkButton(
            button_group,
            text="🔄 プレビュー更新",
            font=BUTTON_FONT,
            command=self._on_preview_refresh,
            width=120,
            height=30,
            fg_color="#0084FF",
            hover_color="#0066CC"
        )
        refresh_btn.pack(side="left", padx=5)

        save_btn = ctk.CTkButton(
            button_group,
            text="💾 保存",
            font=BUTTON_FONT,
            command=self._on_save,
            width=100,
            height=30,
            fg_color="#00AA00",
            hover_color="#008800"
        )
        save_btn.pack(side="left", padx=5)

        close_btn = ctk.CTkButton(
            button_group,
            text="❌ キャンセル",
            font=BUTTON_FONT,
            command=self.destroy,
            width=100,
            height=30,
            fg_color="#AA0000",
            hover_color="#880000"
        )
        close_btn.pack(side="left", padx=5)

        # ========== メインエリア ==========
        main_frame = ctk.CTkFrame(self, fg_color="transparent")
        main_frame.pack(fill="both", expand=True, padx=5, pady=5)

        # 左側: テンプレートエディタ + 引数ボタン
        left_frame = ctk.CTkFrame(main_frame, fg_color="transparent")
        left_frame.pack(side="left", fill="both", expand=True, padx=(0, 5))

        # エディタラベル
        editor_label = ctk.CTkLabel(
            left_frame,
            text="📝 テンプレートテキスト",
            font=("Yu Gothic UI", 10, "bold"),
            text_color="#FFFFFF"
        )
        editor_label.pack(anchor="w", pady=(0, 5))

        # テキストエディタ（Tkinter Text + スクロールバー）
        editor_frame = ctk.CTkFrame(left_frame)
        editor_frame.pack(fill="both", expand=True)

        scrollbar = ctk.CTkScrollbar(editor_frame)
        scrollbar.pack(side="right", fill="y")

        self.text_editor = tk.Text(
            editor_frame,
            font=("Courier New", 11),
            wrap="word",
            yscrollcommand=scrollbar.set,
            bg="#1E1E1E",
            fg="#D4D4D4",
            insertbackground="#FFFFFF",
            selectbackground="#0078D7"
        )
        self.text_editor.pack(side="left", fill="both", expand=True)
        self.text_editor.bind("<KeyRelease>", self._on_text_changed)

        scrollbar.configure(command=self.text_editor.yview)

        # ========== テンプレート引数ボタングループ ==========
        args_label = ctk.CTkLabel(
            left_frame,
            text="🔧 利用可能な変数（クリックで挿入）",
            font=("Yu Gothic UI", 10, "bold"),
            text_color="#FFFFFF"
        )
        args_label.pack(anchor="w", pady=(10, 5))

        # ボタンフレーム（スクロール対応）
        args_frame = ctk.CTkScrollableFrame(left_frame, fg_color="#2B2B2B")
        args_frame.pack(fill="x", pady=(0, 5))

        # 変数ボタンを作成
        args_with_dialog = get_template_args_for_dialog(self.template_type, blacklist=True)
        if args_with_dialog:
            for display_name, var_key in args_with_dialog:
                self._create_arg_button(args_frame, display_name, var_key)
        else:
            no_args_label = ctk.CTkLabel(
                args_frame,
                text="利用可能な変数がありません",
                font=BUTTON_FONT,
                text_color="#888888"
            )
            no_args_label.pack(pady=10)

        # ========== 右側: プレビューエリア ==========
        right_frame = ctk.CTkFrame(main_frame, fg_color="transparent")
        right_frame.pack(side="right", fill="both", expand=True, padx=(5, 0))

        preview_label = ctk.CTkLabel(
            right_frame,
            text="👁️ プレビュー",
            font=("Yu Gothic UI", 10, "bold"),
            text_color="#FFFFFF"
        )
        preview_label.pack(anchor="w", pady=(0, 5))

        preview_frame = ctk.CTkFrame(right_frame)
        preview_frame.pack(fill="both", expand=True)

        preview_scrollbar = ctk.CTkScrollbar(preview_frame)
        preview_scrollbar.pack(side="right", fill="y")

        self.preview_text = tk.Text(
            preview_frame,
            font=PREVIEW_FONT,
            wrap="word",
            yscrollcommand=preview_scrollbar.set,
            bg="#0D1117",
            fg="#C9D1D9",
            state="disabled",
            selectbackground="#238636"
        )
        self.preview_text.pack(side="left", fill="both", expand=True)
        preview_scrollbar.configure(command=self.preview_text.yview)

        # ステータスバー
        status_frame = ctk.CTkFrame(self, fg_color="#2B2B2B")
        status_frame.pack(side="bottom", fill="x", padx=5, pady=5)

        self.status_label = ctk.CTkLabel(
            status_frame,
            text="✅ 準備完了",
            font=("Yu Gothic UI", 9),
            text_color="#00AA00"
        )
        self.status_label.pack(anchor="w", padx=10, pady=5)

    def _create_arg_button(self, parent, display_name: str, var_key: str):
        """テンプレート引数ボタンを作成"""
        def on_click():
            # カーソル位置に {{ var_key }} を挿入
            cursor_pos = self.text_editor.index(tk.INSERT)
            self.text_editor.insert(cursor_pos, f"{{{{ {var_key} }}}}")
            self.text_editor.focus()
            self._on_text_changed(None)

        btn = ctk.CTkButton(
            parent,
            text=display_name,
            font=BUTTON_FONT,
            command=on_click,
            width=100,
            height=28,
            fg_color="#0078D7",
            hover_color="#005A9E",
            corner_radius=4
        )
        btn.pack(side="left", padx=3, pady=3)

    def _on_text_changed(self, event):
        """テキスト変更時のコールバック（自動プレビュー更新）"""
        self._update_preview()

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
            self.template_type,
            template_text,
            event_context=self.sample_context
        )

        if success:
            self._set_preview(result, is_error=False)
            self._set_status(f"✅ プレビュー成功", color="#00AA00")
        else:
            # エラー表示
            self._set_preview(result, is_error=True)
            self._set_status(f"❌ エラー", color="#FF0000")

        self.last_preview_text = result

    def _set_preview(self, text: str, is_error: bool = False):
        """プレビューテキストを設定"""
        self.preview_text.config(state="normal")
        self.preview_text.delete("1.0", "end")

        if is_error:
            self.preview_text.config(fg="#FF6B6B")
        else:
            self.preview_text.config(fg="#C9D1D9")

        self.preview_text.insert("1.0", text)
        self.preview_text.config(state="disabled")

    def _set_status(self, message: str, color: str = "#FFFFFF"):
        """ステータスバーを設定"""
        self.status_label.configure(text=message, text_color=color)

    def _on_save(self):
        """保存ボタンのコールバック"""
        template_text = self.text_editor.get("1.0", "end-1c")

        if not template_text.strip():
            messagebox.showwarning("警告", "テンプレートが空です。保存できません。")
            return

        # 最終検証
        success, result = preview_template(
            self.template_type,
            template_text,
            event_context=self.sample_context
        )

        if not success:
            response = messagebox.askyesno(
                "確認",
                f"テンプレートに問題があります:\n{result}\n\nそれでも保存しますか？"
            )
            if not response:
                return

        # コールバック実行
        if self.on_save_callback:
            try:
                self.on_save_callback(template_text, self.template_type)
                messagebox.showinfo("成功", "テンプレートを保存しました。")
                self.destroy()
            except Exception as e:
                logger.error(f"❌ テンプレート保存エラー: {e}")
                messagebox.showerror("エラー", f"保存中にエラーが発生しました:\n{str(e)}")
        else:
            messagebox.showinfo("成功", "テンプレートを保存しました。")
            self.destroy()


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
    root = ctk.CTk()
    root.title("テンプレート編集ダイアログ テスト")
    root.geometry("1200x100")

    # テストボタン
    def open_editor():
        dialog = TemplateEditorDialog(
            master=root,
            template_type="youtube_new_video",
            initial_text="🎬 {{ channel_name }}\n\n📹 {{ title }}\n\n{{ video_url }}",
            on_save=test_on_save
        )

    test_btn = ctk.CTkButton(
        root,
        text="📝 テンプレート編集ダイアログを開く",
        command=open_editor,
        font=("Yu Gothic UI", 12),
        height=40
    )
    test_btn.pack(padx=20, pady=20, fill="x")

    root.mainloop()

