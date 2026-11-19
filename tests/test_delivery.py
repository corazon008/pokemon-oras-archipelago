"""Offline protocol model only. Fake game ledger is NOT an implemented ORAS feature."""

import asyncio
from dataclasses import replace
import json
from pathlib import Path
import sqlite3
import sys
import tempfile
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from oras_client.game_interface import (
    ApplicationReceipt, CheckpointFingerprint, Delivery, DeliveryIdentity, GameInterface,
    GameState, PersistenceReceipt, RecoveryAnchor, SubmissionIntent,
)
from oras_client.delivery import DeliveryBlocked, DeliveryCoordinator, DeliveryJournal, encode


IDENTITY = DeliveryIdentity("synthetic-world", 0, 1, "a" * 64, "synthetic-save-binding")
ITEM = Delivery(0, 100, -1, 2, 0)  # Synthetic network IDs, not approved AP items.
INITIAL = RecoveryAnchor(CheckpointFingerprint("1" * 64, "2" * 64, "3" * 64, "4" * 64), "fixture-0")
AFTER = RecoveryAnchor(CheckpointFingerprint("5" * 64, "6" * 64, "3" * 64, "7" * 64), "fixture-1")


class FakeGame(GameInterface):
    def __init__(self):
        self.state = GameState(IDENTITY, "epoch-one", True, 0, INITIAL.fingerprint)
        self.applications = []
        self.proof = None
        self.error = None
        self.bad_ack = False
        self.bad_ack_checkpoint = False
        self.valid_anchors = {INITIAL}
        self.checkpoints_checked = []
        self.on_apply = None
        self.last_intent = None

    async def observe(self):
        return self.state

    async def verify_recovery_anchor(self, anchor, expected):
        self.checkpoints_checked.append(anchor)
        return self.state == expected and anchor in self.valid_anchors

    async def apply(self, delivery, expected, intent):
        if self.state != expected or self.state.next_delivery_index != delivery.index:
            raise DeliveryBlocked("Fake atomic guard mismatch")
        if self.on_apply:
            self.on_apply()
        self.last_intent = intent
        self.applications.append(delivery)
        self.state = replace(self.state, next_delivery_index=delivery.index + 1)
        if self.error:
            raise self.error
        return ApplicationReceipt(
            replace(delivery, item=999) if self.bad_ack else delivery,
            self.state.identity, self.state.runtime_epoch,
            replace(intent, before=AFTER) if self.bad_ack_checkpoint else intent,
        )

    async def read_persistence(self, delivery, expected, intent):
        return self.proof

    def save(self, after=AFTER):
        self.state = replace(self.state, checkpoint=after.fingerprint)
        self.valid_anchors.add(after)
        self.proof = PersistenceReceipt(
            self.state.identity, self.state.runtime_epoch, self.state.next_delivery_index,
            self.applications[-1], self.last_intent, after,
        )


