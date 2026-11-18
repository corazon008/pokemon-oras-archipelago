# Experimental ORAS client foundations

This package has **no live BizHawk writer, AP WebSocket client, APWorld, or
approved item/location IDs**. It is an offline-tested contract and journal.
Do not substitute the research Potion probe for a delivery adapter.

## Components

- `game_interface.py`: immutable identity/payload/receipt types and abstract
  `GameInterface`.
- `delivery.py`: SQLite queue and conservative delivery coordinator.
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

- Intent is committed to SQLite before calling an adapter that could modify RAM.
- Only the first uncommitted index can be claimed.
- Identical packet replays are no-ops; conflicts and gaps are rejected.
- Every state except `pending` blocks another application.
- Response loss, cancellation or bad acknowledgment leaves the item uncertain.
- Reopening a journal never turns an unsettled item back into pending.
- `deliver_next()` returning true acknowledges RAM, not SAVE.
- `confirm_saved()` only reads a persistence proof; it never presses SAVE.
- A valid proof can reconcile submitted/uncertain/RAM-acknowledged work.
- No proof means wait/investigate, **not** permission to resend.

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

Without a verified game-side counter, `next_delivery_index` must be `None`.
The coordinator then refuses to submit anything. Potion quantity cannot stand
in for a delivery index: consumption, native gifts and rollback change quantity.

This stage favors stopping over duplication. There is no automatic retry even
after a known item rejection, and no automatic rollback/recovery writer.
Exactly-once delivery **in the actual game has not been demonstrated**.
