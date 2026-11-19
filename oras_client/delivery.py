"""Durable, fail-stopped delivery journal. This is not an exactly-once game adapter."""

from dataclasses import asdict
import json
import os
from pathlib import Path
import sqlite3

from .game_interface import (
    CheckpointFingerprint, Delivery, DeliveryIdentity, GameInterface, PersistenceReceipt,
    RecoveryAnchor, SubmissionIntent,
)


DEFAULT_JOURNAL_PATH = Path(__file__).resolve().parents[1] / "local/oras/client/delivery.sqlite3"
JOURNAL_SCHEMA = 2


class DeliveryBlocked(RuntimeError):
    """Manual investigation or verified native persistence is required."""


def encode(value) -> str:
    return json.dumps(asdict(value), sort_keys=True, separators=(",", ":"))


def decode_anchor(value):
    return RecoveryAnchor(CheckpointFingerprint(**value["fingerprint"]), value["snapshot_ref"])


class DeliveryJournal:
    def __init__(self, path: Path | None, identity: DeliveryIdentity, *, initial_anchor: RecoveryAnchor | None = None):
        self.identity = identity
        path = DEFAULT_JOURNAL_PATH if path is None else path
        if initial_anchor is not None and not isinstance(initial_anchor, RecoveryAnchor):
            raise ValueError("Invalid initial checkpoint anchor")
        if initial_anchor is None and not path.exists():
            raise ValueError("New journal requires an explicit initial checkpoint anchor")
        created = False
        if initial_anchor is not None:
            path.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
            try:
                descriptor = os.open(path, os.O_CREAT | os.O_EXCL | os.O_WRONLY, 0o600)
            except FileExistsError:
                pass
            else:
                os.close(descriptor)
                created = True
        self.db = sqlite3.connect(f"{path.resolve().as_uri()}?mode=rw", uri=True)
        try:
            if not created:
                # Do not initialize or reset an unfamiliar/corrupt database.
                rows = self.db.execute("SELECT version, identity FROM metadata").fetchall()
                if rows != [(JOURNAL_SCHEMA, encode(identity))]:
                    raise ValueError("Journal schema or world/save identity mismatch")
                (stored_anchor,) = self.db.execute("SELECT initial_anchor FROM metadata").fetchone()
                if initial_anchor is not None and stored_anchor != encode(initial_anchor):
                    raise ValueError("Journal initial checkpoint mismatch")
                self.initial_anchor = decode_anchor(json.loads(stored_anchor))
            else:
                self.initial_anchor = initial_anchor
            self.db.execute("PRAGMA journal_mode=DELETE")
            self.db.execute("PRAGMA synchronous=FULL")
            if created:
                with self.db:
                    self.db.execute("BEGIN IMMEDIATE")
                    self.db.execute("""
                        CREATE TABLE metadata(
                            version INTEGER PRIMARY KEY CHECK(version=2), identity TEXT NOT NULL,
                            initial_anchor TEXT NOT NULL
                        )
                    """)
                    self.db.execute("INSERT INTO metadata VALUES(2, ?, ?)", (encode(identity), encode(initial_anchor)))
                    self.db.execute("""
                        CREATE TABLE deliveries(
                            idx INTEGER PRIMARY KEY, payload TEXT NOT NULL,
                            status TEXT NOT NULL CHECK(status IN
                                ('pending','submitted','ram_ack','uncertain','committed')),
                            intent TEXT,
                            proof TEXT,
                            CHECK((status = 'pending') = (intent IS NULL)),
                            CHECK((status = 'committed') = (proof IS NOT NULL))
                        )
                    """)
                directory = os.open(path.parent, os.O_RDONLY | os.O_DIRECTORY)
                try:
                    os.fsync(directory)
                finally:
                    os.close(directory)
        except BaseException:
            self.db.close()
            raise

    def close(self):
        self.db.close()

    def enqueue(self, delivery: Delivery) -> bool:
        """Accept contiguous indices; identical replays are no-ops, conflicts stop."""
        with self.db:
            existing = self.db.execute("SELECT payload FROM deliveries WHERE idx=?", (delivery.index,)).fetchone()
            if existing:
                if existing[0] != encode(delivery):
                    raise ValueError("Conflicting payload for delivery index")
                return False
            last = self.db.execute("SELECT MAX(idx) FROM deliveries").fetchone()[0]
            if delivery.index != (0 if last is None else last + 1):
                raise ValueError("Delivery gap: resynchronize from the first missing index")
            self.db.execute("INSERT INTO deliveries(idx, payload, status) VALUES(?, ?, 'pending')",
                            (delivery.index, encode(delivery)))
        return True

    def head(self) -> tuple[Delivery, str] | None:
        row = self.db.execute("""
            SELECT payload, status FROM deliveries WHERE status != 'committed' ORDER BY idx LIMIT 1
        """).fetchone()
        return (Delivery(**json.loads(row[0])), row[1]) if row else None

    def checkpoint_for(self, index: int) -> RecoveryAnchor:
        if index == 0:
            return self.initial_anchor
        row = self.db.execute("SELECT status, proof FROM deliveries WHERE idx=?", (index - 1,)).fetchone()
        if row is None or row[0] != "committed" or not row[1]:
            raise DeliveryBlocked("No committed predecessor checkpoint")
        return decode_anchor(json.loads(row[1])["after"])

    def intent_for(self, index: int) -> SubmissionIntent:
        row = self.db.execute("SELECT intent FROM deliveries WHERE idx=?", (index,)).fetchone()
        if row is None or not row[0]:
            raise DeliveryBlocked("Missing durable pre-write intent")
        intent = json.loads(row[0])
        return SubmissionIntent(decode_anchor(intent["before"]), intent["runtime_epoch"])

    def _claim(self, index: int, intent: SubmissionIntent):
        with self.db:
            if intent.before != self.checkpoint_for(index):
                raise DeliveryBlocked("Submission intent does not match journal checkpoint")
            cursor = self.db.execute("""
                UPDATE deliveries SET status='submitted', intent=?
                WHERE idx=? AND status='pending'
                AND idx=(SELECT MIN(idx) FROM deliveries WHERE status != 'committed')
            """, (encode(intent), index))
            if cursor.rowcount != 1:
                raise DeliveryBlocked("Delivery already claimed, changed or out of order")

    def _transition(self, index: int, old: tuple[str, ...], new: str, proof: str | None = None):
        with self.db:
            cursor = self.db.execute(f"""
                UPDATE deliveries SET status=?, proof=?
                WHERE idx=? AND status IN ({','.join('?' for _ in old)})
                AND idx=(SELECT MIN(idx) FROM deliveries WHERE status != 'committed')
            """, (new, proof, index, *old))
            if cursor.rowcount != 1:
                raise DeliveryBlocked("Delivery already claimed, changed or out of order")


