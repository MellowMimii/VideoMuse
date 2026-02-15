from __future__ import annotations

import json
import logging

import httpx

from app.config import settings
from app.platforms.base import PlatformAdapter, PlatformRegistry, VideoInfo

logger = logging.getLogger(__name__)

BILIBILI_SEARCH_API = "https://api.bilibili.com/x/web-interface/search/type"
BILIBILI_SUBTITLE_API = "https://api.bilibili.com/x/player/v2"
BILIBILI_PLAY_URL_API = "https://api.bilibili.com/x/player/playurl"

COMMON_HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/131.0.0.0 Safari/537.36"
    ),
    "Referer": "https://www.bilibili.com",
}


@PlatformRegistry.register("bilibili")
class BilibiliAdapter(PlatformAdapter):
    """Bilibili video platform adapter."""

    def __init__(self):
        cookies = {}
        if settings.bilibili_sessdata:
            cookies["SESSDATA"] = settings.bilibili_sessdata
        self._client = httpx.AsyncClient(
            headers=COMMON_HEADERS,
            cookies=cookies,
            timeout=30.0,
        )

    async def search_videos(self, query: str, max_results: int = 10) -> list[VideoInfo]:
        """Search Bilibili for videos matching the query."""
        params = {
            "search_type": "video",
            "keyword": query,
            "page": 1,
            "page_size": min(max_results, 50),
        }
        resp = await self._client.get(BILIBILI_SEARCH_API, params=params)
        resp.raise_for_status()
        data = resp.json()

        if data.get("code") != 0:
            logger.error("Bilibili search API error: %s", data.get("message"))
            return []

        results = data.get("data", {}).get("result", [])
        videos = []
        for item in results[:max_results]:
            # Clean HTML tags from title
            title = item.get("title", "")
            title = title.replace('<em class="keyword">', "").replace("</em>", "")

            bvid = item.get("bvid", "")
            videos.append(
                VideoInfo(
                    video_id=bvid,
                    title=title,
                    author=item.get("author", ""),
                    url=f"https://www.bilibili.com/video/{bvid}",
                    duration=self._parse_duration(item.get("duration", "0:0")),
                    cover_url=("https:" + item.get("pic", "")) if item.get("pic") else "",
                    platform="bilibili",
                )
            )

        logger.info("Found %d videos for query '%s'", len(videos), query)
        return videos

    async def get_subtitles(self, video_id: str) -> str | None:
        """Get subtitle text for a Bilibili video (via AI-generated or manual CC)."""
        # First get cid for the video
        cid = await self._get_cid(video_id)
        if not cid:
            return None

        params = {"bvid": video_id, "cid": cid}
        resp = await self._client.get(BILIBILI_SUBTITLE_API, params=params)
        resp.raise_for_status()
        data = resp.json()

        if data.get("code") != 0:
            logger.warning("Failed to get player info for %s: %s", video_id, data.get("message"))
            return None

        subtitle_info = data.get("data", {}).get("subtitle", {})
        subtitles_list = subtitle_info.get("subtitles", [])

        if not subtitles_list:
            logger.info("No subtitles available for video %s", video_id)
            return None

        # Prefer Chinese subtitles
        subtitle_url = None
        for sub in subtitles_list:
            if "zh" in sub.get("lan", ""):
                subtitle_url = sub.get("subtitle_url", "")
                break
        if not subtitle_url and subtitles_list:
            subtitle_url = subtitles_list[0].get("subtitle_url", "")

        if not subtitle_url:
            return None

        # Ensure URL has protocol
        if subtitle_url.startswith("//"):
            subtitle_url = "https:" + subtitle_url

        # Fetch subtitle JSON
        sub_resp = await self._client.get(subtitle_url)
        sub_resp.raise_for_status()
        sub_data = sub_resp.json()

        # Extract text from subtitle body
        body = sub_data.get("body", [])
        if not body:
            return None

        texts = [item.get("content", "") for item in body if item.get("content")]
        full_text = "\n".join(texts)
        logger.info("Extracted %d subtitle lines for video %s", len(texts), video_id)
        return full_text

    async def get_audio_url(self, video_id: str) -> str | None:
        """Get audio stream URL for Whisper transcription fallback."""
        cid = await self._get_cid(video_id)
        if not cid:
            return None

        params = {
            "bvid": video_id,
            "cid": cid,
            "fnval": 16,  # Request DASH format
        }
        resp = await self._client.get(BILIBILI_PLAY_URL_API, params=params)
        resp.raise_for_status()
        data = resp.json()

        if data.get("code") != 0:
            return None

        dash = data.get("data", {}).get("dash", {})
        audio_list = dash.get("audio", [])

        if not audio_list:
            return None

        # Return highest quality audio
        audio_list.sort(key=lambda x: x.get("bandwidth", 0), reverse=True)
        return audio_list[0].get("baseUrl") or audio_list[0].get("base_url")

    async def _get_cid(self, bvid: str) -> int | None:
        """Get the cid (content ID) for a Bilibili video."""
        url = "https://api.bilibili.com/x/player/pagelist"
        resp = await self._client.get(url, params={"bvid": bvid})
        resp.raise_for_status()
        data = resp.json()

        if data.get("code") != 0 or not data.get("data"):
            return None

        return data["data"][0].get("cid")

    @staticmethod
    def _parse_duration(duration_str: str) -> int:
        """Parse duration string like '12:34' into seconds."""
        try:
            parts = str(duration_str).split(":")
            if len(parts) == 2:
                return int(parts[0]) * 60 + int(parts[1])
            elif len(parts) == 3:
                return int(parts[0]) * 3600 + int(parts[1]) * 60 + int(parts[2])
            return int(duration_str)
        except (ValueError, TypeError):
            return 0
