"""Private knowledge ingestion primitives."""

from .adapters import FileAdapter, MeetingTranscriptAdapter
from .drive import DRIVE_READONLY_SCOPE, DriveIngestionError, DriveSyncService, GoogleDriveProvider
from .gmail import GoogleGmailProvider, GmailIngestionError, GmailSyncService
from .pipeline import IngestionPipeline, IngestionResult
from .raw_store import LocalRawStore, RawRecord, RawStore
from .registry import IngestionRegistry

__all__ = [
    "FileAdapter",
    "DRIVE_READONLY_SCOPE",
    "DriveIngestionError",
    "DriveSyncService",
    "GmailIngestionError",
    "GmailSyncService",
    "GoogleDriveProvider",
    "GoogleGmailProvider",
    "IngestionPipeline",
    "IngestionRegistry",
    "IngestionResult",
    "LocalRawStore",
    "MeetingTranscriptAdapter",
    "RawRecord",
    "RawStore",
]
