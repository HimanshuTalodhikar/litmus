# Implementation Plan — FR-99: Dark Mode for Dashboard

## Context

**Feature:** Add a toggleable dark mode to the dashboard, with persistence across sessions and respect for the user's OS-level preference on first visit.

**Why it matters:**
- User-requested quality-of-life improvement; reduces eye strain for users on the platform for long sessions.
- Aligns the dashboard with the rest of the product surface (marketing site and docs went dark in Q2).
- Accessibility benefit: better contrast options for low-vision users when paired with proper WCAG-AA contrast tokens.

**Priority note:** The score (25/100) suggests this is below the typical P0/P1 cut-line. I'd recommend parking this behind higher-priority work or scoping to a **Phase-1 "lightweight" cut** (system preference + CSS variables only, no toggle UI) and deferring the manual toggle + persistence to a follow-up.

---

## Architecture

**Approach:** CSS custom properties (variables) + a `data-theme` attribute on `<html>`, with a small JS controller to apply theme and persist choice.

**Decisions:**
- **CSS variables over Tailwind dark variants** — Works whether or not the project uses Tailwind; one source of truth for color tokens.
- **`data-theme` attribute over `.dark` class** — More semantic (`data-theme="dark"` reads better in DevTools), avoids class-name collisions with utility frameworks.
- **System preference via `prefers-color-scheme`** — Honor OS setting on first load before any user choice exists (FOUC mitigation via inline script in `<head>`).
- **localStorage for persistence** — Simple, sufficient for a single-user preference; no backend round-trip.
- **No theme provider library** (no `next-themes`, etc.) — Keeps the bundle small; ~40 lines of vanilla TS covers it.

**System design:**

```
┌─────────────────────────────────────────────┐
│  <head> inline script                       │
│  - reads localStorage / prefers-color-scheme│
│  - sets documentElement.dataset.theme       │
│  (runs before <body> to prevent FOUC)       │
└─────────────────────────────────────────────┘
                      ↓
┌─────────────────────────────────────────────┐
│  src/styles/tokens.css                      │
│  - :root { --bg: #fff; --fg: #111; ... }    │
│  - [data-theme="dark"] { --bg: #0a0a0a; ... }│
└─────────────────────────────────────────────┘
                      ↓
┌─────────────────────────────────────────────┐
│  src/theme/ThemeToggle.tsx                  │
│  - reads/writes localStorage                │
│  - mutates documentElement.dataset.theme    │
│  - fires CustomEvent for listeners          │
└─────────────────────────────────────────────┘
```

---

## File Structure

```
src/
├── styles/
│   ├── tokens.css                  # NEW — color/spacing tokens, light + dark
│   └── global.css                  # MODIFY — import tokens, remove hardcoded colors
├── theme/
│   ├── ThemeProvider.tsx           # NEW — React context, sync with DOM
│   ├── useTheme.ts                 # NEW — hook: { theme, setTheme, toggle }
│   ├── ThemeToggle.tsx             # NEW — UI control (sun/moon icon button)
│   └── themes.ts                   # NEW — type + constants ('light' | 'dark' | 'system')
├── components/
│   └── layout/
│       ├── Header.tsx              # MODIFY — mount <ThemeToggle /> in header
│       └── Header.module.css       # MODIFY — use var() for bg/border
├── pages/
│   └── _document.tsx               # MODIFY — inline anti-FOUC script in <head>  (Next.js)
│   └── _app.tsx                    # MODIFY — wrap with <ThemeProvider />           (Next.js)
│       OR
│   └── main.tsx                    # MODIFY — wrap App with <ThemeProvider />       (Vite/React)
└── index.html                      # MODIFY — inline anti-FOUC script (non-Next)

docs/
└── theming.md                      # NEW — how to add a new themed component
```

---

## Implementation Phases

### ## Phase 1: Token Foundation (CSS Variables)

**Goal:** Establish a single source of truth for color tokens, refactor existing hardcoded colors to consume them. Land dark palette. **No toggle UI yet — theme is forced to dark via `[data-theme="dark"]` on `<html>` for QA.**

**Files to create/modify:**
- `src/styles/tokens.css` (new)
- `src/styles/global.css` (modify — import tokens, remove literals)
- `src/components/layout/Header.module.css` (modify — use `var(--color-bg-elevated)`, etc.)
- All other `.module.css` and inline styles (audit & migrate)

**Key decisions:**
- Token naming: semantic, not literal — `--color-bg-base`, `--color-bg-elevated`, `--color-fg-primary`, `--color-fg-muted`, `--color-border`, `--color-accent`. Avoid `--color-white` / `--color-black`.
- Contrast target: WCAG AA (4.5:1 for body text, 3:1 for large text and UI components).
- Dark palette: not pure `#000`; use `#0a0a0a` base with `#171717` elevated surfaces to preserve depth.

