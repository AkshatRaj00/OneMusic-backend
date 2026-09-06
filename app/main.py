from fastapi import FastAPI, HTTPException, Query
from fastapi.middleware.cors import CORSMiddleware

from .cache import get_cache, set_cache
from .provider import get_trending_like_songs, resolve_song_stream, search_all_sources
from .schemas import SongOut, SongsResponse

app = FastAPI(title="OneMusic Powerful Backend", version="2.0.0")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

@app.get("/")
async def root():
    return {"status": "ok", "message": "OneMusic backend is running"}

@app.get("/health")
async def health():
    return {"status": "ok"}

@app.get("/search", response_model=SongsResponse)
async def search(q: str = Query(..., min_length=1)):
    query = q.strip()
    cache_key = f"search:{query.lower()}"
    cached = get_cache(cache_key)
    if cached is not None:
        return SongsResponse(status="SUCCESS", count=len(cached), songs=cached)

    songs = await search_all_sources(query)
    set_cache(cache_key, songs, 1200)
    return SongsResponse(
        status="SUCCESS",
        count=len(songs),
        songs=[SongOut(**song) for song in songs],
    )

@app.get("/trending", response_model=SongsResponse)
async def trending():
    cache_key = "trending"
    cached = get_cache(cache_key)
    if cached is not None:
        return SongsResponse(status="SUCCESS", count=len(cached), songs=cached)

    songs = await get_trending_like_songs()
    set_cache(cache_key, songs, 900)
    return SongsResponse(
        status="SUCCESS",
        count=len(songs),
        songs=[SongOut(**song) for song in songs],
    )

@app.get("/resolve", response_model=SongOut)
async def resolve(
    id: str = Query(...),
    title: str = Query(""),
    artist: str = Query(""),
    album: str = Query(""),
    imageUrl: str = Query(""),
    durationMs: int = Query(0),
    sourceType: str = Query("unknown"),
    sourceId: str = Query(""),
):
    resolved = await resolve_song_stream(id, title=title, artist=artist)
    if not resolved or not resolved.get("streamUrl"):
        raise HTTPException(status_code=404, detail="Playable stream not found")

    song = {
        "id": id,
        "title": title,
        "artist": artist,
        "album": album,
        "imageUrl": imageUrl,
        "durationMs": durationMs,
        "sourceType": sourceType,
        "sourceId": sourceId or id,
        "streamUrl": resolved.get("streamUrl", ""),
        "backupUrls": resolved.get("backupUrls", []),
        "searchableText": f"{title} {artist} {album}".strip(),
        "youtubeUrl": resolved.get("youtubeUrl", ""),
        "providerRank": 0,
    }
    return SongOut(**song)