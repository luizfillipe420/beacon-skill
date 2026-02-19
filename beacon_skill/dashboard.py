from __future__ import annotations

import time
from collections import Counter
from datetime import datetime, timezone
from typing import Any, Dict, Optional

from .codec import encode_envelope
from .config import load_config
from .identity import AgentIdentity
from .inbox import read_inbox
from .storage import append_jsonl
from .transports.udp import udp_send


def _format_ts(ts: Optional[float]) -> str:
    if not ts:
        return "--:--:--"
    return datetime.fromtimestamp(float(ts), tz=timezone.utc).strftime("%H:%M:%S")


def _short_agent(v: str) -> str:
    if not v:
        return "unknown"
    if len(v) <= 14:
        return v
    return v[:11] + "..."


def _as_text(entry: Dict[str, Any]) -> str:
    env = entry.get("envelope") or {}
    txt = env.get("text") or entry.get("text") or ""
    txt = str(txt).replace("\n", " ").strip()
    if len(txt) > 80:
        return txt[:77] + "..."
    return txt


def _rtc_tip(entry: Dict[str, Any]) -> Optional[float]:
    env = entry.get("envelope") or {}
    for k in ("rtc_tip", "tip_rtc", "reward_rtc"):
        v = env.get(k)
        if v is None:
            continue
        try:
            return float(v)
        except Exception:
            continue
    return None


def _transport_tag(entry: Dict[str, Any]) -> str:
    p = (entry.get("platform") or "unknown").lower()
    if p == "udp":
        return "udp"
    if p in {"bottube", "discord", "rustchain", "webhook"}:
        return p
    return p


def _send_quick_ping(raw: str) -> Dict[str, Any]:
    cfg = load_config()
    txt = (raw or "").strip()
    if not txt:
        return {"ok": False, "error": "empty"}

    kind = "hello"
    text = txt
    if txt.startswith("/") and " " in txt:
        head, rest = txt[1:].split(" ", 1)
        if head:
            kind = head.strip().lower()
            text = rest.strip()

    payload = {
        "v": 1,
        "kind": kind,
        "from": cfg.get("beacon", {}).get("agent_name", ""),
        "to": "dashboard:quick-send",
        "ts": int(time.time()),
        "text": text,
    }

    signed = False
    try:
        ident = AgentIdentity.load()
        payload_text = encode_envelope(payload, version=2, identity=ident, include_pubkey=True)
        signed = True
    except Exception:
        payload_text = encode_envelope(payload, version=1)

    # Best effort: emit over UDP only if configured.
    udp_cfg = cfg.get("udp") or {}
    sent_udp = False
    if bool(udp_cfg.get("enabled")):
        host = str(udp_cfg.get("host") or "255.255.255.255")
        port = int(udp_cfg.get("port") or 38400)
        broadcast = bool(udp_cfg.get("broadcast", True))
        ttl = udp_cfg.get("ttl")
        try:
            ttl_int = int(ttl) if ttl is not None else None
        except Exception:
            ttl_int = None

        try:
            udp_send(host, port, payload_text.encode("utf-8", errors="replace"), broadcast=broadcast, ttl=ttl_int)
            sent_udp = True
        except Exception:
            sent_udp = False

    append_jsonl(
        "outbox.jsonl",
        {
            "platform": "dashboard",
            "action": "quick-send",
            "kind": kind,
            "text": text,
            "signed": signed,
            "sent_udp": sent_udp,
            "ts": int(time.time()),
        },
    )

    return {"ok": True, "kind": kind, "signed": signed, "sent_udp": sent_udp}


