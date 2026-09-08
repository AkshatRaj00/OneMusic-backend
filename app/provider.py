import asyncio
from typing import Any, Dict, List, Optional

import httpx


JIOSAAVN_API_BASE = "https://saavn.dev/api"

_http_client: Optional[httpx.AsyncClient] = None


async def get_http_client() -> httpx.AsyncClient:
    global _http_client

    if _http_client is None or _http_client.is_closed:
        _http_client = httpx.AsyncClient(
            base_url=JIOSAAVN_API_BASE,
            timeout=httpx.Timeout(
                connect=10.0,
                read=20.0,
                write=20.0,
                pool=20.0,
            ),
            follow_redirects=True,
            headers={
                "Accept": "application/json",
            },
        )

    return _http_client


async def close_http_client() -> None:
    global _http_client

    if _http_client is not None and not _http_client.is_closed:
        await _http_client.aclose()

    _http_client = None


def _clean_text(value: Any) -> str:
    if value is None:
        return ""

    return str(value).strip()


def _safe_int(value: Any, fallback: int = 0) -> int:
    try:
        return int(value)
    except (TypeError, ValueError):
        return fallback


def _first_image_url(images: Any) -> str:
    if not isinstance(images, list):
        return ""

    for image in reversed(images):
        if not isinstance(image, dict):
            continue

        image_url = _clean_text(image.get("url"))

        if image_url:
            return image_url

    return ""


def _first_download_url(download_urls: Any) -> str:
    if not isinstance(download_urls, list):
        return ""

    for item in reversed(download_urls):
        if not isinstance(item, dict):
            continue

        download_url = _clean_text(item.get("url"))

        if download_url:
            return download_url

    return ""


def _artist_names(song: Dict[str, Any]) -> str:
    artists = song.get("artists")

    if not isinstance(artists, dict):
        return "Unknown artist"

    primary_artists = artists.get("primary")

    if not isinstance(primary_artists, list):
        return "Unknown artist"

    names: List[str] = []

    for artist in primary_artists:
        if not isinstance(artist, dict):
            continue

        name = _clean_text(artist.get("name"))

        if name:
            names.append(name)

    return ", ".join(names) if names else "Unknown artist"


def _album_name(song: Dict[str, Any]) -> str:
    album = song.get("album")

    if not isinstance(album, dict):
        return ""

    return _clean_text(album.get("name"))


def _format_song(song: Dict[str, Any]) -> Dict[str, Any]:
    song_id = _clean_text(song.get("id"))
    duration_seconds = _safe_int(song.get("duration"))

    return {
        "id": song_id,
        "title": _clean_text(song.get("name")) or "Unknown title",
        "artist": _artist_names(song),
        "album": _album_name(song),
        "imageUrl": _first_image_url(song.get("image")),
        "durationMs": duration_seconds * 1000,
        "sourceType": "catalog",
        "sourceId": song_id,
        "streamUrl": _first_download_url(song.get("downloadUrl")),
        "backupUrls": [],
    }


async def _get_json(
    path: str,
    params: Optional[Dict[str, Any]] = None,
) -> Dict[str, Any]:
    client = await get_http_client()

    response = await client.get(path, params=params)
    response.raise_for_status()

    payload = response.json()

    if not isinstance(payload, dict):
        raise ValueError("Music provider returned invalid JSON")

    return payload


def _extract_song_list(payload: Dict[str, Any]) -> List[Dict[str, Any]]:
    raw_data = payload.get("data")

    if isinstance(raw_data, list):
        return [
            item
            for item in raw_data
            if isinstance(item, dict)
        ]

    if isinstance(raw_data, dict):
        results = raw_data.get("results")

        if isinstance(results, list):
            return [
                item
                for item in results
                if isinstance(item, dict)
            ]

        songs = raw_data.get("songs")

        if isinstance(songs, list):
            return [
                item
                for item in songs
                if isinstance(item, dict)
            ]

    return []


async def search_all_sources(
    query: str,
    limit: int = 20,
) -> List[Dict[str, Any]]:
    clean_query = query.strip()

    if not clean_query:
        return []

    try:
        payload = await _get_json(
            "/search/songs",
            {
                "query": clean_query,
                "page": 1,
                "limit": limit,
            },
        )

        raw_songs = _extract_song_list(payload)
        formatted_songs = [_format_song(song) for song in raw_songs]

        print(
            f"[SEARCH] query={clean_query!r}, "
            f"provider_songs={len(raw_songs)}, "
            f"formatted_songs={len(formatted_songs)}"
        )

        return formatted_songs

    except httpx.HTTPStatusError as error:
        print(
            f"[SEARCH HTTP ERROR] query={clean_query!r}, "
            f"status={error.response.status_code}, "
            f"body={error.response.text[:500]}"
        )
        return []

    except httpx.HTTPError as error:
        print(f"[SEARCH NETWORK ERROR] query={clean_query!r}, error={error!r}")
        return []

    except Exception as error:
        print(f"[SEARCH ERROR] query={clean_query!r}, error={error!r}")
        return []


async def get_trending_like_songs(
    limit: int = 20,
) -> List[Dict[str, Any]]:
    queries = [
        "Hindi hits",
        "Punjabi hits",
        "Arijit Singh",
    ]

    responses = await asyncio.gather(
        *[
            search_all_sources(query, limit=10)
            for query in queries
        ],
        return_exceptions=True,
    )

    songs: List[Dict[str, Any]] = []
    seen_song_ids: set[str] = set()

    for query, response in zip(queries, responses):
        if isinstance(response, Exception):
            print(f"[TRENDING ERROR] query={query!r}, error={response!r}")
            continue

        print(f"[TRENDING] query={query!r}, received={len(response)}")

        for song in response:
            song_id = _clean_text(song.get("id"))

            if not song_id or song_id in seen_song_ids:
                continue

            seen_song_ids.add(song_id)
            songs.append(song)

            if len(songs) >= limit:
                return songs

    print(f"[TRENDING] final_song_count={len(songs)}")
    return songs


async def resolve_song_stream(song_id: str) -> Optional[Dict[str, Any]]:
    clean_song_id = song_id.strip()

    if not clean_song_id:
        return None

    try:
        payload = await _get_json(
            "/songs",
            {
                "id": clean_song_id,
            },
        )

        songs = _extract_song_list(payload)

        if not songs:
            print(f"[RESOLVE] no song returned for id={clean_song_id!r}")
            return None

        formatted_song = _format_song(songs[0])

        print(
            f"[RESOLVE] id={clean_song_id!r}, "
            f"title={formatted_song['title']!r}, "
            f"has_stream_url={bool(formatted_song['streamUrl'])}"
        )

        return formatted_song

    except httpx.HTTPStatusError as error:
        print(
            f"[RESOLVE HTTP ERROR] id={clean_song_id!r}, "
            f"status={error.response.status_code}, "
            f"body={error.response.text[:500]}"
        )
        return None

    except httpx.HTTPError as error:
        print(f"[RESOLVE NETWORK ERROR] id={clean_song_id!r}, error={error!r}")
        return None

    except Exception as error:
        print(f"[RESOLVE ERROR] id={clean_song_id!r}, error={error!r}")
        return None