class DeliveryCoordinator:
    def __init__(self, journal: DeliveryJournal, game: GameInterface):
        self.journal, self.game = journal, game

    async def deliver_next(self) -> bool:
        """True means a RAM receipt only; it never means native-save persistence."""
        head = self.journal.head()
        if head is None:
            return False
        delivery, status = head
        if status != "pending":
            raise DeliveryBlocked("Unsettled delivery; never automatically resend")
        state = await self.game.observe()
        if (state.identity != self.journal.identity
                or not isinstance(state.runtime_epoch, str) or not state.runtime_epoch.strip()):
            raise DeliveryBlocked("Wrong world/save/build or missing runtime epoch")
        if state.safe_to_write is not True or state.next_delivery_index is None:
            raise DeliveryBlocked("Unsafe state or no verified game-side delivery ledger")
        if type(state.next_delivery_index) is not int or state.next_delivery_index != delivery.index:
            raise DeliveryBlocked("Game/journal index mismatch; reconciliation required")
        before = self.journal.checkpoint_for(delivery.index)
        if state.checkpoint != before.fingerprint:
            raise DeliveryBlocked("Loaded checkpoint differs from journal anchor; no replay")
        if await self.game.verify_recovery_anchor(before, state) is not True:
            raise DeliveryBlocked("Cannot verify pre-write recovery checkpoint")
        # Claim and exact rollback anchor commit together BEFORE any possible RAM write.
        intent = SubmissionIntent(before, state.runtime_epoch)
        self.journal._claim(delivery.index, intent)
        try:
            receipt = await self.game.apply(delivery, state, intent)
            if (receipt.delivery != delivery or receipt.identity != state.identity
                    or receipt.runtime_epoch != state.runtime_epoch
                    or receipt.intent != intent):
                raise DeliveryBlocked("Application receipt does not match guarded command")
            self.journal._transition(delivery.index, ("submitted",), "ram_ack")
        except BaseException:
            # If this update itself fails, the durable 'submitted' state still
            # blocks retry on next startup. Neither state is considered pending.
            self.journal._transition(delivery.index, ("submitted", "ram_ack"), "uncertain")
            raise
        return True

    async def confirm_saved(self) -> bool:
        """Reconcile an unsettled command using read-only, game-bound native-save proof."""
        head = self.journal.head()
        if head is None:
            return False
        delivery, status = head
        if status not in ("submitted", "ram_ack", "uncertain"):
            raise DeliveryBlocked("No submitted delivery to reconcile")
        state = await self.game.observe()
        if (state.identity != self.journal.identity
                or not isinstance(state.runtime_epoch, str) or not state.runtime_epoch.strip()):
            raise DeliveryBlocked("Loaded game identity is not the journal identity")
        intent = self.journal.intent_for(delivery.index)
        if intent.before != self.journal.checkpoint_for(delivery.index):
            raise DeliveryBlocked("Durable intent is detached from journal history")
        if state.checkpoint is None:
            raise DeliveryBlocked("Loaded checkpoint unavailable; no replay")
        if state.checkpoint == intent.before.fingerprint:
            # Could be an unsaved application or a rollback. Neither resets intent.
            return False
        if (not isinstance(state.checkpoint, CheckpointFingerprint)
                or not state.checkpoint.has_expected_changes_from(intent.before.fingerprint)):
            raise DeliveryBlocked("Loaded checkpoint is not a complete two-file successor")
        proof = await self.game.read_persistence(delivery, state, intent)
        if proof is None:
            return False
        if (not isinstance(proof, PersistenceReceipt)
                or proof.identity != state.identity or proof.runtime_epoch != state.runtime_epoch
                or proof.delivery != delivery or proof.intent != intent
                or not isinstance(proof.after, RecoveryAnchor) or proof.after.fingerprint != state.checkpoint
                or proof.after.snapshot_ref == intent.before.snapshot_ref
                or type(proof.next_delivery_index) is not int
                or proof.next_delivery_index != delivery.index + 1
                or type(state.next_delivery_index) is not int
                or state.next_delivery_index != proof.next_delivery_index):
            raise DeliveryBlocked("Stale, mismatched or incomplete persistence proof")
        if await self.game.verify_recovery_anchor(proof.after, state) is not True:
            raise DeliveryBlocked("Cannot verify post-write recovery checkpoint")
        self.journal._transition(delivery.index, (status,), "committed", encode(proof))
        return True
