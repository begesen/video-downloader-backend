import re
from urllib.parse import urlparse

import yt_dlp
from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel, Field

app = FastAPI(title="Video Downloader API")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


class ExtractRequest(BaseModel):
    url: str = Field(..., min_length=1, description="YouTube veya Pinterest video URL'si")


class ExtractResponse(BaseModel):
    title: str
    thumbnail: str | None
    download_url: str


YOUTUBE_PATTERN = re.compile(
    r"(youtube\.com|youtu\.be|youtube-nocookie\.com|music\.youtube\.com)",
    re.IGNORECASE,
)
PINTEREST_PATTERN = re.compile(r"(pinterest\.|pin\.it)", re.IGNORECASE)


def is_supported_url(url: str) -> bool:
    parsed = urlparse(url.strip())
    if parsed.scheme not in ("http", "https"):
        return False

    host = parsed.netloc.lower()
    if host.startswith("www."):
        host = host[4:]

    target = f"{host}{parsed.path}"
    return bool(YOUTUBE_PATTERN.search(target) or PINTEREST_PATTERN.search(target))


def get_best_download_url(info: dict) -> str:
    if info.get("url"):
        return info["url"]

    requested_formats = info.get("requested_formats") or []
    if requested_formats:
        best = max(
            requested_formats,
            key=lambda fmt: (fmt.get("height") or 0, fmt.get("tbr") or 0),
        )
        if best.get("url"):
            return best["url"]

    formats = info.get("formats") or []
    playable = [
        fmt
        for fmt in formats
        if fmt.get("url") and fmt.get("vcodec") != "none" and fmt.get("acodec") != "none"
    ]

    if playable:
        best = max(
            playable,
            key=lambda fmt: (fmt.get("height") or 0, fmt.get("tbr") or 0),
        )
        return best["url"]

    video_only = [
        fmt for fmt in formats if fmt.get("url") and fmt.get("vcodec") != "none"
    ]
    if video_only:
        best = max(
            video_only,
            key=lambda fmt: (fmt.get("height") or 0, fmt.get("tbr") or 0),
        )
        return best["url"]

    raise ValueError("Video için indirilebilir bir bağlantı bulunamadı.")


def extract_video_metadata(url: str) -> ExtractResponse:
    ydl_opts = {
        "quiet": True,
        "no_warnings": True,
        "skip_download": True,
        "format": "best[acodec!=none][vcodec!=none]/bestvideo+bestaudio/best",
        "noplaylist": True,
    }

    with yt_dlp.YoutubeDL(ydl_opts) as ydl:
        info = ydl.extract_info(url, download=False)

    if not info:
        raise ValueError("Video bilgisi alınamadı.")

    title = info.get("title")
    if not title:
        raise ValueError("Video başlığı bulunamadı.")

    download_url = get_best_download_url(info)

    return ExtractResponse(
        title=title,
        thumbnail=info.get("thumbnail"),
        download_url=download_url,
    )


@app.get("/")
def health_check():
    return {"status": "ok", "message": "Video Downloader API çalışıyor."}


@app.post("/api/extract", response_model=ExtractResponse)
def extract_video(request: ExtractRequest):
    url = request.url.strip()

    if not is_supported_url(url):
        raise HTTPException(
            status_code=400,
            detail="Desteklenmeyen URL. Yalnızca YouTube ve Pinterest linkleri kabul edilir.",
        )

    try:
        return extract_video_metadata(url)
    except yt_dlp.utils.DownloadError as exc:
        raise HTTPException(
            status_code=422,
            detail=f"Video bilgisi alınamadı: {exc}",
        ) from exc
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    except Exception as exc:
        raise HTTPException(
            status_code=500,
            detail=f"Beklenmeyen bir hata oluştu: {exc}",
        ) from exc
