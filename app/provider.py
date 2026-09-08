import asyncio
from typing import Any, Dict, List, Optional
import httpx

JIOSAAVN_API_BASE = "https://saavn.dev/api"

# कनेक्शन पूल को रीयूज़ करने के लिए सिंगल क्लाइंट
_http_client: Optional[httpx.AsyncClient] = None


def _get_client() -> httpx.AsyncClient:
    global _http_client
    if _http_client is None or _http_client.is_closed:
        _http_client = httpx.AsyncClient(
            base_url=JIOSAAVN_API_BASE,
            timeout=httpx.Timeout(15.0),
            follow_redirects=True,
            headers={
                "Accept": "application/json",
                "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36",
            },
        )
    return _http_client


def _clean_text(value: Any) -> str:
    if value is None:
        return ""
    return str(value).strip()


def _first_image_url(images: Any) -> str:
    if not isinstance(images, list):
        return ""
    # उच्चतम रिज़ॉल्यूशन वाली इमेज के लिए reversed ट्रैवर्सल
    for image in reversed(images):
        if isinstance(image, dict):
            url = _clean_text(image.get("url"))
            if url:
                return url
    return ""


def _highest_quality_audio_url(download_urls: Any) -> str:
    if not isinstance(download_urls, list):
        return ""
    # 320kbps / 160kbps (लास्ट आइटम सबसे हाईएस्ट बिटरेट होता है)
    for item in reversed(download_urls):
        if isinstance(item, dict):
            url = _clean_text(item.get("url"))
            if url:
                return url
    return ""


def _format_song(song: Dict[str, Any]) -> Dict[str, Any]:
    artists = song.get("artists", {})
    primary_artists = artists.get("primary", []) if isinstance(artists, dict) else []

    artist_names = [
        _clean_text(artist.get("name"))
        for artist in primary_artists
        if isinstance(artist, dict) and _clean_text(artist.get("name"))
    ]

    album = song.get("album", {})
    album_name = _clean_text(album.get("name")) if isinstance(album, dict) else ""

    # JioSaavn सेकंड में देता है, Flutter को मिलीसेकंड चाहिए
    duration_seconds = 0
    try:
        duration_seconds = int(song.get("duration") or 0)
    except (ValueError, TypeError):
        duration_seconds = 0

    best_url = _highest_quality_audio_url(song.get("downloadUrl"))

    return {
        "id": _clean_text(song.get("id")),
        "title": _clean_text(song.get("name")) or "Unknown title",
        "artist": ", ".join(artist_names) or "Unknown artist",
        "album": album_name,
        "imageUrl": _first_image_url(song.get("image")),  # ✅ Flutter मॉडल की 'imageUrl'
        "durationMs": duration_seconds * 1000,            # ✅ मिलीसेकंड में कन्वर्टेड
        "sourceType": "jiosaavn",
        "sourceId": _clean_text(song.get("id")),
        "streamUrl": best_url,
        "backupUrls": [],
    }


async def _get_json(path: str, params: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
    client = _get_client()
    response = await client.get(path, params=params)
    response.raise_for_status()
    data = response.json()
    if not isinstance(data, dict):
        raise ValueError("Invalid API response")
    return data


async def search_all_sources(query: str, limit: int = 20) -> List[Dict[str, Any]]:
    clean_query = query.strip()
    if not clean_query:
        return []

    try:
        data = await _get_json(
            "/search/songs",
            {"query": clean_query, "page": 1, "limit": limit},
        )
        results = data.get("data", {}).get("results", [])
        if not isinstance(results, list):
            return []

        return [_format_song(song) for song in results if isinstance(song, dict)]
    except Exception as e:
        print(f"[SEARCH ERROR] {e}")
        return []


async def get_trending_like_songs(limit: int = 20) -> List[Dict[str, Any]]:
    queries = ["Hindi hits", "Punjabi hits", "Arijit Singh"]

    try:
        tasks = [
            _get_json("/search/songs", {"query": q, "page": 1, "limit": 10})
            for q in queries
        ]
        responses = await asyncio.gather(*tasks, return_exceptions=True)

        songs: List[Dict[str, Any]] = []
        used_ids = set()

        for response in responses:
            if isinstance(response, Exception):
                continue

            results = response.get("data", {}).get("results", [])
            if not isinstance(results, list):
                continue

            for song in results:
                if not isinstance(song, dict):
                    continue

                formatted = _format_song(song)
                s_id = formatted["id"]

                if s_id and s_id not in used_ids:
                    used_ids.add(s_id)
                    songs.append(formatted)

                if len(songs) >= limit:
                    return songs

        return songs
    except Exception as e:
        print(f"[TRENDING ERROR] {e}")
        return []


async def resolve_song_stream(song_id: str) -> Optional[Dict[str, Any]]:
    clean_song_id = song_id.strip()
    if not clean_song_id:
        return None

    try:
        # ✅ JioSaavn API v4 फिक्स: क्वेरी पैरामीटर (?id=...) का उपयोग
        data = await _get_json("/songs", params={"id": clean_song_id})
        raw_data = data.get("data")

        song = None
        if isinstance(raw_data, list) and raw_data:
            song = raw_data[0]
        elif isinstance(raw_data, dict):
            song = raw_data

        if not isinstance(song, dict):
            return None

        return _format_song(song)
    except Exception as e:
        print(f"[RESOLVE ERROR] ID={clean_song_id} | {e}")
        return None