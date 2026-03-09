# -*- coding: utf-8 -*-
"""
ニコニコ動画 RSS取得プラグイン

- ニコニコ動画の新着を監視
- RSS ポーリング方式で実装
- リトライ・タイムアウト対応
- NotificationPlugin 準拠
- ユーザー名自動取得（RSS <dc:creator> > 静画API > ユーザーページ > 環境変数 > ユーザーID）
"""

import os
import logging
import time
import re
from typing import Dict, Any, Optional
from threading import Thread, Event
from pathlib import Path
import feedparser
from socket import timeout as socket_timeout
import requests
import xml.etree.ElementTree as ET
from bs4 import BeautifulSoup
from image_manager import get_image_manager
from thumbnails import get_niconico_ogp_url

from plugin_interface import NotificationPlugin
from database import Database

logger = logging.getLogger("NiconicoLogger")

# 定数
RSS_TIMEOUT = 10  # RSS 取得タイムアウト（秒）
RSS_RETRY_MAX = 3  # リトライ回数
RSS_RETRY_WAIT = 2  # リトライ待機時間（秒）
NICONICO_USER_ID_PATTERN = r'^\d+$'  # ユーザーID は数字のみ
SEIGA_API_URL = "http://seiga.nicovideo.jp/api/user/info"  # ニコニコ静画 API URL
SEIGA_API_TIMEOUT = 5  # 静画API タイムアウト（秒）
NICONICO_USER_PAGE_TIMEOUT = 5  # ユーザーページ取得タイムアウト（秒）
SETTINGS_ENV_PATH = Path(__file__).parent.parent / "settings.env"  # 設定ファイルパス


