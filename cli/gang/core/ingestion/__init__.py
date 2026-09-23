"""Private knowledge ingestion primitives."""

from .adapters import FileAdapter, MeetingTranscriptAdapter
from .attachments import AttachmentIngestionService, AttachmentOccurrence, AttachmentReport
from .drive import (
    DRIVE_READONLY_SCOPE,
    DriveFolder,
    DriveIngestionError,
    DriveSyncService,
    GoogleDriveProvider,
    load_drive_folders,
    save_drive_folders,
)
from .gmail import GoogleGmailProvider, GmailIngestionError, GmailSyncService
from .pipeline import IngestionPipeline, IngestionResult
from .raw_store import LocalRawStore, RawRecord, RawStore
from .registry import IngestionRegistry

__all__ = [
    "AttachmentIngestionService",
    "AttachmentOccurrence",
    "AttachmentReport",
    "DriveFolder",
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
    "load_drive_folders",
    "save_drive_folders",
]
