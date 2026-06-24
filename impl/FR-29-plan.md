# Implementation Plan — FR-29: Collaboration & Payment Split

## Context

**What this feature does:** Enables multiple users to collaboratively create, view, and manage shared bills with flexible cost-splitting logic. Users can split expenses equally, by percentage, or with custom amounts per person. The system tracks who has paid their share and maintains a running settlement balance per group.

**Why it matters:** Bill Snap currently helps individuals capture and organize receipts. This feature transforms it into a *group* tool — addressing the #1 pain point for friends splitting dinners, roommates sharing utilities, or coworkers splitting work lunches. Without this, users resort to spreadsheets, Venmo DMs, or memory. With it, Bill Snap becomes the central hub for shared expenses.

**Scope boundaries for this plan:**
- Group management (create, invite, leave groups)
- Bill creation with multi-person splits
- Payment status tracking per participant
- Settlement engine (who owes whom)
- Basic reminders (in-app notifications; payment link integration is out of scope for v1)

---

## Architecture

### Technology Stack Assumptions

Since the existing Bill Snap codebase isn't specified, this plan assumes:

| Layer | Technology | Rationale |
|-------|-----------|-----------|
| **Mobile App** | React Native (Expo) | Cross-platform, fast iteration. Assumed for "Bill Snap" mobile UX. |
| **Backend API** | Node.js + Express | Shared TypeScript with RN, strong JSON ecosystem for flexible split schemas |
| **Database** | PostgreSQL | Relational data with complex joins (users ↔ groups ↔ bills ↔ splits). ACID compliance critical for money. |
| **Real-time** | Socket.IO | Group edits, payment updates, live balance recalculation |
| **Auth** | JWT + refresh tokens | Stateless auth; refresh tokens for session management |
| **File Storage** | S3-compatible (e.g., Supabase Storage) | Receipt image attachments per bill |
| **Notifications** | In-app + Firebase Cloud Messaging (FCM) / APNs | Reminders and live updates |

### High-Level Data Model

```
┌─────────────┐       ┌─────────────┐       ┌─────────────┐
│   User      │       │   Group     │       │    Bill     │
├─────────────┤       ├─────────────┤       ├─────────────┤
│ id          │───┐   │ id          │   ┌───│ id          │
│ email       │   │   │ name        │   │   │ group_id    │
│ name        │   └──►│ created_by  │───┘   │ title       │
│ avatar_url  │       │ created_at  │       │ total_amount│
└─────────────┘       └─────────────┘       │ created_by  │
                               │            │ receipt_url │
                               │            │ created_at  │
                               ▼            └─────────────┘
                    ┌─────────────────┐             │
                    │  GroupMember    │             │
                    ├─────────────────┤             ▼
                    │ group_id        │     ┌───────────────┐
                    │ user_id         │     │ BillSplit     │
                    │ role (owner/    │     ├───────────────┤
                    │   member)       │◄────│ bill_id       │
                    │ balance         │     │ user_id       │
                    │ joined_at       │     │ amount        │
                    └─────────────────┘     │ percentage    │
                                            │ is_paid       │
                                            │ paid_at       │
                                            └───────────────┘
```

### API Design (RESTful + WebSocket Events)

**REST Endpoints:**
```
POST   /api/groups                    → Create group
GET    /api/groups                    → List user's groups
POST   /api/groups/:id/members        → Invite member
DELETE /api/groups/:id/members/:uid   → Remove member

POST   /api/groups/:id/bills          → Create shared bill
GET    /api/groups/:id/bills          → List group bills
PATCH  /api/bills/:id/splits/:uid     → Update split status (mark paid)

GET    /api/groups/:id/settlements    → Get who owes whom
POST   /api/groups/:id/settle         → Mark settlement complete
```

**WebSocket Events:**
```
group:bill:created     → New bill in group
group:bill:updated     → Split amounts changed
group:payment:marked   → Someone marked their share paid
group:balance:updated  → Settlement recalculated
```

---

## File Structure

