from __future__ import annotations

import hashlib
import logging
import time
import urllib.parse
from functools import reduce

import asyncio

import httpx

from app.config import settings
from app.platforms.base import PlatformAdapter, PlatformRegistry, VideoInfo

logger = logging.getLogger(__name__)

BILIBILI_SEARCH_API = "https://api.bilibili.com/x/web-interface/search/type"
BILIBILI_VIEW_API = "https://api.bilibili.com/x/web-interface/view"
BILIBILI_SUBTITLE_API = "https://api.bilibili.com/x/player/v2"
BILIBILI_PLAY_URL_API = "https://api.bilibili.com/x/player/playurl"
BILIBILI_NAV_API = "https://api.bilibili.com/x/web-interface/nav"
BILIBILI_SPI_API = "https://api.bilibili.com/x/frontend/finger/spi"

COMMON_HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/131.0.0.0 Safari/537.36"
    ),
    "Referer": "https://www.bilibili.com",
}

# Wbi mixin key encoding table (from Bilibili's frontend JS)
MIXIN_KEY_ENC_TAB = [
    46, 47, 18, 2, 53, 8, 23, 32, 15, 50, 10, 31, 58, 3, 45, 35,
    27, 43, 5, 49, 33, 9, 42, 19, 29, 28, 14, 39, 12, 38, 41, 13,
    37, 48, 7, 16, 24, 55, 40, 61, 26, 17, 0, 1, 60, 51, 30, 4,
    22, 25, 54, 21, 56, 59, 6, 63, 57, 62, 11, 36, 20, 34, 44, 52,
]

# Module-level shared client (lazily initialized, reused across adapter instances)
_shared_client: httpx.AsyncClient | None = None

# Cached wbi mixin key and its expiry time
_wbi_mixin_key: str | None = None
_wbi_key_expires: float = 0

# Whether buvid cookies have been initialised on the shared client
_buvid_initialized: bool = False


def _get_shared_client() -> httpx.AsyncClient:
    """Get or create the shared httpx client for Bilibili API calls."""
    global _shared_client
    if _shared_client is None or _shared_client.is_closed:
        cookies = {}
        if settings.bilibili_sessdata:
            cookies["SESSDATA"] = settings.bilibili_sessdata
        _shared_client = httpx.AsyncClient(
            headers=COMMON_HEADERS,
            cookies=cookies,
            timeout=30.0,
        )
    return _shared_client


def _get_mixin_key(orig: str) -> str:
    """Generate the mixin key from concatenated img_key + sub_key."""
    return reduce(lambda s, i: s + orig[i], MIXIN_KEY_ENC_TAB, "")[:32]


def _sign_wbi_params(params: dict, mixin_key: str) -> dict:
    """Sign request parameters with Bilibili wbi signature."""
    params = dict(params)
    params["wts"] = int(time.time())
    # Sort by key
    params = dict(sorted(params.items()))
    # Filter characters not allowed in wbi signing
    params = {
        k: "".join(c for c in str(v) if c not in "!'()*")
        for k, v in params.items()
    }
    query = urllib.parse.urlencode(params)
    wbi_sign = hashlib.md5((query + mixin_key).encode()).hexdigest()
    params["w_rid"] = wbi_sign
    return params


async def _get_wbi_mixin_key(client: httpx.AsyncClient) -> str:
    """Fetch and cache the wbi mixin key from Bilibili's nav API."""
    global _wbi_mixin_key, _wbi_key_expires

    now = time.time()
    if _wbi_mixin_key and now < _wbi_key_expires:
        return _wbi_mixin_key

    logger.info("Fetching wbi keys from Bilibili nav API")
    resp = await client.get(BILIBILI_NAV_API)
    resp.raise_for_status()
    data = resp.json()

    wbi_img = data.get("data", {}).get("wbi_img", {})
    img_url = wbi_img.get("img_url", "")
    sub_url = wbi_img.get("sub_url", "")

    img_key = img_url.rsplit("/", 1)[-1].split(".")[0]
    sub_key = sub_url.rsplit("/", 1)[-1].split(".")[0]

    _wbi_mixin_key = _get_mixin_key(img_key + sub_key)
    # Cache for 30 minutes (wbi keys change infrequently)
    _wbi_key_expires = now + 1800

    logger.info("Obtained wbi mixin key (cached for 30min)")
    return _wbi_mixin_key


