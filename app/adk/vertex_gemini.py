"""
Custom Gemini LLM for Vertex AI with explicit credentials.

The ADK GoogleLLM.api_client only passes http_options, which doesn't include
credentials. This subclass overrides api_client to inject credentials from
Application Default Credentials (GOOGLE_APPLICATION_CREDENTIALS or gcloud ADC).
"""

from functools import cached_property
from google.adk.models import Gemini
from google.genai import Client, types
from google import auth


class VertexGemini(Gemini):
    """
    Gemini LLM backed by Vertex AI using Application Default Credentials.

    Use like:
        agent = Agent(model=VertexGemini(model="gemini-2.0-flash"))
    """

    @cached_property
    def api_client(self) -> Client:
        credentials, _ = auth.default()
        base_url, api_version = self._base_url_and_api_version
        http_kwargs = {
            "headers": self._tracking_headers(),
            "retry_options": self.retry_options,
            "base_url": base_url,
        }
        if api_version:
            http_kwargs["api_version"] = api_version
        return Client(
            credentials=credentials,
            vertexai=True,
            http_options=types.HttpOptions(**http_kwargs),
        )
