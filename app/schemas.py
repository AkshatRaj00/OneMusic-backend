from pydantic import BaseModel, Field
from typing import List, Optional


class SongOut(BaseModel):
    id: str
    title: str
    artist: str
    album: str = ""
    imageUrl: str = ""
    durationMs: int = 0
    sourceType: str
    sourceId: str
    streamUrl: str = ""
    backupUrls: List[str] = Field(default_factory=list)
    searchableText: str = ""
    youtubeUrl: str = ""
    providerRank: int = 999


class SongsResponse(BaseModel):
    status: str
    count: int
    songs: List[SongOut]
    message: Optional[str] = None