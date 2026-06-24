
# Implementation Plan — FR-18: Notifications Badge on Mobile App Icon

## Context

The notifications badge feature displays an unread count overlay on the mobile app's home screen icon, allowing users to see pending notifications without opening the app. This eliminates friction for time-sensitive updates and reduces missed communications — a common pain point identified in user feedback. The feature requires coordination between push notification infrastructure, local state management, and cross-platform badge APIs.

---

## Architecture

### High-Level Design

```
┌─────────────────────────────────────────────────────────────────┐
│                        Push Notification Flow                    │
└─────────────────────────────────────────────────────────────────┘
                                │
        ┌───────────────────────┼───────────────────────┐
        ▼                       ▼                       ▼
┌───────────────┐     ┌─────────────────┐     ┌─────────────────┐
│  APNs (iOS)   │     │  FCM (Android)  │     │  Backend API    │
│  / FCM        │     │                 │     │  / WebSocket    │
└───────┬───────┘     └────────┬────────┘     └────────┬────────┘
        │                       │                       │
        ▼                       ▼                       ▼
┌─────────────────────────────────────────────────────────────────┐
│                    Mobile Client SDK Layer                       │
│  ┌─────────────┐  ┌─────────────┐  ┌─────────────────────────┐  │
│  │ Badge API   │  │ Notif Store │  │ Sync Service (counts)   │  │
│  │ (Expo/Nat.) │  │ (MMKV/SQL)  │  │                         │  │
│  └─────────────┘  └─────────────┘  └─────────────────────────┘  │
└─────────────────────────────────────────────────────────────────┘
```

### Technology Choices

| Component | Choice | Rationale |
|-----------|--------|-----------|
| **iOS Badge** | `UIApplication.shared.applicationIconBadgeNumber` via native bridge or `expo-notifications` | Apple's native badge API |
| **Android Badge** | `ShortcutBadger` library or OEM-specific APIs | Android has no unified badge standard; multiple OEMs require compatibility layer |
| **Cross-platform** | `expo-application` + `expo-notifications` (SDK 52+) | Unified API for managed workflow; fallback to native modules for bare workflow |
| **Local Storage** | `MMKV` for badge count caching | Fast synchronous reads for app launch |
| **Backend Sync** | REST API endpoint + WebSocket for real-time updates | Fallback polling + push-based updates |

---

## File Structure

For a typical React Native project with a Node.js backend:

```
mobile-app/
├── src/
│   ├── features/
│   │   └── notifications/
│   │       ├── components/
│   │       │   ├── NotificationBadge.tsx          # Badge display logic
│   │       │   └── NotificationList.tsx          # List view of notifications
│   │       ├── hooks/
│   │       │   ├── useBadgeCount.ts               # Badge state management
│   │       │   └── useNotificationListener.ts     # Push notification handler
│   │       ├── services/
│   │       │   ├── BadgeService.ts                # Platform-specific badge API
│   │       │   └── NotificationSyncService.ts     # Backend sync logic
│   │       ├── store/
│   │       │   └── notificationStore.ts           # Zustand/Redux slice
│   │       ├── types/
│   │       │   └── notification.types.ts
│   │       └── utils/
│   │           └── badgeUtils.ts                  # Count capping, formatting
│   ├── api/
│   │   ├── client.ts
│   │   └── endpoints/
│   │       ├── notifications.ts
│   │       └── badgeSync.ts
│   └── app/
│       └── (tabs)/
│           └── notifications/
│               └── page.tsx
├── ios/
│   └── LocalPods/
│       └── BadgeManager/                          # Custom native badge module
│           ├── BadgeManager.podspec
│           ├── BadgeManager.swift
│           └── BadgeManagerModule.m               # TurboModule bridge
├── android/
│   └── app/src/main/java/.../badge/
│       ├── BadgeModule.kt                         # React Native bridge
│       └── BadgePackage.kt
├── app.json                                       # Expo config for permissions
└── package.json

backend/
├── src/
│   ├── modules/
│   │   └── notifications/
│   │       ├── notifications.controller.ts
│   │       ├── notifications.service.ts
│   │       ├── notifications.gateway.ts           # WebSocket gateway
│   │       ├── schemas/
│   │       │   └── notification.schema.ts
│   │       └── dto/
│   │           ├── create-notification.dto.ts
│   │           └── badge-response.dto.ts
│   └── common/
│       └── redis/
│           └── badgeCache.service.ts              # Redis for fast badge lookups
└── package.json
```

