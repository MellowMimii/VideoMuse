from app.platforms.base import PlatformAdapter, PlatformRegistry, VideoInfo

# Import adapters to trigger registration
from app.platforms import bilibili as _  # noqa: F401

__all__ = ["PlatformAdapter", "PlatformRegistry", "VideoInfo"]
