"""Step-by-step connection check for a Centauri Carbon 2, with a plain-French verdict for each step."""

from __future__ import annotations

import asyncio
import ipaddress
import socket
from typing import Any

import httpx


def _step(name: str, ok: bool, detail: str, fix: str = "") -> dict[str, Any]:
    return {"step": name, "ok": ok, "detail": detail, "fix": fix}


async def check(host: str, access_code: str, mqtt_port: int = 1883, http_port: int = 80) -> dict[str, Any]:
    """Network → access code / LAN mode → printer answers. Stops at the first blocking failure."""
    host, access_code = host.strip(), access_code.strip()
    steps: list[dict[str, Any]] = []
    out: dict[str, Any] = {"ok": False, "steps": steps}

    try:
        ipaddress.ip_address(host)
    except ValueError:
        if not host:
            steps.append(_step("Adresse", False, "Aucune adresse saisie.",
                               "Sur l'écran de l'imprimante : Paramètres → Réseau, note l'adresse IP (ex. 192.168.1.42)."))
            return out
    if not access_code:
        steps.append(_step("Code d'accès", False, "Aucun code saisi.",
                           "Le code d'accès s'affiche dans Paramètres → Réseau, à côté du mode LAN."))
        return out

    # 1. network
    try:
        await asyncio.wait_for(asyncio.open_connection(host, mqtt_port), timeout=4)
        steps.append(_step("Réseau", True, f"L'imprimante répond sur {host} (port {mqtt_port})."))
    except (OSError, asyncio.TimeoutError) as err:
        steps.append(_step("Réseau", False, f"Rien ne répond sur {host}:{mqtt_port} ({type(err).__name__}).",
                           "Vérifie que l'imprimante est allumée, sur le même réseau que ce PC, et que l'adresse IP est la "
                           "bonne. Astuce : fixe son IP dans ta box (bail DHCP statique)."))
        return out

    # 2. access code + LAN mode (HTTP bootstrap gives the serial)
    try:
        async with httpx.AsyncClient(timeout=6) as client:
            r = await client.get(f"http://{host}:{http_port}/system/info", params={"X-Token": access_code})
        if r.status_code == 401:
            steps.append(_step("Code d'accès", False, "L'imprimante refuse ce code.",
                               "Recopie le code affiché sur l'écran (sensible aux majuscules). Il change si on le régénère."))
            return out
        r.raise_for_status()
        serial = r.json().get("system_info", {}).get("sn", "")
        steps.append(_step("Code d'accès et mode LAN", True, f"Code accepté, numéro de série {serial or '?'}."))
        out["serial"] = serial
    except (httpx.HTTPError, ValueError) as err:
        steps.append(_step("Mode LAN", False, f"Pas de réponse de l'API locale ({type(err).__name__}).",
                           "Active « LAN Only » dans Paramètres → Réseau de l'imprimante : sans lui, l'accès local est fermé."))
        return out

    # 3. the printer itself (MQTT, read-only)
    try:
        from pycentauri.cc2 import CC2Printer
        import pycentauri.cc2 as cc2
        old_port = cc2.MQTT_PORT
        cc2.MQTT_PORT = mqtt_port
        try:
            p = await CC2Printer.connect(host, access_code=access_code, serial_number=out.get("serial") or None,
                                         connect_timeout=8)
            try:
                attrs = await p.attributes()
                st = await p.status()
            finally:
                await p.close()
        finally:
            cc2.MQTT_PORT = old_port
        out["printer"] = {"model": attrs.machine_name, "firmware": attrs.firmware_version, "name": attrs.name,
                          "nozzle": st.temp_nozzle, "bed": st.temp_bed}
        steps.append(_step("Imprimante", True, f"{attrs.machine_name} · firmware {attrs.firmware_version} · "
                                               f"buse {st.temp_nozzle:.0f} °C"))
        out["ok"] = True
    except Exception as err:  # MQTT auth or protocol: report, do not crash the page
        steps.append(_step("Imprimante", False, f"Connexion MQTT impossible : {str(err)[:160]}",
                           "Code d'accès refusé par MQTT ou firmware trop différent : vérifie le code, puis signale le "
                           "message ci-dessus (le protocole de la CC2 n'est pas documenté officiellement)."))
    return out


def resolve_hint() -> str:
    """Local IP of this PC, to tell the user which network the printer must be on."""
    try:
        with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as s:
            s.connect(("192.0.2.1", 80))  # no packet sent: just picks the outgoing interface
            return s.getsockname()[0]
    except OSError:
        return ""
