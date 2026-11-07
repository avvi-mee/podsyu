from datetime import datetime

from sqlalchemy import JSON, Boolean, DateTime, Float, ForeignKey, Integer, LargeBinary, String, Text
from sqlalchemy.orm import Mapped, mapped_column

from app.database.db import Base, utcnow


class Setting(Base):
    __tablename__ = "settings"
    key: Mapped[str] = mapped_column(String, primary_key=True)
    value: Mapped[object] = mapped_column(JSON)


class Project(Base):
    __tablename__ = "projects"
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    title: Mapped[str] = mapped_column(String, default="Untitled")
    source_type: Mapped[str] = mapped_column(String)  # youtube | local | story
    engine: Mapped[str | None] = mapped_column(String, nullable=True)  # None/"podcast" | "creator" | "asmr"
    source_url: Mapped[str | None] = mapped_column(String, nullable=True)
    source_path: Mapped[str | None] = mapped_column(String, nullable=True)
    channel: Mapped[str | None] = mapped_column(String, nullable=True)
    thumbnail_url: Mapped[str | None] = mapped_column(String, nullable=True)
    duration: Mapped[float | None] = mapped_column(Float, nullable=True)
    width: Mapped[int | None] = mapped_column(Integer, nullable=True)
    height: Mapped[int | None] = mapped_column(Integer, nullable=True)
    fps: Mapped[float | None] = mapped_column(Float, nullable=True)
    language: Mapped[str | None] = mapped_column(String, nullable=True)
    # created | queued | processing | completed | failed
    status: Mapped[str] = mapped_column(String, default="created")
    error: Mapped[str | None] = mapped_column(Text, nullable=True)
    options: Mapped[dict] = mapped_column(JSON, default=dict)  # durations, count, category, strategy
    caption_style: Mapped[dict | None] = mapped_column(JSON, nullable=True)
    music: Mapped[str | None] = mapped_column(String, nullable=True)  # MusicTrack id as text, or None = no music
    music_volume: Mapped[float | None] = mapped_column(Float, nullable=True)  # 0..1, None = default (low)
    source_deleted: Mapped[bool] = mapped_column(Boolean, default=False)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow, onupdate=utcnow)


class Short(Base):
    __tablename__ = "shorts"
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    project_id: Mapped[int] = mapped_column(ForeignKey("projects.id", ondelete="CASCADE"), index=True)
    rank: Mapped[int] = mapped_column(Integer, default=0)
    start: Mapped[float] = mapped_column(Float)
    end: Mapped[float] = mapped_column(Float)
    transcript: Mapped[str] = mapped_column(Text, default="")
    hook: Mapped[str] = mapped_column(Text, default="")
    title: Mapped[str] = mapped_column(String, default="")
    description: Mapped[str] = mapped_column(Text, default="")
    hashtags: Mapped[str] = mapped_column(Text, default="")
    category: Mapped[str] = mapped_column(String, default="")
    reason: Mapped[str] = mapped_column(Text, default="")
    score: Mapped[int] = mapped_column(Integer, default=0)
    status: Mapped[str] = mapped_column(String, default="pending")  # candidate | pending | rendering | ready | failed
    details: Mapped[dict | None] = mapped_column(JSON, nullable=True)  # engine-specific: scene, score breakdown...
    review: Mapped[str] = mapped_column(String, default="none")  # none | approved | rejected
    video_path: Mapped[str | None] = mapped_column(String, nullable=True)
    thumb_path: Mapped[str | None] = mapped_column(String, nullable=True)
    caption_style: Mapped[dict | None] = mapped_column(JSON, nullable=True)
    words: Mapped[list | None] = mapped_column(JSON, nullable=True)  # per-clip re-transcription override
    crop_mode: Mapped[str] = mapped_column(String, default="auto")  # auto | manual
    crop_x: Mapped[float] = mapped_column(Float, default=0.5)  # 0..1 for manual mode
    music: Mapped[str | None] = mapped_column(String, nullable=True)  # None = use project's, "none" = off, else track id
    music_volume: Mapped[float | None] = mapped_column(Float, nullable=True)
    framing: Mapped[str | None] = mapped_column(String, nullable=True)  # what auto-reframe ended up doing
    error: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow, onupdate=utcnow)


class Job(Base):
    __tablename__ = "jobs"
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    type: Mapped[str] = mapped_column(String)  # process | render | recaption | metadata
    project_id: Mapped[int | None] = mapped_column(ForeignKey("projects.id", ondelete="CASCADE"), nullable=True)
    short_id: Mapped[int | None] = mapped_column(ForeignKey("shorts.id", ondelete="CASCADE"), nullable=True)
    payload: Mapped[dict] = mapped_column(JSON, default=dict)
    status: Mapped[str] = mapped_column(String, default="queued")  # queued | running | done | failed | cancelled
    stage: Mapped[str] = mapped_column(String, default="")
    progress: Mapped[float] = mapped_column(Float, default=0.0)  # 0..1 overall
    message: Mapped[str] = mapped_column(Text, default="")
    error: Mapped[str | None] = mapped_column(Text, nullable=True)
    cancel_requested: Mapped[bool] = mapped_column(Boolean, default=False)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)
    started_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    finished_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)


