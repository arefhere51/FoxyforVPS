from __future__ import annotations

import json
from pathlib import Path


def build_config(locations: list[dict], state: dict) -> dict:
    inbounds, outbounds, rules = [], [], []
    outbounds.append({"type": "direct", "tag": "direct"})
    for location in locations:
        code = location["code"]
        settings = state.get("locations", {}).get(code, {})
        if not settings.get("enabled"):
            continue
        node = settings.get("node") or (location.get("servers") or [{}])[0]
        port = int(settings.get("port", 0))
        if not (1 <= port <= 65535):
            continue
        in_tag, out_tag = f"socks-{code.lower()}", f"vpn-{code.lower()}"
        inbounds.append({
            "type": "socks",
            "tag": in_tag,
            "listen": "0.0.0.0",
            "listen_port": port,
        })
        outbounds.append({
            "type": "http",
            "tag": out_tag,
            "server": node["host"],
            "server_port": int(node["port"]),
            "dynamic_bearer_token": True,
            "version": 2,
            "disable_version_fallback": True,
            "tls": {
                "enabled": True,
                "server_name": node["host"],
                "utls": {"enabled": True, "fingerprint": "chrome"},
            },
        })
        rules.append({"inbound": [in_tag], "outbound": out_tag})
    return {
        "log": {"level": "warn", "timestamp": True},
        "inbounds": inbounds,
        "outbounds": outbounds,
        "route": {"rules": rules, "final": "direct"},
    }


def write_config(path: Path, locations: list[dict], state: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temp = path.with_suffix(".tmp")
    temp.write_text(json.dumps(build_config(locations, state), indent=2))
    temp.chmod(0o600)
    temp.replace(path)
