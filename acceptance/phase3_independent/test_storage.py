"""Public storage-interface checks with independent synthetic identities and bytes."""

from concurrent.futures import ThreadPoolExecutor
import hashlib
from pathlib import Path
import tempfile
import threading
import unittest
from unittest.mock import patch
from uuid import uuid4

from app.storage import files, repository


class StorageContract(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory(prefix="receipt-independent-storage-")
        self.addCleanup(self.temporary.cleanup)
        self.root = Path(self.temporary.name)
        self.db = self.root / "receipts.sqlite3"
        self.receipt_id = str(uuid4())
        self.payload = b"Independent storage-only payload 127.\x00\xfe"

    def test_sqlite_concurrent_claims_have_one_owner_and_one_stable_identity(self):
        repository.initialize_database(db_path=self.db, data_dir=self.root)
        barrier = threading.Barrier(9)
        digest = hashlib.sha256(self.payload).hexdigest()

        def claim(index):
            barrier.wait(timeout=10)
            return repository.claim_receipt(str(uuid4()), digest, db_path=self.db)

        with ThreadPoolExecutor(max_workers=9) as executor:
            results = list(executor.map(claim, range(9)))
        self.assertEqual(sum(owner for _, owner in results), 1)
        ids = {record.response.receipt_id for record, _ in results}
        self.assertEqual(len(ids), 1)
        self.assertTrue(all(record.pdf_sha256 == digest for record, _ in results))
        self.assertTrue(all(record.response.status == "processing" for record, _ in results))

    def test_identical_original_is_reused_and_conflicting_bytes_never_replace_it(self):
        reference = files.save_original_pdf(self.payload, self.receipt_id, data_dir=self.root)
        self.assertEqual(reference, f"originals/{self.receipt_id}.pdf")
        self.assertEqual(files.save_original_pdf(self.payload, self.receipt_id, data_dir=self.root), reference)
        with self.assertRaises(Exception):
            files.save_original_pdf(b"Different independent bytes", self.receipt_id, data_dir=self.root)
        self.assertEqual((self.root / reference).read_bytes(), self.payload)
        self.assertEqual(list((self.root / "originals").iterdir()), [self.root / reference])

    def test_replace_fault_leaves_no_success_or_own_temp_and_preserves_unrelated_files(self):
        directory = self.root / "originals"
        directory.mkdir()
        unrelated = directory / ".unrelated-retained.tmp"
        unrelated.write_bytes(b"Unrelated recovery evidence")
        with patch.object(files.os, "replace", side_effect=OSError("Synthetic replacement fault")) as replace:
            with self.assertRaises(OSError):
                files.save_original_pdf(self.payload, self.receipt_id, data_dir=self.root)
        self.assertEqual(replace.call_count, 1)
        self.assertEqual(unrelated.read_bytes(), b"Unrelated recovery evidence")
        self.assertEqual(list(directory.iterdir()), [unrelated])

    def test_original_flush_and_fsync_precede_atomic_replace(self):
        original_fsync = files.os.fsync
        original_replace = files.os.replace
        events = []

        def fsync(descriptor):
            events.append("fsync")
            return original_fsync(descriptor)

        def replace(source, target):
            events.append("replace")
            self.assertEqual(Path(source).parent, Path(target).parent)
            self.assertEqual(Path(source).read_bytes(), self.payload)
            self.assertFalse(Path(target).exists())
            return original_replace(source, target)

        with patch.object(files.os, "fsync", side_effect=fsync), patch.object(files.os, "replace", side_effect=replace):
            reference = files.save_original_pdf(self.payload, self.receipt_id, data_dir=self.root)
        self.assertLess(events.index("fsync"), events.index("replace"))
        self.assertEqual((self.root / reference).read_bytes(), self.payload)


def unsafe_id_case(identifier):
    def test(self):
        with self.assertRaises(Exception):
            files.save_original_pdf(self.payload, identifier, data_dir=self.root)
        self.assertEqual(list(self.root.iterdir()), [])
    return test


for _label, _identifier in (("traversal", "../escape"), ("absolute", "C:/escape"),
                            ("not_uuid", "receipt-127"),
                            ("uppercase", "ABCDEFAB-1234-4567-8901-ABCDEFABCDEF"),
                            ("compact", "abcdefab123445678901abcdefabcdef")):
    setattr(StorageContract, f"test_rejects_{_label}_id", unsafe_id_case(_identifier))
