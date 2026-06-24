"""
PDF generator for feature requests — renders styled HTML then converts to PDF.
"""
from app.models.feature_request import FeatureRequest


PRIORITY_COLORS = {
    "Highest": "#dc2626",  # red
    "High": "#ea580c",     # orange
    "Medium": "#d97706",   # amber
    "Low": "#059669",      # green
}


def _priority_label(score: float | None) -> str:
    if score is None:
        return "Unknown"
    if score >= 80:
        return "Highest"
    if score >= 60:
        return "High"
    if score >= 40:
        return "Medium"
    return "Low"


def _priority_color(score: float | None) -> str:
    return PRIORITY_COLORS[_priority_label(score)]


def _status_badge_color(status: str) -> tuple[str, str]:
    colors = {
        "requested":    ("#3b82f6", "#eff6ff"),   # blue
        "under_review": ("#8b5cf6", "#f5f3ff"),   # purple
        "accepted":    ("#10b981", "#ecfdf5"),   # green
        "rejected":    ("#ef4444", "#fef2f2"),   # red
        "backlog":     ("#f59e0b", "#fffbeb"),   # amber
        "scheduled":   ("#06b6d4", "#ecfeff"),   # cyan
        "in_progress": ("#6366f1", "#eef2ff"),   # indigo
        "shipped":     ("#059669", "#ecfdf5"),   # emerald
    }
    return colors.get(status, ("#64748b", "#f8fafc"))


