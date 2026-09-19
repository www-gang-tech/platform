"""Private knowledge ingestion primitives."""

from .adapters import FileAdapter, MeetingTranscriptAdapter
from .pipeline import IngestionPipeline, IngestionResult
from .raw_store import LocalRawStore, RawRecord, RawStore

__all__ = [
    "FileAdapter",
    "IngestionPipeline",
    "IngestionResult",
    "LocalRawStore",
    "MeetingTranscriptAdapter",
    "RawRecord",
    "RawStore",
]
