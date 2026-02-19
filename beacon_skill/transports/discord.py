from __future__ import annotations

from typing import Any, Dict, List, Optional

import requests

from ..retry import with_retry


class DiscordError(RuntimeError):
    pass


class DiscordClient:
    """Discord webhook transport for Beacon envelopes."""

    def __init__(
        self,
        webhook_url: Optional[str] = None,
        timeout_s: int = 20,
        username: Optional[str] = None,
        avatar_url: Optional[str] = None,
    ):
        self.webhook_url = webhook_url or ""
        self.timeout_s = timeout_s
        self.username = username
        self.avatar_url = avatar_url
        self.session = requests.Session()
        self.session.headers.update({"User-Agent": "Beacon/2.12.0 (Elyan Labs)"})

    def _send_payload(self, payload: Dict[str, Any]) -> Dict[str, Any]:
        if not self.webhook_url:
            raise DiscordError("Discord webhook_url required")

        def _do() -> Dict[str, Any]:
            resp = self.session.post(self.webhook_url, json=payload, timeout=self.timeout_s)
            if resp.status_code >= 400:
                msg = resp.text
                try:
                    data = resp.json()
                    if isinstance(data, dict):
                        msg = data.get("message", msg)
                except Exception:
                    pass
                raise DiscordError(msg or f"HTTP {resp.status_code}")

            if resp.status_code == 204 or not resp.text.strip():
                return {"ok": True, "status": resp.status_code}

            try:
                data = resp.json()
            except Exception:
                data = {"raw": resp.text}
            return {"ok": True, "status": resp.status_code, "data": data}

        return with_retry(_do)

    def send_message(
        self,
        content: str,
        *,
        username: Optional[str] = None,
        avatar_url: Optional[str] = None,
        embeds: Optional[List[Dict[str, Any]]] = None,
    ) -> Dict[str, Any]:
        payload: Dict[str, Any] = {"content": content[:2000]}
        if username or self.username:
            payload["username"] = (username or self.username or "")[:80]
        if avatar_url or self.avatar_url:
            payload["avatar_url"] = avatar_url or self.avatar_url
        if embeds:
            payload["embeds"] = embeds
        return self._send_payload(payload)

    def send_beacon(
        self,
        *,
        content: str,
        kind: str,
        agent_id: str,
        rtc_tip: Optional[float] = None,
        signature_preview: str = "",
        username: Optional[str] = None,
        avatar_url: Optional[str] = None,
    ) -> Dict[str, Any]:
        fields: List[Dict[str, Any]] = [
            {"name": "Kind", "value": kind[:64] or "unknown", "inline": True},
            {
                "name": "Agent",
                "value": (agent_id[:24] + "...") if len(agent_id) > 24 else (agent_id or "unknown"),
                "inline": True,
            },
        ]
        if rtc_tip is not None:
            fields.append({"name": "RTC Tip", "value": f"{rtc_tip:g} RTC", "inline": True})
        if signature_preview:
            fields.append({"name": "Signature", "value": signature_preview[:32], "inline": True})

        embed = {
            "title": f"Beacon Ping · {kind.upper()}",
            "description": (content or "Beacon ping")[:4096],
            "color": 65450 if rtc_tip else 7506394,
            "fields": fields,
        }
        return self.send_message(
            content=content,
            username=username,
            avatar_url=avatar_url,
            embeds=[embed],
        )
