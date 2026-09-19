"""Private knowledge ingestion primitives."""

from .adapters import FileAdapter, MeetingTranscriptAdapter
from .pipeline import IngestionPipeline, IngestionResult
from .raw_store import LocalRawStore, RawRecord, RawStore
from .registry import IngestionRegistry

__all__ = [
    "FileAdapter",
    "IngestionPipeline",
    "IngestionRegistry",
    "IngestionResult",
    "LocalRawStore",
    "MeetingTranscriptAdapter",
    "RawRecord",
    "RawStore",
]