**Snippet — `src/styles/tokens.css`:**
```css
:root {
  --color-bg-base: #ffffff;
  --color-bg-elevated: #f8f8f8;
  --color-fg-primary: #111111;
  --color-fg-muted: #555555;
  --color-border: #e5e5e5;
  --color-accent: #2563eb;

  --shadow-sm: 0 1px 2px rgba(0, 0, 0, 0.06);
}

[data-theme="dark"] {
  --color-bg-base: #0a0a0a;
  --color-bg-elevated: #171717;
  --color-fg-primary: #f5f5f5;
  --color-fg-muted: #a3a3a3;
  --color-border: #2a2a2a;
  --color-accent: #60a5fa;

  --shadow-sm: 0 1px 2px rgba(0, 0, 0, 0.4);
}
```

**Verification:**
- [ ] Temporarily add `data-theme="dark"` to `<html>` in DevTools → entire dashboard re-themes.
- [ ] Run a contrast checker (e.g. axe DevTools) on key screens in both themes.
- [ ] `grep -rE "#[0-9a-fA-F]{3,6}" src/ --include="*.css" --include="*.tsx"` shows no stray hex literals in component files (allowlist `tokens.css`).

---

### ## Phase 2: Anti-FOUC Inline Script

**Goal:** Apply the correct theme **before** React mounts, so users never see a flash of the wrong theme on reload.

**Files to modify:**
- `pages/_document.tsx` (Next.js) — add `<script dangerouslySetInnerHTML>` inside `<Head>`.
- OR `index.html` (Vite/CRA) — add `<script>` in `<head>`.

**Key decisions:**
- Script must be **synchronous and blocking** — place in `<head>`, no `defer`/`async`.
- Read order: `localStorage.theme` → `prefers-color-scheme` → default `light`.
- Keep script < 500 bytes; minify in production build.

**Snippet:**
```html
<script>
  (function () {
    try {
      var stored = localStorage.getItem('theme');
      var sys = window.matchMedia('(prefers-color-scheme: dark)').matches ? 'dark' : 'light';
      var theme = stored || sys;
      document.documentElement.setAttribute('data-theme', theme);
    } catch (e) {}
  })();
</script>
```

**Verification:**
- [ ] Throttle network to "Slow 3G" → reload page → no white flash before dashboard paints in dark mode.
- [ ] Test in private/incognito (localStorage blocked) → falls back to system preference, no JS error.
- [ ] View source → script is present in `<head>` and renders before `<body>`.

---

### ## Phase 3: Theme Controller (React Layer)

**Goal:** Expose a `useTheme()` hook and `<ThemeProvider />` so any component can read/mutate the active theme.

**Files to create:**
- `src/theme/themes.ts`
- `src/theme/ThemeProvider.tsx`
- `src/theme/useTheme.ts`

**Key decisions:**
- Three modes: `light`, `dark`, `system` (resolves to OS preference and re-resolves on `matchMedia` change).
- State source: React Context, but **DOM is the source of truth** for the actual applied theme. The hook reads `document.documentElement.dataset.theme` on mount to stay in sync with the anti-FOUC script.
- Listen to `matchMedia('(prefers-color-scheme: dark)').change` only when mode === `system`.

**Snippet — `src/theme/ThemeProvider.tsx`:**
```tsx
export function ThemeProvider({ children }: { children: React.ReactNode }) {
  const [mode, setMode] = useState<ThemeMode>(() => {
    if (typeof window === 'undefined') return 'system';
    return (localStorage.getItem('theme') as ThemeMode) ?? 'system';
  });

  const apply = useCallback((m: ThemeMode) => {
    const resolved = m === 'system'
      ? (matchMedia('(prefers-color-scheme: dark)').matches ? 'dark' : 'light')
      : m;
    document.documentElement.setAttribute('data-theme', resolved);
    localStorage.setItem('theme', m);
  }, []);

  useEffect(() => { apply(mode); }, [mode, apply]);

  // Re-resolve on OS change when in 'system' mode
  useEffect(() => {
    if (mode !== 'system') return;
    const mq = matchMedia('(prefers-color-scheme: dark)');
    const handler = () => apply('system');
    mq.addEventListener('change', handler);
    return () => mq.removeEventListener('change', handler);
  }, [mode, apply]);

  return (
    <ThemeContext.Provider value={{ mode, setMode, toggle: () => setMode(m => m === 'dark' ? 'light' : 'dark') }}>
      {children}
    </ThemeContext.Provider>
  );
}
```

**Verification:**
- [ ] In a test component: `const { mode, setMode } = useTheme();` then `setMode('dark')` → `<html>` attribute updates within one tick.
- [ ] Refresh page → mode persists.
- [ ] Set OS to dark, choose `system` mode in app → flip OS to light → app re-themes without reload.

---

### ## Phase 4: Toggle UI

**Goal:** Ship a visible, accessible theme toggle in the dashboard header.