class YouTubeAccount(Base):
    __tablename__ = "youtube_accounts"
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    channel_id: Mapped[str] = mapped_column(String, unique=True)
    channel_title: Mapped[str] = mapped_column(String)
    thumbnail_url: Mapped[str | None] = mapped_column(String, nullable=True)
    token: Mapped[bytes] = mapped_column(LargeBinary)  # encrypted with Windows DPAPI
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)

    def to_dict(self) -> dict:
        d = super().to_dict()
        d.pop("token")  # never leaves the backend
        return d


class Publication(Base):
    __tablename__ = "publications"
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    short_id: Mapped[int] = mapped_column(ForeignKey("shorts.id", ondelete="CASCADE"), index=True)
    account_id: Mapped[int] = mapped_column(ForeignKey("youtube_accounts.id", ondelete="CASCADE"))
    title: Mapped[str] = mapped_column(String)
    description: Mapped[str] = mapped_column(Text, default="")
    tags: Mapped[list] = mapped_column(JSON, default=list)
    privacy: Mapped[str] = mapped_column(String)  # public | private | unlisted
    made_for_kids: Mapped[bool] = mapped_column(Boolean, default=False)
    # now | youtube (upload now, YouTube publishes at publish_at) | local (this app uploads at publish_at)
    mode: Mapped[str] = mapped_column(String, default="now")
    publish_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)  # UTC
    # pending | uploading | scheduled | published | uploaded | failed | cancelled
    status: Mapped[str] = mapped_column(String, default="pending")
    progress: Mapped[float] = mapped_column(Float, default=0.0)
    youtube_video_id: Mapped[str | None] = mapped_column(String, nullable=True)
    message: Mapped[str | None] = mapped_column(Text, nullable=True)
    error: Mapped[str | None] = mapped_column(Text, nullable=True)
    attempts: Mapped[int] = mapped_column(Integer, default=0)
    retry_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)  # UTC; set after a quota error
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow, onupdate=utcnow)


class MusicTrack(Base):
    __tablename__ = "music_tracks"
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    filename: Mapped[str] = mapped_column(String, unique=True)  # file inside data/music
    title: Mapped[str] = mapped_column(String)
    credit: Mapped[str] = mapped_column(Text, default="")  # attribution added to the YouTube description
    duration: Mapped[float] = mapped_column(Float, default=0.0)
    category: Mapped[str | None] = mapped_column(String, nullable=True)  # funny, dark, horror, relaxing...
    license: Mapped[str | None] = mapped_column(String, nullable=True)
    source_url: Mapped[str | None] = mapped_column(String, nullable=True)
    favourite: Mapped[bool | None] = mapped_column(Boolean, nullable=True)
    parent_id: Mapped[int | None] = mapped_column(Integer, nullable=True)  # set for snippets cut from a full track
    clip_start: Mapped[float | None] = mapped_column(Float, nullable=True)  # snippet start inside the parent
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)


class BackgroundMedia(Base):
    """Background footage for story videos: user uploads, generated loops, or licensed imports."""
    __tablename__ = "background_media"
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    filename: Mapped[str] = mapped_column(String, unique=True)  # inside data/media
    title: Mapped[str] = mapped_column(String)
    category: Mapped[str] = mapped_column(String, default="satisfying")  # gameplay, satisfying, dark, nature...
    duration: Mapped[float] = mapped_column(Float, default=0.0)
    width: Mapped[int] = mapped_column(Integer, default=0)
    height: Mapped[int] = mapped_column(Integer, default=0)
    source: Mapped[str] = mapped_column(String, default="upload")  # upload | generated | pexels
    source_url: Mapped[str | None] = mapped_column(String, nullable=True)
    creator: Mapped[str | None] = mapped_column(String, nullable=True)
    license: Mapped[str | None] = mapped_column(String, nullable=True)
    attribution: Mapped[str | None] = mapped_column(Text, nullable=True)
    favourite: Mapped[bool] = mapped_column(Boolean, default=False)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)


class Story(Base):
    """A story for the ASMR engine, with where it came from and whether we may use it."""
    __tablename__ = "stories"
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    source_type: Mapped[str] = mapped_column(String)  # reddit | user | ai_original | licensed
    title: Mapped[str] = mapped_column(String)
    body: Mapped[str] = mapped_column(Text)
    category: Mapped[str] = mapped_column(String, default="life")
    # unknown | needs_permission | granted | not_required (own/AI-original)
    permission: Mapped[str] = mapped_column(String, default="unknown")
    attribution: Mapped[str | None] = mapped_column(Text, nullable=True)
    subreddit: Mapped[str | None] = mapped_column(String, nullable=True)
    author: Mapped[str | None] = mapped_column(String, nullable=True)
    url: Mapped[str | None] = mapped_column(String, nullable=True)
    score: Mapped[int | None] = mapped_column(Integer, nullable=True)  # real values from the API only
    num_comments: Mapped[int | None] = mapped_column(Integer, nullable=True)
    posted_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    nsfw: Mapped[bool] = mapped_column(Boolean, default=False)
    script: Mapped[str | None] = mapped_column(Text, nullable=True)  # adapted narration script
    status: Mapped[str] = mapped_column(String, default="new")  # new | selected | rejected | used
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)


class CaptionTemplate(Base):
    __tablename__ = "caption_templates"
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    name: Mapped[str] = mapped_column(String)
    style: Mapped[dict] = mapped_column(JSON)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)