```
bill-snap/
├── mobile/                          # React Native app
│   ├── src/
│   │   ├── components/
│   │   │   ├── BillCard.tsx
│   │   │   ├── SplitEditor.tsx
│   │   │   ├── MemberList.tsx
│   │   │   ├── SettlementSummary.tsx
│   │   │   └── PaymentStatusBadge.tsx
│   │   ├── screens/
│   │   │   ├── GroupListScreen.tsx
│   │   │   ├── GroupDetailScreen.tsx
│   │   │   ├── CreateGroupScreen.tsx
│   │   │   ├── SharedBillScreen.tsx
│   │   │   ├── CreateSharedBillScreen.tsx
│   │   │   └── SettlementScreen.tsx
│   │   ├── navigation/
│   │   │   └── AppNavigator.tsx
│   │   ├── services/
│   │   │   ├── api.ts               # Axios instance
│   │   │   ├── groupService.ts
│   │   │   ├── billService.ts
│   │   │   └── socketService.ts      # Socket.IO client
│   │   ├── hooks/
│   │   │   ├── useGroups.ts
│   │   │   ├── useSharedBills.ts
│   │   │   └── useSettlements.ts
│   │   ├── store/
│   │   │   ├── slices/
│   │   │   │   ├── groupsSlice.ts
│   │   │   │   ├── billsSlice.ts
│   │   │   │   └── settlementsSlice.ts
│   │   │   └── store.ts
│   │   ├── types/
│   │   │   └── index.ts              # Shared TypeScript types
│   │   └── utils/
│   │       ├── splitCalculator.ts     # Split logic
│   │       └── settlementEngine.ts    # Debt simplification algorithm
│   └── package.json
│
├── server/                          # Node.js/Express API
│   ├── src/
│   │   ├── config/
│   │   │   └── database.ts           # pg Pool config
│   │   ├── controllers/
│   │   │   ├── groupController.ts
│   │   │   ├── billController.ts
│   │   │   └── settlementController.ts
│   │   ├── services/
│   │   │   ├── groupService.ts
│   │   │   ├── billService.ts
│   │   │   └── settlementService.ts
│   │   ├── repositories/
│   │   │   ├── groupRepository.ts
│   │   │   ├── billRepository.ts
│   │   │   └── splitRepository.ts
│   │   ├── middleware/
│   │   │   ├── auth.ts               # JWT verification
│   │   │   ├── groupAccess.ts        # Verify member of group
│   │   │   └── validate.ts           # Input validation
│   │   ├── socket/
│   │   │   ├── index.ts              # Socket.IO setup
│   │   │   └── handlers.ts           # Event handlers
│   │   ├── routes/
│   │   │   ├── index.ts
│   │   │   ├── groups.ts
│   │   │   ├── bills.ts
│   │   │   └── settlements.ts
│   │   ├── types/
│   │   │   └── index.ts
│   │   ├── utils/
│   │   │   ├── splitCalculator.ts
│   │   │   └── settlementEngine.ts
│   │   ├── db/
│   │   │   ├── migrations/
│   │   │   │   ├── 001_create_users.sql
│   │   │   │   ├── 002_create_groups.sql
│   │   │   │   ├── 003_create_group_members.sql
│   │   │   │   ├── 004_create_bills.sql
│   │   │   │   └── 005_create_bill_splits.sql
│   │   │   └── seeds/
│   │   │       └── seed.sql
│   │   └── app.ts
│   ├── package.json
│   └── tsconfig.json
│
└── docs/
    └── FR-29-collaboration-split.md
```

---

## Implementation Phases

### Phase 1: Data Foundation

**Goal:** Create database schema, migrations, and repository layer for groups, bills, and splits. Establish the core data model.

**Files to create/modify:**
- `server/src/db/migrations/001_create_users.sql` *(if not exists)*
- `server/src/db/migrations/002_create_groups.sql`
- `server/src/db/migrations/003_create_group_members.sql`
- `server/src/db/migrations/004_create_bills.sql`
- `server/src/db/migrations/005_create_bill_splits.sql`
- `server/src/repositories/groupRepository.ts`
- `server/src/repositories/billRepository.ts`
- `server/src/repositories/splitRepository.ts`
- `server/src/config/database.ts`

**Key decisions:**
- Use UUIDs for all primary keys (scales better than sequential IDs; avoids enumeration attacks)
- `bill_splits` table stores the *intent* (percentage or fixed amount) and the *actual* computed amount — this lets users change split method without losing historical data
- `group_members.balance` is a running tally updated via triggers or application logic; used for quick settlement queries
- Use soft deletes (`deleted_at`) on groups and bills for data recovery

