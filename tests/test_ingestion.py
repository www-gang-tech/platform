import json
import sys
import unittest
from pathlib import Path
from tempfile import TemporaryDirectory

import yaml

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "cli" / "gang"))

from core.ingestion import FileAdapter, IngestionPipeline, LocalRawStore, MeetingTranscriptAdapter


class IngestionTests(unittest.TestCase):
    def test_file_import_preserves_raw_versions_and_private_document(self):
        with TemporaryDirectory() as tempdir:
            root = Path(tempdir)
            source = root / "notes.txt"
            source.write_text("Launch notes\nFirst version\n", encoding="utf-8")

            pipeline = IngestionPipeline(
                LocalRawStore(root / "brain/raw"),
                inbox_path=root / "brain/vault/inbox",
            )
            first = pipeline.ingest(FileAdapter(source))[0]
            second = pipeline.ingest(FileAdapter(source))[0]

            self.assertEqual(first.source_id, second.source_id)
            self.assertEqual(first.version, second.version)
            self.assertEqual(first.content_hash, second.content_hash)

            source.write_text("Launch notes\nSecond version\n", encoding="utf-8")
            third = pipeline.ingest(FileAdapter(source))[0]
            self.assertEqual(first.source_id, third.source_id)
            self.assertEqual(third.version, 2)
            self.assertNotEqual(first.content_hash, third.content_hash)

            content = third.document_path.read_text(encoding="utf-8")
            frontmatter = yaml.safe_load(content.split("---", 2)[1])
            self.assertEqual(frontmatter["visibility"], "private")
            self.assertEqual(frontmatter["status"], "active")
            self.assertEqual(frontmatter["source_type"], "file")
            self.assertNotEqual(frontmatter["id"], frontmatter["source_id"])
            self.assertEqual(frontmatter["ingestion_envelope"]["source_type"], "file")
            self.assertEqual(frontmatter["ingestion_envelope"]["version"], 2)
            self.assertEqual(frontmatter["ingestion_envelope"]["content_hash"], third.content_hash)

    def test_jsonl_file_normalizes_to_readable_markdown(self):
        with TemporaryDirectory() as tempdir:
            root = Path(tempdir)
            source = root / "events.jsonl"
            source.write_text(
                json.dumps({"event": "start"}) + "\n" + json.dumps({"event": "stop"}) + "\n",
                encoding="utf-8",
            )

            pipeline = IngestionPipeline(LocalRawStore(root / "raw"), inbox_path=root / "inbox")
            result = pipeline.ingest(FileAdapter(source))[0]

            content = result.document_path.read_text(encoding="utf-8")
            self.assertIn("# JSONL Import", content)
            self.assertIn("## Record 1", content)
            self.assertIn('"event": "stop"', content)

    def test_meeting_transcript_extracts_participants(self):
        with TemporaryDirectory() as tempdir:
            root = Path(tempdir)
            source = root / "weekly.md"
            source.write_text("# Weekly Sync\n\nAlice: Hello\nBob: Hi\n", encoding="utf-8")

            pipeline = IngestionPipeline(LocalRawStore(root / "raw"), inbox_path=root / "inbox")
            result = pipeline.ingest(MeetingTranscriptAdapter(source))[0]

            frontmatter = yaml.safe_load(result.document_path.read_text(encoding="utf-8").split("---", 2)[1])
            self.assertEqual(frontmatter["source_type"], "meeting")
            self.assertEqual(frontmatter["ingestion_envelope"]["participants"], ["Alice", "Bob"])


if __name__ == "__main__":
    unittest.main()
