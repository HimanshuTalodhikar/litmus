// ============================================
// Product Copilot Portal — Shared JS
// ============================================

const API = window.location.origin;

// ---- Toast notifications ----
function showToast(message, type = 'info', duration = 4000) {
  let container = document.querySelector('.toast-container');
  if (!container) {
    container = document.createElement('div');
    container.className = 'toast-container';
    document.body.appendChild(container);
  }

  const icons = {
    success: `<svg fill="none" viewBox="0 0 24 24" stroke="currentColor"><path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M9 12l2 2 4-4m6 2a9 9 0 11-18 0 9 9 0 0118 0z"/></svg>`,
    error: `<svg fill="none" viewBox="0 0 24 24" stroke="currentColor"><path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M12 8v4m0 4h.01M21 12a9 9 0 11-18 0 9 9 0 0118 0z"/></svg>`,
    info: `<svg fill="none" viewBox="0 0 24 24" stroke="currentColor"><path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M13 16h-1v-4h-1m1-4h.01M21 12a9 9 0 11-18 0 9 9 0 0118 0z"/></svg>`,
  };

  const toast = document.createElement('div');
  toast.className = `toast ${type}`;
  toast.innerHTML = `${icons[type] || icons.info}<span>${message}</span>`;
  container.appendChild(toast);

  setTimeout(() => {
    toast.style.opacity = '0';
    toast.style.transform = 'translateY(8px)';
    toast.style.transition = 'all 0.3s ease';
    setTimeout(() => toast.remove(), 300);
  }, duration);
}

// ---- API helpers ----
async function apiFetch(url, options = {}) {
  const res = await fetch(API + url, {
    headers: { 'Content-Type': 'application/json', ...options.headers },
    ...options,
  });
  const data = await res.json().catch(() => ({}));
  if (!res.ok) throw new Error(data.detail || `HTTP ${res.status}`);
  return data;
}

// ---- Sidebar active state ----
function initSidebar() {
  const links = document.querySelectorAll('.nav-link');
  const path = window.location.pathname.replace(/\/$/, '');
  links.forEach(link => {
    const href = link.getAttribute('href').replace(/\/$/, '');
    if (href === path || (href && path.endsWith(href))) {
      link.classList.add('active');
    }
  });
}

// ---- Status badge helper ----
function statusBadge(status) {
  const map = {
    requested:    ['badge-blue', 'Requested'],
    under_review: ['badge-purple', 'Under Review'],
    accepted:     ['badge-green', 'Accepted'],
    rejected:     ['badge-red', 'Rejected'],
    backlog:      ['badge-amber', 'Backlog'],
    scheduled:    ['badge-cyan', 'Scheduled'],
    in_progress:  ['badge-indigo', 'In Progress'],
    shipped:      ['badge-green', 'Shipped'],
  };
  const [cls, label] = map[status] || ['badge-gray', status];
  return `<span class="badge ${cls}">${label}</span>`;
}

// ---- Priority helper ----
function priorityDisplay(score) {
  if (score == null) return `<span class="td-muted">—</span>`;
  const cls = score >= 60 ? 'priority-high' : score >= 40 ? 'priority-medium' : 'priority-low';
  return `<span class="priority-dot ${cls}">${score.toFixed(1)}</span>`;
}

// ---- Date helper ----
function formatDate(dateStr) {
  if (!dateStr) return '—';
  const d = new Date(dateStr);
  return d.toLocaleDateString('en-US', { month: 'short', day: 'numeric', year: 'numeric' });
}

function timeAgo(dateStr) {
  if (!dateStr) return '—';
  const diff = Date.now() - new Date(dateStr).getTime();
  const mins = Math.floor(diff / 60000);
  if (mins < 1) return 'just now';
  if (mins < 60) return `${mins}m ago`;
  const hrs = Math.floor(mins / 60);
  if (hrs < 24) return `${hrs}h ago`;
  const days = Math.floor(hrs / 24);
  if (days < 7) return `${days}d ago`;
  return formatDate(dateStr);
}

// ---- Loading state ----
function setLoading(el, loading) {
  if (loading) {
    el.dataset.original = el.innerHTML;
    el.disabled = true;
    el.innerHTML = `<span class="spinner"></span> Loading...`;
  } else {
    el.disabled = false;
    el.innerHTML = el.dataset.original || el.innerHTML;
  }
}

// ---- Init ----
document.addEventListener('DOMContentLoaded', initSidebar);
