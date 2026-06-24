"""
Jira REST API client for creating and updating tickets.
"""
import base64
import re
import httpx
from app.config import get_settings
import structlog

logger = structlog.get_logger()
settings = get_settings()


class JiraClient:
    def __init__(self):
        self.base_url = settings.jira_url
        self.email = settings.jira_email
        self.api_token = settings.jira_api_token
        self.project_key = settings.jira_project_key

    def _headers(self):
        creds = f"{self.email}:{self.api_token}"
        return {
            "Authorization": f"Basic {base64.b64encode(creds.encode()).decode()}",
            "Content-Type": "application/json",
            "Accept": "application/json",
        }

    async def create_ticket(self, fr: dict) -> dict:
        """Create a Jira ticket from a feature request."""
        priority_label = self._map_priority(fr.get("priority_score", 50))
        title = self._extract_title(fr.get("raw_text", ""))

        payload = {
            "fields": {
                "project": {"key": self.project_key},
                "summary": f"[FR-{fr['fr_number']}] {title}",
                "description": {
                    "type": "doc",
                    "version": 1,
                    "content": [
                        {
                            "type": "paragraph",
                            "content": [
                                {"type": "text", "text": f"**Original request:**\n{fr.get('raw_text', '')}"}
                            ]
                        },
                        {
                            "type": "paragraph",
                            "content": [
                                {"type": "text", "text": f"**Enriched:**\n{fr.get('enriched_text', 'N/A')}"}
                            ]
                        },
                        {
                            "type": "paragraph",
                            "content": [
                                {"type": "text", "text": f"**Submitted by:** {fr.get('requester_id', 'unknown')}"}
                            ]
                        },
                        {
                            "type": "paragraph",
                            "content": [
                                {"type": "text", "text": f"**Priority score:** {fr.get('priority_score', 'N/A')}/100"}
                            ]
                        },
                    ]
                },
                "issuetype": {"name": "Story"},
                "priority": {"name": priority_label},
                "labels": ["slack-captured", "auto-generated"],
            }
        }

        async with httpx.AsyncClient() as client:
            response = await client.post(
                f"{self.base_url}/rest/api/3/issue",
                headers=self._headers(),
                json=payload,
                timeout=30,
            )
            response.raise_for_status()
            data = response.json()

            return {
                "jira_key": data["key"],
                "jira_url": f"{self.base_url}/browse/{data['key']}",
            }

    def _map_priority(self, score: float) -> str:
        if score is None:
            return "Medium"
        if score >= 80:
            return "Highest"
        if score >= 60:
            return "High"
        if score >= 40:
            return "Medium"
        return "Low"

    def _extract_title(self, text: str) -> str:
        first_sentence = re.split(r'[.!?]', text)[0].strip()
        return first_sentence[:80] if first_sentence else text[:80]


async def create_jira_ticket(fr_id: str) -> dict:
    """High-level function: fetch FR from DB, create Jira ticket, update FR."""
    from app.db.feature_request_repo import get_feature_request, update_feature_request

    fr = await get_feature_request(fr_id)
    if not fr:
        return {"error": "Feature request not found"}

    if not settings.jira_url or not settings.jira_email or not settings.jira_api_token:
        return {"error": "Jira not configured"}

    client = JiraClient()
    try:
        result = await client.create_ticket(fr.model_dump())
        # Update FR with Jira key
        await update_feature_request(
            fr_id,
            jira_issue_key=result["jira_key"],
            jira_issue_url=result["jira_url"],
        )
        return result
    except Exception as e:
        logger.error("jira_create_error", fr_id=fr_id, error=str(e))
        return {"error": str(e)}