**Verification:**
- Run migrations against a fresh database: `npm run migrate`
- Run `SELECT * FROM information_schema.tables WHERE table_schema = 'public'` — verify 5 tables exist
- Write a quick integration test: create user → create group → add member → assert member exists in group_members

---

### Phase 2: API & Business Logic

**Goal:** Build REST endpoints for group/bill CRUD and the settlement calculation engine. No UI yet.

**Files to create/modify:**
- `server/src/controllers/groupController.ts`
- `server/src/controllers/billController.ts`
- `server/src/controllers/settlementController.ts`
- `server/src/services/groupService.ts`
- `server/src/services/billService.ts`
- `server/src/services/settlementService.ts`
- `server/src/routes/groups.ts`
- `server/src/routes/bills.ts`
- `server/src/routes/settlements.ts`
- `server/src/middleware/auth.ts`
- `server/src/middleware/groupAccess.ts`
- `server/src/middleware/validate.ts`
- `server/src/utils/splitCalculator.ts`
- `server/src/utils/settlementEngine.ts`

**Key decisions:**
- **Split calculation logic** lives in `splitCalculator.ts`:
  ```typescript
  // Equal split
  function equalSplit(total: number, participants: string[]): Map<string, number> {
    const each = Math.round((total / participants.length) * 100) / 100; // 2 decimal places
    const remainder = Math.round((total - each * participants.length) * 100) / 100;
    const result = new Map(participants.map(p => [p, each]));
    // Add remainder to first person to avoid floating-point drift
    result.set(participants[0], result.get(participants[0]) + remainder);
    return result;
  }

  // Percentage split
  function percentageSplit(total: number, percentages: Map<string, number>): Map<string, number> {
    const result = new Map<string, number>();
    percentages.forEach((pct, userId) => {
      result.set(userId, Math.round(total * (pct / 100) * 100) / 100);
    });
    return result;
  }
  ```
- **Settlement engine** uses a greedy debt simplification algorithm to minimize transactions:
  ```typescript
  // Returns minimum transactions to settle all debts in a group
  function simplifyDebts(balances: Map<string, number>): Array<{from: string, to: string, amount: number}> {
    // Separate into creditors (positive balance) and debtors (negative)
    // Greedily match largest debtor to largest creditor
    // Returns array of transactions
  }
  ```
- **Authorization:** `groupAccess` middleware verifies the requesting user is a member before any operation. Owners can delete groups; members can only remove themselves.

**Verification:**
- Use Postman or `curl` to:
  1. Create a group → get group ID
  2. Add 3 members
  3. Create a bill with equal split → verify each split = total/3
  4. Create a bill with 50/30/20 split → verify amounts
  5. Mark one member's split as paid
  6. Call `/settlements` → verify correct "who owes whom" output

---

### Phase 3: Real-Time Layer

**Goal:** Add WebSocket support so group members receive live updates when bills are added or payments are marked.

**Files to create/modify:**
- `server/src/socket/index.ts`
- `server/src/socket/handlers.ts`
- `server/src/services/billService.ts` *(update to emit events)*
- `server/src/services/groupService.ts` *(update to emit events)*

**Key decisions:**
- Socket.IO room per group: `group:{groupId}` — when a user joins, they subscribe to their groups
- JWT auth on WebSocket handshake (verify token before connection)
- Emit events from service layer after DB commits, not from controllers:
  ```typescript
  // In billService.createSharedBill()
  const bill = await billRepository.create(data);
  io.to(`group:${groupId}`).emit('group:bill:created', bill);
  return bill;
  ```
- Fallback: clients can poll `/groups/:id` on app foreground (React Native AppState listener)

**Verification:**
- Connect two Socket.IO clients (e.g., Postman + Node script)
- Client A creates a bill in a group
- Verify Client B receives `group:bill:created` event within 500ms
- Verify payment mark triggers `group:balance:updated` on all members

---

### Phase 4: Mobile UI — Core Screens

**Goal:** Build React Native screens for group management and shared bill viewing. Connect to API.

