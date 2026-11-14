from __future__ import annotations

import httpx

DIRECTORY_URL = "https://firefox.settings.services.mozilla.com/v1/buckets/main/collections/vpn-serverlist/records"
HEADERS = {"User-Agent": "MozillaVPN/2.24.0 (sys:android 14)", "Accept": "application/json"}


class DirectoryError(RuntimeError):
    pass


async def fetch_locations() -> list[dict]:
    try:
        async with httpx.AsyncClient(timeout=25, headers=HEADERS, follow_redirects=True) as client:
            response = await client.get(DIRECTORY_URL)
            response.raise_for_status()
            payload = response.json()
    except (httpx.HTTPError, ValueError) as exc:
        raise DirectoryError(f"Could not fetch Mozilla's public server directory: {exc}") from exc

    merged: dict[str, dict] = {}
    for record in payload.get("data", []):
        country = record.get("country") or record
        code = str(country.get("code") or "").strip().upper()
        if not code:
            continue
        item = merged.setdefault(code, {
            "code": code,
            "name": country.get("name") or code,
            "locked": bool(record.get("locked", country.get("locked", False))),
            "servers": [],
        })
        # Treat a country as locked if any corresponding directory record marks it locked.
        item["locked"] = item["locked"] or bool(record.get("locked", country.get("locked", False)))
        for city in country.get("cities", []):
            city_code = str(city.get("code") or "").strip().upper()
            for server in city.get("servers", []):
                if server.get("quarantined"):
                    continue
                hostname = str(server.get("hostname") or "").strip()
                fallback_port = int(server.get("port") or 0)
                target_host, target_port = "", 0
                protocols = server.get("protocols") or []
                connect = next((p for p in protocols if p.get("name") == "connect"), None)
                if connect:
                    target_host = str(connect.get("host") or hostname).strip()
                    target_port = int(connect.get("port") or fallback_port)
                elif not protocols:
                    target_host, target_port = hostname, fallback_port
                if not target_host or not 1 <= target_port <= 65535:
                    continue
                item["servers"].append({
                    "city": city.get("name") or city_code,
                    "city_code": city_code,
                    "host": target_host,
                    "port": target_port,
                })
    locations = []
    for item in merged.values():
        # A stable first node is selected for a country; it can be changed on refresh if Mozilla changes the directory.
        deduped = {(s["host"].lower(), s["port"]): s for s in item["servers"]}
        item["servers"] = list(deduped.values())
        item["servers"].sort(key=lambda s: (s["city_code"], s["host"]))
        if item["servers"]:
            locations.append(item)
    locations.sort(key=lambda x: x["name"].casefold())
    return locations