---

## Implementation Phases

### ## Phase 1: Badge Infrastructure (Foundation)

**Goal** — Establish platform-specific badge APIs and local caching layer. This phase ensures we can read/write the badge count on both iOS and Android, regardless of push notification state.

**Files to create/modify:**
- `src/features/notifications/utils/badgeUtils.ts`
- `src/features/notifications/services/BadgeService.ts`
- `src/features/notifications/hooks/useBadgeCount.ts`
- `src/features/notifications/store/notificationStore.ts`
- `android/app/src/main/java/.../badge/BadgeModule.kt`
- `ios/LocalPods/BadgeManager/BadgeManager.swift`

**Key decisions:**
- **Count cap at 99**: Display "99+" for counts exceeding 99 (industry convention).
- **Zero-pad display**: Never show "0" badge; remove it entirely.
- **Native-first approach**: Use native platform APIs directly rather than JS-only simulation.

**Implementation:**

```typescript
// src/features/notifications/utils/badgeUtils.ts
export const MAX_BADGE_DISPLAY = 99;

export function formatBadgeCount(count: number): string | null {
  if (count <= 0) return null;
  if (count > MAX_BADGE_DISPLAY) return `${MAX_BADGE_DISPLAY}+`;
  return String(count);
}

export function shouldShowBadge(count: number): boolean {
  return count > 0 && count <= MAX_BADGE_DISPLAY;
}
```

```typescript
// src/features/notifications/services/BadgeService.ts
import { Platform } from 'react-native';
import { formatBadgeCount } from '../utils/badgeUtils';

interface IBadgeService {
  setBadgeCount(count: number): Promise<void>;
  getBadgeCount(): Promise<number>;
  clearBadge(): Promise<void>;
}

class BadgeService implements IBadgeService {
  async setBadgeCount(count: number): Promise<void> {
    const displayCount = count > 99 ? 99 : count; // Native accepts up to 99
    
    if (Platform.OS === 'ios') {
      // Uses native TurboModule or Bridge
      await NativeModules.BadgeManager.setBadgeCount(displayCount);
    } else if (Platform.OS === 'android') {
      // ShortcutBadger implementation
      await NativeModules.BadgeManager.setBadgeCount(displayCount);
    }
  }

  async clearBadge(): Promise<void> {
    await this.setBadgeCount(0);
  }

  async getBadgeCount(): Promise<number> {
    if (Platform.OS === 'ios') {
      return await NativeModules.BadgeManager.getBadgeCount();
    }
    return 0; // Android doesn't support reading badge count
  }
}

export const badgeService = new BadgeService();
```

```kotlin
// android/app/src/main/java/.../badge/BadgeModule.kt
package com.app.badge

import com.facebook.react.bridge.Promise
import com.facebook.react.bridge.ReactApplicationContext
import com.facebook.react.bridge.ReactContextBaseJavaModule
import com.facebook.react.bridge.ReactMethod
import me.leolin.shortcutbadger.ShortcutBadger

class BadgeModule(reactContext: ReactApplicationContext) : 
    ReactContextBaseJavaModule(reactContext) {

    override fun getName() = "BadgeManager"

    @ReactMethod
    fun setBadgeCount(count: Int, promise: Promise) {
        try {
            ShortcutBadger.applyCount(reactApplicationContext, count)
            promise.resolve(true)
        } catch (e: Exception) {
            promise.reject("BADGE_ERROR", e.message)
        }
    }
}
```

