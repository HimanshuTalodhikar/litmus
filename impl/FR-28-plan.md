# Implementation Plan — FR-28: Real-Time Collaboration for BillSnap

---

## Context

BillSnap is a billing and invoice management platform. The real-time collaboration feature enables multiple team members to simultaneously view, edit, and annotate the same bill or invoice — with changes propagated instantly, cursor positions visible, and conflicts resolved automatically. This eliminates the "last write wins" chaos of polling-based updates and removes the bottleneck of sequential review workflows. It matters because finance teams, accountants, and small business owners often work in parallel on the same documents and need a shared, live view without stepping on each other.

---

## Architecture

The core architecture uses a **WebSocket pub/sub hub** backed by **Yjs CRDTs** for conflict-free concurrent editing, with a **presence layer** for live cursor and selection awareness. All state changes flow through a dedicated collaboration service that broadcasts deltas to connected clients and persists snapshots to the existing PostgreSQL store.

```
┌─────────────────────────────────────────────────────────┐
│  Browser Client (React)                                 │
│  ┌──────────────┐  ┌──────────────┐  ┌──────────────┐  │
│  │ Bill Editor  │  │ Presence Bar │  │ Cursor Layer │  │
│  └──────┬───────┘  └──────┬───────┘  └──────┬───────┘  │
│         │                 │                 │          │
│         └────────────┬─────┴────────────────┘          │
│                      │                                  │
│              ┌───────▼────────┐                        │
│              │  useCollab()   │  ← React context/hook  │
│              │  (Yjs + WS)    │                        │
│              └───────┬────────┘                        │
└──────────────────────┼──────────────────────────────────┘
                       │ Socket.io (WebSocket + HTTP)
        ┌──────────────▼──────────────┐
        │  Node.js / Express Backend   │
        │  ┌────────────────────────┐  │
        │  │  CollaborationService │  │  ← in-process hub
        │  │  (y-websocket server)  │  │
        │  └──────────┬─────────────┘  │
        │             │                │
        │  ┌──────────▼─────────────┐  │
        │  │  Broadcast (Yjs deltas)│  │
        │  └──────────┬─────────────┘  │
        └─────────────┼────────────────┘
                      │ persist on demand
          ┌───────────▼───────────────┐
          │  PostgreSQL               │
          │  bills, collaboration_    │
          │  snapshots, presence_log  │
          └───────────────────────────┘
```

**Technology choices:**
- **WebSocket server:** `y-websocket` (Yjs provider backed by a Node.js server) — handles room management, document syncing, and reconnection
- **CRDT engine:** `yjs` — handles concurrent edits to structured bill data (line items, amounts, notes) without conflicts
- **Presence:** Custom Socket.io room + `y-awareness` — broadcasts cursor position, user color, and online status
- **Frontend state:** `zustand` or React context synced from Yjs — minimal additional state management
- **Auth:** JWT middleware on the WebSocket handshake — rooms scoped to bill ID, authorized against the existing auth layer
- **Persistence:** Yjs snapshots written to PostgreSQL via a debounced "save" trigger on the server, and on-demand via a `PERSIST` event from the client before navigation

---

## File Structure

```
bill-snap/
├── server/
│   ├── src/
│   │   ├── index.ts                        # Express entry point
│   │   ├── ws/
│   │   │   ├── collaborationServer.ts       # y-websocket server setup
│   │   │   ├── authMiddleware.ts           # JWT validation on WS upgrade
│   │   │   ├── roomManager.ts              # Bill-ID → room + user mapping
│   │   │   └── presenceBroadcaster.ts      # Awareness (cursor/presence) handler
│   │   ├── services/
│   │   │   ├── collaborationService.ts      # High-level collab orchestration
│   │   │   └── snapshotService.ts          # Persist Yjs snapshots to DB
│   │   └── models/
│   │       └── collaborationSnapshot.ts    # Prisma model for snapshots
│   └── prisma/
│       └── migrations/
│           └── add_collaboration_tables/
│               └── migration.sql
├── client/
│   ├── src/
│   │   ├── main.tsx
│   │   ├── App.tsx
│   │   ├── hooks/
│   │   │   ├── useCollab.ts                # Primary hook: Yjs + WS lifecycle
│   │   │   ├── usePresence.ts              # Presence/cursor state
│   │   │   └── useSnapshot.ts             # Load/save snapshots
│   │   ├── components/
│   │   │   ├── BillEditor/
│   │   │   │   ├── BillEditor.tsx          # Main editor shell
│   │   │   │   ├── LineItemsTable.tsx       # CRDT-synced line items
│   │   │   │   ├── BillHeader.tsx          # Bill metadata (client, date, etc.)
│   │   │   │   ├── NotesField.tsx          # Rich text / plain text notes
│   │   │   │   ├── CursorOverlay.tsx       # SVG/absolute-positioned cursors
│   │   │   │   └── PresenceBar.tsx         # Avatar strip of active users
│   │   │   └── shared/
│   │   │       ├── UserAvatar.tsx
│   │   │       └── CollabStatusBadge.tsx   # "Connected" / "Syncing" / "Offline"
│   │   ├── lib/
│   │   │   ├── yjs.ts                      # Yjs document factory + providers
│   │   │   └── socket.ts                   # Socket.io client singleton
│   │   ├── store/
│   │   │   └── collabStore.ts              # Zustand store for collab meta-state
│   │   └── types/
│   │       └── collab.ts                   # Shared types: UserPresence, CursorPos
│   └── package.json
└── tests/
    └── integration/
        ├── collab.todo.test.ts
        └── presence.test.ts
```

