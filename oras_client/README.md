# Experimental ORAS client foundations

This package has **no live BizHawk writer, AP WebSocket client, APWorld, or
approved item/location IDs**. It is an offline-tested contract and journal.
Do not substitute the research Potion probe for a delivery adapter.

## Components

- `game_interface.py`: immutable identity/payload/receipt types and abstract
  `GameInterface`.
- `delivery.py`: SQLite queue, durable checkpoint-bound intents and conservative
  delivery coordinator.
- `../tests/test_delivery.py`: synthetic backend implementing a hypothetical
  atomic game-side ledger. That ledger has **not** been identified in ORAS.

`DeliveryIdentity` binds the queue to world fingerprint, team, slot, exact ROM
hash and stable save binding. These must eventually be verified by the real
adapter and generated metadata. Arbitrary strings or the hash of an ordinary
changing save file do not establish a stable game/save identity.

## State machine

```text
pending -> submitted -> ram_ack -> committed
              |            |
              +-> uncertain+
```

- The exact pre-write anchor and originating runtime epoch commit to SQLite
  in the same transaction that claims the delivery, before calling `apply`.
- Only the first uncommitted index can be claimed.
- Identical packet replays are no-ops; conflicts and gaps are rejected.
- Every state except `pending` blocks another application.
- Response loss, cancellation or bad acknowledgment leaves the item uncertain.
- Reopening a journal never turns an unsettled item back into pending.
- `deliver_next()` returning true acknowledges RAM, not SAVE.
- `confirm_saved()` only reads a persistence proof; it never presses SAVE.
- A valid proof can reconcile submitted/uncertain/RAM-acknowledged work.
- No proof means wait/investigate, **not** permission to resend.

## Checkpoint binding

The initial anchor is explicit at journal creation. It contains hashes of
`main`, the sidecar, archive metadata and the complete archive tree, plus an
opaque reference to a recoverable snapshot. The journal never follows that
reference as a path. After the first commit, only the preceding delivery's
committed post-save anchor is accepted as the next baseline. The adapter has
to verify the loaded checkpoint and the referenced snapshot; values with
the right syntax alone do not pass the contract.

RAM and post-SAVE receipts must identify the exact intent and delivery.
The post-SAVE receipt must also match the currently loaded checkpoint and
current runtime epoch. Both data files must differ from the pre-write pair
and archive metadata must match. This is a necessary change check, **not**
proof of order or causality. The hypothetical adapter must establish that
the exact item and index were saved together and verify the post-write
snapshot before the journal advances. It may reconcile across a cold boot
only from proof tied to the newly observed epoch.

Missing snapshots, unknown checkpoints, either half of a split SAVE, or a
rollback block progression even if an index looks right. An unsaved or
rolled-back in-flight delivery stays unsettled. There is no automatic
re-anchoring if ordinary gameplay saves change the archive between deliveries.

This contract uses journal schema **v2**. A new journal requires
`initial_anchor=...`; reopening reads the existing anchor and refuses to
replace it. Schema v1 is refused unchanged. It cannot be migrated safely by
inventing historical checkpoints; preserve existing files and do not create
a substitute queue to force replay.

The journal uses SQLite transactions, `synchronous=FULL`, a private database
file, and parent-directory synchronization on creation. Passing `None` as its
path selects `local/oras/client/delivery.sqlite3`; tests pass isolated temporary
paths. An existing foreign, incompatible or corrupt database is not reset.

Use one active device for a journal. Do not merge or synchronize a live SQLite
database between PCs through Nextcloud. Native-save snapshots do not include
this database. Lost journals and rollback of either side require reconciliation;
they must not be handled by blindly recreating indices or replaying items.

## Requirements for a future live adapter

Before implementing `apply`, prove all of the following on the exact build:

1. Runtime/world/save identification and epoch invalidation after reload.
2. A genuinely safe write context, not a guessed menu flag.
3. Supported item mapping and full-inventory rejection.
4. Atomic item application **and** game-side delivery-index update.
5. Those two changes persisted together in a CRC-valid native save.
6. Persistence proof tied to the currently loaded state, not a stale disk file.
7. Guard exceptions cannot accidentally execute a following WRITE.

The upstream GUARD handler's exception behavior is a known limitation (report
008). The [strict research shim](../docs/reports/017-ledger-storage-and-strict-guards.md)
now rejects errors, partial reads and domain/range fallback; the Potion probe
requires it. It is still **not** a transaction across multiple WRITE requests.
PC-side SQLite alone does not close the crash window between changing the game
and recording an acknowledgment.

Frame-level [native-save research](../docs/reports/021-native-save-observation.md)
observed a CRC-invalid backing-file sample between valid initial/final saves.
A UI success message or matching RAM is therefore not a durable receipt.
The [inter-file interruption](../docs/reports/029-interrupted-native-save.md)
then left a CRC-valid updated `main` paired with the old test sidecar. A fresh
fork of the old checkpoint booted, but that was rollback, not AP recovery.
Filesystem atomicity and item/index persistence are not established. The
experimental cold reload used an explicit fixed clock on an isolated copy;
an unknown EventWork tail byte varies with time context and is neither masked
nor repurposed as AP storage.

The [research recovery fork](../docs/reports/022-recovery-forks-and-load-reset.md)
boots a verified older snapshot in a new profile only. It does not establish AP
world binding, infer a delivery index, reset this journal or authorize replay.
Restoring a CRC-valid file is not reconciliation of delivered items.
Full-archive v2 snapshots also preserve opaque sidecars and empty directories;
their hashes establish byte integrity, not AP identity or item/index coherence.

Without a verified game-side counter, `next_delivery_index` must be `None`.
The coordinator then refuses to submit anything. Potion quantity cannot stand
in for a delivery index: consumption, native gifts and rollback change quantity.

This stage favors stopping over duplication. There is no automatic retry even
after a known item rejection, and no automatic rollback/recovery writer.
Exactly-once delivery **in the actual game has not been demonstrated**.
See [report 030](../docs/reports/030-checkpoint-bound-delivery-intent.md) for
offline checkpoint tests and remaining limits.
