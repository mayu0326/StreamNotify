# Asset ディレクトリ

## 概要

`Asset/` ディレクトリは、全プラグイン・全サービス用のテンプレートや画像を保管する場所です。

## 自動配置について

**プラグイン導入時に必要なファイルは自動でコピーされます。**

- プラグインが読み込まれて有効化された時点で、`asset_manager.deploy_plugin_assets(plugin_name)` が呼び出される
- 該当するテンプレート・画像が Asset/ から自動コピーされる
- 既に存在するファイルは上書きされない（ユーザーの手動編集を保護）
- ファイルコピー状況は `logs/app.log` に記録される

**手動コピーは不要です。** AssetManager が自動的に処理します。

## ディレクトリ構成

```
Asset/
├── templates/              # テンプレート保管所
│   ├── default/           # デフォルト用テンプレート（→ .templates/ へコピー）
│   ├── youtube/           # YouTube 関連（YouTube API/Live プラグイン用）
│   ├── niconico/          # ニコニコ関連（ニコニコプラグイン用）
│   └── twitch/            # Twitch 関連（将来予定）
├── images/                # 画像保管所
│   ├── default/           # デフォルト画像
│   ├── YouTube/           # YouTube 画像保管先
│   ├── Niconico/          # ニコニコ画像保管先
│   └── Twitch/            # Twitch 画像保管先
└── README.md              # このファイル
```

## 自動配置時のディレクトリ名規則

Asset から本番ディレクトリへ配置される際、以下のルールに従います：

**テンプレート:** 小文字で統一
- `Asset/templates/default/` → `templates/.templates/` (デフォルト/フォールバック用)
- `Asset/templates/youtube/` → `templates/youtube/`
- `Asset/templates/niconico/` → `templates/niconico/`
- `Asset/templates/twitch/` → `templates/twitch/`

**画像:** default画像以外は大文字始まりで統一（image_manager.py の仕様）
- `Asset/images/default/` → `images/default/`
- `Asset/images/YouTube/` → `images/YouTube/`
- `Asset/images/Niconico/` → `images/Niconico/`
- `Asset/images/Twitch/` → `images/Twitch/`

> ℹ️ **ディレクトリ名の大文字小文字は厳密に統一されており、v3 の image_manager.py 仕様に準拠

## 対応プラグイン別の配置

| プラグイン | テンプレート | 画像 | 配置タイミング |
|-----------|-----------|------|-----------|
| `youtube_api_plugin` | `templates/youtube/` | `images/YouTube/` | プラグイン有効化時 |
| `youtube_live_plugin` | `templates/youtube/` | `images/YouTube/` | プラグイン有効化時 |
| `niconico_plugin` | `templates/niconico/` | `images/Niconico/` | プラグイン有効化時 |
| `bluesky_plugin` | `templates/.templates/` | `images/default/` | プラグイン有効化時 ← **デフォルトテンプレート** |

> ℹ️ **重要**: デフォルトテンプレートは Bluesky プラグイン有効化時に `Asset/templates/default/default_template.txt` から `templates/.templates/default_template.txt` へコピーされます（フォールバック用）

## 手動で追加・カスタマイズする場合

### Asset に新しいテンプレート・画像を追加する場合
1. Asset ディレクトリに新しいテンプレート・画像を追加
2. アプリケーションを再起動（または 対応するプラグインを再ロード）
3. 自動コピーされる
   - ディレクトリ名規則に従う（小文字テンプレート、大文字画像）
   - `logs/app.log` でコピー状況を確認

### テンプレート・画像をカスタマイズする場合
- `templates/` または `images/` ディレクトリ内のファイルを直接編集
- **Asset 側への変更は自動反映されません** - Asset に記録する場合は手動で同期
- 既存ファイルは上書き保護されているため、削除後に再コピーする場合は：
  1. `templates/` または `images/` 内のファイルを削除
  2. アプリケーション再起動
  3. Asset から自動コピーされる

## トラブルシューティング

### ファイルがコピーされない場合
- `logs/app.log` を確認してエラーメッセージを確認
- Asset ディレクトリが正しい場所にあるか確認
- 対応するプラグインが正しくロードされているか確認（`gui_v3.py` または `logs/app.log` で確認）
- デバッグモードで詳細ログを確認：`settings.env` で `DEBUG_MODE=true` に設定

### 古いファイルが残っている場合
- 上書き保護機能により、既存ファイルは削除されません
- 最新版をコピーしたい場合：
  1. `templates/` または `images/` 内の古いファイルを削除
  2. アプリケーション再起動
  3. Asset から自動コピーされる

### Asset 側で変更したが反映されない場合
- Asset の変更は自動監視されません - アプリケーション再起動が必要
- 対応するプラグインが再度ロードされるまで反映されない
- または手動で `templates/` または `images/` から該当ファイルを削除

## ライセンス

**このリポジトリ全体は GPLv2 です。詳細はルートの LICENSE を参照してください。**

このディレクトリ内のすべてのアセット（テンプレート、画像、ドキュメント）は、親リポジトリの GPLv2 ライセンスの対象です。
