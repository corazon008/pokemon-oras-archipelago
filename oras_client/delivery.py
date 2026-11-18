"""Durable, fail-stopped delivery journal. This is not an exactly-once game adapter."""

from dataclasses import asdict
import json
import os
from pathlib import Path
import re
import sqlite3

from .game_interface import Delivery, DeliveryIdentity, GameInterface


DEFAULT_JOURNAL_PATH = Path(__file__).resolve().parents[1] / "local/oras/client/delivery.sqlite3"


class DeliveryBlocked(RuntimeError):
    """Manual investigation or verified native persistence is required."""


def encode(value) -> str:
    return json.dumps(asdict(value), sort_keys=True, separators=(",", ":"))


class DeliveryJournal:
    def __init__(self, path: Path | None, identity: DeliveryIdentity):
        self.identity = identity
        path = DEFAULT_JOURNAL_PATH if path is None else path
        path.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
        try:
            descriptor = os.open(path, os.O_CREAT | os.O_EXCL | os.O_WRONLY, 0o600)
        except FileExistsError:
            created = False
        else:
            os.close(descriptor)
            created = True
        self.db = sqlite3.connect(path)
        try:
            if not created:
                # Do not initialize or reset an unfamiliar/corrupt database.
                rows = self.db.execute("SELECT version, identity FROM metadata").fetchall()
                if rows != [(1, encode(identity))]:
                    raise ValueError("Journal schema or world/save identity mismatch")
            self.db.execute("PRAGMA journal_mode=DELETE")
            self.db.execute("PRAGMA synchronous=FULL")
            if created:
                with self.db:
                    self.db.execute("CREATE TABLE metadata(version INTEGER PRIMARY KEY CHECK(version=1), identity TEXT NOT NULL)")
                    self.db.execute("INSERT INTO metadata VALUES(1, ?)", (encode(identity),))
                    self.db.execute("""
                        CREATE TABLE deliveries(
                            idx INTEGER PRIMARY KEY, payload TEXT NOT NULL,
                            status TEXT NOT NULL CHECK(status IN
                                ('pending','submitted','ram_ack','uncertain','committed')),
                            proof TEXT
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
            self.db.execute("INSERT INTO deliveries VALUES(?, ?, 'pending', NULL)",
                            (delivery.index, encode(delivery)))
        return True

    def head(self) -> tuple[Delivery, str] | None:
        row = self.db.execute("""
            SELECT payload, status FROM deliveries WHERE status != 'committed' ORDER BY idx LIMIT 1
        """).fetchone()
        return (Delivery(**json.loads(row[0])), row[1]) if row else None

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
        # The intent is committed to disk BEFORE any call that could write RAM.
        self.journal._transition(delivery.index, ("pending",), "submitted")
        try:
            receipt = await self.game.apply(delivery, state)
            if (receipt.delivery != delivery or receipt.identity != state.identity
                    or receipt.runtime_epoch != state.runtime_epoch):
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
        proof = await self.game.read_persistence(delivery, state)
        if proof is None:
            return False
        if (proof.identity != state.identity or proof.runtime_epoch != state.runtime_epoch
                or type(proof.next_delivery_index) is not int
                or proof.next_delivery_index != delivery.index + 1
                or type(state.next_delivery_index) is not int
                or state.next_delivery_index != proof.next_delivery_index
                or not re.fullmatch(r"[0-9a-f]{64}", proof.save_sha256)):
            raise DeliveryBlocked("Stale, mismatched or incomplete persistence proof")
        self.journal._transition(delivery.index, (status,), "committed", encode(proof))
        return True
