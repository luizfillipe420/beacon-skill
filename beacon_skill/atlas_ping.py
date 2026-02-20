"""Atlas Ping — Auto-register and heartbeat with the central Beacon Atlas.

When the beacon-skill daemon starts, it pings the Atlas relay to announce
this agent. Periodic pings keep the agent listed as "active" on the public
Atlas at https://rustchain.org/beacon/.

Uses the open /relay/ping endpoint (no auth required). Any agent running
beacon-skill automatically appears on the Atlas — no manual registration
needed.

Beacon 2.15.0 — Elyan Labs.
"""

import time
from typing import Any, Dict, List, Optional

import requests

DEFAULT_ATLAS_URL = "https://rustchain.org/beacon"
ATLAS_PING_INTERVAL_S = 600  # 10 minutes


def atlas_ping(
    agent_id: str,
    name: str = "",
    *,
    capabilities: Optional[List[str]] = None,
    provider: str = "beacon",
    atlas_url: str = DEFAULT_ATLAS_URL,
    preferred_city: str = "",
    timeout: int = 10,
) -> Dict[str, Any]:
    """Ping the Beacon Atlas to register or refresh this agent.

    On first ping, the Atlas auto-registers the agent. On subsequent pings,
    it refreshes the heartbeat so the agent stays listed as "active".

    Args:
        agent_id: This agent's bcn_ identifier.
        name: Display name for the Atlas.
        capabilities: List of capability domains (e.g. ["coding", "ai"]).
        provider: Provider identifier (default "beacon" for SDK users).
        atlas_url: Base URL of the Atlas relay server.
        preferred_city: Optional ClawCities preferred city.
        timeout: HTTP request timeout in seconds.

    Returns:
        Server response dict with ok, agent_id, beat_count, etc.
    """
    url = f"{atlas_url.rstrip('/')}/relay/ping"
    body: Dict[str, Any] = {
        "agent_id": agent_id,
        "name": name or agent_id,
        "capabilities": capabilities or ["general"],
        "status": "alive",
        "provider": provider,
    }
    if preferred_city:
        body["preferred_city"] = preferred_city

    try:
        resp = requests.post(url, json=body, timeout=timeout)
        if resp.ok:
            return resp.json()
        return {"ok": False, "error": f"HTTP {resp.status_code}"}
    except Exception as exc:
        return {"ok": False, "error": str(exc)}