def generate_fr_pdf(fr: FeatureRequest) -> bytes:
    """Render a feature request as a styled PDF using weasyprint."""
    try:
        from weasyprint import HTML
    except ImportError:
        raise RuntimeError("weasyprint is not installed. Add it to requirements.txt")

    score = fr.priority_score or 0
    prio_label = _priority_label(score)
    prio_color = _priority_color(score)
    status_fg, status_bg = _status_badge_color(fr.status.value)

    created = fr.created_at.strftime("%B %d, %Y") if fr.created_at else "N/A"
    workspace = fr.workspace_id or "default"

    # Format enriched text for display
    enriched = fr.enriched_text or fr.raw_text or ""
    enriched_html = enriched.replace("\n", "<br>")

    html = f"""<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="UTF-8">
<style>
  @import url('https://fonts.googleapis.com/css2?family=Inter:wght@400;500;600;700&display=swap');

  * {{ margin: 0; padding: 0; box-sizing: border-box; }}

  body {{
    font-family: 'Inter', 'Helvetica Neue', Arial, sans-serif;
    background: #ffffff;
    color: #1e293b;
    padding: 48px 56px;
    font-size: 13px;
    line-height: 1.6;
  }}

  .header {{
    display: flex;
    align-items: flex-start;
    justify-content: space-between;
    border-bottom: 3px solid #6366f1;
    padding-bottom: 20px;
    margin-bottom: 28px;
  }}

  .fr-id {{
    font-size: 11px;
    font-weight: 600;
    color: #6366f1;
    text-transform: uppercase;
    letter-spacing: 0.08em;
    margin-bottom: 6px;
  }}

  .fr-number {{
    font-size: 28px;
    font-weight: 700;
    color: #0f172a;
    line-height: 1;
  }}

  .meta {{
    text-align: right;
    font-size: 11px;
    color: #64748b;
    line-height: 1.8;
  }}

  .badge {{
    display: inline-block;
    padding: 4px 14px;
    border-radius: 9999px;
    font-size: 11px;
    font-weight: 600;
    text-transform: capitalize;
  }}

  .rice-grid {{
    display: grid;
    grid-template-columns: repeat(4, 1fr);
    gap: 14px;
    margin: 24px 0 28px;
  }}

  .rice-card {{
    background: #f8fafc;
    border: 1px solid #e2e8f0;
    border-radius: 12px;
    padding: 18px 14px;
    text-align: center;
  }}

  .rice-value {{
    font-size: 32px;
    font-weight: 700;
    color: #0f172a;
    line-height: 1;
    margin-bottom: 4px;
  }}

  .rice-label {{
    font-size: 10px;
    font-weight: 600;
    color: #64748b;
    text-transform: uppercase;
    letter-spacing: 0.06em;
  }}

  .rice-sub {{
    font-size: 10px;
    color: #94a3b8;
    margin-top: 2px;
  }}

  .section {{
    margin-bottom: 24px;
  }}

  .section-title {{
    font-size: 10px;
    font-weight: 700;
    color: #6366f1;
    text-transform: uppercase;
    letter-spacing: 0.08em;
    margin-bottom: 8px;
    padding-bottom: 4px;
    border-bottom: 1px solid #e2e8f0;
  }}

  .content-box {{
    background: #f8fafc;
    border: 1px solid #e2e8f0;
    border-radius: 10px;
    padding: 14px 16px;
    font-size: 13px;
    line-height: 1.7;
    color: #334155;
    white-space: pre-wrap;
    word-break: break-word;
  }}

  .enriched-box {{
    background: #f5f3ff;
    border: 1px solid #c7d2fe;
    border-radius: 10px;
    padding: 14px 16px;
    font-size: 12.5px;
    line-height: 1.8;
    color: #3730a3;
    white-space: pre-wrap;
    word-break: break-word;
  }}

  .info-row {{
    display: flex;
    gap: 24px;
    margin-bottom: 20px;
  }}

  .info-item {{
    display: flex;
    flex-direction: column;
    gap: 2px;
  }}

  .info-label {{
    font-size: 9px;
    font-weight: 700;
    color: #94a3b8;
    text-transform: uppercase;
    letter-spacing: 0.06em;
  }}

  .info-value {{
    font-size: 12px;
    font-weight: 500;
    color: #334155;
  }}

  .jira-link {{
    color: #6366f1;
    text-decoration: none;
    font-weight: 500;
  }}

  .footer {{
    margin-top: 36px;
    padding-top: 14px;
    border-top: 1px solid #e2e8f0;
    display: flex;
    justify-content: space-between;
    font-size: 10px;
    color: #94a3b8;
  }}

  .priority-section {{
    background: #f0fdf4;
    border: 1px solid #bbf7d0;
    border-radius: 10px;
    padding: 14px 16px;
    margin: 20px 0;
    display: flex;
    align-items: center;
    gap: 14px;
  }}

  .priority-big {{
    font-size: 36px;
    font-weight: 800;
    color: {prio_color};
    line-height: 1;
  }}

  .priority-details {{
    flex: 1;
  }}

  .priority-score-label {{
    font-size: 11px;
    font-weight: 600;
    color: #16a34a;
    text-transform: uppercase;
    letter-spacing: 0.06em;
    margin-bottom: 2px;
  }}

  .priority-score-sub {{
    font-size: 10px;
    color: #64748b;
  }}

  .two-col {{
    display: grid;
    grid-template-columns: 1fr 1fr;
    gap: 20px;
  }}
</style>
</head>
<body>

  <!-- Header -->
  <div class="header">
    <div>
      <div class="fr-id">Feature Request</div>
      <div class="fr-number">FR-{fr.fr_number}</div>
    </div>
    <div class="meta">
      <span class="badge" style="background:{status_bg};color:{status_fg};">{fr.status.value.replace('_', ' ')}</span>
      <div style="margin-top:8px">Created {created}</div>
      <div>Workspace: {workspace}</div>
    </div>
  </div>

  <!-- Priority Score -->
  <div class="priority-section">
    <div class="priority-big">{score:.0f}</div>
    <div class="priority-details">
      <div class="priority-score-label">Priority Score / 100</div>
      <div class="priority-score-sub">RICE-based — {prio_label} Priority</div>
    </div>
  </div>

  <!-- RICE Scores -->
  <div class="rice-grid">
    <div class="rice-card">
      <div class="rice-value">{fr.reach_score or '—'}</div>
      <div class="rice-label">Reach</div>
      <div class="rice-sub">(users affected, 1-10)</div>
    </div>
    <div class="rice-card">
      <div class="rice-value">{fr.impact_score or '—'}</div>
      <div class="rice-label">Impact</div>
      <div class="rice-sub">(effect on users, 1-3)</div>
    </div>
    <div class="rice-card">
      <div class="rice-value">{f"{fr.confidence_score:.0f}" if fr.confidence_score else '—'}</div>
      <div class="rice-label">Confidence</div>
      <div class="rice-sub">(%, 50-100%)</div>
    </div>
    <div class="rice-card">
      <div class="rice-value">{fr.effort_estimate or '—'}</div>
      <div class="rice-label">Effort</div>
      <div class="rice-sub">(xs/s/m/l/xl)</div>
    </div>
  </div>

  <!-- Info Row -->
  <div class="info-row">
    <div class="info-item">
      <span class="info-label">Requester</span>
      <span class="info-value">{fr.requester_id or 'Unknown'}</span>
    </div>
    <div class="info-item">
      <span class="info-label">Jira Ticket</span>
      <span class="info-value">
        {"<a href='" + fr.jira_issue_url + "' class='jira-link'>" + fr.jira_issue_key + "</a>" if fr.jira_issue_url else "Not created"}
      </span>
    </div>
  </div>

  <!-- Raw + Enriched side by side -->
  <div class="two-col">
    <div class="section">
      <div class="section-title">Original Request</div>
      <div class="content-box">{fr.raw_text}</div>
    </div>
    <div class="section">
      <div class="section-title">Enriched Request</div>
      <div class="enriched-box">{enriched_html}</div>
    </div>
  </div>

  <!-- Footer -->
  <div class="footer">
    <span>Generated by Product Copilot</span>
    <span>{created}</span>
  </div>

</body>
</html>"""

    return HTML(string=html).write_pdf()