class DeliveryTests(unittest.TestCase):
    def setUp(self):
        self.directory = tempfile.TemporaryDirectory(dir="/tmp/opencode")
        self.addCleanup(self.directory.cleanup)
        self.path = Path(self.directory.name) / "persistent/delivery.sqlite3"
        self.journal = self.open_journal()
        self.game = FakeGame()
        self.coordinator = DeliveryCoordinator(self.journal, self.game)

    def open_journal(self, identity=IDENTITY):
        journal = DeliveryJournal(self.path, identity, initial_anchor=None if self.path.exists() else INITIAL)
        self.addCleanup(journal.close)
        return journal

    def submit(self):
        self.journal.enqueue(ITEM)
        return asyncio.run(self.coordinator.deliver_next())

    def test_identical_replay_is_deduplicated(self):
        self.assertTrue(self.journal.enqueue(ITEM))
        self.assertFalse(self.journal.enqueue(ITEM))
        self.assertEqual(self.journal.head(), (ITEM, "pending"))

    def test_conflicting_payload_and_index_gaps_are_rejected(self):
        with self.assertRaisesRegex(ValueError, "gap"):
            self.journal.enqueue(replace(ITEM, index=1))
        self.journal.enqueue(ITEM)
        with self.assertRaisesRegex(ValueError, "Conflicting"):
            self.journal.enqueue(replace(ITEM, player=3))
        self.assertEqual(self.journal.head(), (ITEM, "pending"))

    def test_ram_acknowledgment_is_not_persistence(self):
        self.assertTrue(self.submit())
        self.assertEqual(self.journal.head()[1], "ram_ack")
        self.assertFalse(asyncio.run(self.coordinator.confirm_saved()))
        with self.assertRaisesRegex(DeliveryBlocked, "never automatically resend"):
            asyncio.run(self.coordinator.deliver_next())
        self.assertEqual(len(self.game.applications), 1)

    def test_verified_native_save_advances_once(self):
        self.submit()
        self.game.save()
        self.assertTrue(asyncio.run(self.coordinator.confirm_saved()))
        self.assertIsNone(self.journal.head())
        self.assertFalse(self.journal.enqueue(ITEM))
        self.assertFalse(asyncio.run(self.coordinator.confirm_saved()))
        self.assertFalse(asyncio.run(self.coordinator.deliver_next()))
        self.assertEqual(len(self.game.applications), 1)
        proof = self.journal.db.execute("SELECT status, proof, intent FROM deliveries").fetchone()
        self.assertEqual(proof[0], "committed")
        self.assertEqual(json.loads(proof[1])["after"]["snapshot_ref"], AFTER.snapshot_ref)
        self.assertEqual(json.loads(proof[2])["before"]["snapshot_ref"], INITIAL.snapshot_ref)

    def test_next_delivery_blocked_until_first_saved(self):
        self.journal.enqueue(ITEM)
        self.journal.enqueue(replace(ITEM, index=1))
        asyncio.run(self.coordinator.deliver_next())
        with self.assertRaises(DeliveryBlocked):
            asyncio.run(self.coordinator.deliver_next())
        self.game.save()
        asyncio.run(self.coordinator.confirm_saved())
        self.assertTrue(asyncio.run(self.coordinator.deliver_next()))
        self.assertEqual([item.index for item in self.game.applications], [0, 1])

    def test_lost_response_never_resends_and_can_reconcile(self):
        self.game.error = ConnectionError("lost after application")
        with self.assertRaises(ConnectionError):
            self.submit()
        self.assertEqual(self.journal.head()[1], "uncertain")
        reopened = self.open_journal()
        coordinator = DeliveryCoordinator(reopened, self.game)
        with self.assertRaises(DeliveryBlocked):
            asyncio.run(coordinator.deliver_next())
        self.game.save()
        self.assertTrue(asyncio.run(coordinator.confirm_saved()))
        self.assertEqual(len(self.game.applications), 1)

    def test_cancelled_submission_is_uncertain(self):
        self.game.error = asyncio.CancelledError()
        with self.assertRaises(asyncio.CancelledError):
            self.submit()
        self.assertEqual(self.journal.head()[1], "uncertain")

    def test_bad_acknowledgment_is_uncertain(self):
        self.game.bad_ack = True
        with self.assertRaisesRegex(DeliveryBlocked, "receipt"):
            self.submit()
        self.assertEqual(self.journal.head()[1], "uncertain")

    def test_bad_intent_receipt_is_uncertain_and_preserves_anchor(self):
        self.game.bad_ack_checkpoint = True
        with self.assertRaisesRegex(DeliveryBlocked, "receipt"):
            self.submit()
        self.assertEqual(self.journal.head(), (ITEM, "uncertain"))
        self.assertEqual(self.journal.intent_for(0), SubmissionIntent(INITIAL, "epoch-one"))

    def test_anchor_and_claim_are_visible_from_second_connection_before_apply(self):
        def check_intent():
            reopened = self.open_journal()
            self.assertEqual(reopened.head(), (ITEM, "submitted"))
            self.assertEqual(reopened.intent_for(0), SubmissionIntent(INITIAL, "epoch-one"))
            self.assertIsNone(reopened.db.execute("SELECT proof FROM deliveries").fetchone()[0])

        self.game.on_apply = check_intent
        self.assertTrue(self.submit())

    def test_missing_pre_write_snapshot_blocks_even_if_loaded_hashes_match(self):
        self.game.valid_anchors.clear()
        with self.assertRaisesRegex(DeliveryBlocked, "pre-write recovery checkpoint"):
            self.submit()
        self.assertEqual(self.journal.head(), (ITEM, "pending"))
        self.assertIsNone(self.journal.db.execute("SELECT intent FROM deliveries").fetchone()[0])
        self.assertFalse(self.game.applications)

    def test_checkpoint_change_after_verification_leaves_intent_unsettled(self):
        async def switched_after_verify(anchor, expected):
            self.assertEqual(anchor.fingerprint, expected.checkpoint)
            self.game.state = replace(self.game.state, checkpoint=AFTER.fingerprint, runtime_epoch="other-epoch")
            return True

        self.game.verify_recovery_anchor = switched_after_verify
        with self.assertRaisesRegex(DeliveryBlocked, "atomic guard mismatch"):
            self.submit()
        self.assertEqual(self.journal.head(), (ITEM, "uncertain"))
        self.assertEqual(self.journal.intent_for(0), SubmissionIntent(INITIAL, "epoch-one"))
        self.assertFalse(self.game.applications)

    def test_crash_after_intent_commit_blocks_reopened_journal(self):
        self.journal.enqueue(ITEM)
        self.journal._claim(0, SubmissionIntent(INITIAL, "epoch-one"))
        reopened = self.open_journal()
        with self.assertRaises(DeliveryBlocked):
            asyncio.run(DeliveryCoordinator(reopened, self.game).deliver_next())
        self.assertEqual(self.game.applications, [])
        # Even if the game counter is still zero, no automatic retry is safe.
        self.assertFalse(asyncio.run(DeliveryCoordinator(reopened, self.game).confirm_saved()))

    def test_unsafe_unsupported_or_wrong_index_does_not_submit(self):
        self.journal.enqueue(ITEM)
        for changes in (
            {"safe_to_write": False}, {"safe_to_write": 1}, {"next_delivery_index": None},
            {"next_delivery_index": True}, {"next_delivery_index": 1}, {"runtime_epoch": ""},
            {"checkpoint": None}, {"checkpoint": AFTER.fingerprint},
        ):
            self.game.state = replace(GameState(IDENTITY, "epoch-one", True, 0, INITIAL.fingerprint), **changes)
            with self.subTest(changes=changes), self.assertRaises(DeliveryBlocked):
                asyncio.run(self.coordinator.deliver_next())
            self.assertEqual(self.journal.head()[1], "pending")
        self.assertEqual(self.game.applications, [])

    def test_wrong_game_save_identity_cannot_receive_item(self):
        self.game.state = replace(self.game.state, identity=replace(IDENTITY, save_binding="other-save"))
        with self.assertRaises(DeliveryBlocked):
            self.submit()
        self.assertEqual(self.game.applications, [])

    def test_either_half_saved_with_advanced_index_still_blocks(self):
        self.submit()
        self.game.save()
        for current in (
            replace(AFTER.fingerprint, main_sha256=INITIAL.fingerprint.main_sha256),
            replace(AFTER.fingerprint, sidecar_sha256=INITIAL.fingerprint.sidecar_sha256),
            replace(AFTER.fingerprint, metadata_sha256="8" * 64),
            replace(AFTER.fingerprint, archive_tree_sha256=INITIAL.fingerprint.archive_tree_sha256),
        ):
            self.game.state = replace(self.game.state, checkpoint=current, runtime_epoch="reloaded")
            with self.subTest(current=current), self.assertRaisesRegex(DeliveryBlocked, "two-file successor"):
                asyncio.run(self.coordinator.confirm_saved())
            self.assertEqual(self.journal.head(), (ITEM, "ram_ack"))
            with self.assertRaisesRegex(DeliveryBlocked, "never automatically resend"):
                asyncio.run(self.coordinator.deliver_next())
        self.assertEqual(self.game.applications, [ITEM])

    def test_post_checkpoint_must_be_recoverable_and_bound_to_current_epoch(self):
        self.submit()
        self.game.save()
        current = replace(self.game.state, runtime_epoch="epoch-two")
        self.game.state = current
        self.game.proof = replace(self.game.proof, runtime_epoch="epoch-two")
        self.game.valid_anchors.remove(AFTER)
        with self.assertRaisesRegex(DeliveryBlocked, "post-write recovery checkpoint"):
            asyncio.run(self.coordinator.confirm_saved())
        self.game.valid_anchors.add(AFTER)
        self.assertEqual(self.journal.head(), (ITEM, "ram_ack"))
        self.assertTrue(asyncio.run(self.coordinator.confirm_saved()))
        self.assertEqual(self.journal.checkpoint_for(1), AFTER)

    def test_rollback_of_unsettled_item_does_not_requeue_it(self):
        self.submit()
        self.game.save()
        self.game.state = GameState(IDENTITY, "epoch-two", True, 0, INITIAL.fingerprint)
        reopened = self.open_journal()
        coordinator = DeliveryCoordinator(reopened, self.game)
        self.assertFalse(asyncio.run(coordinator.confirm_saved()))
        with self.assertRaisesRegex(DeliveryBlocked, "never automatically resend"):
            asyncio.run(coordinator.deliver_next())
        self.assertEqual(reopened.head(), (ITEM, "ram_ack"))
        self.assertEqual(self.game.applications, [ITEM])

    def test_rollback_blocks_next_delivery_even_with_matching_index(self):
        self.submit()
        self.game.save()
        asyncio.run(self.coordinator.confirm_saved())
        self.game.state = replace(self.game.state, checkpoint=INITIAL.fingerprint, runtime_epoch="epoch-two")
        self.journal.enqueue(replace(ITEM, index=1))
        reopened = self.open_journal()
        with self.assertRaisesRegex(DeliveryBlocked, "journal anchor"):
            asyncio.run(DeliveryCoordinator(reopened, self.game).deliver_next())
        self.assertEqual(reopened.head(), (replace(ITEM, index=1), "pending"))
        self.assertEqual(self.game.applications, [ITEM])

    def test_stale_or_mismatched_native_proof_cannot_commit(self):
        self.submit()
        self.game.save()
        good = self.game.proof
        for bad in (
            replace(good, runtime_epoch="old-epoch"),
            replace(good, identity=replace(IDENTITY, slot=2)),
            replace(good, next_delivery_index=2),
            replace(good, next_delivery_index=True),
            replace(good, delivery=replace(ITEM, item=999)),
            replace(good, intent=SubmissionIntent(AFTER, "epoch-one")),
            replace(good, intent=SubmissionIntent(INITIAL, "different-submission-epoch")),
            replace(good, after=INITIAL),
            replace(good, after=replace(AFTER, snapshot_ref=INITIAL.snapshot_ref)),
        ):
            self.game.proof = bad
            with self.subTest(proof=bad), self.assertRaises(DeliveryBlocked):
                asyncio.run(self.coordinator.confirm_saved())
            self.assertEqual(self.journal.head()[1], "ram_ack")
        self.game.proof = good
        self.game.state = replace(self.game.state, next_delivery_index=0)
        with self.assertRaises(DeliveryBlocked):
            asyncio.run(self.coordinator.confirm_saved())

    def test_wrong_journal_identity_does_not_modify_database(self):
        self.journal.enqueue(ITEM)
        before = self.path.read_bytes()
        with self.assertRaisesRegex(ValueError, "identity mismatch"):
            DeliveryJournal(self.path, replace(IDENTITY, world_fingerprint="other-world"))
        self.assertEqual(self.path.read_bytes(), before)

    def test_committed_payload_survives_close_and_reopen(self):
        self.submit()
        self.game.save()
        asyncio.run(self.coordinator.confirm_saved())
        self.journal.close()
        reopened = self.open_journal()
        self.assertIsNone(reopened.head())
        self.assertFalse(reopened.enqueue(ITEM))
        self.assertFalse(asyncio.run(DeliveryCoordinator(reopened, self.game).deliver_next()))
        self.assertEqual(len(self.game.applications), 1)

    def test_unfamiliar_database_is_not_reset(self):
        path = Path(self.directory.name) / "unfamiliar.sqlite3"
        data = b"unfamiliar user file"
        path.write_bytes(data)
        with self.assertRaises(sqlite3.DatabaseError):
            DeliveryJournal(path, IDENTITY)
        self.assertEqual(path.read_bytes(), data)

    def test_legacy_journal_is_refused_without_migration(self):
        path = Path(self.directory.name) / "legacy.sqlite3"
        with sqlite3.connect(path) as db:
            db.execute("CREATE TABLE metadata(version INTEGER PRIMARY KEY, identity TEXT NOT NULL)")
            db.execute("INSERT INTO metadata VALUES(1, ?)", (encode(IDENTITY),))
            db.execute("CREATE TABLE deliveries(idx INTEGER, status TEXT)")
            db.execute("INSERT INTO deliveries VALUES(0, 'submitted')")
        db.close()
        before = path.read_bytes()
        with self.assertRaisesRegex(ValueError, "schema"):
            DeliveryJournal(path, IDENTITY, initial_anchor=INITIAL)
        self.assertEqual(path.read_bytes(), before)

    def test_new_journal_requires_anchor_and_existing_anchor_cannot_be_replaced(self):
        path = Path(self.directory.name) / "no-initial-anchor.sqlite3"
        with self.assertRaisesRegex(ValueError, "explicit initial checkpoint"):
            DeliveryJournal(path, IDENTITY)
        self.assertFalse(path.exists())
        before = self.path.read_bytes()
        with self.assertRaisesRegex(ValueError, "initial checkpoint mismatch"):
            DeliveryJournal(self.path, IDENTITY, initial_anchor=AFTER)
        self.assertEqual(self.path.read_bytes(), before)

    def test_single_head_can_only_be_claimed_once(self):
        self.journal.enqueue(ITEM)
        second = self.open_journal()
        self.journal._claim(0, SubmissionIntent(INITIAL, "epoch-one"))
        with self.assertRaises(DeliveryBlocked):
            second._claim(0, SubmissionIntent(INITIAL, "epoch-two"))

    def test_invalid_payloads_and_identity_are_rejected(self):
        for change in ({"index": True}, {"index": -1}, {"flags": -1}, {"item": -1}):
            with self.subTest(change=change), self.assertRaises(ValueError):
                replace(ITEM, **change)
        with self.assertRaises(ValueError):
            replace(IDENTITY, rom_sha256="unknown")
        with self.assertRaises(ValueError):
            replace(IDENTITY, world_fingerprint=1)
        with self.assertRaises(ValueError):
            replace(INITIAL.fingerprint, sidecar_sha256=None)
        with self.assertRaises(ValueError):
            replace(INITIAL, snapshot_ref=" ")


if __name__ == "__main__":
    unittest.main()
