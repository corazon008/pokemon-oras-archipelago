"""Cold-fork preconditions with generated saves and a local interruption witness."""

import json
from pathlib import Path
import sys
import tempfile
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "tools"))

from oras_index_probe import index_payload, inspect_index_archive, inspect_interrupted_index
from oras_potion_recovery import recovery_plan
from oras_profiles import snapshot_save
from oras_save import BLOCKS, inventory_bytes
from oras_sidecar_probe import NAME, TEST_METADATA
from oras_sidecar_recovery import OR_HASH, OR_TITLE
from run_bizhawk_save_probe import save_destination
from save_fixtures import synthetic_save, update_fixture_crcs


class PotionRecoveryTests(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory(dir="/tmp/opencode")
        self.addCleanup(temporary.cleanup)
        root = Path(temporary.name)
        self.main = save_destination(root / "runtime", OR_TITLE)
        self.main.parent.mkdir(parents=True)
        old = synthetic_save()
        slot = BLOCKS[1][0] + 0x970
        old[slot:slot + 4] = b"\x11\x00\x01\x00"
        update_fixture_crcs(old)
        self.main.write_bytes(old)
        (self.main.parent / NAME).write_bytes(index_payload(old, b"test034!", 0))
        self.main.parent.with_suffix(".metadata").write_bytes(TEST_METADATA)
        snapshot = snapshot_save(self.main, OR_TITLE, OR_HASH, "before", root / "snapshots")
        self.seed = snapshot / "00000001/main"
        _, before = inspect_index_archive(self.seed)
        old[slot + 2] = 2
        old[BLOCKS[3][0]] ^= 1
        update_fixture_crcs(old)
        self.main.write_bytes(old)
        split = inspect_interrupted_index(self.main, before, inventory_bytes(old))
        self.path = root / "result.json"
        self.report = {
            "schema_version": 1, "status": "complete", "exit_code": -9,
            "bootstrap": {"mode": "sidecar-index-potion-interrupt"},
            "rom_identity": {"rom_sha256": OR_HASH, "program_id": OR_TITLE},
            "memory_write_requests": 1, "full_archive_source_unchanged": True,
            "interruption": {"barrier_hex": "01000000544e1200ffffffff02000000",
                             "caller_return": 0x124E54, "sidecar_ram_unchanged": True, "sigkill_confirmed": True},
            "potion_experiment": {"status": "full_inventory_readback_verified",
                                 "readback": {"sha256": split["inventory_sha256"]}},
            "sidecar_index_before": before, "interrupted_pair": split,
            "backup_before_launch": str(snapshot), "forensic_archive": str(self.main.parent),
        }
        self.path.write_text(json.dumps(self.report))

    def test_loss_preview_is_read_only_and_includes_non_inventory_blocks(self):
        initial, interrupted = self.seed.read_bytes(), self.main.read_bytes()
        result = recovery_plan(self.seed, self.path)
        self.assertEqual(result["changed_main_block_ids_not_carried_into_fork"], [1, 3])
        self.assertEqual(result["potion_quantity_in_interrupted_main"], 2)
        self.assertEqual(result["potion_quantity_in_fork"], 1)
        self.assertFalse(result["delivery_replay_authorized"])
        self.assertEqual((self.seed.read_bytes(), self.main.read_bytes()), (initial, interrupted))

    def test_other_snapshot_is_refused_even_with_identical_content(self):
        sibling = snapshot_save(self.seed, OR_TITLE, OR_HASH, "sibling", self.seed.parents[2])
        with self.assertRaisesRegex(ValueError, "explicit pre-SAVE"):
            recovery_plan(sibling / "00000001/main", self.path)

    def test_crc_valid_evidence_changed_after_interruption_is_refused(self):
        changed = bytearray(self.main.read_bytes())
        changed[BLOCKS[4][0]] ^= 1
        update_fixture_crcs(changed)
        self.main.write_bytes(changed)
        with self.assertRaisesRegex(ValueError, "recorded split"):
            recovery_plan(self.seed, self.path)

    def test_other_run_or_missing_barrier_is_refused(self):
        for override in ({"exit_code": 0}, {"backup_after_exit": str(self.seed.parents[1])},
                         {"bootstrap": {"mode": "sidecar-index-potion-save"}},
                         {"interruption": {**self.report["interruption"], "barrier_hex": "00" * 16}}):
            self.path.write_text(json.dumps({**self.report, **override}))
            with self.subTest(override=override), self.assertRaises(ValueError):
                recovery_plan(self.seed, self.path)