**Verification:**
- Unit test: `formatBadgeCount()` correctly handles edge cases (0, 99, 100, negative)
- Manual test: App icon shows correct badge count after `adb shell am set-debug-app` or simulator test

---

### ## Phase 2: Notification Store & State Management

**Goal** — Create a reactive state layer that holds the unread count and syncs with local storage. This provides the data source for badge updates across the app.

**Files to create/modify:**
- `src/features/notifications/store/notificationStore.ts`
- `src/features/notifications/types/notification.types.ts`
- `src/features/notifications/hooks/useBadgeCount.ts`

**Key decisions:**
- **Zustand over Redux**: Lighter weight; no boilerplate; built-in persistence middleware.
- **Persist badge count to MMKV**: Ensures badge shows correct count on cold launch before API sync completes.
- **Optimistic updates**: Update local state immediately; reconcile with server on sync.

**Implementation:**

```typescript
// src/features/notifications/types/notification.types.ts
export interface Notification {
  id: string;
  type: 'alert' | 'reminder' | 'system';
  title: string;
  body: string;
  read: boolean;
  createdAt: string;
  metadata?: Record<string, unknown>;
}

export interface BadgeState {
  unreadCount: number;
  lastSyncedAt: string | null;
  isLoading: boolean;
  error: string | null;
}
```

```typescript
// src/features/notifications/store/notificationStore.ts
import { create } from 'zustand';
import { persist, createJSONStorage } from 'zustand/middleware';
import { MMKV } from 'react-native-mmkv';

const storage = new MMKV({ id: 'notification-storage' });

const mmkvStorage = {
  getItem: (name: string) => storage.getString(name) ?? null,
  setItem: (name: string, value: string) => storage.set(name, value),
  removeItem: (name: string) => storage.delete(name),
};

interface NotificationState {
  unreadCount: number;
  lastSyncedAt: string | null;
  isLoading: boolean;
  
  // Actions
  incrementUnread: (delta?: number) => void;
  decrementUnread: (delta?: number) => void;
  setUnreadCount: (count: number) => void;
  markAsSynced: () => void;
  reset: () => void;
}

export const useNotificationStore = create<NotificationState>()(
  persist(
    (set) => ({
      unreadCount: 0,
      lastSyncedAt: null,
      isLoading: false,

      incrementUnread: (delta = 1) =>
        set((state) => ({ 
          unreadCount: state.unreadCount + delta,
          lastSyncedAt: null, // Mark as needing sync
        })),

      decrementUnread: (delta = 1) =>
        set((state) => ({
          unreadCount: Math.max(0, state.unreadCount - delta),
        })),

      setUnreadCount: (count) =>
        set({ unreadCount: Math.max(0, count), lastSyncedAt: new Date().toISOString() }),

      markAsSynced: () =>
        set({ lastSyncedAt: new Date().toISOString() }),

      reset: () => set({ unreadCount: 0, lastSyncedAt: null }),
    }),
    {
      name: 'notification-state',
      storage: createJSONStorage(() => mmkvStorage),
      partialize: (state) => ({ unreadCount: state.unreadCount }),
    }
  )
);
```

```typescript
// src/features/notifications/hooks/useBadgeCount.ts
import { useEffect, useRef } from 'react';
import { useNotificationStore } from '../store/notificationStore';
import { badgeService } from '../services/BadgeService';

export function useBadgeCount() {
  const { unreadCount, setUnreadCount } = useNotificationStore();
  const isSyncingRef = useRef(false);

  // Sync badge count to system UI
  useEffect(() => {
    badgeService.setBadgeCount(unreadCount);
  }, [unreadCount]);

  // Sync with backend on app foreground
  useEffect(() => {
    const syncBadgeCount = async () => {
      if (isSyncingRef.current) return;
      isSyncingRef.current = true;

      try {
        const { unreadCount } = await fetchUnreadCount();
        setUnreadCount(unreadCount);
      } catch (error) {
        console.warn('Badge sync failed:', error);
      } finally {
        isSyncingRef.current = false;
      }
    };

    syncBadgeCount();
  }, []);

  return { unreadCount };
}
```

