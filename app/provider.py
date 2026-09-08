import asyncio
from typing import Any, Dict, List, Optional

import httpx


JIOSAAVN_API_BASE = "https://saavn.dev/api"


def _clean_text(value: Any) -> str:
    if value is None:
        return ""

    if isinstance(value, str):
        return value.strip()

    return str(value).strip()


def _first_image_url(images: Any) -> str:
    if not isinstance(images, list):
        return ""

    for image in reversed(images):
        if isinstance(image, dict):
            url = _clean_text(image.get("url"))
            if url:
                return url

    return ""


def _first_download_url(download_urls: Any) -> str:
    if not isinstance(download_urls, list):
        return ""

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

    return {
        "id": _clean_text(song.get("id")),
        "title": _clean_text(song.get("name")) or "Unknown title",
        "artist": ", ".join(artist_names) or "Unknown artist",
        "album": album_name,
        "image": _first_image_url(song.get("image")),
        "duration": int(song.get("duration") or 0),
        "streamUrl": _first_download_url(song.get("downloadUrl")),
    }


async def _get_json(
    client: httpx.AsyncClient,
    path: str,
    params: Optional[Dict[str, Any]] = None,
) -> Dict[str, Any]:
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

    async with httpx.AsyncClient(
        base_url=JIOSAAVN_API_BASE,
        timeout=httpx.Timeout(20.0),
        follow_redirects=True,
        headers={"Accept": "application/json"},
    ) as client:
        data = await _get_json(
            client,
            "/search/songs",
            {"query": clean_query, "page": 1, "limit": limit},
        )

    results = data.get("data", {}).get("results", [])
    if not isinstance(results, list):
        return []

    return [_format_song(song) for song in results if isinstance(song, dict)]


async def get_trending_like_songs(limit: int = 20) -> List[Dict[str, Any]]:
    queries = ["Hindi hits", "Punjabi hits", "Indian pop"]

    async with httpx.AsyncClient(
        base_url=JIOSAAVN_API_BASE,
        timeout=httpx.Timeout(20.0),
        follow_redirects=True,
        headers={"Accept": "application/json"},
    ) as client:
        responses = await asyncio.gather(
            *[
                _get_json(
                    client,
                    "/search/songs",
                    {"query": query, "page": 1, "limit": 10},
                )
                for query in queries
            ],
            return_exceptions=True,
        )

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

            formatted_song = _format_song(song)
            song_id = formatted_song["id"]

            if song_id and song_id not in used_ids:
                used_ids.add(song_id)
                songs.append(formatted_song)

            if len(songs) >= limit:
                return songs

    return songs


async def resolve_song_stream(song_id: str) -> Optional[Dict[str, Any]]:
    clean_song_id = song_id.strip()

    if not clean_song_id:
        return None

    async with httpx.AsyncClient(
        base_url=JIOSAAVN_API_BASE,
        timeout=httpx.Timeout(20.0),
        follow_redirects=True,
        headers={"Accept": "application/json"},
    ) as client:
        data = await _get_json(client, f"/songs/{clean_song_id}")

    song = data.get("data", [None])

    if isinstance(song, list):
        song = song[0] if song else None

    if not isinstance(song, dict):
        return None

    return _format_song(song)