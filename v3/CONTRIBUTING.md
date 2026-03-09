# StreamNotify on Bluesky への貢献ガイド

まずはじめに、貢献をご検討いただきありがとうございます！このプロジェクトを改善するためのどんな助けも歓迎します。  \
バグの報告、新機能の提案、コードの記述など、あなたの貢献は価値があります。

## 📋 クイックリンク

- [開発環境のセットアップ](#開発環境のセットアップ)
- [貢献方法](#貢献方法)
- [コーディング規約](#コーディング規約)
- [テストの実行](#テストの実行)
- [Pre-commitフック](#pre-commitフック)

---

## 開発環境のセットアップ

### 必要な環境

- **OS**: Windows 10 以降、または Debian/Ubuntu 系 Linux
- **Python**: 3.10 以上
- **Git**: 最新版推奨

### 手動でのセットアップ

1. **リポジトリをクローン**

```bash
git clone https://git.neco-server.net/mayuneco/Streamnotify_on_Bluesky.git
cd Streamnotify_on_Bluesky/v3
```

2. **仮想環境を作成・有効化**

```bash
python -m venv venv

# Windows
venv\Scripts\activate

# Linux / WSL / macOS
source venv/bin/activate
```

3. **依存パッケージをインストール**

```bash
# 本体
pip install -r requirements.txt

# 開発用（テスト・フォーマッティング）
pip install pytest autopep8 black flake8
```

4. **設定ファイルを作成**

```bash
cp settings.env.example settings.env
```

5. **`settings.env` を編集**

テキストエディタで `settings.env` を開き、以下を設定します：

- `YOUTUBE_CHANNEL_ID` - 監視対象チャンネルID（UC から始まる）
- `BLUESKY_USERNAME` - Blueskyハンドル
- `BLUESKY_PASSWORD` - Blueskyアプリパスワード
- `POLL_INTERVAL_MINUTES` - ポーリング間隔（分）

詳細は `settings.env` 内のコメントまたは [SETTINGS_OVERVIEW](docs/Technical/SETTINGS_OVERVIEW.md) を参照。

### 開発環境の確認

```bash
python main_v3.py --version
```

---

## 貢献方法

### バグ報告

1. [Issues](https://git.neco-server.net/mayuneco/Streamnotify_on_Bluesky/issues) で、同じバグが既に報告されていないか確認します。
2. 報告されていない場合は、[新しいIssueを開き](https://git.neco-server.net/mayuneco/Streamnotify_on_Bluesky/issues/new)、以下を含めます：
   - **タイトル**: 明確で簡潔な説明
   - **説明**: 何が起きたか、期待される動作、実際の動作
   - **再現手順**: バグを再現するための具体的なステップ
   - **環境情報**: OS、Pythonバージョン、プラグイン導入状況
   - **ログ**: `logs/app.log` の関連部分（個人情報は削除）

### 機能提案

1. [Issues](https://git.neco-server.net/mayuneco/Streamnotify_on_Bluesky/issues) で、類似の提案が既にないか確認します。
2. 提案がない場合は、[新しいIssueを開き](https://git.neco-server.net/mayuneco/Streamnotify_on_Bluesky/issues/new)、以下を含めます：
   - **機能の概要**: 何ができるようになるか
   - **ユースケース**: なぜ必要か、使用シーン
   - **提案される実装**: 実装方法の案（任意）

### プルリクエスト (PR) プロセス

1. **フォークして、ローカルにクローン**

```bash
git clone https://git.neco-server.net/mayuneco/Streamnotify_on_Bluesky.git
cd Streamnotify_on_Bluesky/v3
```

2. **feature ブランチを作成**

```bash
git checkout -b feature/your-feature-name
```

ブランチ名の例：
- `feature/add-niconico-plugin` - 新機能追加
- `fix/issue-123-bluesky-post-error` - バグ修正
- `docs/update-readme` - ドキュメント更新

3. **変更を実装**

コードを編集し、[コーディング規約](#コーディング規約)に従います。

4. **テストがパスすることを確認**

```bash
python -m pytest tests/
```

5. **ドキュメントを更新**

変更内容に応じて、以下を更新します：
- `README_GITHUB_v3.md` - 主要な変更
- `docs/Technical/` - アーキテクチャ変更
- `docs/Guides/` - 実装手順変更
- コード内のコメント・docstring

6. **コミットしてプッシュ**

```bash
git add .
git commit -m "feat: 短い説明" # または fix:, docs:, test: など
git push origin feature/your-feature-name
```

コミットメッセージの例：
- `feat: プラグインシステムの改善`
- `fix: Bluesky投稿エラーの修正 (#123)`
- `docs: セットアップガイドの更新`
- `test: database.pyの単体テスト追加`

7. **プルリクエストを作成**

GitリポジトリでPRを開き、以下を記載します：
- 変更内容の明確な説明
- 関連するIssue（`Fixes #123` など）
- テストの実施状況
- スクリーンショット（GUIの変更がある場合）

8. **レビューに対応**

メンテナーがレビューし、修正を依頼することがあります。
コメントに対応し、変更をコミット・プッシュしてください。

---

## コーディング規約

### Python コーディング規約

すべてのPythonコードは以下に従います：

- **[PEP 8](https://pep8.org/)**: 標準的なスタイルガイド
- **インデント**: スペース 4 個
- **行の長さ**: 100文字以下（ドキュメント文字列は除外）
- **関数・クラス**: 上下に空行を2行
- **メソッド**: 上下に空行を1行

### 変数・関数命名

- **変数**: スネークケース (`my_variable`)
- **定数**: 大文字スネークケース (`MY_CONSTANT`)
- **関数**: スネークケース (`my_function()`)
- **クラス**: パスカルケース (`MyClass`)
- **プライベートメンバ**: アンダースコアプレフィックス (`_private_var`)

### コメント・ドキュメント

```python
def process_video(video_id: str) -> Dict[str, Any]:
    """
    動画情報を処理してBlueskyに投稿します。

    Args:
        video_id: YouTube動画ID

    Returns:
        処理結果を含む辞書

    Raises:
        ValueError: 動画IDが無効な場合
        BlueskyAPIError: API呼び出しエラー
    """
    pass
```

- 関数・クラスには docstring を記載
- 複雑なロジックには説明コメントを追加
- 日本語でのコメント・docstring も可能

### 自動フォーマット

自動フォーマットツールを使用してコード品質を維持します：

```bash
# autopep8
autopep8 --in-place --aggressive your_file.py

# Black
black your_file.py

# flake8で確認
flake8 your_file.py
```

---

## テストの実行

### ユニットテストの実行

```bash
# すべてのテスト
python -m pytest tests/

# 特定のテストファイル
python -m pytest tests/test_database.py

# テストと覆率を表示
python -m pytest --cov=. tests/
```

### テストを追加する

新しい機能や修正を追加する場合は、対応するテストも追加してください：

```bash
# tests/test_my_feature.py
import pytest
from my_module import my_function

def test_my_function_success():
    """正常系のテスト"""
    result = my_function("input")
    assert result == "expected_output"

def test_my_function_error():
    """エラー系のテスト"""
    with pytest.raises(ValueError):
        my_function(None)
```

### テストベストプラクティス

- テストは `tests/` ディレクトリに配置
- ファイル名は `test_*.py` とする
- テスト関数名は `test_*` とする
- 各テストは単一の機能のみをテスト
- テストはすべてパスしなければならない

---

## Pre-commitフック

コミット前に自動的にコード品質をチェックします。

### セットアップ

```bash
pip install pre-commit
pre-commit install
```

### 使用

```bash
# 自動実行（`git commit` 時）
git commit -m "your message"

# 手動実行（すべてのファイル）
pre-commit run --all-files

# 特定のフックを実行
pre-commit run flake8 --all-files
```

### 設定されているフック

- **flake8**: Python構文・スタイルチェック
- **autopep8**: 自動フォーマット
- **ggshield**: シークレットスキャン（GitGuardian）

---

## コードレビュープロセス

プルリクエスト提出後、メンテナーがレビューします。

### レビュー時に確認される内容

- ✅ コーディング規約に従っているか
- ✅ テストがすべてパスしているか
- ✅ ドキュメントが更新されているか
- ✅ コミットメッセージが明確か
- ✅ 不要なファイル（`__pycache__`、`.pyc` など）が含まれていないか

### 修正依頼への対応

フィードバックをもらった場合：

1. コメントを読み、修正内容を理解
2. コードを修正
3. テストを再実行
4. 変更をコミット・プッシュ
5. コメント欄で「修正しました」と報告

---

## プラグイン開発ガイド

v3 ではプラグインで機能を拡張できます。

### プラグインの基本

```python
# v3/plugins/my_plugin.py
from plugin_interface import NotificationPlugin
from typing import Dict, Any

class MyPlugin(NotificationPlugin):
    """カスタムプラグイン"""

    def is_available(self) -> bool:
        """プラグインが使用可能かチェック"""
        # 必要な環境変数・APIキーなどを確認
        return True

    def post_video(self, video: Dict[str, Any]) -> bool:
        """動画情報を投稿"""
        # 投稿処理
        return True

    def get_name(self) -> str:
        """プラグイン名"""
        return "MyPlugin"

    def get_version(self) -> str:
        """プラグインバージョン"""
        return "1.0.0"
```

詳細は [PLUGIN_SYSTEM.md](docs/Technical/PLUGIN_SYSTEM.md) を参照。

---

## 質問・相談がある場合

- Gitリポジトリ の Issue で質問を開く
- 既存の Issue やディスカッションで情報を探す
- README や Documentation を確認

---

## ライセンス

本プロジェクトは **GPL License v2** の下で公開されています。
貢献することで、あなたのコードも同じライセンスの下で公開されることに同意したものとします。

---

**最終更新**: 2025-12-18
**対応バージョン**: v3.1.0 以上