**Verification:**
- Cold launch app: Badge shows persisted count immediately (no flash)
- Clear unread: Badge disappears from icon
- State update: `unreadCount` increments in DevTools store inspector

---

### ## Phase 3: Push Notification Integration

**Goal** — Wire push notification reception to badge updates. When a push arrives or user reads a notification, the badge reflects the current unread count.

**Files to create/modify:**
- `src/features/notifications/hooks/useNotificationListener.ts`
- `src/features/notifications/services/NotificationSyncService.ts`
- `src/app/_layout.tsx` (register listeners)
- `AppDelegate.swift` (iOS push setup)
- `MainApplication.kt` (Android FCM setup)

**Key decisions:**
- **Increment badge on new push**: Server sends `content-available: 1` for silent pushes; we update badge without showing alert.
- **Decrement on read**: Marking notification as read locally AND sending ACK to server.
- **Clear on mark-all-read**: Single API call clears all unread and updates badge.

**Implementation:**

```typescript
// src/features/notifications/hooks/useNotificationListener.ts
import { useEffect } from 'react';
import * as Notifications from 'expo-notifications';
import { useNotificationStore } from '../store/notificationStore';
import { notificationSyncService } from '../services/NotificationSyncService';

// Configure handler for foreground notifications
Notifications.setNotificationHandler({
  handleNotification: async (notification) => {
    // Show notification if app is in foreground
    return { shouldShowAlert: true, shouldPlaySound: true };
  },
  handleSuccessHook: async (notificationId) => {
    // Silent push received — increment badge
    const { incrementUnread } = useNotificationStore.getState();
    incrementUnread();
    return notificationId;
  },
});

export function useNotificationListener() {
  const { incrementUnread, decrementUnread } = useNotificationStore();

  useEffect(() => {
    const responseListener = Notifications.addNotificationReceivedResponseListener(
      (response) => {
        // User tapped notification — navigate and mark as read
        const notificationId = response.notification.request.identifier;
        handleNotificationTap(notificationId);
      }
    );

    const receivedListener = Notifications.addNotificationReceivedListener(
      (notification) => {
        // Foreground notification received
        if (notification.request.content.data?.incrementBadge) {
          incrementUnread();
        }
      }
    );

    return () => {
      Notifications.removeNotificationSubscription(responseListener);
      Notifications.removeNotificationSubscription(receivedListener);
    };
  }, []);

  async function handleNotificationTap(notificationId: string) {
    // Mark as read on backend
    await notificationSyncService.markAsRead(notificationId);
    decrementUnread();
  }
}
```

```typescript
// src/features/notifications/services/NotificationSyncService.ts
import { apiClient } from '../../api/client';
import { useNotificationStore } from '../store/notificationStore';

class NotificationSyncService {
  async markAsRead(notificationId: string): Promise<void> {
    await apiClient.patch(`/notifications/${notificationId}/read`);
    useNotificationStore.getState().decrementUnread();
  }

  async markAllAsRead(): Promise<void> {
    await apiClient.post('/notifications/read-all');
    useNotificationStore.getState().setUnreadCount(0);
  }

  async fetchUnreadCount(): Promise<{ unreadCount: number }> {
    const response = await apiClient.get<{ unreadCount: number }>('/notifications/badge');
    return response.data;
  }
}

export const notificationSyncService = new NotificationSyncService();
```

