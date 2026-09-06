import asyncio
import os
import re
from typing import Any, Dict, List, Optional

import yt_dlp
from cachetools import TTLCache
from ytmusicapi import YTMusic

_stream_cache = TTLCache(maxsize=3000, ttl=10800)
_ytmusic_client = YTMusic()

# 1. PROXY POOL SETUP (Environment variable से उठाएगा, अगर उपलब्ध हो)
# Format: "http://user:pass@host:port,http://user:pass@host2:port"
RAW_PROXIES = os.getenv("STREAM_PROXY_POOL", "").strip()
PROXY_POOL = [p.strip() for p in RAW_PROXIES.split(",") if p.strip()]
_proxy_index = 0

def _get_next_proxy() -> Optional[str]:
    global _proxy_index
    if not PROXY_POOL:
        return None
    proxy = PROXY_POOL[_proxy_index % len(PROXY_POOL)]
    _proxy_index += 1
    return proxy

# 2. FAILOVER CLIENT TIERS (Anti-Bot Bypass Profiles)
CLIENT_TIERS = [
    {
        "name": "android_music",
        "client": ["android_music"],
        "user_agent": "com.google.android.apps.youtube.music/6.40.52 (Linux; U; Android 14) gzip",
    },
    {
        "name": "tv_embedded",
        "client": ["tvhtml5_embedded"],
        "user_agent": "Mozilla/5.0 (PlayStation 4 5.05) AppleWebKit/601.2 (KHTML, like Gecko)",
    },
    {
        "name": "ios_direct",
        "client": ["ios"],
        "user_agent": "com.google.ios.youtube/19.10.1 (iPhone14,3; U; CPU iOS 17_4 like Mac OS X)",
    },
]

def _clean_text(value: Any) -> str:
    if value is None:
        return ""
    return re.sub(r"\s+", " ", str(value)).strip()

def _ytm_song_to_model(song: Dict[str, Any], rank: int) -> Dict[str, Any]:
    video_id = _clean_text(song.get("videoId"))
    title = _clean_text(song.get("title"))
    artists = song.get("artists") or []
    artist = ", ".join(
        _clean_text(a.get("name")) for a in artists if isinstance(a, dict) and a.get("name")
    )
    album = ""
    if isinstance(song.get("album"), dict):
        album = _clean_text(song["album"].get("name"))

    thumbs = song.get("thumbnails") or []
    image_url = ""
    if isinstance(thumbs, list) and thumbs:
        image_url = _clean_text(thumbs[-1].get("url"))

    duration_text = _clean_text(song.get("duration"))
    duration_ms = 0
    if duration_text:
        parts = duration_text.split(":")
        try:
            total = 0
            for p in parts:
                total = total * 60 + int(p)
            duration_ms = total * 1000
        except Exception:
            duration_ms = 0

    return {
        "id": f"ytm_{video_id}",
        "title": title,
        "artist": artist,
        "album": album,
        "imageUrl": image_url,
        "durationMs": duration_ms,
        "sourceType": "youtube_music",
        "sourceId": video_id,
        "streamUrl": "",
        "backupUrls": [],
        "searchableText": f"{title} {artist} {album}".strip(),
        "youtubeUrl": f"https://www.youtube.com/watch?v={video_id}" if video_id else "",
        "providerRank": rank,
    }

def _ytmusic_search_sync(query: str, limit: int = 20) -> List[Dict[str, Any]]:
    try:
        results = _ytmusic_client.search(query, filter="songs", limit=limit) or []
        out = []
        for idx, item in enumerate(results):
            if isinstance(item, dict) and item.get("videoId"):
                out.append(_ytm_song_to_model(item, idx))
        return out
    except Exception as e:
        print(f"[METADATA SEARCH ERROR] {e}")
        return []

async def search_all_sources(query: str) -> List[Dict[str, Any]]:
    return await asyncio.to_thread(_ytmusic_search_sync, query)

# 3. SELF-HEALING STREAM RESOLVER ENGINE
def _extract_with_tier(video_id: str, tier: Dict[str, Any], proxy: Optional[str]) -> Optional[Dict[str, Any]]:
    youtube_url = f"https://www.youtube.com/watch?v={video_id}"

    opts = {
        "quiet": True,
        "no_warnings": True,
        "skip_download": True,
        "format": "bestaudio/best",
        "socket_timeout": 8,
        "extractor_args": {
            "youtube": {
                "player_client": tier["client"],
                "player_skip": ["webpage", "configs"],
            }
        },
        "http_headers": {
            "User-Agent": tier["user_agent"],
            "Accept-Language": "en-US,en;q=0.9",
        },
    }

    if proxy:
        opts["proxy"] = proxy

    try:
        with yt_dlp.YoutubeDL(opts) as ydl:
            info = ydl.extract_info(youtube_url, download=False)

        formats = info.get("formats") or []
        audio_urls = []
        for fmt in formats:
            if not isinstance(fmt, dict):
                continue
            acodec = fmt.get("acodec")
            vcodec = fmt.get("vcodec")
            url = fmt.get("url")
            if url and acodec != "none" and (vcodec == "none" or not vcodec):
                audio_urls.append(str(url))

        best_url = audio_urls[-1] if audio_urls else str(info.get("url") or "")
        if best_url:
            return {
                "streamUrl": best_url,
                "backupUrls": audio_urls[-5:],
            }
    except Exception as e:
        print(f"[EXTRACTOR TIER FAILED] Tier: {tier['name']} | Proxy: {bool(proxy)} | Error: {e}")

    return None

def _resolve_stream_resilient(video_id: str) -> Optional[Dict[str, Any]]:
    # Attempt extraction across multiple tiers and routing states
    for tier in CLIENT_TIERS:
        # First attempt: Direct / Primary Routing
        result = _extract_with_tier(video_id, tier, proxy=None)
        if result and result.get("streamUrl"):
            return result

        # Second attempt: Proxy Failover (if configured)
        proxy = _get_next_proxy()
        if proxy:
            result = _extract_with_tier(video_id, tier, proxy=proxy)
            if result and result.get("streamUrl"):
                return result

    return None

async def resolve_song_stream(song_id: str, title: str = "", artist: str = "") -> Optional[Dict[str, Any]]:
    video_id = ""
    if song_id.startswith("ytm_"):
        video_id = song_id.replace("ytm_", "", 1)
    elif song_id.strip():
        video_id = song_id.strip()

    if not video_id:
        search_query = f"{title} {artist}".strip()
        if not search_query:
            return None
        ytm_results = await search_all_sources(search_query)
        if not ytm_results:
            return None
        video_id = ytm_results[0].get("sourceId", "")

    if not video_id:
        return None

    # Cache Lookup
    if video_id in _stream_cache:
        return _stream_cache[video_id]

    # Automated Failover Execution
    resolved = await asyncio.to_thread(_resolve_stream_resilient, video_id)

    if resolved and resolved.get("streamUrl"):
        output = {
            "youtubeUrl": f"https://www.youtube.com/watch?v={video_id}",
            "streamUrl": resolved.get("streamUrl"),
            "backupUrls": resolved.get("backupUrls", []),
        }
        _stream_cache[video_id] = output
        return output

    return None

async def get_trending_like_songs() -> List[Dict[str, Any]]:
    return await search_all_sources("top hindi songs")