import json
import os
import shutil
import subprocess
import sys
import threading
import tkinter as tk
from pathlib import Path
from tkinter import messagebox, scrolledtext, ttk

CONFIG_FILE = "launcher_config.json"
VERSIONS = ["v1", "v2", "v3", "v4"]
ROOT_DIR = Path(__file__).parent.absolute()


def load_config():
    if os.path.exists(CONFIG_FILE):
        try:
            with open(CONFIG_FILE, "r", encoding="utf-8") as f:
                return json.load(f)
        except:
            pass
    return {"last_used_version": "v4"}


def save_config(config):
    try:
        with open(CONFIG_FILE, "w", encoding="utf-8") as f:
            json.dump(config, f, indent=4)
    except Exception as e:
        print(f"Failed to save config: {e}")


class StreamNotifyLauncher(tk.Tk):
    def __init__(self):
        super().__init__()
        self.title("StreamNotify Launcher")
        self.geometry("420x380")
        self.resizable(False, False)

        # Apply strict styling
        style = ttk.Style(self)
        try:
            style.theme_use("vista")
        except:
            pass

        self.config_data = load_config()
        self.available_versions = [v for v in VERSIONS if (ROOT_DIR / v).exists()]

        # Handle case where no versions exist
        if not self.available_versions:
            messagebox.showerror("Error", "ディレクトリ内にアプリケーションのバージョン (v1-v4) が見つかりませんでした。")
            sys.exit(1)

        # Determine initial selection
        last_used = self.config_data.get("last_used_version")
        if last_used in self.available_versions:
            self.selected_version = tk.StringVar(value=last_used)
        else:
            self.selected_version = tk.StringVar(value=self.available_versions[-1])  # Default to newest available

        self.create_widgets()

    def create_widgets(self):
        # Title
        ttk.Label(self, text="StreamNotify", font=("Segoe UI", 18, "bold")).pack(pady=(15, 5))
        ttk.Label(self, text="起動またはセットアップするバージョンを選択してください:").pack(pady=5)

        # Version selection - only show available versions
        frame_versions = ttk.Frame(self)
        frame_versions.pack(pady=10)

        for v in self.available_versions:
            rb = ttk.Radiobutton(frame_versions, text=v.upper(), value=v, variable=self.selected_version)
            rb.pack(side=tk.LEFT, padx=10)

        # Buttons
        frame_btns = ttk.Frame(self)
        frame_btns.pack(pady=15)

        self.btn_launch = ttk.Button(frame_btns, text="起動", command=self.launch_app, width=18)
        self.btn_launch.pack(pady=5)

        self.btn_setup = ttk.Button(frame_btns, text="セットアップ / 修復", command=self.setup_app, width=18)
        self.btn_setup.pack(pady=5)

        # Logs
        ttk.Label(self, text="ステータスメッセージ:").pack(anchor="w", padx=20)
        self.log_text = scrolledtext.ScrolledText(self, width=45, height=6, state="disabled", font=("Consolas", 9))
        self.log_text.pack(pady=(5, 10), padx=20)

        self.log("ランチャーの準備が完了しました。", "INFO")

    def log(self, message, level="INFO"):
        self.log_text.config(state="normal")
        self.log_text.insert(tk.END, f"[{level}] {message}\n")
        self.log_text.see(tk.END)
        self.log_text.config(state="disabled")
        self.update_idletasks()

    def get_python_exe(self, target_dir):
        # Look for a specific .venv inside the version directory
        venv_path = target_dir / ".venv"
        if venv_path.exists():
            exe_path = venv_path / "Scripts" / "python.exe" if os.name == "nt" else venv_path / "bin" / "python"
            if exe_path.exists():
                return str(exe_path)

        # Look for venv
        venv_path2 = target_dir / "venv"
        if venv_path2.exists():
            exe_path = venv_path2 / "Scripts" / "python.exe" if os.name == "nt" else venv_path2 / "bin" / "python"
            if exe_path.exists():
                return str(exe_path)

        # Default fallback to system python
        return "python"

    def run_command_in_thread(self, command, cwd, success_msg):
        def target():
            self.log(f"セットアップを実行しています。お待ちください...")
            try:
                creationflags = subprocess.CREATE_NO_WINDOW if os.name == "nt" else 0
                process = subprocess.Popen(
                    command, cwd=cwd, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True, creationflags=creationflags
                )

                for line in process.stdout:
                    if line.strip():
                        self.log(line.strip(), "CMD")

                process.wait()
                if process.returncode == 0:
                    self.log(success_msg, "SUCCESS")
                else:
                    self.log(f"プロセスがエラーコード {process.returncode} で終了しました。", "ERROR")
            except Exception as e:
                self.log(f"エラーが発生しました: {e}", "ERROR")
            finally:
                self.btn_launch.config(state="normal")
                self.btn_setup.config(state="normal")

        threading.Thread(target=target, daemon=True).start()

    def setup_app(self):
        v = self.selected_version.get()
        target_dir = ROOT_DIR / v

        self.config_data["last_used_version"] = v
        save_config(self.config_data)

        self.btn_launch.config(state="disabled")
        self.btn_setup.config(state="disabled")
        self.log(f"{v} のセットアップを開始しています...")

        # Deploy settings.env if it doesn't exist
        env_ex = target_dir / "settings.env.example"
        env_file = target_dir / "settings.env"
        if not env_file.exists() and env_ex.exists():
            try:
                shutil.copy(env_ex, env_file)
                self.log("settings.env.example を settings.env にコピーしました。")
            except Exception as e:
                self.log(f"設定のコピーに失敗しました: {e}", "ERROR")

        # Handle virtual environment
        venv_path = target_dir / ".venv"
        if not venv_path.exists() and not (target_dir / "venv").exists():
            self.log("仮想環境が見つかりません。.venv を作成しています...")
            try:
                subprocess.run([sys.executable, "-m", "venv", ".venv"], cwd=str(target_dir), check=True)
                self.log(".venv の作成に成功しました。")
            except Exception as e:
                self.log(f".venv の作成に失敗しました: {e}", "ERROR")
                self.btn_launch.config(state="normal")
                self.btn_setup.config(state="normal")
                return

        # Install Python dependencies inside version's venv
        req_file = target_dir / "requirements.txt"
        if req_file.exists():
            python_exe = self.get_python_exe(target_dir)
            cmd = [python_exe, "-m", "pip", "install", "-r", "requirements.txt"]
            self.run_command_in_thread(cmd, str(target_dir), "パッケージのインストールに成功しました。")
        else:
            self.log("requirements.txt が見つかりません。pip install をスキップします。", "WARNING")
            self.btn_launch.config(state="normal")
            self.btn_setup.config(state="normal")

    def launch_app(self):
        v = self.selected_version.get()
        target_dir = ROOT_DIR / v

        self.config_data["last_used_version"] = v
        save_config(self.config_data)

        main_file = f"main_{v}.py"
        if not (target_dir / main_file).exists():
            messagebox.showerror("Error", f"{v} 内に {main_file} が見つかりません！")
            return

        self.btn_launch.config(state="disabled")
        self.btn_setup.config(state="disabled")
        self.log(f"{v} を起動しています。コンソールウィンドウを確認してください。", "INFO")

        # Warn if venv is missing
        if not (target_dir / ".venv").exists() and not (target_dir / "venv").exists():
            self.log("警告: .venv が見つかりません。セットアップを実行する必要があるかもしれません。", "WARNING")

        try:
            python_exe = self.get_python_exe(target_dir)
            # Open the application in a new command window so user can see application logs
            creationflags = subprocess.CREATE_NEW_CONSOLE if os.name == "nt" else 0
            subprocess.Popen([python_exe, main_file], cwd=str(target_dir), creationflags=creationflags)
            self.log("アプリケーションの起動に成功しました。ランチャーを閉じます。", "SUCCESS")
            # Close the launcher after a short delay
            self.after(2000, self.destroy)
        except Exception as e:
            self.log(f"起動に失敗しました: {e}", "ERROR")
            self.btn_launch.config(state="normal")
            self.btn_setup.config(state="normal")


if __name__ == "__main__":
    app = StreamNotifyLauncher()
    app.mainloop()