**iOS Setup (AppDelegate.swift):**
```swift
// iOS 14+: Use the new notification center delegate
UNUserNotificationCenter.current().delegate = self

func application(
  _ application: UIApplication,
  didReceiveRemoteNotification userInfo: [AnyHashable: Any],
  fetchCompletionHandler completionHandler: @escaping (UIBackgroundFetchResult) -> Void
) {
  if let incrementBadge = userInfo["incrementBadge"] as? Bool, incrementBadge {
    let currentCount = UIApplication.shared.applicationIconBadgeNumber
    UIApplication.shared.applicationIconBadgeNumber = currentCount + 1
  }
  completionHandler(.newData)
}
```

**Verification:**
- Send test push: Badge increments by 1
- Open notification: Badge decrements
- Mark all read: Badge clears to 0
- Background push: Badge updates without notification alert

---

### ## Phase 4: Backend API Endpoints

**Goal** — Expose endpoints for badge count retrieval and modification. Support real-time updates via WebSocket for multi-device sync.

**Files to create/modify:**
- `backend/src/modules/notifications/notifications.controller.ts`
- `backend/src/modules/notifications/notifications.service.ts`
- `backend/src/modules/notifications/notifications.gateway.ts`
- `backend/src/modules/notifications/dto/badge-response.dto.ts`
- `backend/src/common/redis/badgeCache.service.ts`

**Key decisions:**
- **Redis cache for badge counts**: Sub-millisecond reads; avoid DB hit on every app launch.
- **WebSocket for real-time sync**: Users on multiple devices see badge update immediately.
- **Event-driven badge updates**: When notification created/marked-read, publish event to Redis pub/sub.

**Implementation:**

```typescript
// backend/src/modules/notifications/dto/badge-response.dto.ts
import { ApiProperty } from '@nestjs/swagger';

export class BadgeResponseDto {
  @ApiProperty({ example: 5, description: 'Unread notification count' })
  unreadCount: number;

  @ApiProperty({ example: '2024-01-15T10:30:00Z' })
  updatedAt: string;
}
```

```typescript
// backend/src/modules/notifications/notifications.service.ts
@Injectable()
export class NotificationsService {
  constructor(
    @InjectRepository(Notification) private repo: Repository<Notification>,
    private badgeCache: BadgeCacheService,
    private notificationsGateway: NotificationsGateway,
  ) {}

  async getUnreadCount(userId: string): Promise<number> {
    // Try cache first
    const cached = await this.badgeCache.getBadgeCount(userId);
    if (cached !== null) return cached;

    // Fallback to DB
    const count = await this.repo.count({
      where: { userId, read: false },
    });

    await this.badgeCache.setBadgeCount(userId, count);
    return count;
  }

  async markAsRead(userId: string, notificationId: string): Promise<void> {
    await this.repo.update(
      { id: notificationId, userId },
      { read: true, readAt: new Date() }
    );

    const newCount = await this.getUnreadCount(userId);
    await this.badgeCache.setBadgeCount(userId, newCount);
    
    // Emit to all user's devices via WebSocket
    this.notificationsGateway.emitBadgeUpdate(userId, newCount);
  }

  async createNotification(userId: string, dto: CreateNotificationDto): Promise<Notification> {
    const notification = this.repo.create({ ...dto, userId });
    await this.repo.save(notification);

    const newCount = await this.getUnreadCount(userId);
    await this.badgeCache.setBadgeCount(userId, newCount);
    
    this.notificationsGateway.emitBadgeUpdate(userId, newCount);
    
    return notification;
  }
}
```

```typescript
// backend/src/modules/notifications/notifications.gateway.ts
@WebSocketGateway({ namespace: '/notifications' })
export class NotificationsGateway {
  @WebSocketServer() server: Server;

  emitBadgeUpdate(userId: string, unreadCount: number) {
    this.server.to(`user:${userId}`).emit('badge:update', { unreadCount });
  }
}
```