**Files to create/modify:**
- `mobile/src/types/index.ts`
- `mobile/src/services/api.ts`
- `mobile/src/services/groupService.ts`
- `mobile/src/services/billService.ts`
- `mobile/src/hooks/useGroups.ts`
- `mobile/src/hooks/useSharedBills.ts`
- `mobile/src/screens/GroupListScreen.tsx`
- `mobile/src/screens/GroupDetailScreen.tsx`
- `mobile/src/screens/CreateGroupScreen.tsx`
- `mobile/src/components/GroupCard.tsx`
- `mobile/src/components/MemberList.tsx`
- `mobile/src/components/BillCard.tsx`
- `mobile/src/navigation/AppNavigator.tsx`

**Key decisions:**
- Use React Query (TanStack Query) for server state — handles caching, refetching, optimistic updates for payment marks
- Member invitation via shareable link with embedded invite token (no email/phone required for v1)
- Pull-to-refresh on all list screens
- Skeleton loaders during data fetch

**Verification:**
- Login as User A → create group "Weekend Trip" → add User B
- Login as User B on separate device → see "Weekend Trip" in group list
- User A creates a shared bill → User B sees it appear (real-time)

---

### Phase 5: Split Editor & Settlement UI

**Goal:** Full split configuration UI (equal, percentage, custom) and settlement summary screen.

**Files to create/modify:**
- `mobile/src/screens/CreateSharedBillScreen.tsx`
- `mobile/src/screens/SharedBillScreen.tsx`
- `mobile/src/screens/SettlementScreen.tsx`
- `mobile/src/components/SplitEditor.tsx`
- `mobile/src/components/SettlementSummary.tsx`
- `mobile/src/components/PaymentStatusBadge.tsx`
- `mobile/src/hooks/useSettlements.ts`
- `mobile/src/store/slices/settlementsSlice.ts`
- `mobile/src/utils/splitCalculator.ts`

**Key decisions:**
- **Split editor UX:** Three tabs — "Equal", "By Percentage", "Custom". Live preview of each person's amount as user adjusts.
- **Settlement screen** shows "You owe $X" or "You are owed $X" prominently, then a list of individual transactions needed to settle.
- **Mark as paid:** Optimistic update with rollback on failure. Visual feedback (checkmark animation).
- Currency formatting: use `Intl.NumberFormat` with user's locale

**SplitEditor snippet:**
```typescript
// SplitEditor.tsx
type SplitMode = 'equal' | 'percentage' | 'custom';

function SplitEditor({ mode, total, members, onSplitChange }: Props) {
  const [customAmounts, setCustomAmounts] = useState<Map<string, number>>(new Map());

  const splits = useMemo(() => {
    if (mode === 'equal') {
      return equalSplit(total, members.map(m => m.id));
    } else if (mode === 'percentage') {
      return percentageSplit(total, percentageMap); // from form state
    } else {
      return customAmounts;
    }
  }, [mode, total, customAmounts, percentageMap]);

  return (
    <View>
      {members.map(member => (
        <SplitRow
          key={member.id}
          member={member}
          amount={splits.get(member.id)}
          mode={mode}
          onCustomChange={(val) => handleCustomChange(member.id, val)}
        />
      ))}
      <Text>Total: ${total.toFixed(2)} | Assigned: ${assignedTotal.toFixed(2)}</Text>
    </View>
  );
}
```

**Verification:**
- Create bill with $100 total, 3 members → equal split shows $33.33, $33.33, $33.34
- Switch to percentage → set 50%, 30%, 20% → verify $50, $30, $20
- Switch to custom → manually enter $25, $25, $50 → verify validation (must sum to total)
- Settlement screen: User A paid for a $90 dinner with 3 people → verify it shows "User A is owed $60" and "You owe User A $30"

---

### Phase 6: Polish & Notifications

**Goal:** In-app notifications for group activity, loading states, error handling, empty states.

**Files to create/modify:**
- `mobile/src/services/socketService.ts`
- `mobile/src/screens/` *(update all to handle socket events)*
- `mobile/src/components/NotificationBanner.tsx`
- `server/src/services/groupService.ts` *(notification creation)*
- `server/src/services/billService.ts` *(notification creation)*