class NiconicoPlugin(NotificationPlugin):
    """ニコニコ動画 RSS取得プラグイン"""

    def __init__(self, user_id: str, poll_interval: int, db: Database, user_name: str = None):
        """
        初期化

        Args:
            user_id: 監視対象のニコニコユーザーID（数字のみ）
            poll_interval: ポーリング間隔（分）
            db: Database インスタンス
            user_name: ニコニコユーザー名（display用。省略時はIDから推測）
        """
        self.user_id = user_id.strip() if user_id else ""
        self.poll_interval_min = max(int(poll_interval), 5)  # 最小 5 分
        self.poll_interval_sec = self.poll_interval_min * 60
        self.db = db
        self.shutdown_event = Event()
        self._monitor_thread = None
        self.last_video_id = None
        self._validation_error = None
        self.image_manager = get_image_manager()

        # ユーザー名キャッシング（初回のみ取得）
        self._user_name_cache = None
        self._user_name_env = user_name or os.getenv("NICONICO_USER_NAME", "")

        # バリデーション
        self._validate_user_id()

    def _validate_user_id(self):
        """ユーザーID をバリデーション"""
        if not self.user_id:
            self._validation_error = "ユーザーID が空です"
            logger.warning(f"[バリデーション] {self._validation_error}")
            return

        if not re.match(NICONICO_USER_ID_PATTERN, self.user_id):
            self._validation_error = f"ユーザーID は数字のみである必要があります: {self.user_id}"
            logger.warning(f"[バリデーション] {self._validation_error}")
            return

        logger.debug(f"[バリデーション] ユーザーID OK: {self.user_id}")
        self._validation_error = None

    def _get_user_name(self) -> str:
        """
        ユーザー名を取得（キャッシング付き）

        優先順位:
        1. RSS <dc:creator> から取得
        2. 静画API から取得
        3. ニコニコ公式ユーザーページ から取得（og:title から抽出）
        4. 環境変数または初期化パラメータ (NICONICO_USER_NAME)
        5. ユーザーID をそのまま使用

        Returns:
            str: ユーザー名またはユーザーID
        """
        # キャッシュがあれば返す
        if self._user_name_cache is not None:
            return self._user_name_cache

        # 優先度1: RSSから <dc:creator> を取得
        rss_author = self._get_user_name_from_rss()
        if rss_author:
            logger.debug(f"[ユーザー名取得] RSS <dc:creator> から取得: {rss_author}")
            self._user_name_cache = rss_author
            return self._user_name_cache

        # 優先度2: 静画API から取得
        seiga_author = self._get_user_name_from_seiga_api()
        if seiga_author:
            logger.debug(f"[ユーザー名取得] 静画API から取得: {seiga_author}")
            self._user_name_cache = seiga_author
            # 設定ファイルが未設定なら書き込む
            self._save_user_name_to_config(seiga_author)
            return self._user_name_cache

        # 優先度3: ニコニコ公式ページから取得
        page_author = self._get_user_name_from_user_page()
        if page_author:
            logger.debug(f"[ユーザー名取得] ユーザーページから取得: {page_author}")
            self._user_name_cache = page_author
            # 設定ファイルが未設定なら書き込む
            self._save_user_name_to_config(page_author)
            return self._user_name_cache

        # 優先度4: 環境変数が設定されていれば使用
        if self._user_name_env:
            logger.debug(f"[ユーザー名取得] 環境変数から取得: {self._user_name_env}")
            self._user_name_cache = self._user_name_env
            return self._user_name_cache

        # 優先度5: ユーザーIDをそのまま使用
        logger.debug(f"[ユーザー名取得] デフォルト（ユーザーID）を使用: {self.user_id}")
        self._user_name_cache = self.user_id
        return self._user_name_cache

    def _get_user_name_from_rss(self) -> Optional[str]:
        """
        RSS フィード から <dc:creator> を抽出してユーザー名を取得

        Returns:
            str または None: ユーザー名（取得できない場合は None）
        """
        try:
            url = f"https://www.nicovideo.jp/user/{self.user_id}/video?rss=2.0"
            logger.debug(f"[RSS著者取得] {url}")

            # feedparser で解析（namespace 対応）
            feed = feedparser.parse(url)

            if hasattr(feed, 'bozo_exception') and feed.bozo_exception:
                logger.warning(f"[RSS解析エラー] {feed.bozo_exception}")
                return None

            if not feed.entries:
                logger.debug("[RSS著者取得] エントリなし")
                return None

            # 最初のエントリから dc:creator を取得
            entry = feed.entries[0]

            # feedparser は dc:creator を "author" または "author_detail" に格納
            author = entry.get("author", "") or entry.get("author_detail", {}).get("name", "")

            if author:
                logger.info(f"[RSS著者取得成功] {author}")
                return author

            logger.debug("[RSS著者取得] dc:creator なし")
            return None

        except Exception as e:
            logger.warning(f"[RSS著者取得エラー] {type(e).__name__}: {e}")
            return None

    def _get_user_name_from_seiga_api(self) -> Optional[str]:
        """
        ニコニコ静画 API からユーザー名を取得

        公式API: http://seiga.nicovideo.jp/api/user/info?id=ユーザーID
        レスポンス: XML形式、<nickname> 要素にニックネームが含まれる

        Returns:
            str または None: ユーザー名（取得できない場合は None）
        """
        try:
            url = f"{SEIGA_API_URL}?id={self.user_id}"
            logger.debug(f"[静画API] {url}")

            response = requests.get(url, timeout=SEIGA_API_TIMEOUT)
            response.raise_for_status()

            # XML をパース
            root = ET.fromstring(response.content)

            # <nickname> 要素を検索（namespace 考慮）
            nickname_elem = root.find(".//nickname")
            if nickname_elem is not None and nickname_elem.text:
                nickname = nickname_elem.text.strip()
                logger.info(f"[静画API取得成功] {nickname}")
                return nickname

            logger.debug("[静画API] <nickname> 要素なし")
            return None

        except requests.exceptions.HTTPError as e:
            logger.debug(f"[静画APIエラー] HTTP {e.response.status_code}: {e}")
            return None
        except requests.exceptions.RequestException as e:
            logger.warning(f"[静画APIリクエストエラー] {type(e).__name__}: {e}")
            return None
        except ET.ParseError as e:
            logger.warning(f"[静画APIXML解析エラー] {e}")
            return None
        except Exception as e:
            logger.warning(f"[静画API取得エラー] {type(e).__name__}: {e}")
            return None

    def _get_user_name_from_user_page(self) -> Optional[str]:
        """
        ニコニコ公式ユーザーページ からユーザー名を取得

        ページ: https://www.nicovideo.jp/user/ユーザーID
        og:title メタタグから抽出

        Returns:
            str または None: ユーザー名（取得できない場合は None）
        """
        try:
            url = f"https://www.nicovideo.jp/user/{self.user_id}"
            logger.debug(f"[ユーザーページ] {url}")

            response = requests.get(url, timeout=NICONICO_USER_PAGE_TIMEOUT)
            response.raise_for_status()
            response.encoding = 'utf-8'

            # BeautifulSoupでHTML解析
            soup = BeautifulSoup(response.text, 'html.parser')

            # og:title メタタグからユーザー名を抽出
            og_title = soup.find('meta', property='og:title')
            if og_title:
                title = og_title.get('content', '')
                # "ユーザー名 - ニコニコ" のような形式から名前を抽出
                match = re.search(r'^([^ ]+)\s*[-|]', title)
                if match:
                    user_name = match.group(1).strip()
                    logger.info(f"[ユーザーページ取得成功] {user_name}")
                    return user_name

            logger.debug("[ユーザーページ] og:title から名前を抽出できない")
            return None

        except requests.exceptions.HTTPError as e:
            logger.debug(f"[ユーザーページエラー] HTTP {e.response.status_code}: {e}")
            return None
        except requests.exceptions.RequestException as e:
            logger.warning(f"[ユーザーページリクエストエラー] {type(e).__name__}: {e}")
            return None
        except Exception as e:
            logger.warning(f"[ユーザーページ取得エラー] {type(e).__name__}: {e}")
            return None

    def _save_user_name_to_config(self, user_name: str) -> None:
        """
        取得したユーザー名を設定ファイルに保存

        NICONICO_USER_NAME が未設定の場合のみ書き込む

        Args:
            user_name: 保存するユーザー名
        """
        try:
            # 既に環境変数が設定されている場合はスキップ
            if self._user_name_env:
                logger.debug(f"[設定保存] NICONICO_USER_NAME は既に設定済み、スキップ")
                return

            # 設定ファイルが存在しない場合はスキップ
            if not SETTINGS_ENV_PATH.exists():
                logger.warning(f"[設定保存] 設定ファイルが見つかりません: {SETTINGS_ENV_PATH}")
                return

            # 既存の設定ファイルを読み込む
            with open(SETTINGS_ENV_PATH, 'r', encoding='utf-8') as f:
                lines = f.readlines()

            # NICONICO_USER_NAME が既に存在するかチェック
            user_name_found = False
            for i, line in enumerate(lines):
                if line.startswith('NICONICO_USER_NAME='):
                    user_name_found = True
                    current_value = line.split('=', 1)[1].strip()
                    # 既に値が設定されていれば何もしない
                    if current_value:
                        logger.debug(f"[設定保存] NICONICO_USER_NAME は既に設定済み: {current_value}")
                        return
                    # 空の場合は上書き
                    lines[i] = f'NICONICO_USER_NAME={user_name}\n'
                    logger.info(f"[設定保存] NICONICO_USER_NAME を更新: {user_name}")
                    break

            # NICONICO_USER_NAME が存在しない場合は追加
            if not user_name_found:
                # NICONICO_USER_ID の後に追加
                for i, line in enumerate(lines):
                    if line.startswith('NICONICO_USER_ID='):
                        lines.insert(i + 1, f'NICONICO_USER_NAME={user_name}\n')
                        logger.info(f"[設定保存] NICONICO_USER_NAME を新規追加: {user_name}")
                        break

            # 設定ファイルに書き込む
            with open(SETTINGS_ENV_PATH, 'w', encoding='utf-8') as f:
                f.writelines(lines)

        except Exception as e:
            logger.warning(f"[設定保存エラー] {type(e).__name__}: {e}")

    def is_available(self) -> bool:
        """プラグインが利用可能か判定"""
        return bool(self.user_id and not self._validation_error)

    def get_name(self) -> str:
        return "ニコニコ動画 RSS取得プラグイン"

    def get_version(self) -> str:
        return "0.4.0"

    def get_description(self) -> str:
        return "ニコニコ動画の新着を RSS 監視するプラグイン（ユーザー名自動取得・自動保存、リトライ・タイムアウト対応）"

    def start_monitoring(self):
        """監視スレッドを開始"""
        if not self.is_available():
            logger.warning(f"[起動エラー] プラグインが利用不可です: {self._validation_error}")
            return

        if self._monitor_thread is None or not self._monitor_thread.is_alive():
            self.shutdown_event.clear()
            self._monitor_thread = Thread(target=self._monitor_loop, daemon=True)
            self._monitor_thread.start()
            logger.info(f"[監視スレッド開始] ユーザーID={self.user_id}, ポーリング間隔={self.poll_interval_min}分")
        else:
            logger.debug("[監視スレッド] 既に実行中です")

    def stop_monitoring(self):
        """監視スレッドを停止"""
        if self._monitor_thread and self._monitor_thread.is_alive():
            logger.debug("[監視スレッド停止] シグナル送信中...")
            self.shutdown_event.set()
            self._monitor_thread.join(timeout=10)
            logger.info("[監視スレッド停止] 完了")
        else:
            logger.debug("[監視スレッド停止] スレッドが実行していません")

    def _monitor_loop(self):
        """監視ループ（スレッド実行用）"""
        logger.info("[監視ループ] 開始")
        app_logger = logging.getLogger("AppLogger")
        niconico_logger = logging.getLogger("NiconicoLogger")
        while not self.shutdown_event.is_set():
            try:
                logger.info("[ニコニコ] ニコニコ動画から RSS を取得しています...")
                app_logger.info("[ニコニコ] ニコニコ動画から RSS を取得しています...")

                # 動画をチェック
                video_entry = self.get_latest_video_entry()
                if video_entry:
                    if not self.last_video_id or video_entry.get("id") != self.last_video_id:
                        # ニコニコ RSS の取得・照合・判定ログ（新着動画がある場合のみ）
                        niconico_logger.info(f"[ニコニコ RSS] 1 個の動画を DB に照合しています...")

                        video = self._entry_to_video_dict(video_entry)
                        is_new = self.post_video(video)
                        if is_new:
                            niconico_logger.info(f"✅ 1 個の新着動画を保存しました")
                        else:
                            niconico_logger.info(f"ℹ️ 新着動画はありません（既存: 1 個）")
                        self.last_video_id = video_entry.get("id")
                        logger.debug(f"[ラストID更新] video_id={self.last_video_id}")
                    else:
                        logger.debug("[監視] 新着動画なし")
                else:
                    logger.debug("[監視] RSS エントリ取得失敗")

            except Exception as e:
                logger.error(f"[監視ループエラー] {e}", exc_info=True)
                app_logger.error(f"[ニコニコ監視エラー] {e}", exc_info=True)

            # ポーリング間隔待機（割り込み可能）
            logger.debug(f"[待機] {self.poll_interval_min}分間ポーリング待機中...")
            self.shutdown_event.wait(self.poll_interval_sec)

        logger.info("[監視ループ] 終了")

    # ...existing code...

    def get_latest_video_entry(self) -> Optional[Dict[str, Any]]:
        """
        ユーザーの最新動画 RSS エントリを取得（リトライ対応）

        Returns:
            dict または None
        """
        url = f"https://www.nicovideo.jp/user/{self.user_id}/video?rss=2.0"
        logger.debug(f"[RSS取得] 動画: {url}")
        return self._fetch_rss_with_retry(url, kind="video")

    def _fetch_rss_with_retry(self, url: str, kind: str = "video") -> Optional[Dict[str, Any]]:
        """
        RSS を取得（リトライロジック付き）

        Args:
            url: RSS フィード URL
            kind: "video"

        Returns:
            dict または None
        """
        for attempt in range(1, RSS_RETRY_MAX + 1):
            try:
                logger.debug(f"[RSS取得試行] {attempt}/{RSS_RETRY_MAX}")

                # feedparser は timeout パラメータに対応していないため、
                # 基本的なエラーハンドリングのみ実装
                feed = feedparser.parse(url)

                # feedparser のエラーチェック
                if hasattr(feed, 'bozo_exception') and feed.bozo_exception:
                    raise feed.bozo_exception

                if feed.entries:
                    entry = feed.entries[0]
                    result = {
                        "id": entry.get("id", ""),
                        "title": entry.get("title", ""),
                        "link": entry.get("link", ""),
                        "published": entry.get("published", ""),
                        "author": entry.get("author", ""),
                    }
                    logger.debug(f"[RSS取得成功] entry_id={result.get('id')}")
                    return result

                logger.debug(f"[RSS取得] エントリなし（フィード空）")
                return None

            except Exception as e:
                logger.warning(f"[RSS取得エラー] 試行 {attempt}/{RSS_RETRY_MAX}: {type(e).__name__}: {e}")

                if attempt < RSS_RETRY_MAX:
                    logger.debug(f"[リトライ待機] {RSS_RETRY_WAIT}秒待機中...")
                    time.sleep(RSS_RETRY_WAIT)
                else:
                    logger.error(f"[RSS取得失敗] 最大リトライ回数に達しました")
                    return None

        return None

    def _entry_to_video_dict(self, entry: Dict[str, Any]) -> Dict[str, Any]:
        """
        RSS エントリを video dict に変換（動画専用）

        Args:
            entry: feedparser エントリ

        Returns:
            video dict（DB insert 用）
        """
        import re
        from email.utils import parsedate_to_datetime
        title = entry.get("title", "")
        link = entry.get("link", "")
        published = entry.get("published", "")
        # ユーザー名を自動取得（キャッシング付き）
        author = self._get_user_name()

        # ニコニコ動画IDをlinkから抽出
        video_id = ""
        m = re.search(r'/watch/([a-z]{2}\d+)', link)
        if m:
            video_id = m.group(1)
        else:
            # フォールバック: idフィールドの末尾がsm等ならそれを使う
            id_field = entry.get("id", "")
            m2 = re.search(r'/watch/([a-z]{2}\d+)', id_field)
            if m2:
                video_id = m2.group(1)
            else:
                video_id = id_field  # それでもなければそのまま

        # publishedをISO8601に変換
        published_at = published
        try:
            dt = parsedate_to_datetime(published)
            published_at = dt.isoformat()
        except Exception:
            pass

        video = {
            "video_id": video_id,
            "title": title,
            "video_url": link,
            "published_at": published_at,
            "channel_name": author,
            "content_type": "video",
            "source": "niconico",
            "thumbnail_url": self._fetch_thumbnail_url(video_id) or "",
        }

        logger.debug(f"[エントリ変換] video_id={video_id}, title={title}, author={author}")
        return video

    def post_video(self, video: Dict[str, Any]) -> bool:
        """
        ビデオ情報を DB に保存

        Args:
            video: {video_id, title, video_url, published_at?, channel_name?, content_type?, source?}

        Returns:
            bool: 成功時 True（新規登録）、既存の場合 False
        """
        video_id = video.get("video_id")
        if not video_id:
            logger.error("[post_video] video_id が指定されていません")
            return False

        title = video.get("title", "[ニコニコ]")
        video_url = video.get("video_url", "")
        published_at = video.get("published_at", "")
        channel_name = video.get("channel_name", "")
        content_type = video.get("content_type", "video")
        thumbnail_url = video.get("thumbnail_url", "")

        try:
            # database モジュールのロガーを一時的に NiconicoLogger に切り替え
            import database as db_module
            original_db_logger = db_module.logger
            niconico_logger = logging.getLogger("NiconicoLogger")
            db_module.logger = niconico_logger

            try:
                logger.debug(f"[DB保存] video_id={video_id}, title={title}")
                is_new = self.db.insert_video(
                    video_id=video_id,
                    title=title,
                    video_url=video_url,
                    published_at=published_at,
                    channel_name=channel_name,
                    thumbnail_url=thumbnail_url,
                    content_type=content_type,
                    source="niconico",
                )
                if is_new:
                    logger.debug(f"[DB保存成功] video_id={video_id}")
                    # 新規登録の場合のみ画像処理を実行
                    if thumbnail_url:
                        self._ensure_image_download(video_id, thumbnail_url)
                else:
                    logger.debug(f"[DB保存] 既存レコード（スキップ）: video_id={video_id}")
                return is_new
            finally:
                # ロガーを元に戻す
                db_module.logger = original_db_logger
        except Exception as e:
            logger.error(f"[DB保存エラー] {type(e).__name__}: {e}", exc_info=True)
            return False

    def _ensure_image_download(self, video_id: str, thumbnail_url: str):
        """DBに画像ファイルがなければダウンロードして登録"""
        try:
            # database と image_manager のロガーを一時的に NiconicoLogger に切り替え
            import database as db_module
            import image_manager as im_module

            original_db_logger = db_module.logger
            original_im_logger = im_module.logger
            niconico_logger = logging.getLogger("NiconicoLogger")
            db_module.logger = niconico_logger
            im_module.logger = niconico_logger

            try:
                videos = self.db.get_all_videos()
                video = next((v for v in videos if v.get("video_id") == video_id), None)
                if video and video.get("image_filename"):
                    return

                filename = self.image_manager.download_and_save_thumbnail(
                    thumbnail_url=thumbnail_url,
                    site="Niconico",
                    video_id=video_id,
                    mode="import",
                )
                if filename:
                    self.db.update_image_info(video_id, image_mode="import", image_filename=filename)
                    logger.info(f"[自動画像取得] {video_id} -> {filename}")
            finally:
                # ロガーを元に戻す
                db_module.logger = original_db_logger
                im_module.logger = original_im_logger
        except Exception as e:
            logger.warning(f"[自動画像取得失敗] {video_id}: {e}")

    def _fetch_thumbnail_url(self, video_id: str) -> Optional[str]:
        """ニコニコ動画のOGP画像URLを取得（常にOGPを使用）"""
        if not video_id:
            return None

        ogp_url = get_niconico_ogp_url(video_id)
        if ogp_url:
            return ogp_url
        return None

    def on_interval(self):
        """定期実行（プラグインマネージャから呼び出される場合用）"""
        # 監視スレッドで処理しているため、ここでは何もしない
        pass
