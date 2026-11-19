"""Transport-independent contracts. No game addresses or AP item IDs are defined here."""

from abc import ABC, abstractmethod
from dataclasses import dataclass
import re


def is_sha256(value):
    return isinstance(value, str) and re.fullmatch(r"[0-9a-f]{64}", value) is not None


@dataclass(frozen=True)
class DeliveryIdentity:
    world_fingerprint: str
    team: int
    slot: int
    rom_sha256: str
    save_binding: str

    def __post_init__(self):
        if (not isinstance(self.world_fingerprint, str) or not self.world_fingerprint.strip()
                or not isinstance(self.save_binding, str) or not self.save_binding.strip()
                or type(self.team) is not int or self.team < 0
                or type(self.slot) is not int or self.slot < 1
                or not is_sha256(self.rom_sha256)):
            raise ValueError("Invalid delivery identity")


@dataclass(frozen=True)
class Delivery:
    index: int
    item: int
    location: int
    player: int
    flags: int

    def __post_init__(self):
        if (any(type(value) is not int for value in vars(self).values())
                or min(self.index, self.item, self.player, self.flags) < 0):
            raise ValueError("Invalid delivery payload")


@dataclass(frozen=True)
class CheckpointFingerprint:
    """Verified archive contents, not a save identity or monotonic generation."""

    main_sha256: str
    sidecar_sha256: str
    metadata_sha256: str
    archive_tree_sha256: str

    def __post_init__(self):
        if not all(is_sha256(value) for value in vars(self).values()):
            raise ValueError("Invalid checkpoint fingerprint")

    def has_expected_changes_from(self, previous: "CheckpointFingerprint") -> bool:
        """Necessary changes for this two-file prototype; not proof of causality."""
        return (self.main_sha256 != previous.main_sha256
                and self.sidecar_sha256 != previous.sidecar_sha256
                and self.archive_tree_sha256 != previous.archive_tree_sha256
                and self.metadata_sha256 == previous.metadata_sha256)


@dataclass(frozen=True)
class RecoveryAnchor:
    fingerprint: CheckpointFingerprint
    # Opaque adapter reference; the journal never opens this as a path.
    snapshot_ref: str

    def __post_init__(self):
        if (not isinstance(self.fingerprint, CheckpointFingerprint)
                or not isinstance(self.snapshot_ref, str) or not self.snapshot_ref.strip()
                or len(self.snapshot_ref) > 4096):
            raise ValueError("Invalid recovery anchor")


@dataclass(frozen=True)
class SubmissionIntent:
    before: RecoveryAnchor
    runtime_epoch: str

    def __post_init__(self):
        if (not isinstance(self.before, RecoveryAnchor)
                or not isinstance(self.runtime_epoch, str) or not self.runtime_epoch.strip()):
            raise ValueError("Invalid submission intent")


@dataclass(frozen=True)
class GameState:
    identity: DeliveryIdentity
    runtime_epoch: str
    safe_to_write: bool
    # None means no verified atomic game-side delivery ledger: writes must stop.
    next_delivery_index: int | None
    # Current loaded state's durable checkpoint, not just a read of the disk.
    checkpoint: CheckpointFingerprint | None = None


@dataclass(frozen=True)
class ApplicationReceipt:
    delivery: Delivery
    identity: DeliveryIdentity
    runtime_epoch: str
    intent: SubmissionIntent


@dataclass(frozen=True)
class PersistenceReceipt:
    identity: DeliveryIdentity
    runtime_epoch: str
    next_delivery_index: int
    delivery: Delivery
    intent: SubmissionIntent
    after: RecoveryAnchor


class GameInterface(ABC):
    @abstractmethod
    async def observe(self) -> GameState:
        """Identify loaded world/save/build, runtime epoch and durable baseline."""

    @abstractmethod
    async def verify_recovery_anchor(self, anchor: RecoveryAnchor, expected: GameState) -> bool:
        """Reverify the exact complete snapshot is recoverable before claiming intent.

        Verify bytes and game identity as well as consistency of item/index state.
        A syntactically valid digest, CRC-valid main, or sidecar marker is not
        enough. This check must not trigger a save, mutate the game or re-pin a
        journal to a different checkpoint.
        """

    @abstractmethod
    async def apply(
        self, delivery: Delivery, expected: GameState, intent: SubmissionIntent,
    ) -> ApplicationReceipt:
        """Guard identity, epoch, checkpoint, safe state and index; apply item+index atomically.

        Bind the result to the intent; return only after full readback.
        Unsupported items or full inventory must fail without modification.
        A lost response does not authorize a retry.
        No existing ORAS probe currently implements this contract.
        """

    @abstractmethod
    async def read_persistence(
        self, delivery: Delivery, expected: GameState, intent: SubmissionIntent,
    ) -> PersistenceReceipt | None:
        """Read-only proof that this intent produced a recoverable item+index checkpoint.

        Bind proof to the currently loaded save and epoch, not a stale disk
        file after rollback. Reverify the complete post-save snapshot and bind
        the actual delivery to the pre-write intent. Two changed file hashes
        alone prove neither causality nor consistency. Never trigger SAVE.
        """
