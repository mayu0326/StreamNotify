import tkinter as tk
from tkinter import ttk, messagebox, filedialog
import logging
from .. import styles
from v4.core.templates.templates import templates

logger = logging.getLogger("v4.gui.views")

class TemplateEditorView:
    """Dialog for editing post templates with live preview"""
    def __init__(self, parent, db_adapter):
        self.parent = parent
        self.db = db_adapter
        self.loaded_file_path = None

        # Window setup
        self.window = tk.Toplevel(parent)
        self.window.title("📝 テンプレート編集")
        self.window.geometry("1000x700")
        self.window.transient(parent)
        self.window.grab_set()

        # Apply theme to window
        self.window.configure(bg=styles.ThemeManager.COLOR_BG)

        self.setup_ui()
        self.load_template("youtube_new_video") # Default

    def setup_ui(self):
        container = ttk.Frame(self.window, padding=styles.PADDING)
        container.pack(fill=tk.BOTH, expand=True)

        # Top Section: Template Type Selection
        top_frame = ttk.Frame(container)
        top_frame.pack(fill=tk.X, pady=(0, styles.MARGIN))

        ttk.Label(top_frame, text="📄 種別:").pack(side=tk.LEFT)
        self.type_var = tk.StringVar(value="youtube_new_video")

        # Dynamic template types from adapter
        template_types = self.db.get_available_template_types()
        # Fallback if empty (shouldn't happen with refactoring)
        if not template_types:
            template_types = ["youtube_new_video", "twitch_online", "niconico_new_video"]

        self.cmb_type = ttk.Combobox(top_frame, textvariable=self.type_var,
                                    values=template_types,
                                    state="readonly", width=30)
        self.cmb_type.pack(side=tk.LEFT, padx=styles.MARGIN)
        self.cmb_type.bind("<<ComboboxSelected>>", lambda e: self.load_template(self.type_var.get()))

        # Top Buttons Group
        ttk.Button(top_frame, text="📂 開く", command=self._on_open_file).pack(side=tk.LEFT, padx=2)
        ttk.Button(top_frame, text="🆕 新規", command=self._on_new_template).pack(side=tk.LEFT, padx=2)
        ttk.Button(top_frame, text="🔄 更新", command=self.update_preview).pack(side=tk.LEFT, padx=2)

        # Main Area: Editor and Preview
        paned = ttk.PanedWindow(container, orient=tk.HORIZONTAL)
        paned.pack(fill=tk.BOTH, expand=True)

        # Left: Editor Container
        left_container = ttk.Frame(paned)
        paned.add(left_container, weight=1)

        # Editor
        editor_frame = ttk.Frame(left_container, padding=styles.MARGIN)
        editor_frame.pack(fill=tk.BOTH, expand=True)

        ttk.Label(editor_frame, text="エディタ (Jinja2):", font=styles.FONT_BOLD).pack(anchor=tk.W)
        self.text_editor = tk.Text(editor_frame, font=("Consolas", 11), undo=True)
        self.text_editor.configure(
            bg=styles.ThemeManager.COLOR_BG_SECONDARY,
            fg=styles.ThemeManager.COLOR_TEXT,
            insertbackground=styles.ThemeManager.COLOR_TEXT
        )
        self.text_editor.pack(fill=tk.BOTH, expand=True)
        self.text_editor.bind("<KeyRelease>", lambda e: self.update_preview())

        # Args Buttons Section
        self.args_frame = ttk.Frame(left_container, padding=styles.MARGIN)
        self.args_frame.pack(fill=tk.X)
        ttk.Label(self.args_frame, text="🔧 変数挿入:", font=styles.FONT_BOLD).pack(anchor=tk.W)
        self.buttons_container = ttk.Frame(self.args_frame)
        self.buttons_container.pack(fill=tk.X, pady=5)

        # Right: Preview
        preview_frame = ttk.Frame(paned, padding=styles.MARGIN)
        paned.add(preview_frame, weight=1)

        ttk.Label(preview_frame, text="プレビュー (サンプルデータ使用):", font=styles.FONT_BOLD).pack(anchor=tk.W)
        self.preview_area = tk.Text(preview_frame, font=styles.FONT_MAIN, state=tk.DISABLED)
        self.preview_area.configure(
            bg=styles.ThemeManager.COLOR_BG_SECONDARY,
            fg=styles.ThemeManager.COLOR_TEXT
        )
        self.preview_area.pack(fill=tk.BOTH, expand=True)

        # Bottom Buttons
        btn_frame = ttk.Frame(container)
        btn_frame.pack(fill=tk.X, pady=(styles.MARGIN*2, 0))

        ttk.Button(btn_frame, text="キャンセル", command=self.window.destroy).pack(side=tk.RIGHT, padx=styles.MARGIN)
        ttk.Button(btn_frame, text="💾 保存", command=self.save_template).pack(side=tk.RIGHT, padx=styles.MARGIN)

    def load_template(self, template_type):
        content = self.db.get_template_content(template_type)
        self.text_editor.delete("1.0", tk.END)
        self.text_editor.insert("1.0", content)

        # In v4 adapter, get_template_content doesn't return path.
        # But now template engine delegates to template_utils, which handles logic.
        from v4.core.templates.template_utils import get_template_path
        self.loaded_file_path = get_template_path(template_type)

        self._update_args_buttons(template_type)
        self.update_preview()

    def _update_args_buttons(self, template_type):
        """Update variable insertion buttons based on template type"""
        # Clear existing buttons
        for child in self.buttons_container.winfo_children():
            child.destroy()

        # Get args via adapter (which calls engine -> utils)
        args = self.db.get_template_args(template_type)

        # Create buttons in a grid (4 columns)
        for i, (display_name, var_key) in enumerate(args):
            row = i // 4
            col = i % 4
            btn = ttk.Button(self.buttons_container, text=display_name,
                            command=lambda v=var_key: self._insert_variable(v))
            btn.grid(row=row, column=col, padx=2, pady=2, sticky="ew")

        # Configure weights for grid
        for i in range(4):
            self.buttons_container.grid_columnconfigure(i, weight=1)

    def _insert_variable(self, var_key):
        """Insert {{ var_key }} at current cursor position"""
        self.text_editor.insert(tk.INSERT, f"{{{{ {var_key} }}}}")
        self.update_preview()
        self.text_editor.focus()

    def update_preview(self):
        content = self.text_editor.get("1.0", tk.END).strip()
        template_type = self.type_var.get()

        try:
            # Simple preview using adapter
            rendered = self.db.preview_template_custom(template_type, content)
            self.preview_area.config(state=tk.NORMAL)
            self.preview_area.delete("1.0", tk.END)
            self.preview_area.insert("1.0", rendered)
            self.preview_area.config(state=tk.DISABLED)
        except Exception as e:
            logger.error(f"Preview update failed: {e}")

    def save_template(self):
        content = self.text_editor.get("1.0", tk.END).strip()
        template_type = self.type_var.get()

        try:
            # If we have a specific file path, write to it directly
            if self.loaded_file_path:
                save_path = self.loaded_file_path
                with open(save_path, "w", encoding="utf-8") as f:
                    f.write(content)
                messagebox.showinfo("成功", f"テンプレートを '{save_path}' に保存しました")
                self.window.destroy()
                return

            if self.db.save_template_content(template_type, content):
                messagebox.showinfo("成功", f"テンプレート '{template_type}' を保存しました")
                self.window.destroy()
            else:
                messagebox.showerror("エラー", "保存に失敗しました")
        except Exception as e:
            logger.error(f"Save failed: {e}")
            messagebox.showerror("エラー", f"保存中にエラーが発生しました: {e}")

    def _on_open_file(self):
        """Open a template file from disk"""
        file_path = filedialog.askopenfilename(
            title="テンプレートファイルを開く",
            filetypes=[("Text Files", "*.txt"), ("Jinja2 Templates", "*.jinja2"), ("All Files", "*.*")],
            initialdir="v4/templates"
        )
        if file_path:
            try:
                with open(file_path, "r", encoding="utf-8") as f:
                    content = f.read()
                self.text_editor.delete("1.0", tk.END)
                self.text_editor.insert("1.0", content)
                self.loaded_file_path = file_path
                self.update_preview()
            except Exception as e:
                messagebox.showerror("エラー", f"ファイルを開けませんでした: {e}")

    def _on_new_template(self):
        """Clear the editor for a new template"""
        if self.text_editor.get("1.0", tk.END).strip():
            if not messagebox.askyesno("確認", "現在の内容が消去されます。よろしいですか？"):
                return
        self.text_editor.delete("1.0", tk.END)
        self.loaded_file_path = None
        self.update_preview()
