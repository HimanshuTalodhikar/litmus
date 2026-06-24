#!/usr/bin/env python3
"""Backfill Jira tickets for all FRs that don't have one yet."""
import asyncio
import base64
import httpx
import os

JIRA_BASE = "https://himanshutalodhikar581.atlassian.net"
EMAIL = "himanshutalodhikar581@gmail.com"
API_TOKEN = os.environ.get("JIRA_API_TOKEN", "")
PROJECT_KEY = "SCRUM"

async def main():
    import asyncpg
    pool = await asyncpg.create_pool(
        host=os.environ.get("DB_HOST", "localhost"),
        port=int(os.environ.get("DB_PORT", "5432")),
        user=os.environ.get("DB_USER", "copilot"),
        password=os.environ.get("DB_PASSWORD", "password"),
        database=os.environ.get("DB_NAME", "productcopilot"),
        min_size=1,
        max_size=5,
    )

    # Fetch all FRs without Jira tickets
    rows = await pool.fetch("""
        SELECT id, fr_number, raw_text, enriched_text, priority_score, requester_id
        FROM feature_requests
        WHERE (jira_issue_key IS NULL OR jira_issue_key = '')
        ORDER BY fr_number
    """)
    print(f"Found {len(rows)} FRs needing Jira tickets")
    await pool.close()

    creds = f"{EMAIL}:{API_TOKEN}"
    headers = {
        "Authorization": f"Basic {base64.b64encode(creds.encode()).decode()}",
        "Content-Type": "application/json",
        "Accept": "application/json",
    }

    async with httpx.AsyncClient() as client:
        for row in rows:
            fr_id = str(row["id"])
            fr_number = row["fr_number"]
            raw_text = row["raw_text"] or ""
            enriched_text = row["enriched_text"] or raw_text or ""
            priority_score = float(row["priority_score"]) if row["priority_score"] else 50.0
            requester_id = row["requester_id"] or "unknown"

            # Extract title from raw text
            title = raw_text[:80] if raw_text else f"FR-{fr_number}"

            # Map priority
            if priority_score >= 80:
                priority_name = "Highest"
            elif priority_score >= 60:
                priority_name = "High"
            elif priority_score >= 40:
                priority_name = "Medium"
            else:
                priority_name = "Low"

            payload = {
                "fields": {
                    "project": {"key": PROJECT_KEY},
                    "summary": f"[FR-{fr_number}] {title}",
                    "description": {
                        "type": "doc",
                        "version": 1,
                        "content": [
                            {"type": "paragraph", "content": [{"type": "text", "text": f"**Original request:**\n{raw_text}"}]},
                            {"type": "paragraph", "content": [{"type": "text", "text": f"**Enriched:**\n{enriched_text}"}]},
                            {"type": "paragraph", "content": [{"type": "text", "text": f"**Submitted by:** {requester_id}"}]},
                            {"type": "paragraph", "content": [{"type": "text", "text": f"**Priority score:** {priority_score}/100"}]},
                        ]
                    },
                    "issuetype": {"name": "Story"},
                    "priority": {"name": priority_name},
                    "labels": ["slack-captured", "auto-generated"],
                }
            }

            print(f"  FR-{fr_number}: Creating Jira ticket (priority={priority_name})...")
            resp = await client.post(
                f"{JIRA_BASE}/rest/api/3/issue",
                headers=headers,
                json=payload,
                timeout=30,
            )
            if resp.status_code == 201:
                data = resp.json()
                jira_key = data["key"]
                jira_url = f"{JIRA_BASE}/browse/{jira_key}"
                print(f"  FR-{fr_number}: Created {jira_key}")

                # Update DB
                pool2 = await asyncpg.create_pool(
                    host=os.environ.get("DB_HOST", "localhost"),
                    port=int(os.environ.get("DB_PORT", "5432")),
                    user=os.environ.get("DB_USER", "copilot"),
                    password=os.environ.get("DB_PASSWORD", "password"),
                    database=os.environ.get("DB_NAME", "productcopilot"),
                    min_size=1,
                    max_size=5,
                )
                await pool2.execute("""
                    UPDATE feature_requests
                    SET jira_issue_key = $1, jira_issue_url = $2
                    WHERE id = $3
                """, jira_key, jira_url, fr_id)
                await pool2.close()
            else:
                print(f"  FR-{fr_number}: FAILED ({resp.status_code}) - {resp.text[:200]}")

            await asyncio.sleep(0.5)  # Rate limit protection

    print("Done!")

if __name__ == "__main__":
    asyncio.run(main())
