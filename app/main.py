import os
import logging
from typing import Optional, List
import httpx
import yt_dlp
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

# ---------------------------------------------------------------------------
# हथियार 1 & 2: TV/VR क्लाइंट स्पूफिंग + रेजिडेंशियल प्रॉक्सी (अगर सेट हो)
# ---------------------------------------------------------------------------
RESIDENTIAL_PROXY = os.getenv("PROXY_URL", None)

YDL_OPTS = {
    'format': 'bestaudio[ext=m4a]/bestaudio/best',
    'quiet': True,
    'no_warnings': True,
    'extract_flat': False,
    'extractor_args': {
        'youtube': {
            'player_client': ['tv_embedded', 'android_vr', 'ios'],
            'player_skip': ['webpage', 'configs'],
        }
    },
}

if RESIDENTIAL_PROXY:
    YDL_OPTS['proxy'] = RESIDENTIAL_PROXY

# ---------------------------------------------------------------------------
# हथियार 3: डिसेंट्रलाइज़्ड Piped API पूल (नोड फॉलबैक)
# ---------------------------------------------------------------------------
PIPED_INSTANCES = [
    "https://pipedapi.kavin.rocks",
    "https://api.piped.privacydev.net",
    "https://pipedapi.tokhmi.xyz",
    "https://piped-api.garudalinux.org",
]

async def _extract_via_piped(video_id: str) -> Optional[str]:
    async with httpx.AsyncClient(timeout=4.0) as client:
        for instance in PIPED_INSTANCES:
            try:
                url = f"{instance}/streams/{video_id}"
                resp = await client.get(url)
                if resp.status_code == 200:
                    data = resp.json()
                    audio_streams = [
                        s for s in data.get("audioStreams", [])
                        if s.get("format") == "M4A" or "mp4" in s.get("mimeType", "")
                    ]
                    if audio_streams:
                        best = max(audio_streams, key=lambda x: x.get("bitrate", 0))
                        return best.get("url")
            except Exception as e:
                logging.warning(f"[PIPED MESH] Node {instance} failed: {e}")
                continue
    return None

def _extract_via_spoof(video_id: str) -> Optional[str]:
    try:
        url = f"https://www.youtube.com/watch?v={video_id}"
        with yt_dlp.YoutubeDL(YDL_OPTS) as ydl:
            info = ydl.extract_info(url, download=False)
            return info.get('url')
    except Exception as e:
        logging.warning(f"[YTDL SPOOF FAILED] {e}")
        return None

# ---------------------------------------------------------------------------
# एंडपॉइंट्स
# ---------------------------------------------------------------------------

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
    stream_url = ""
    youtube_url = ""
    clean_video_id = sourceId or id.replace("ytm_", "").strip()

    # चरण 1: तुम्हारा मौजूदा प्रोवाइडर कोशिश करेगा
    try:
        resolved = await resolve_song_stream(id, title=title, artist=artist)
        if resolved and resolved.get("streamUrl"):
            stream_url = resolved["streamUrl"]
            youtube_url = resolved.get("youtubeUrl", "")
    except Exception as e:
        logging.warning(f"[RESOLVER] Base provider failed: {e}")

    # चरण 2: अगर बेस प्रोवाइडर ब्लॉक हुआ, तो TV/VR क्लाइंट स्पूफिंग चलाओ
    if not stream_url and clean_video_id:
        logging.info(f"[RESOLVER] Trying TV/VR Client Spoofing for {clean_video_id}...")
        stream_url = _extract_via_spoof(clean_video_id)
        if stream_url:
            youtube_url = f"https://www.youtube.com/watch?v={clean_video_id}"

    # चरण 3: अगर YouTube ने फिर भी ब्लॉक किया, तो डिसेंट्रलाइज़्ड Piped मेश से निकालो
    if not stream_url and clean_video_id:
        logging.info(f"[RESOLVER] Switching to Decentralized Piped Mesh for {clean_video_id}...")
        stream_url = await _extract_via_piped(clean_video_id)
        if stream_url:
            youtube_url = f"https://www.youtube.com/watch?v={clean_video_id}"

    # अगर तीनों टियर के बाद भी नहीं मिला
    if not stream_url:
        raise HTTPException(status_code=404, detail="Playable stream not found across all tiers")

    song = {
        "id": id,
        "title": title,
        "artist": artist,
        "album": album,
        "imageUrl": imageUrl,
        "durationMs": durationMs,
        "sourceType": sourceType,
        "sourceId": clean_video_id,
        "streamUrl": stream_url,
        "backupUrls": [],
        "searchableText": f"{title} {artist} {album}".strip(),
        "youtubeUrl": youtube_url or f"https://www.youtube.com/watch?v={clean_video_id}",
        "providerRank": 0,
    }
    return SongOut(**song)