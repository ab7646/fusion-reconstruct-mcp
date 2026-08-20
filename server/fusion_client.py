"""Thin HTTP client for the Fusion 360 add-in bridge.

The add-in (fusion_addin/FusionReconstructBridge) runs a small local HTTP
server *inside* Fusion 360's Python process and executes every request on
Fusion's main thread (the Fusion API is not thread-safe - see
fusion_addin/.../lib/thread_bridge.py). This client just does JSON-over-HTTP
against http://127.0.0.1:<port>/command.
"""

from __future__ import annotations

import requests

from . import config


class FusionBridgeError(RuntimeError):
    """Raised when the add-in is unreachable or returns an error."""


def call(action: str, **params) -> dict:
    try:
        resp = requests.post(
            f"{config.FUSION_BRIDGE_URL}/command",
            json={"action": action, "params": params},
            timeout=config.FUSION_BRIDGE_TIMEOUT_S,
        )
    except requests.exceptions.ConnectionError as exc:
        raise FusionBridgeError(
            "Could not reach the Fusion 360 bridge add-in at "
            f"{config.FUSION_BRIDGE_URL}. Is Fusion 360 running with the "
            "FusionReconstructBridge add-in started (Utilities > Add-Ins)?"
        ) from exc
    except requests.exceptions.Timeout as exc:
        raise FusionBridgeError(
            f"Fusion bridge did not respond to '{action}' within "
            f"{config.FUSION_BRIDGE_TIMEOUT_S}s."
        ) from exc

    try:
        body = resp.json()
    except ValueError as exc:
        raise FusionBridgeError(f"Fusion bridge returned a non-JSON response: {resp.text[:500]}") from exc

    if resp.status_code != 200 or not body.get("ok", False):
        raise FusionBridgeError(body.get("error", f"Fusion bridge call '{action}' failed (HTTP {resp.status_code})"))

    return body.get("result", {})