**Verification:**
- `GET /notifications/badge` returns correct count
- Mark read via `PATCH /notifications/:id/read` — count decrements
- WebSocket event received on second device when first device reads notification

---

### ## Phase 5: Real-Time Sync (WebSocket)

**Goal** — Enable instant badge sync across multiple devices when a user reads a notification on one device.

**Files to create/modify:**
- `src/features/notifications/services/NotificationSyncService.ts` (add WS client)
- `src/app/_layout.tsx` (initialize socket connection)
- `backend/src/modules/notifications/notifications.gateway.ts` (refine room joining)

**Key decisions:**
- **Authenticate WebSocket with JWT**: Validate user identity on connection.
- **Reconnect with exponential backoff**: Handle network interruptions gracefully.
- **Single source of truth**: Backend is always authoritative; client state syncs to it.

**Implementation:**

```typescript
// src/features/notifications/services/NotificationSyncService.ts
import { io, Socket } from 'socket.io-client';
import { useNotificationStore } from '../store/notificationStore';
import { getAuthToken } from '../../auth/tokenStorage';

let socket: Socket | null = null;

export function initializeBadgeSocket(userId: string) {
  if (socket?.connected) return;

  socket = io(`${API_BASE_URL}/notifications`, {
    auth: { token: getAuthToken() },
    transports: ['websocket'],
    reconnection: true,
    reconnectionDelay: 1000,
    reconnectionDelayMax: 5000,
    reconnectionAttempts: 10,
  });

  socket.on('badge:update', ({ unreadCount }) => {
    useNotificationStore.getState().setUnreadCount(unreadCount);
  });

  socket.on('connect', () => {
    socket?.emit('join:user', userId);
  });
}

export function disconnectBadgeSocket() {
  socket?.disconnect();
  socket = null;
}
```

**Verification:**
- Open app on Device A and Device B (same user)
- Mark notification read on Device A
- Badge updates on Device B within 500ms without refresh

---

### ## Phase 6: Polish & Error Handling

**Goal** — Ensure robustness under edge cases: network failures, stale data, concurrent updates.

**Files to create/modify:**
- `src/features/notifications/hooks/useBadgeCount.ts` (add retry logic)
- `src/features/notifications/utils/badgeUtils.ts` (edge case coverage)
- Add E2E tests
- Update monitoring/analytics

**Key decisions:**
- **Offline queue**: If user reads notifications while offline, queue the action and replay on reconnect.
- **Periodic sync**: Background fetch every 15 minutes as fallback.
- **Metrics**: Track badge-to-open conversion and sync failure rate.

**Implementation:**

```typescript
// src/features/notifications/hooks/useBadgeCount.ts
import { useEffect, useRef, useCallback } from 'react';
import { AppState, AppStateStatus } from 'react-native';
import { useNotificationStore } from '../store/notificationStore';
import { badgeService } from '../services/BadgeService';
import { notificationSyncService } from '../services/NotificationSyncService';

const BACKGROUND_SYNC_INTERVAL = 15 * 60 * 1000; // 15 minutes

export function useBadgeCount() {
  const { unreadCount, setUnreadCount, markAsSynced } = useNotificationStore();
  const syncIntervalRef = useRef<NodeJS.Timeout>();
  const retryCountRef = useRef(0);
  const MAX_RETRIES = 3;

  // Set system badge
  useEffect(() => {
    badgeService.setBadgeCount(unreadCount);
  }, [unreadCount]);

  // Foreground sync
  useEffect(() => {
    const handleAppStateChange = async (nextState: AppStateStatus) => {
      if (nextState === 'active') {
        await syncWithRetry();
      }
    };

    const subscription = AppState.addEventListener('change', handleAppStateChange);
    return () => subscription.remove();
  }, []);

  // Periodic background sync
  useEffect(() => {
    syncIntervalRef.current = setInterval(syncWithRetry, BACKGROUND_SYNC_INTERVAL);
    return () => clearInterval(syncIntervalRef.current);
  }, []);

  const syncWithRetry = useCallback(async () => {
    try {
      const { unreadCount } = await notificationSyncService.fetchUnreadCount();
      setUnreadCount(unreadCount);
      markAsSynced();
      retryCountRef.current = 0;
    } catch (error) {
      if (retryCountRef.current < MAX_RETRIES) {
        retryCountRef.current++;
        console.warn(`Badge sync failed, retry ${retryCountRef.current}/${MAX_RETRIES}`);
      }
    }
  }, []);

  return { unreadCount };
}
```

