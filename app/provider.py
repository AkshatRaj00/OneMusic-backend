import asyncio
import re
from typing import Any, Dict, List, Optional

from cachetools import TTLCache
from ytmusicapi import YTMusic


_stream_cache = TTLCache(maxsize=500, ttl=3600)
_ytmusic_client = YTMusic()

# Temporary stable MP3 for player/backend testing.
# Later replace this with your own licensed MP3 hosting URL.
_TEST_AUDIO_URL = "https://www.soundhelix.com/examples/mp3/SoundHelix-Song-1.mp3"


def _clean_text(value: Any) -> str:
    if value is None:
        return ""
    return re.sub(r"\s+", " ", str(value)).strip()


def _ytm_song_to_model(song: Dict[str, Any], rank: int) -> Dict[str, Any]:
    video_id = _clean_text(song.get("videoId"))
    title = _clean_text(song.get("title"))

    artists = song.get("artists") or []
    artist = ", ".join(
        _clean_text(item.get("name"))
        for item in artists
        if isinstance(item, dict) and item.get("name")
    )

    album = ""
    if isinstance(song.get("album"), dict):
        album = _clean_text(song["album"].get("name"))

    thumbnails = song.get("thumbnails") or []
    image_url = ""
    if isinstance(thumbnails, list) and thumbnails:
        image_url = _clean_text(thumbnails[-1].get("url"))

    duration_ms = 0
    duration_text = _clean_text(song.get("duration"))

    if duration_text:
        try:
            seconds = 0
            for part in duration_text.split(":"):
                seconds = seconds * 60 + int(part)
            duration_ms = seconds * 1000
        except (TypeError, ValueError):
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
        "youtubeUrl": (
            f"https://www.youtube.com/watch?v={video_id}"
            if video_id
            else ""
        ),
        "providerRank": rank,
    }


def _ytmusic_search_sync(query: str, limit: int = 20) -> List[Dict[str, Any]]:
    try:
        results = _ytmusic_client.search(
            query,
            filter="songs",
            limit=limit,
        ) or []

        output: List[Dict[str, Any]] = []

        for index, item in enumerate(results):
            if isinstance(item, dict) and item.get("videoId"):
                output.append(_ytm_song_to_model(item, index))

        return output

    except Exception as error:
        print(f"[YTMUSIC SEARCH ERROR] {error}")
        return []


async def search_all_sources(query: str) -> List[Dict[str, Any]]:
    return await asyncio.to_thread(_ytmusic_search_sync, query)


def _extract_audio_stream(video_id: str) -> Optional[Dict[str, Any]]:
    print(f"[RESOLVER] Test audio stream returned for video={video_id}")

    return {
        "streamUrl": _TEST_AUDIO_URL,
        "backupUrls": [],
    }


async def resolve_song_stream(
    song_id: str,
    title: str = "",
    artist: str = "",
) -> Optional[Dict[str, Any]]:
    video_id = _clean_text(song_id)

    if video_id.startswith("ytm_"):
        video_id = video_id[4:]

    if not video_id:
        search_query = f"{title} {artist}".strip()

        if not search_query:
            return None

        results = await search_all_sources(search_query)

        if not results:
            return None

        video_id = _clean_text(results[0].get("sourceId"))

    if not video_id:
        return None

    cached = _stream_cache.get(video_id)

    if cached:
        print(f"[RESOLVER] Cache hit: {video_id}")
        return cached

    resolved = _extract_audio_stream(video_id)

    if not resolved or not resolved.get("streamUrl"):
        return None

    output = {
        "youtubeUrl": f"https://www.youtube.com/watch?v={video_id}",
        "streamUrl": resolved["streamUrl"],
        "backupUrls": resolved.get("backupUrls", []),
    }

    _stream_cache[video_id] = output
    return output


async def get_trending_like_songs() -> List[Dict[str, Any]]:
    return await search_all_sources("top hindi songs")