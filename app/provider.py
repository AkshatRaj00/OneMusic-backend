import asyncio
import re
import time
from typing import Any, Dict, List, Optional

import httpx
import yt_dlp
from cachetools import TTLCache
from ytmusicapi import YTMusic

# In-Memory Cache: 2000 songs for 3 hours (10800 seconds)
_stream_cache = TTLCache(maxsize=2000, ttl=10800)

_ytmusic_client = YTMusic()
DEFAULT_TIMEOUT = 12.0

# Decentralized Public Piped Instances for emergency fallback
PIPED_INSTANCES = [
    "https://pipedapi.kavin.rocks",
    "https://api.piped.privacy.com.de",
    "https://piped-api.garudalinux.org",
    "https://api.piped.yt",
]


def _clean_text(value: Any) -> str:
    if value is None:
        return ""
    return re.sub(r"\s+", " ", str(value)).strip()


def _normalize_song_key(title: str, artist: str) -> str:
    raw = f"{title} {artist}".lower()
    raw = re.sub(r"[^a-z0-9\s]", " ", raw)
    return re.sub(r"\s+", " ", raw).strip()


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

    youtube_url = f"https://www.youtube.com/watch?v={video_id}" if video_id else ""
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
        "youtubeUrl": youtube_url,
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
        print(f"[YTM SEARCH ERROR] {e}")
        return []


async def search_all_sources(query: str) -> List[Dict[str, Any]]:
    return await asyncio.to_thread(_ytmusic_search_sync, query)


def _resolve_ytdlp_sync(video_id: str) -> Optional[Dict[str, Any]]:
    youtube_url = f"https://www.youtube.com/watch?v={video_id}"
    
    # Android & iOS client profile stops 429 Bot Check & n-token failure
    opts = {
        "quiet": True,
        "no_warnings": True,
        "skip_download": True,
        "format": "bestaudio/best",
        "extractor_args": {
            "youtube": {
                "player_client": ["android", "ios", "mweb"]
            }
        },
    }

    try:
        with yt_dlp.YoutubeDL(opts) as ydl:
            info = ydl.extract_info(youtube_url, download=False)

        formats = info.get("formats") or []
        audio_urls = []
        for fmt in formats:
            if not isinstance(fmt, dict):
                continue
            vcodec = fmt.get("vcodec")
            acodec = fmt.get("acodec")
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
        print(f"[YTDLP PRIMARY ERROR] {e}")

    return None


async def _resolve_piped_fallback(video_id: str) -> Optional[Dict[str, Any]]:
    # Emergency fallback across decentralized nodes
    async with httpx.AsyncClient(timeout=DEFAULT_TIMEOUT, follow_redirects=True) as client:
        for instance in PIPED_INSTANCES:
            endpoint = f"{instance}/streams/{video_id}"
            try:
                res = await client.get(endpoint)
                if res.status_code == 200:
                    data = res.json()
                    audio_streams = data.get("audioStreams") or []
                    if audio_streams:
                        # Highest bitrate stream
                        best_stream = audio_streams[-1].get("url")
                        if best_stream:
                            return {
                                "streamUrl": best_stream,
                                "backupUrls": [s.get("url") for s in audio_streams if s.get("url")],
                            }
            except Exception:
                continue
    return None


async def resolve_song_stream(song_id: str, title: str = "", artist: str = "") -> Optional[Dict[str, Any]]:
    # 1. Extract Video ID
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

    # 2. Check L1 Memory Cache (3 hours validity)
    if video_id in _stream_cache:
        cached_val = _stream_cache[video_id]
        print(f"[CACHE HIT] Returning in-memory stream for: {video_id}")
        return cached_val

    print(f"[CACHE MISS] Resolving fresh stream for: {video_id}")
    youtube_url = f"https://www.youtube.com/watch?v={video_id}"

    # 3. Layer 1: yt-dlp Native Android Client
    resolved = await asyncio.to_thread(_resolve_ytdlp_sync, video_id)

    # 4. Layer 2: Emergency Piped Mesh Fallback
    if not resolved or not resolved.get("streamUrl"):
        print(f"[FALLBACK TRIGGERED] Switching to Piped mesh for: {video_id}")
        resolved = await _resolve_piped_fallback(video_id)

    if resolved and resolved.get("streamUrl"):
        output = {
            "youtubeUrl": youtube_url,
            "streamUrl": resolved.get("streamUrl"),
            "backupUrls": resolved.get("backupUrls", []),
        }
        # Save in Cache
        _stream_cache[video_id] = output
        return output

    return None


async def get_trending_like_songs() -> List[Dict[str, Any]]:
    return await search_all_sources("top hindi songs")