---

## Key Technical Decisions

| Decision | Choice | Rationale |
|----------|--------|-----------|
| **Native badge APIs** | iOS: `applicationIconBadgeNumber`, Android: `ShortcutBadger` | Required for actual system-level badge; JS-only would only show in-app |
| **ShortCutBadger** | Android compatibility layer | 26+ launchers supported; handles OEM fragmentation |
| **MMKV for persistence** | `react-native-mmkv` | Synchronous reads prevent badge flash on cold launch |
| **Zustand over Redux** | Zustand + `persist` middleware | 3KB vs 14KB; no action creators; simpler persistence |
| **WebSocket over polling** | Socket.IO | Real-time badge updates across devices; automatic reconnection |
| **Redis badge cache** | Backend-side caching | Avoid DB query on every app launch; sub-ms latency |
| **Count cap at 99+** | Industry standard | Screen real estate; consistent with iOS/messaging apps |
| **Push + badge decoupling** | Handle badge via state, not just push payload | Badge updates on read actions that don't trigger push |

---

## Verification Plan

### Unit Tests
```typescript
// __tests__/features/notifications/badgeUtils.test.ts
describe('formatBadgeCount', () => {
  it('returns null for 0', () => {
    expect(formatBadgeCount(0)).toBeNull();
  });

  it('returns null for negative numbers', () => {
    expect(formatBadgeCount(-5)).toBeNull();
  });

  it('returns string for positive numbers ≤ 99', () => {
    expect(formatBadgeCount(42)).toBe('42');
  });

  it('returns 99+ for counts over 99', () => {
    expect(formatBadgeCount(100)).toBe('99+');
    expect(formatBadgeCount(1000)).toBe('99+');
  });
});
```

### Integration Tests
1. **Push → Badge Increment**: Send test push via APNs/FCM console; verify badge increments
2. **Read → Badge Decrement**: Tap notification; verify badge decrements and API called
3. **Mark All Read**: Call endpoint; verify badge clears
4. **Multi-device Sync**: Mark read on device A; verify device B badge updates via WebSocket
5. **Cold Launch**: Kill app; reopen; verify persisted badge count displays immediately

### E2E Test Scenario (Detox)
```typescript
// e2e/notifications/badge.spec.ts
describe('Notification Badge', () => {
  it('shows badge on unread notifications', async () => {
    // Send test notification via API
    await api.createNotification(userId, { title: 'Test', body: 'Badge test' });
    
    // App should show badge
    await expect(element(by.text('1'))).toBeVisible();
  });

  it('clears badge when all notifications read', async () => {
    await element(by.id('notification-item')).tap();
    await element(by.text('Mark all as read')).tap();
    
    // Badge should be gone
    await expect(element(by.id('app-icon'))).toHaveBadge(0);
  });
});
```

### Manual QA Checklist
- [ ] iOS 16+: Badge displays and clears correctly
- [ ] Android 13+: Badge displays on home screen (Samsung, Pixel, OnePlus tested)
- [ ] Offline scenario: Badge persists, syncs on reconnect
- [ ] Network interruption: Exponential backoff retry works
- [ ] VoiceOver/TalkBack: Badge count announced correctly

---

What are you working on — is this for a specific platform (iOS only, Android only, cross-platform) or tech stack? That'll help me drill deeper into any particular phase. 🙂