**Files to create/modify:**
- `src/theme/ThemeToggle.tsx` (new)
- `src/components/layout/Header.tsx` (modify — mount toggle)
- `src/components/layout/Header.module.css` (modify if needed)

**Key decisions:**
- **Icon button** (sun/moon) for header placement — minimum visual footprint.
- `aria-label` and `aria-pressed` for screen readers; visible focus ring using `--color-accent`.
- For users wanting more control, expose a 3-way segmented control in user-settings page: Light / Dark / System (post-MVP).

**Snippet — `ThemeToggle.tsx`:**
```tsx
export function ThemeToggle() {
  const { mode, setMode } = useTheme();
  const isDark = mode === 'dark' ||
    (mode === 'system' && matchMedia('(prefers-color-scheme: dark)').matches);

  return (
    <button
      type="button"
      onClick={() => setTheme(isDark ? 'light' : 'dark')}
      aria-label={isDark ? 'Switch to light mode' : 'Switch to dark mode'}
      aria-pressed={isDark}
      className={styles.toggle}
    >
      {isDark ? <SunIcon /> : <MoonIcon />}
    </button>
  );
}
```

**Verification:**
- [ ] Click toggle → theme flips instantly; no layout shift.
- [ ] Tab to button → focus ring visible against both backgrounds.
- [ ] Screen reader (VoiceOver/NVDA) announces "Switch to dark mode, button".
- [ ] Reload → state persists.

---

### ## Phase 5: Audit, Hardening & Documentation

**Goal:** Catch remaining hardcoded colors, edge cases, and write the theming guide.

**Files:**
- All `.css` / `.tsx` files (audit pass)
- `docs/theming.md` (new)

**Key decisions:**
- Use Stylelint rule `declaration-property-value-disallowed-list` to ban hex/rgb in components going forward.
- Capture screenshots of both themes for the PR description and design QA.
- Add a Storybook story (if Storybook is in use) for `ThemeProvider` showcasing all three modes.

**Verification:**
- [ ] Stylelint passes in CI; PR introducing `#fff` in a component file is blocked.
- [ ] All 12 dashboard routes screenshotted in both themes and attached to PR.
- [ ] Lighthouse a11y score ≥ 95 in both themes.

---

## Key Technical Decisions

| Decision | Choice | Rationale |
|---|---|---|
| Theming primitive | CSS custom properties | Framework-agnostic, zero runtime cost, easy to override per-component |
| Theme attribute | `data-theme="dark"` on `<html>` | Semantic, no class collisions, inspectable |
| Anti-FOUC | Inline blocking script in `<head>` | Only reliable way to prevent flash |
| Persistence | `localStorage` | Single user, single device; no auth round-trip needed |
| State management | React Context + DOM as source of truth | Avoids hydration mismatch with anti-FOUC script |
| Mode options | `light` / `dark` / `system` | Matches OS conventions; `system` is the expected default |
| Icons | Inline SVG (sun/moon) | No icon-font dep, tree-shakable, themable via `currentColor` |
| Bundle size target | < 1 KB gzipped added | Theme code is tiny by design |

---

## Verification Plan

**Unit tests** (`src/theme/__tests__/`):
- `ThemeProvider` applies correct `data-theme` for each mode
- `apply()` writes correct value to `localStorage`
- `system` mode re-resolves on `matchMedia` change event

**Integration / E2E** (Playwright):
1. **First-visit (no localStorage):** clear storage, set OS to dark → page loads in dark.
2. **First-visit (no localStorage):** clear storage, set OS to light → page loads in light.
3. **Persistence:** toggle to dark → reload → still dark.
4. **Toggle round-trip:** click toggle twice → returns to original theme.
5. **No FOUC:** record video at 0.5x speed while reloading in dark mode → confirm no light frame at top of page.
6. **System override:** in `system` mode, flip OS pref while page is open → theme updates without reload.

**Manual QA checklist:**
- [ ] All 12 dashboard routes render correctly in both themes
- [ ] No element is invisible (e.g. light-gray text on light background)
- [ ] Charts, tables, modals, dropdowns all themed
- [ ] Print stylesheet (if any) unaffected
- [ ] `prefers-reduced-motion` not affected (we're not adding motion)

**Accessibility:**
- [ ] axe DevTools: 0 critical/serious issues in both themes
- [ ] Contrast ≥ 4.5:1 for body text, ≥ 3:1 for UI components
- [ ] Toggle reachable by keyboard, has visible focus, announced correctly

**Performance:**
- [ ] No CLS regression (theme switch should not shift layout)
- [ ] Lighthouse performance score unchanged (±1 point acceptable)

---

**Recommendation given the 25/100 priority:** Ship **Phase 1 + Phase 2 only** behind a `?theme=dark` query flag for the next sprint. This delivers the visual fix and unblocks users who want dark mode, with ~4–6 hours of work. Phases 3–5 (the user-facing toggle and persistence) become a separate, properly-scoped ticket that can be prioritized against the rest of the backlog.