---

## Implementation Phases

### ## Phase 1: WebSocket Infrastructure & Room Management

**Goal:** Establish the WebSocket server, JWT auth on connection, and per-bill room routing. No editing yet — just connected/disconnected state and presence broadcast.

**Files to create/modify:**
- `server/src/ws/collaborationServer.ts` — new
- `server/src/ws/authMiddleware.ts` — new
- `server/src/ws/roomManager.ts` — new
- `server/src/index.ts` — modify to mount WS server
- `server/src/models/collaborationSnapshot.ts` — new Prisma model stub
- `client/src/lib/socket.ts` — new Socket.io client singleton
- `client/src/components/shared/CollabStatusBadge.tsx` — new (shows "Connecting…")

**Key decisions:**
- Rooms are named `bill:{billId}` — simple, auditable, easy to scope in Redis later if scaling is needed.
- Auth happens at WS upgrade time: the client sends the JWT as a query param (`?token=…`) or in the `auth` handshake object. The middleware decodes it and attaches `req.user` before the socket is正式 connected.
- Reject with code 4001 if the JWT is missing or expired; 4003 if the user doesn't have read access to that billId.

**Verification:**
- `curl -i -- Upgrade websocket` via a test script succeeds with a valid JWT and is rejected without one.
- A client in room `bill:42` does not receive events from room `bill:99`.
- `CollabStatusBadge` transitions: `disconnected → connecting → connected` on a clean load.

---

### ## Phase 2: Yjs Document Bootstrap & Snapshot Persistence

**Goal:** Every bill gets a Yjs document on first collaborative access. The document is persisted to PostgreSQL and rehydrated on subsequent connections so no state is lost if all clients disconnect.

**Files to create/modify:**
- `server/src/services/collaborationService.ts` — new
- `server/src/services/snapshotService.ts` — new
- `server/src/ws/collaborationServer.ts` — modify to use collaborationService
- `server/prisma/schema.prisma` — modify: add `CollaborationSnapshot`, `BillCollaborator` models
- `server/prisma/migrations/add_collaboration_tables/migration.sql` — new migration
- `client/src/lib/yjs.ts` — new: `createBillDoc(billId)` factory
- `client/src/hooks/useCollab.ts` — new: initializes Yjs doc + WebsocketProvider, exposes `doc` and `provider`
- `client/src/hooks/useSnapshot.ts` — new: loads persisted snapshot into Yjs doc

**Key decisions:**
- The Yjs document structure is: `Y.Doc` with sub-maps `header` (bill metadata), `lineItems` (Y.Array), `notes` (Y.Text), and `totals` (Y.Map).
- Persistence strategy: a debounced (800 ms) server-side `persistDoc(docId)` triggered by `y-websocket`'s `sync` events. Additionally, the client emits `PERSIST_NOW` before every navigation event and on window `beforeunload`.
- Snapshot storage: a `CollaborationSnapshot` row with `billId`, `yjsState` (bytea / JSON-encoded state vector + update blob), `savedAt`, `savedBy`.
- If no snapshot exists (cold start), an initial document is built from the existing `Bill` row in the DB, populating the Yjs doc from that relational state.

**Verification:**
- Create a bill, connect two clients, make edits on client A, disconnect A, reconnect A — edits from the previous session are present.
- Snapshot row is written to DB within 2 seconds of the last edit.
- Cold-start: new bill without a snapshot initializes with the relational DB values.

