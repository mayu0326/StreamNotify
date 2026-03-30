# -*- coding: utf-8 -*-
"""
v4 Niconico Client
ニコニコ動画の RSS 取得、ユーザー情報解決、動画詳細取得を担当するクライアント。
旧プラグインシステムからロジックを移植し、内蔵モジュール化。
"""

import logging
import re
import time
import requests
import feedparser
import xml.etree.ElementTree as ET
from datetime import datetime, timezone
from email.utils import parsedate_to_datetime
from typing import Optional, Dict, Any
from pathlib import Path
from bs4 import BeautifulSoup

from v4.core.config import settings

logger = logging.getLogger("v4.core.niconico.niconico_client")

# 定数
RSS_TIMEOUT = 10
RSS_RETRY_MAX = 3
RSS_RETRY_WAIT = 2
SEIGA_API_URL = "http://seiga.nicovideo.jp/api/user/info"
SEIGA_API_TIMEOUT = 5
NICONICO_USER_PAGE_TIMEOUT = 5

class NiconicoClient:
    """ニコニコ動画 データ取得クライアント"""

    def __init__(self, user_id: str = None):
        """
        Args:
            user_id: 監視対象のユーザーID（オプション、RSS監視時に必須）
        """
        self.user_id = user_id
        if self.user_id:
            self.rss_url = f"https://www.nicovideo.jp/user/{self.user_id}/video?rss=2.0"

        # ユーザー名キャッシュ
        self._user_name_cache = None
        self._user_name_env = settings.niconico_user_name

    # ==============================
    # ユーザー名解決
    # ==============================

    def get_user_name(self) -> str:
        """
        ユーザー名を取得（キャッシング付き）
        RSS -> 静画API -> ユーザーページ -> 環境変数 -> ID の順で試行
        """
        if self._user_name_cache:
            return self._user_name_cache

        # 1. RSS
        name = self._get_user_name_from_rss()
        if name:
            self._user_name_cache = name
            return name

        # 2. 静画API
        name = self._get_user_name_from_seiga_api()
        if name:
            self._user_name_cache = name
            self._save_user_name_to_config(name)
            return name

        # 3. ユーザーページ
        name = self._get_user_name_from_user_page()
        if name:
            self._user_name_cache = name
            self._save_user_name_to_config(name)
            return name

        # 4. 設定値
        if self._user_name_env:
            self._user_name_cache = self._user_name_env
            return self._user_name_env

        # 5. IDフォールバック
        self._user_name_cache = self.user_id or "Unknown User"
        return self._user_name_cache

    def _get_user_name_from_rss(self) -> Optional[str]:
        if not self.user_id: return None
        try:
            feed = feedparser.parse(self.rss_url)
            if feed.entries:
                entry = feed.entries[0]
                return entry.get("author", "") or entry.get("author_detail", {}).get("name", "")
        except Exception:
            pass
        return None

    def _get_user_name_from_seiga_api(self) -> Optional[str]:
        if not self.user_id: return None
        try:
            url = f"{SEIGA_API_URL}?id={self.user_id}"
            resp = requests.get(url, timeout=SEIGA_API_TIMEOUT)
            if resp.status_code == 200:
                root = ET.fromstring(resp.content)
                nick = root.find(".//nickname")
                if nick is not None and nick.text:
                    return nick.text.strip()
        except Exception:
            pass
        return None

    def _get_user_name_from_user_page(self) -> Optional[str]:
        if not self.user_id: return None
        try:
            url = f"https://www.nicovideo.jp/user/{self.user_id}"
            resp = requests.get(url, timeout=NICONICO_USER_PAGE_TIMEOUT)
            if resp.status_code == 200:
                soup = BeautifulSoup(resp.content, 'html.parser')
                og_title = soup.find('meta', property='og:title')
                if og_title:
                    content = og_title.get('content', '')
                    m = re.search(r'^([^ ]+)\s*[-|]', content)
                    if m: return m.group(1).strip()
        except Exception:
            pass
        return None

    def _save_user_name_to_config(self, name: str):
        """
        RSS の author が取れず、静画API / ユーザーページで表示名を得たときの案内ログ。
        （関数名は歴史的経緯。settings.env への自動書き込みは行わない）
        """
        env = (self._user_name_env or "").strip()
        if env and env != name:
            logger.info(
                "Niconico: 表示名を RSS 以外で取得しました (%s)。"
                "settings.env の NICONICO_USER_NAME (%s) と異なります。"
                "テンプレートの表記を設定どおりにしたい場合は手動で合わせてください。",
                name,
                env,
            )
        elif not env:
            logger.info(
                "Niconico: 表示名を RSS 以外で取得しました: %s。"
                "固定したい場合は settings.env に NICONICO_USER_NAME を設定できます。",
                name,
            )
        else:
            logger.debug("Niconico display name matches NICONICO_USER_NAME (%s)", name)

    # ==============================
    # RSS 取得
    # ==============================

    def fetch_rss_feed(self) -> list:
        """RSSを取得してエントリリストを返す"""
        if not self.user_id: return []

        for attempt in range(1, RSS_RETRY_MAX + 1):
            try:
                feed = feedparser.parse(self.rss_url)
                if hasattr(feed, 'bozo_exception') and feed.bozo_exception:
                    raise feed.bozo_exception

                return feed.entries
            except Exception as e:
                logger.warning(f"RSS fetch failed ({attempt}/{RSS_RETRY_MAX}): {e}")
                if attempt < RSS_RETRY_MAX:
                    time.sleep(RSS_RETRY_WAIT)

        return []

    # ==============================
    # 動画詳細取得 (Scraping)
    # ==============================

    def get_video_details(self, video_id: str) -> Optional[Dict[str, Any]]:
        """動画詳細情報をスクレイピングで取得"""
        if not video_id: return None

        url = f"https://www.nicovideo.jp/watch/{video_id}"
        try:
            resp = requests.get(url, timeout=10)
            resp.raise_for_status()

            soup = BeautifulSoup(resp.content, 'html.parser')

            title = ""
            desc = ""
            for meta in soup.find_all('meta'):
                p = meta.get('property', '') or meta.get('name', '')
                c = meta.get('content', '')
                if p == 'og:title': title = c
                elif p == 'og:description': desc = c

            if not title: title = f"Niconico Video {video_id}"

            # 公開日時抽出
            published_at = None
            # 1. video:release_date
            m_date = soup.find('meta', property='video:release_date')
            if m_date: published_at = m_date.get('content')

            # 2. initial state json fallback
            if not published_at:
                s_tag = soup.find("script", {"id": "__NUXT_STATE__"})
                if s_tag and s_tag.string:
                    m = re.search(r'"createTime":"([^"]+)"', s_tag.string)
                    if m: published_at = m.group(1)

            # Fallback to now
            if not published_at:
                published_at = datetime.now(timezone.utc).isoformat()

            # JST に変換し、「T」をスペースに置き換え
            if published_at:
                from v4.core.utils_v4 import format_datetime_filter
                try:
                    published_at = format_datetime_filter(published_at, fmt="%Y-%m-%d %H:%M:%S")
                except Exception as e:
                    logger.warning(f"⚠️ ニコニコ動画の日時変換失敗: {e}")

            # サムネイル (OGP)
            thumbnail_url = ""
            m_thumb = soup.find('meta', property='og:image')
            if m_thumb: thumbnail_url = m_thumb.get('content')

            return {
                "video_id": video_id,
                "title": title,
                "video_url": url,
                "published_at": published_at,
                "channel_name": self.get_user_name(),
                "thumbnail_url": thumbnail_url,
                "description": desc,
                "source": "niconico"
            }

        except Exception as e:
            logger.error(f"Failed to scrape video details for {video_id}: {e}")
            return None

def get_niconico_client(user_id: str = None) -> NiconicoClient:
    return NiconicoClient(user_id)
