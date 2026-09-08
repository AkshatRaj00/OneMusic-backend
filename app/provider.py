import asyncio
import os
import re
import shutil
import tempfile
from typing import Any, Dict, List, Optional

import yt_dlp
from cachetools import TTLCache
from ytmusicapi import YTMusic


_stream_cache = TTLCache(maxsize=500, ttl=3600)
_ytmusic_client = YTMusic()


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


def _get_secret_cookie_file() -> Optional[str]:
    cookie_file = os.getenv("YTDLP_COOKIE_FILE", "").strip()

    if cookie_file and os.path.isfile(cookie_file):
        return cookie_file

    return None


def _make_writable_cookie_copy() -> Optional[str]:
    secret_file = _get_secret_cookie_file()

    if not secret_file:
        print("[RESOLVER] No cookies file configured.")
        return None

    try:
        temp_dir = tempfile.gettempdir()
        writable_cookie_file = os.path.join(temp_dir, "youtube_cookies.txt")

        shutil.copyfile(secret_file, writable_cookie_file)

        print("[RESOLVER] Using configured YouTube cookies.")
        return writable_cookie_file
    except Exception as error:
        print(f"[RESOLVER] Could not copy cookie file: {error}")
        return None


def _extract_audio_stream(video_id: str) -> Optional[Dict[str, Any]]:
    youtube_url = f"https://www.youtube.com/watch?v={video_id}"
    writable_cookie_file = _make_writable_cookie_copy()

    options: Dict[str, Any] = {
        "quiet": True,
        "no_warnings": False,
        "skip_download": True,
        "noplaylist": True,
        "socket_timeout": 30,
        "retries": 3,
        "fragment_retries": 3,
        "cachedir": False,
        "format": (
            "bestaudio[acodec!=none][protocol=https]"
            "/bestaudio[acodec!=none]"
            "/bestaudio"
            "/best"
        ),
        "extractor_args": {
            "youtube": {
                "player_client": [
                    "default",
                    "web_safari",
                    "-android_sdkless",
                ],
            },
        },
        "http_headers": {
            "Accept-Language": "en-US,en;q=0.9",
        },
    }

    if writable_cookie_file:
        options["cookiefile"] = writable_cookie_file

    try:
        with yt_dlp.YoutubeDL(options) as ydl:
            info = ydl.extract_info(youtube_url, download=False)

        formats = info.get("formats") or []
        candidates: List[Dict[str, Any]] = []

        for fmt in formats:
            if not isinstance(fmt, dict):
                continue

            url = str(fmt.get("url") or "").strip()
            acodec = str(fmt.get("acodec") or "none")
            vcodec = str(fmt.get("vcodec") or "none")
            protocol = str(fmt.get("protocol") or "")

            if not url or acodec == "none":
                continue

            if vcodec not in ("none", ""):
                continue

            if protocol and not protocol.startswith("http"):
                continue

            candidates.append(fmt)

        candidates.sort(
            key=lambda item: (
                item.get("abr") or 0,
                item.get("tbr") or 0,
                item.get("filesize") or 0,
            ),
            reverse=True,
        )

        if candidates:
            best = candidates[0]
            stream_url = str(best.get("url") or "").strip()

            if stream_url:
                backups = [
                    str(item.get("url"))
                    for item in candidates[1:6]
                    if item.get("url")
                ]

                print(
                    "[RESOLVER] Stream resolved "
                    f"video={video_id}, "
                    f"format={best.get('format_id')}, "
                    f"ext={best.get('ext')}, "
                    f"abr={best.get('abr')}"
                )

                return {
                    "streamUrl": stream_url,
                    "backupUrls": backups,
                }

        fallback_url = str(info.get("url") or "").strip()

        if fallback_url.startswith(("http://", "https://")):
            return {
                "streamUrl": fallback_url,
                "backupUrls": [],
            }

        print(f"[RESOLVER] No playable audio format found: {video_id}")
        return None

    except Exception as error:
        print(f"[RESOLVER ERROR] video={video_id} | {error}")
        return None

    finally:
        if writable_cookie_file:
            try:
                os.remove(writable_cookie_file)
            except OSError:
                pass


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

    resolved = await asyncio.to_thread(
        _extract_audio_stream,
        video_id,
    )

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