---

### ## Phase 3: Real-Time Bill Editing with Conflict-Free Merging

**Goal:** Line items, header fields, and notes are editable in real time by multiple users with automatic conflict resolution — no "your changes were overwritten" dialogs.

**Files to create/modify:**
- `client/src/components/BillEditor/BillEditor.tsx` — modify: wrap in `useCollab` provider
- `client/src/components/BillEditor/LineItemsTable.tsx` — modify: bind to `Y.Array` via `observe` / `y-array` binding
- `client/src/components/BillEditor/BillHeader.tsx` — modify: bind to `header` Y.Map
- `client/src/components/BillEditor/NotesField.tsx` — modify: bind to `notes` Y.Text
- `client/src/hooks/useCollab.ts` — modify: expose typed document sub-collections (`header`, `lineItems`, `notes`)
- `client/src/types/collab.ts` — new: `BillDoc`, `LineItem`, `BillHeader` types

**Key decisions:**
- Use Yjs structural types: `Y.Array<LineItem>` for line items (index-based, good for CRDT array), `Y.Map` for header fields (key-value), `Y.Text` for notes (character-level merging for concurrent text edits).
- Totals (subtotal, tax, total) are **computed client-side** from the `lineItems` Y.Array — not independently editable CRDT fields. This prevents a conflict where two users independently change the total to different values.
- For the line items table, each row is keyed by a UUID (stored in the Yjs item) so concurrent row insertions are distinguishable. No positional locking.
- The `LineItemsTable` renders from `yArray.toArray()` using `useMemo` keyed on the Yjs document version.

**Code sketch — `LineItemsTable.tsx`:**
```tsx
import { Y } from 'yjs'
import { useEffect, useState } from 'react'

interface LineItem {
  id: string
  description: string
  quantity: number
  unitPrice: number
}

export function LineItemsTable({ yArray }: { yArray: Y.Array<LineItem> }) {
  const [items, setItems] = useState<LineItem[]>([])

  useEffect(() => {
    const render = () => setItems(yArray.toArray())
    yArray.observe(render)
    render()
    return () => yArray.unobserve(render)
  }, [yArray])

  const addRow = () => {
    yArray.push([{ id: crypto.randomUUID(), description: '', quantity: 1, unitPrice: 0 }])
  }

  const updateRow = (index: number, patch: Partial<LineItem>) => {
    const item = { ...yArray.get(index), ...patch }
    yArray.delete(index, 1)
    yArray.insert(index, [item as LineItem])
  }

  const deleteRow = (index: number) => yArray.delete(index, 1)

  return (
    <table>
      <thead>...</thead>
      <tbody>
        {items.map((item, i) => (
          <tr key={item.id}>
            <td><input value={item.description}
              onChange={e => updateRow(i, { description: e.target.value })} /></td>
            <td>...</td>
          </tr>
        ))}
      </tbody>
    </table>
  )
}
```

**Verification:**
- Open the same bill in two browser tabs. Edit line item A in tab 1 and line item B in tab 2 simultaneously — both changes appear in both tabs within 1 second with no data loss.
- Insert a row in tab 1 while deleting a different row in tab 2 — both operations succeed with no corruption.
- Totals recompute correctly as line items change.

---

### ## Phase 4: Presence — Live Cursors & Active Users

**Goal:** Show who is currently in the document, where their cursor is, and what field they have focused. This gives the "Google Docs" feel and prevents accidental simultaneous field edits.

**Files to create/modify:**
- `server/src/ws/presenceBroadcaster.ts` — new
- `client/src/hooks/usePresence.ts` — new
- `client/src/components/BillEditor/CursorOverlay.tsx` — new
- `client/src/components/BillEditor/PresenceBar.tsx` — new
- `client/src/components/shared/UserAvatar.tsx` — modify: add color ring for collab state
- `client/src/types/collab.ts` — modify: add `UserPresence`, `CursorPosition`

**Key decisions:**
- Use `y-awareness` (built into `y-websocket`) — it maintains a local state object per client and broadcasts it to all peers in the same room. No server-side presence storage needed; state lives in memory on the y-websocket server and propagates via the WebSocket connection.
- Awareness state shape per client:
  ```ts
  interface UserPresence {
    userId: string
    name: string
    color: string        // assigned deterministically from userId hash
    cursor: CursorPosition | null
    focusedField: string | null   // e.g. "lineItems.3.description"
    lastSeen: number
  }
  ```
