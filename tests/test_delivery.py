"""Offline protocol model only. Fake game ledger is NOT an implemented ORAS feature."""

import asyncio
from dataclasses import replace
from pathlib import Path
import sqlite3
import sys
import tempfile
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from oras_client.game_interface import (
    ApplicationReceipt, Delivery, DeliveryIdentity, GameInterface, GameState, PersistenceReceipt,
)
from oras_client.delivery import DeliveryBlocked, DeliveryCoordinator, DeliveryJournal


IDENTITY = DeliveryIdentity("synthetic-world", 0, 1, "a" * 64, "synthetic-save-binding")
ITEM = Delivery(0, 100, -1, 2, 0)  # Synthetic network IDs, not approved AP items.


class FakeGame(GameInterface):
    def __init__(self):
        self.state = GameState(IDENTITY, "epoch-one", True, 0)
        self.applications = []
        self.proof = None
        self.error = None
        self.bad_ack = False

    async def observe(self):
        return self.state

    async def apply(self, delivery, expected):
        if self.state != expected or self.state.next_delivery_index != delivery.index:
            raise DeliveryBlocked("Fake atomic guard mismatch")
        self.applications.append(delivery)
        self.state = replace(self.state, next_delivery_index=delivery.index + 1)
        if self.error:
            raise self.error
        return ApplicationReceipt(
            replace(delivery, item=999) if self.bad_ack else delivery,
            self.state.identity, self.state.runtime_epoch,
        )

    async def read_persistence(self, delivery, expected):
        return self.proof

    def save(self):
        self.proof = PersistenceReceipt(self.state.identity, self.state.runtime_epoch,
                                        self.state.next_delivery_index, "b" * 64)


class DeliveryTests(unittest.TestCase):
    def setUp(self):
        self.directory = tempfile.TemporaryDirectory(dir="/tmp/opencode")
        self.addCleanup(self.directory.cleanup)
        self.path = Path(self.directory.name) / "persistent/delivery.sqlite3"
        self.journal = self.open_journal()
        self.game = FakeGame()
        self.coordinator = DeliveryCoordinator(self.journal, self.game)

    def open_journal(self, identity=IDENTITY):
        journal = DeliveryJournal(self.path, identity)
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
        proof = self.journal.db.execute("SELECT status, proof FROM deliveries").fetchone()
        self.assertEqual(proof[0], "committed")
        self.assertIn("save_sha256", proof[1])

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

    def test_crash_after_intent_commit_blocks_reopened_journal(self):
        self.journal.enqueue(ITEM)
        self.journal._transition(0, ("pending",), "submitted")
        reopened = self.open_journal()
        with self.assertRaises(DeliveryBlocked):
            asyncio.run(DeliveryCoordinator(reopened, self.game).deliver_next())
        self.assertEqual(self.game.applications, [])
        # Even if the game counter is still zero, no automatic retry is safe.
        self.assertFalse(asyncio.run(DeliveryCoordinator(reopened, self.game).confirm_saved()))

    def test_unsafe_unsupported_or_wrong_index_does_not_submit(self):
        self.journal.enqueue(ITEM)
        for state in (
            replace(self.game.state, safe_to_write=False),
            replace(self.game.state, safe_to_write=1),
            replace(self.game.state, next_delivery_index=None),
            replace(self.game.state, next_delivery_index=True),
            replace(self.game.state, next_delivery_index=1),
            replace(self.game.state, runtime_epoch=""),
        ):
            self.game.state = state
            with self.subTest(state=state), self.assertRaises(DeliveryBlocked):
                asyncio.run(self.coordinator.deliver_next())
            self.assertEqual(self.journal.head()[1], "pending")
        self.assertEqual(self.game.applications, [])

    def test_wrong_game_save_identity_cannot_receive_item(self):
        self.game.state = replace(self.game.state, identity=replace(IDENTITY, save_binding="other-save"))
        with self.assertRaises(DeliveryBlocked):
            self.submit()
        self.assertEqual(self.game.applications, [])

    def test_stale_or_mismatched_native_proof_cannot_commit(self):
        self.submit()
        self.game.save()
        good = self.game.proof
        for bad in (
            replace(good, runtime_epoch="old-epoch"),
            replace(good, identity=replace(IDENTITY, slot=2)),
            replace(good, next_delivery_index=2),
            replace(good, next_delivery_index=True),
            replace(good, save_sha256="invalid"),
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

    def test_single_head_can_only_be_claimed_once(self):
        self.journal.enqueue(ITEM)
        second = self.open_journal()
        self.journal._transition(0, ("pending",), "submitted")
        with self.assertRaises(DeliveryBlocked):
            second._transition(0, ("pending",), "submitted")

    def test_invalid_payloads_and_identity_are_rejected(self):
        for change in ({"index": True}, {"index": -1}, {"flags": -1}, {"item": -1}):
            with self.subTest(change=change), self.assertRaises(ValueError):
                replace(ITEM, **change)
        with self.assertRaises(ValueError):
            replace(IDENTITY, rom_sha256="unknown")
        with self.assertRaises(ValueError):
            replace(IDENTITY, world_fingerprint=1)


if __name__ == "__main__":
    unittest.main()
