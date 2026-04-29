"""Guard notification adapters."""

from __future__ import annotations

import httpx

from agent.domain import VisitorRegistration


class GuardNotifier:
    async def send(self, registration: VisitorRegistration) -> bool:
        raise NotImplementedError


class WeComWebhookNotifier(GuardNotifier):
    def __init__(self, webhook_url: str) -> None:
        self.webhook_url = webhook_url

    async def send(self, registration: VisitorRegistration) -> bool:
        if not self.webhook_url:
            return False

        payload = {
            "msgtype": "text",
            "text": {"content": registration.guard_message()},
        }
        async with httpx.AsyncClient(timeout=5) as client:
            response = await client.post(self.webhook_url, json=payload)
            response.raise_for_status()
        return True