**Key decisions:**
- In-app notification store (SQLite on device) — not push notifications for v1 (requires Firebase setup)
- Socket events trigger notification entries:
  ```typescript
  // On receiving group:payment:marked
  socket.on('group:payment:marked', ({ billTitle, payerName, amount }) => {
    addNotification({
      title: 'Payment Received',
      body: `${payerName} paid ${formatCurrency(amount)} for ${billTitle}`,
      groupId,
    });
  });
  ```
- Deep linking: tapping notification navigates to the relevant bill/group

**Verification:**
- User A marks their split paid → User B gets in-app notification within 2 seconds
- Offline scenario: user opens app after 2 days → notifications populated from `/notifications` endpoint on login
- Error handling: API failure shows toast with retry option

---

## Key Technical Decisions

| Decision | Choice | Rationale |
|----------|--------|-----------|
| **Database** | PostgreSQL | Complex relational queries (balances, settlements) are cleaner in SQL. ACID compliance critical for financial data. |
| **ORM** | Raw SQL + pg + repository pattern | Avoids ORM overhead for complex split calculations. Easier to tune queries. |
| **Real-time** | Socket.IO | Battle-tested, works well with Redis adapter for horizontal scaling. |
| **Split precision** | 2 decimal places, round half-up | Standard for currency. Server does all math; client only displays. |
| **Settlement algorithm** | Greedy debt simplification | O(n log n) — sufficient for typical group sizes (<20 people). NP-hard "optimal" settlement is overkill. |
| **Auth** | JWT with short-lived access tokens (15min) + refresh tokens (7 days) | Stateless; refresh tokens stored in HTTP-only cookie or secure storage on mobile. |
| **Idempotency** | UUID-based invite links with expiry | Prevents duplicate joins if user clicks invite twice. |
| **Mobile state** | React Query + Zustand | React Query for server state, Zustand for UI state (selected group, modal visibility). |

---

## Verification Plan

### Unit Tests
```bash
# Server-side
npm test -- --testPathPattern=splitCalculator
npm test -- --testPathPattern=settlementEngine

# Mobile (if logic extracted)
npm test -- splitCalculator
```

**Test cases for `splitCalculator`:**
- Equal split: $100 / 3 = $33.33, $33.33, $33.34
- Percentage: $100 at 50/30/20 = $50, $30, $20
- Custom: [50, 30, 20] = [50, 30, 20]
- Custom that doesn't sum to total → error thrown

**Test cases for `settlementEngine`:**
- Two people: A paid $100, B owes $50 → output: B → A $50
- Three people, net balances: A +$50, B -$30, C -$20 → B → A $30, C → A $20

### Integration Tests (Server)
```bash
# Using Jest + Supertest
POST /api/groups                    → 201, returns groupId
POST /api/groups/:id/members        → 201, member added
POST /api/groups/:id/bills          → 201, splits created
PATCH /api/bills/:id/splits/:uid     → 200, is_paid = true
GET  /api/groups/:id/settlements    → 200, correct balances
```

### End-to-End Flow (Manual)
1. **Setup:** Create 3 test users (Alice, Bob, Charlie) via seed data or UI
2. **Group creation:** Alice creates "Dinner Club" group, gets invite link
3. **Join:** Bob and Charlie join via invite link
4. **Create bill:** Alice creates "Friday Dinner" for $150, splits equally
5. **Verify splits:** Each sees $50 owed
6. **Mark payment:** Bob marks his $50 paid → Alice and Charlie see updated status
7. **Settlement:** After 3 of 3 paid, settlement screen shows $0 owed (or if Alice paid entire bill upfront, shows Bob+Charlie each owe Alice $50)
8. **Real-time:** Bob marks paid from his device → Alice sees update without refreshing

### Load Testing (Optional for v1)
- 100 concurrent users in same group creating bills
- Socket.IO message delivery < 200ms under load

---

## Summary

This plan breaks FR-29 into 6 phases, from database foundation through real-time collaboration to mobile UI polish. The split logic and settlement engine are the core algorithmic work; everything else is standard CRUD + WebSocket wiring. A skilled team of 2–3 could implement this in **6–8 weeks** (Phases 1–2: 2 weeks, Phase 3: 1 week, Phase 4: 2 weeks, Phase 5: 1 week, Phase 6: 1 week including bug fixes).

What would you like to drill into further — the settlement algorithm, the API contract, or the mobile architecture?