- Cursor positions are captured via `onPointerMove` on individual form fields, storing `{ fieldKey, offset }` — the offset is character index for text fields, row index for line items.
- The `CursorOverlay` is an absolutely-positioned SVG layer over the editor that renders one cursor line + name label per remote user, positioned by measuring the target element's `getBoundingClientRect()`.
- User colors: deterministic hex color from `userId` via a simple hash → 8 preset palette — ensures the same user always gets the same color across sessions.

**Verification:**
- Open bill in two tabs as two different users — both appear in each other's PresenceBar.
- Move cursor in tab 1 — a colored cursor label appears in tab 2 at the corresponding field within 200 ms.
- Disconnect tab 1 (close tab or kill network) — the remote cursor disappears from tab 2 within 5 seconds (y-awareness timeout).
- Click into a field in tab 1 — `focusedField` appears in tab 2's awareness state; consider showing a subtle "Editing…" indicator on that field.

---

### ## Phase 5: Conflict Notification & Edit Awareness UI

**Goal:** When two users are editing the same field simultaneously, show a gentle "User X is editing this" indicator. Provide an "undo" mechanism so users can back out of conflicts.

**Files to create/modify:**
- `client/src/components/BillEditor/BillHeader.tsx` — modify: add conflict indicator
- `client/src/components/BillEditor/LineItemsTable.tsx` — modify: add per-cell conflict badge
- `client/src/components/shared/EditingIndicator.tsx` — new: "Alice is editing…" chip
- `client/src/hooks/useCollab.ts` — modify: add `conflicts` derived state
- `client/src/store/collabStore.ts` — new Zustand store for UI-level collab metadata
- `server/src/services/snapshotService.ts` — modify: add undo stack snapshots (last N changes per user)

**Key decisions:**
- Conflict detection: a field has a conflict when `focusedField` of a *remote* user equals the local user's current `focusedField`. Tracked in `usePresence`.
- The conflict badge is informational only — it does not lock the field. Users can still edit; Yjs will merge.
- Undo: each user has a local `Y.UndoManager` scoped to their own client ID tag (`clientID`). Pressing Ctrl+Z undoes only their own changes, not collaborators'. The undo stack is ephemeral (lost on refresh) — acceptable for a first pass.
- A conflict resolution log (who changed what, when) is written to a `collaboration_log` table for audit purposes, with debouncing (batch writes every 5 seconds).

**Verification:**
- Two users click into the same line item description field — both see an "Alice is editing…" badge on that cell.
- User A types "Invoice #", User B types "Bill #" — both values are merged correctly by Yjs (character-level interleaving).
- User A presses Ctrl+Z — only User A's typing is undone; User B's characters remain.

---

### ## Phase 6: Permission Scoping, Loading States & Edge Cases

**Goal:** Polish: read-only access for viewers, proper loading skeletons, graceful degradation when WebSocket is unavailable, and cross-device continuity.

**Files to create/modify:**
- `server/src/ws/authMiddleware.ts` — modify: add `viewer` vs `editor` role per bill
- `client/src/hooks/useCollab.ts` — modify: downgrade to read-only mode if user has viewer role
- `client/src/components/shared/CollabStatusBadge.tsx` — modify: add "Read-only" and "Offline" states
- `client/src/components/BillEditor/BillEditor.tsx` — modify: add loading skeleton while Yjs doc initializes
- `server/src/services/snapshotService.ts` — modify: implement full snapshot restore from `yjsState` blob
- `server/prisma/migrations/add_collaboration_tables/migration.sql` — finalize schema

**Key decisions:**
- Viewer role: the WS connection is still established, but the client initializes the Yjs doc in *local read-only mode* — `observe` only, no `unobserve` / write transactions. The presence cursor still appears so viewers see live activity.
- Offline mode: if WebSocket disconnects (network loss), the client continues editing locally against the in-memory Yjs doc. On reconnect, Yjs automatically syncs the delta. The `CollabStatusBadge` shows "Offline — changes will sync when reconnected."
- Reconnect strategy: `y-websocket` provider uses exponential backoff with a 1-second initial delay and a 30-second cap — standard WebSocket reconnect behavior.
- Full snapshot restore: on cold load, the client requests the latest `yjsState` blob from `CollaborationSnapshot`, calls `Y.applyUpdate(doc, state)`, and then connects to the live y-websocket room to receive any changes that happened while the client was loading.

