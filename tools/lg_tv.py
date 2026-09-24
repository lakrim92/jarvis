"""Controle de la television LG webOS (via le protocole SSAP local, sans cloud)."""
import asyncio
import difflib
import json
from pathlib import Path

TOKEN_PATH = Path(__file__).resolve().parent.parent / ".secrets" / "lg_tv_token.json"


def _load_config():
    if not TOKEN_PATH.exists():
        raise FileNotFoundError(
            "La television n'est pas encore appairee. Lance l'appairage initial d'abord."
        )
    with open(TOKEN_PATH) as f:
        return json.load(f)


async def _run(coro_factory):
    from aiowebostv import WebOsClient

    cfg = _load_config()
    client = WebOsClient(cfg["host"], client_key=cfg["client_key"])
    await client.connect()
    try:
        return await coro_factory(client)
    finally:
        await client.disconnect()


def _sync(coro_factory):
    return asyncio.run(_run(coro_factory))


def tv_power_off() -> dict:
    """Eteint la television (veille)."""
    try:
        _sync(lambda c: c.power_off())
        return {"success": True}
    except Exception as exc:
        return {"success": False, "error": str(exc)}


def tv_set_volume(level: int) -> dict:
    """Regle le volume de la television (0-100)."""
    try:
        level = max(0, min(100, int(level)))
        _sync(lambda c: c.set_volume(level))
        return {"success": True, "volume": level}
    except Exception as exc:
        return {"success": False, "error": str(exc)}


def tv_volume_step(direction: str) -> dict:
    """Monte ou baisse le volume d'un cran. direction: 'up' ou 'down'."""
    try:
        if direction == "up":
            _sync(lambda c: c.volume_up())
        elif direction == "down":
            _sync(lambda c: c.volume_down())
        else:
            return {"success": False, "error": f"Direction inconnue: {direction}"}
        return {"success": True}
    except Exception as exc:
        return {"success": False, "error": str(exc)}


def tv_mute(mute: bool = True) -> dict:
    """Coupe ou retablit le son de la television."""
    try:
        _sync(lambda c: c.set_mute(mute))
        return {"success": True, "muted": mute}
    except Exception as exc:
        return {"success": False, "error": str(exc)}


def tv_launch_app(app_name: str) -> dict:
    """Lance une application sur la television (Netflix, Canal+, Disney+...)."""
    try:
        async def _do(client):
            apps = await client.get_apps()
            names = [a.get("title", "") for a in apps]
            match = difflib.get_close_matches(app_name, names, n=1, cutoff=0.4)
            if not match:
                substr = [a for a in apps if app_name.lower() in a.get("title", "").lower()]
                if not substr:
                    raise ValueError(f"Application introuvable sur la TV : {app_name}")
                target = substr[0]
            else:
                target = next(a for a in apps if a.get("title") == match[0])
            await client.launch_app(target["id"])
            return target.get("title")

        launched = _sync(_do)
        return {"success": True, "app": launched}
    except Exception as exc:
        return {"success": False, "error": str(exc)}


def tv_status() -> dict:
    """Renvoie l'etat actuel de la television (volume, app en cours)."""
    try:
        async def _do(client):
            volume = await client.get_volume()
            app = await client.get_current_app()
            return {"volume": volume, "current_app": app}

        return {"success": True, **_sync(_do)}
    except Exception as exc:
        return {"success": False, "error": str(exc)}