async def _ensure_buvid(client: httpx.AsyncClient) -> None:
    """Ensure buvid3/buvid4 cookies are set — many Bilibili APIs need them."""
    global _buvid_initialized
    if _buvid_initialized:
        return
    _buvid_initialized = True
    try:
        resp = await client.get(BILIBILI_SPI_API)
        resp.raise_for_status()
        data = resp.json()
        if data.get("code") == 0:
            b3 = data.get("data", {}).get("b_3", "")
            b4 = data.get("data", {}).get("b_4", "")
            if b3:
                client.cookies.set("buvid3", b3)
            if b4:
                client.cookies.set("buvid4", b4)
            logger.info(
                "Initialized buvid3=%s… buvid4=%s…",
                b3[:24] if b3 else "N/A",
                b4[:24] if b4 else "N/A",
            )
        else:
            logger.warning("SPI API returned code=%s", data.get("code"))
    except Exception:
        logger.warning("Failed to get buvid cookies, continuing without them")


@PlatformRegistry.register("bilibili")
class BilibiliAdapter(PlatformAdapter):
    """Bilibili video platform adapter."""

    def __init__(self):
        # cid cache to avoid redundant API calls for the same video
        self._cid_cache: dict[str, int] = {}

    @property
    def _client(self) -> httpx.AsyncClient:
        return _get_shared_client()

    async def _ensure_initialized(self) -> None:
        """Ensure shared client has required cookies (buvid etc.)."""
        await _ensure_buvid(self._client)

    async def _signed_get(self, url: str, params: dict) -> httpx.Response:
        """Make a GET request with wbi-signed parameters."""
        mixin_key = await _get_wbi_mixin_key(self._client)
        signed_params = _sign_wbi_params(params, mixin_key)
        resp = await self._client.get(url, params=signed_params)
        resp.raise_for_status()
        return resp

    async def _plain_get(self, url: str, params: dict) -> httpx.Response:
        """Make a plain GET request without wbi signing."""
        resp = await self._client.get(url, params=params)
        resp.raise_for_status()
        return resp

    # ------------------------------------------------------------------
    # Search
    # ------------------------------------------------------------------
    async def search_videos(self, query: str, max_results: int = 10) -> list[VideoInfo]:
        """Search Bilibili for videos matching the query."""
        await self._ensure_initialized()

        params = {
            "search_type": "video",
            "keyword": query,
            "page": 1,
            "page_size": min(max_results, 50),
        }
        try:
            resp = await self._signed_get(BILIBILI_SEARCH_API, params)
        except httpx.HTTPStatusError as exc:
            status_code = exc.response.status_code if exc.response is not None else None
            logger.error(
                "Bilibili search HTTP error %s for query '%s': %s",
                status_code,
                query,
                exc,
            )
            if status_code == 412:
                logger.error(
                    "Received 412 Precondition Failed — missing/invalid cookies. "
                    "Set a valid SESSDATA in settings."
                )
            return []

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

    # ------------------------------------------------------------------
    # Subtitles — primary flow via /x/web-interface/view API
    # ------------------------------------------------------------------
    async def get_subtitles(self, video_id: str) -> str | None:
        """Get subtitle text for a Bilibili video.

        Uses the *view* API to obtain cid + subtitle list in a single call,
        then falls back to the player v2 API if the view API doesn't carry
        subtitle info.
        """
        await self._ensure_initialized()

        # Step 1 — get comprehensive video info from view API
        view_data = await self._get_view_info(video_id)
        if not view_data:
            logger.warning(
                "View API unavailable for %s, falling back to legacy flow",
                video_id,
            )
            return await self._get_subtitles_legacy(video_id)

        # Verify the response matches the requested video
        returned_bvid = view_data.get("bvid", "")
        returned_title = view_data.get("title", "")
        logger.info(
            "[subtitle] view API confirmed bvid=%s title='%s' (requested %s)",
            returned_bvid,
            returned_title[:60],
            video_id,
        )

        # Get cid and aid from view data
        cid = view_data.get("cid")
        aid = view_data.get("aid")
        if not cid:
            pages = view_data.get("pages", [])
            if pages:
                cid = pages[0].get("cid")

        if cid:
            self._cid_cache[video_id] = cid
            logger.info("[subtitle] cid=%s aid=%s for %s (from view API)", cid, aid, video_id)
        else:
            logger.warning("[subtitle] no cid found for %s in view data", video_id)
            return None

        # Step 2 — try to get subtitle list from view API response
        subtitle_info = view_data.get("subtitle", {})
        subtitles_list = subtitle_info.get("list", [])

        # The view API often returns subtitle *metadata* (lan, id) but with
        # empty subtitle_url fields.  Detect this and fall through.
        has_urls = any(sub.get("subtitle_url") for sub in subtitles_list)

        if not subtitles_list or not has_urls:
            # Fall back to player v2 API which returns actual subtitle URLs.
            logger.info(
                "[subtitle] view API has %d subtitle entries (has_urls=%s) for %s, "
                "trying player v2 (cid=%s, aid=%s)",
                len(subtitles_list),
                has_urls,
                video_id,
                cid,
                aid,
            )
            subtitles_list = await self._get_subtitle_list_from_player(
                video_id, cid, aid=aid,
            )

        if not subtitles_list:
            logger.warning(
                "[subtitle] no subtitles available for %s ('%s'), trying Whisper...",
                video_id,
                returned_title[:40],
            )
            return await self._whisper_fallback(video_id)

        # Step 3 — fetch actual subtitle content
        return await self._fetch_subtitle_content(video_id, subtitles_list, returned_title)

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------
    async def _get_view_info(self, bvid: str) -> dict | None:
        """Get comprehensive video info from the view API.

        Returns ``data`` dict with keys: bvid, title, cid, pages, subtitle, …
        """
        try:
            resp = await self._signed_get(BILIBILI_VIEW_API, {"bvid": bvid})
            data = resp.json()
            if data.get("code") != 0:
                logger.warning(
                    "View API error for %s: code=%s msg=%s",
                    bvid,
                    data.get("code"),
                    data.get("message"),
                )
                return None
            return data.get("data", {})
        except httpx.HTTPStatusError as exc:
            logger.warning("View API HTTP error for %s: %s", bvid, exc)
            return None
        except Exception:
            logger.exception("Unexpected error fetching view info for %s", bvid)
            return None

    async def _get_subtitle_list_from_player(
        self, bvid: str, cid: int, *, aid: int | None = None
    ) -> list:
        """Get subtitle list from the player v2 API.

        When *aid* is provided, the returned subtitle URLs are verified:
        AI-subtitle URLs embed ``{aid}{cid}`` in their path, so we can
        detect when Bilibili's anti-crawling returns data for the wrong
        video.  Up to ``MAX_SUBTITLE_RETRIES`` attempts are made.
        """
        MAX_SUBTITLE_RETRIES = 8
        RETRY_DELAY = 1.2  # seconds between retries

        for attempt in range(1, MAX_SUBTITLE_RETRIES + 1):
            try:
                params = {"bvid": bvid, "cid": cid}
                # Set Referer to the specific video page (like a real browser)
                headers = {"Referer": f"https://www.bilibili.com/video/{bvid}/"}
                mixin_key = await _get_wbi_mixin_key(self._client)
                signed_params = _sign_wbi_params(params, mixin_key)
                resp = await self._client.get(
                    BILIBILI_SUBTITLE_API,
                    params=signed_params,
                    headers=headers,
                )
                resp.raise_for_status()
                data = resp.json()

                if data.get("code") != 0:
                    logger.warning(
                        "Player v2 error for %s (attempt %d): code=%s msg=%s",
                        bvid, attempt, data.get("code"), data.get("message"),
                    )
                    if attempt < MAX_SUBTITLE_RETRIES:
                        await asyncio.sleep(RETRY_DELAY)
                        continue
                    return []

                subtitle_info = data.get("data", {}).get("subtitle", {})
                subs = subtitle_info.get("subtitles", [])

                if not subs:
                    logger.info(
                        "[subtitle] player v2 returned 0 subtitle tracks for %s "
                        "(attempt %d)",
                        bvid, attempt,
                    )
                    if attempt < MAX_SUBTITLE_RETRIES:
                        await asyncio.sleep(RETRY_DELAY)
                        continue
                    return []

                # --- Verify subtitle URL belongs to the correct video ---
                if aid is not None:
                    aid_str = str(aid)
                    verified_subs = []
                    for sub in subs:
                        url = sub.get("subtitle_url", "")
                        if not url:
                            continue
                        # AI subtitle URLs contain {aid}{cid} in the path
                        # e.g. /prod/6228144751380920774...
                        if "/ai_subtitle/" in url and aid_str not in url:
                            logger.warning(
                                "[subtitle] MISMATCH: expected aid=%s in URL "
                                "but got %s (attempt %d/%d)",
                                aid_str, url[:80], attempt, MAX_SUBTITLE_RETRIES,
                            )
                            continue
                        verified_subs.append(sub)

                    if verified_subs:
                        logger.info(
                            "[subtitle] player v2: %d/%d tracks verified for %s "
                            "(attempt %d)",
                            len(verified_subs), len(subs), bvid, attempt,
                        )
                        return verified_subs

                    # All URLs failed verification — retry
                    if attempt < MAX_SUBTITLE_RETRIES:
                        logger.info(
                            "[subtitle] all %d tracks failed aid verification "
                            "for %s, retrying (%d/%d)…",
                            len(subs), bvid, attempt, MAX_SUBTITLE_RETRIES,
                        )
                        await asyncio.sleep(RETRY_DELAY)
                        continue
                    else:
                        logger.warning(
                            "[subtitle] all %d retries exhausted for %s — "
                            "subtitle URLs never matched aid=%s",
                            MAX_SUBTITLE_RETRIES, bvid, aid_str,
                        )
                        return []
                else:
                    # No aid to verify against, return as-is
                    logger.info(
                        "[subtitle] player v2 returned %d tracks for %s "
                        "(no aid verification)",
                        len(subs), bvid,
                    )
                    return subs

            except Exception:
                logger.exception(
                    "Player v2 API failed for %s (attempt %d)", bvid, attempt,
                )
                if attempt < MAX_SUBTITLE_RETRIES:
                    await asyncio.sleep(RETRY_DELAY)
                    continue
                return []

        return []

    async def _fetch_subtitle_content(
        self, video_id: str, subtitles_list: list, video_title: str = ""
    ) -> str | None:
        """Pick the best subtitle track and fetch its content."""
        # Prefer Chinese subtitles, then AI-generated, then any
        subtitle_url: str | None = None
        subtitle_lang: str | None = None
        for sub in subtitles_list:
            lan = sub.get("lan", "")
            if "zh" in lan:
                subtitle_url = sub.get("subtitle_url", "")
                subtitle_lang = lan
                break
        if not subtitle_url and subtitles_list:
            subtitle_url = subtitles_list[0].get("subtitle_url", "")
            subtitle_lang = subtitles_list[0].get("lan", "unknown")

        if not subtitle_url:
            return None

        logger.info(
            "[subtitle] lang=%s url=%s for %s",
            subtitle_lang,
            subtitle_url[:80],
            video_id,
        )

        # Ensure URL has protocol
        if subtitle_url.startswith("//"):
            subtitle_url = "https:" + subtitle_url

        # Fetch subtitle JSON (CDN doesn't need wbi signing)
        sub_resp = await self._client.get(subtitle_url)
        sub_resp.raise_for_status()
        sub_data = sub_resp.json()

        # Extract text from subtitle body
        body = sub_data.get("body", [])
        if not body:
            return None

        texts = [item.get("content", "") for item in body if item.get("content")]
        full_text = "\n".join(texts)
        logger.info(
            "[subtitle] extracted %d lines (%d chars) for %s ['%s']",
            len(texts),
            len(full_text),
            video_id,
            video_title[:30],
        )
        return full_text

    async def _whisper_fallback(self, video_id: str) -> str | None:
        """Fall back to Whisper transcription when no subtitles are available."""
        logger.info("[whisper-fallback] Attempting Whisper for %s", video_id)
        try:
            audio_url = await self.get_audio_url(video_id)
            if not audio_url:
                logger.warning("[whisper-fallback] No audio URL for %s", video_id)
                return None

            from app.platforms.whisper import transcribe_from_url

            text = await transcribe_from_url(
                audio_url,
                referer=f"https://www.bilibili.com/video/{video_id}/",
            )
            if text:
                logger.info(
                    "[whisper-fallback] Transcribed %d chars for %s",
                    len(text), video_id,
                )
            return text
        except Exception:
            logger.exception("[whisper-fallback] Failed for %s", video_id)
            return None

    async def _get_subtitles_legacy(self, video_id: str) -> str | None:
        """Legacy subtitle flow: pagelist (unsigned) → player v2 → fetch."""
        cid = await self._get_cid(video_id)
        if not cid:
            logger.warning("[subtitle-legacy] no cid for %s", video_id)
            return await self._whisper_fallback(video_id)

        subtitles_list = await self._get_subtitle_list_from_player(video_id, cid)
        if not subtitles_list:
            return await self._whisper_fallback(video_id)

        return await self._fetch_subtitle_content(video_id, subtitles_list)

    # ------------------------------------------------------------------
    # Audio URL (for future Whisper fallback)
    # ------------------------------------------------------------------
    async def get_audio_url(self, video_id: str) -> str | None:
        """Get audio stream URL for Whisper transcription fallback."""
        await self._ensure_initialized()
        cid = await self._get_cid(video_id)
        if not cid:
            return None

        params = {
            "bvid": video_id,
            "cid": cid,
            "fnval": 16,  # Request DASH format
        }
        resp = await self._signed_get(BILIBILI_PLAY_URL_API, params)
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

    # ------------------------------------------------------------------
    # CID resolution (pagelist — unsigned, with signed fallback)
    # ------------------------------------------------------------------
    async def _get_cid(self, bvid: str) -> int | None:
        """Get the cid (content ID) for a Bilibili video, with caching."""
        if bvid in self._cid_cache:
            return self._cid_cache[bvid]

        url = "https://api.bilibili.com/x/player/pagelist"

        # pagelist API traditionally doesn't need wbi signing;
        # try unsigned first, fall back to signed if that fails.
        try:
            resp = await self._plain_get(url, {"bvid": bvid})
        except httpx.HTTPStatusError:
            logger.info("Unsigned pagelist failed for %s, retrying with wbi", bvid)
            resp = await self._signed_get(url, {"bvid": bvid})

        data = resp.json()

        if data.get("code") != 0 or not data.get("data"):
            logger.warning("Failed to get cid for %s: code=%s", bvid, data.get("code"))
            return None

        page = data["data"][0]
        cid = page.get("cid")
        page_title = page.get("part", "")
        logger.info("Got cid=%s for %s (page: %s)", cid, bvid, page_title[:40])

        if cid is not None:
            self._cid_cache[bvid] = cid
        return cid

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