**Verification:**
- User with `viewer` role on a bill sees the editor populated with live data but all inputs are `disabled` and a "View only" badge is shown.
- Disconnect the network cable while editing — edits continue locally; reconnecting within 2 minutes restores full sync with no data loss.
- The bill loads correctly on a third device after two other users have made changes — no stale data, no duplicate rows.

---

## Key Technical Decisions

| Decision | Choice | Rationale |
|---|---|---|
| Real-time protocol | **Socket.io + y-websocket** | Socket.io gives us rooms, auth, fallback to HTTP long-polling, and reconnect logic out of the box. y-websocket is the canonical Yjs server provider. Combining them keeps a single WebSocket connection rather than managing two. |
| Conflict resolution | **Yjs CRDTs** | CRDTs are mathematically proven to converge regardless of message ordering. For a billing app, we need guarantees that $472.50 + $12.00 never silently becomes either value alone. OT (Operational Transformation) was the alternative but Yjs requires less application-level complexity. |
| Document structure | **`Y.Map` + `Y.Array` + `Y.Text`** | Matches the natural shape of a bill (header fields = map, line items = ordered array, notes = rich text). Each sub-document is independently observable by React components. |
| Persistence | **State vector snapshots in PostgreSQL** | Bytea column storing `Y.encodeStateAsUpdate(doc)`. Simple to implement, works with the existing Prisma setup, avoids a separate document store like MongoDB or Redis. Snapshots are written debounced 800 ms after last change + on-demand before navigation. |
| Presence | **y-awareness** | Built into the y-websocket provider. Zero additional infrastructure. Awareness state is ephemeral (gone on server restart) — acceptable since presence is inherently transient. |
| Totals | **Client-side computed, not CRDT** | Totals are a pure function of line items. Making them independently editable CRDT fields would create divergent values with no correct merge. Computing them client-side from the `lineItems` Y.Array guarantees consistency. |
| Undo/redo | **Per-user `Y.UndoManager`** | `Y.UndoManager` tracks edits by `clientID`. Each user's undo is scoped to their own edits — collaborators' changes are never rolled back by someone else's Ctrl+Z. |
| Auth | **JWT at WS upgrade** | Same JWT used by the REST API. Rooms are `bill:{billId}`; server checks the JWT claims include read or write access to that bill before adding the socket to the room. |

---

## Verification Plan

**End-to-end test scenario:**

1. **Setup:** Spin up the server and two browser sessions, logged in as `user_A` and `user_B`, both opening bill #101.
2. **Phase 1 check:** `CollabStatusBadge` shows "Connected" in both sessions. A third session with an invalid JWT is rejected.
3. **Phase 2 check:** User A adds a line item and waits 2 seconds. `CollaborationSnapshot` row exists in PostgreSQL. User B loads the page fresh — the line item appears immediately without stale data.
4. **Phase 3 check:** User A edits the description of row 1; User B simultaneously edits the quantity of row 2. Both changes are visible in both sessions with no "saved over" behavior. A third simultaneous edit to the same cell interleaves character-by-character correctly.
5. **Phase 4 check:** User A moves cursor to the "tax rate" field — User B sees a colored cursor label at that field within 200 ms. User A's avatar appears in User B's `PresenceBar` with their name and color.
6. **Phase 5 check:** Both users click into the same description cell — both see an "X is editing this" indicator. User A presses Ctrl+Z — only User A's recent keystrokes are undone.
7. **Phase 6 check:** User C (viewer role) loads bill #101 and sees a "View only" badge. Network is cut for User B — `CollabStatusBadge` shows "Offline." Network restores — badge returns to "Connected" and all User A's changes made during the outage are synced into User B's document.
8. **Load test:** 20 users connecting to the same bill simultaneously — all cursors visible, no perceptible lag (< 200 ms end-to-end latency for character updates at 20 users).

**Unit tests:**
- `snapshotService.ts`: encode a Yjs doc → persist → retrieve → decode → compare document content (should be identical).
- `usePresence.ts`: mock awareness state transitions, verify cursor/presence UI state.
- `useCollab.ts`: verify that an editor with viewer role produces no write transactions.

**Integration tests:**
- Socket connection flow: connect → auth → join room → receive broadcast → disconnect.
- Concurrent edit merge: two Yjs clients apply conflicting patches offline, reconnect, verify convergence.

---

That's the full plan. It starts thin — just the wire and rooms — and layers CRDT editing, presence, and polish on top of a solid foundation. Want me to start implementing any specific phase?