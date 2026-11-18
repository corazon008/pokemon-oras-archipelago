"""Transport-independent contracts. No game addresses or AP item IDs are defined here."""

from abc import ABC, abstractmethod
from dataclasses import dataclass
import re


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
                or not isinstance(self.rom_sha256, str)
                or not re.fullmatch(r"[0-9a-f]{64}", self.rom_sha256)):
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
class GameState:
    identity: DeliveryIdentity
    runtime_epoch: str
    safe_to_write: bool
    # None means no verified atomic game-side delivery ledger: writes must stop.
    next_delivery_index: int | None


@dataclass(frozen=True)
class ApplicationReceipt:
    delivery: Delivery
    identity: DeliveryIdentity
    runtime_epoch: str


@dataclass(frozen=True)
class PersistenceReceipt:
    identity: DeliveryIdentity
    runtime_epoch: str
    next_delivery_index: int
    save_sha256: str


class GameInterface(ABC):
    @abstractmethod
    async def observe(self) -> GameState:
        """Identify loaded world/save/build and runtime epoch; no inferred safe state."""

    @abstractmethod
    async def apply(self, delivery: Delivery, expected: GameState) -> ApplicationReceipt:
        """Guard identity, epoch, safe state and index, then atomically apply item+index.

        Return only after full readback. Unsupported items or full inventory must
        fail without modification. A lost response does not authorize a retry.
        No existing ORAS probe currently implements this contract.
        """

    @abstractmethod
    async def read_persistence(self, delivery: Delivery, expected: GameState) -> PersistenceReceipt | None:
        """Read-only proof of item+index in the same CRC-valid native save.

        Bind proof to the currently loaded save and epoch, not a stale disk
        file after rollback. Return None if not yet saved. Never trigger SAVE.
        """