def run_dashboard(poll_interval: float = 1.0, sound: bool = False) -> int:
    try:
        from textual.app import App, ComposeResult
        from textual.containers import Horizontal, Vertical
        from textual.widgets import DataTable, Footer, Header, Input, Static, TabbedContent, TabPane
    except Exception as e:  # pragma: no cover
        raise RuntimeError(
            "textual is required for dashboard. Install with: pip install textual"
        ) from e

    class BeaconDashboard(App):
        CSS = """
        Screen {
            background: #000000;
            color: #8ff58f;
        }
        #root {
            height: 1fr;
        }
        #sidebar {
            width: 34;
            border: solid #1f6f1f;
            padding: 1;
            background: #050505;
        }
        #tabs {
            width: 1fr;
            border: solid #1f6f1f;
        }
        DataTable {
            height: 1fr;
            background: #0a0a0a;
        }
        Input {
            dock: bottom;
            border: solid #1f6f1f;
            background: #030303;
            color: #b8ffb8;
        }
        """

        BINDINGS = [
            ("q", "quit", "Quit"),
            ("ctrl+c", "quit", "Quit"),
        ]

        def __init__(self) -> None:
            super().__init__()
            self._last_ts = 0.0
            self._count_today = 0
            self._transport_counter: Counter[str] = Counter()
            self._agent_counter: Counter[str] = Counter()

        def compose(self) -> ComposeResult:
            yield Header(show_clock=True)
            with Horizontal(id="root"):
                yield Static("Booting...", id="sidebar")
                with TabbedContent(id="tabs"):
                    with TabPane("All", id="tab-all"):
                        yield DataTable(id="tbl-all")
                    with TabPane("BoTTube", id="tab-bottube"):
                        yield DataTable(id="tbl-bottube")
                    with TabPane("Discord", id="tab-discord"):
                        yield DataTable(id="tbl-discord")
                    with TabPane("RustChain", id="tab-rustchain"):
                        yield DataTable(id="tbl-rustchain")
                    with TabPane("Drama", id="tab-drama"):
                        yield DataTable(id="tbl-drama")
                    with TabPane("Bounties", id="tab-bounty"):
                        yield DataTable(id="tbl-bounty")
            yield Input(placeholder="Send ping: type message or /kind message and press Enter", id="quick-send")
            yield Footer()

        def on_mount(self) -> None:
            for tid in (
                "tbl-all",
                "tbl-bottube",
                "tbl-discord",
                "tbl-rustchain",
                "tbl-drama",
                "tbl-bounty",
            ):
                table = self.query_one(f"#{tid}", DataTable)
                table.add_columns("Time", "Transport", "Agent", "Kind", "Message", "RTC")
                table.zebra_stripes = True
            self.set_interval(max(0.25, float(poll_interval)), self._poll_inbox)
            self.set_interval(1.0, self._refresh_sidebar)
            self.title = "Beacon Dashboard"
            self.sub_title = "Live transport activity"

        def _route_table_id(self, transport: str, kind: str) -> str:
            t = (transport or "").lower()
            k = (kind or "").lower()
            if t == "bottube":
                return "tbl-bottube"
            if t == "discord":
                return "tbl-discord"
            if t == "rustchain":
                return "tbl-rustchain"
            if k in {"mayday", "drama", "roast", "clapback"}:
                return "tbl-drama"
            if k in {"bounty", "offer", "contract", "task"}:
                return "tbl-bounty"
            return "tbl-all"

        def _add_row(self, table_id: str, row: tuple[str, str, str, str, str, str]) -> None:
            table = self.query_one(f"#{table_id}", DataTable)
            table.add_row(*row)
            # Keep memory bounded.
            if table.row_count > 400:
                try:
                    first_key = next(iter(table.rows.keys()))
                    table.remove_row(first_key)
                except Exception:
                    pass

        def _poll_inbox(self) -> None:
            entries = read_inbox(since=self._last_ts, limit=500)
            if not entries:
                return

            for e in entries:
                rts = float(e.get("received_at") or 0.0)
                if rts > self._last_ts:
                    self._last_ts = rts

                env = e.get("envelope") or {}
                kind = str(env.get("kind") or "raw")
                transport = _transport_tag(e)
                agent = str(env.get("agent_id") or e.get("from") or "")
                msg = _as_text(e)
                rtc = _rtc_tip(e)

                row = (
                    _format_ts(rts),
                    transport.upper(),
                    _short_agent(agent),
                    kind,
                    msg,
                    f"{rtc:g}" if rtc is not None else "-",
                )

                self._add_row("tbl-all", row)
                specific = self._route_table_id(transport, kind)
                if specific != "tbl-all":
                    self._add_row(specific, row)

                self._count_today += 1
                self._transport_counter[transport] += 1
                self._agent_counter[_short_agent(agent)] += 1

                high_value = rtc is not None and rtc >= 5
                mayday = kind.lower() == "mayday"
                if high_value or mayday:
                    self.notify(
                        f"{kind.upper()} from {_short_agent(agent)} ({rtc:g} RTC)" if rtc is not None else f"{kind.upper()} from {_short_agent(agent)}",
                        severity="warning",
                        timeout=4,
                    )
                    if sound:
                        print("\a", end="", flush=True)

        def _refresh_sidebar(self) -> None:
            top_agents = self._agent_counter.most_common(5)
            lines = [
                "[b]Beacon Network[/b]",
                "",
                f"Pings today: {self._count_today}",
                "",
                "Transports:",
            ]
            for t in ["udp", "webhook", "discord", "bottube", "rustchain", "moltbook", "clawcities", "clawsta", "fourclaw", "pinchedin", "clawtasks", "clawnews"]:
                n = self._transport_counter.get(t, 0)
                marker = "[green]●[/green]" if n > 0 else "[red]●[/red]"
                lines.append(f"{marker} {t}: {n}")

            lines.append("")
            lines.append("Top agents:")
            if top_agents:
                for agent, n in top_agents:
                    lines.append(f"- {agent}: {n}")
            else:
                lines.append("- none yet")

            self.query_one("#sidebar", Static).update("\n".join(lines))

        def on_input_submitted(self, event: Input.Submitted) -> None:
            raw = event.value.strip()
            if not raw:
                return
            outcome = _send_quick_ping(raw)
            if outcome.get("ok"):
                self.notify(f"Sent quick ping ({outcome.get('kind')})", severity="information", timeout=2)
            else:
                self.notify(f"Send failed: {outcome.get('error', 'unknown')}", severity="error", timeout=3)
            event.input.value = ""

    BeaconDashboard().run()
    return 0
