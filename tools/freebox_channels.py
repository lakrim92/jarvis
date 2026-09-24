"""Liste des chaines de la Freebox (numero <-> nom), pour changer de chaine par son nom.

Source : API Freebox OS (permission 'tv'), bouquet de l'abonnement. Mise en cache localement (7 jours).
"""
import hashlib
import hmac
import json
import re
import time
import unicodedata
import urllib.request
from pathlib import Path
from typing import Optional

ROOT = Path(__file__).resolve().parent.parent
TOKEN_PATH = ROOT / ".secrets" / "freebox_token.json"
CACHE_PATH = ROOT / "cache" / "freebox_channels.json"
CACHE_MAX_AGE = 7 * 24 * 3600
BASE = "http://mafreebox.freebox.fr"

_channels: Optional[list] = None


def _api(path: str, session: Optional[str] = None, payload: Optional[dict] = None) -> dict:
    headers = {"Content-Type": "application/json"}
    if session:
        headers["X-Fbx-App-Auth"] = session
    data = json.dumps(payload).encode() if payload is not None else None
    req = urllib.request.Request(BASE + path, data=data, headers=headers, method="POST" if data else "GET")
    with urllib.request.urlopen(req, timeout=10) as resp:
        return json.loads(resp.read())


def _fetch() -> list:
    cfg = json.loads(TOKEN_PATH.read_text())
    challenge = _api("/api/v8/login/")["result"]["challenge"]
    password = hmac.new(cfg["app_token"].encode(), challenge.encode(), hashlib.sha1).hexdigest()
    session = _api("/api/v8/login/session/", payload={"app_id": cfg["app_id"], "password": password})[
        "result"]["session_token"]

    names = _api("/api/v8/tv/channels/", session)["result"]
    bouquet_id = _api("/api/v8/tv/bouquets/", session)["result"][0]["id"]
    entries = _api(f"/api/v8/tv/bouquets/{bouquet_id}/channels/", session)["result"]

    channels = []
    for e in entries:
        info = names.get(e.get("uuid"))
        if info and e.get("available") and info.get("name") and e.get("number"):
            channels.append({"number": e["number"], "sub": e.get("sub_number", 0), "name": info["name"]})
    return channels


def load(force: bool = False) -> list:
    """Charge la liste (cache, sinon API). Renvoie [] si rien n'est disponible."""
    global _channels
    if _channels is not None and not force:
        return _channels
    fresh = CACHE_PATH.exists() and time.time() - CACHE_PATH.stat().st_mtime < CACHE_MAX_AGE
    if fresh and not force:
        _channels = json.loads(CACHE_PATH.read_text())
        return _channels
    try:
        _channels = _fetch()
        CACHE_PATH.parent.mkdir(exist_ok=True)
        CACHE_PATH.write_text(json.dumps(_channels, ensure_ascii=False))
    except Exception:
        _channels = json.loads(CACHE_PATH.read_text()) if CACHE_PATH.exists() else []
    return _channels


def _norm(text: str) -> str:
    text = unicodedata.normalize("NFD", text.lower().replace("+", " plus "))
    text = "".join(c for c in text if unicodedata.category(c) != "Mn")
    text = re.sub(r"\((?:hd|sd|4k|uhd)\)|\b(?:hd|sd|4k|uhd)\b", " ", text)
    text = re.sub(r"[^a-z0-9]+", " ", text)
    return re.sub(r"\s+", " ", text).strip()


def find_channel(query: str) -> Optional[dict]:
    """Retrouve la chaine dont le nom correspond a `query` ({'number', 'name'}), ou None."""
    q = _norm(query)
    if len(q) < 2:
        return None
    q_tokens = q.split()
    best = None
    for ch in load():
        name = _norm(ch["name"])
        n_tokens = name.split()
        if name == q or name.replace(" ", "") == q.replace(" ", ""):
            score = (0, ch["number"], ch["sub"])          # nom exact : prioritaire
        elif all(t in n_tokens for t in q_tokens):
            score = (1 + len(n_tokens) - len(q_tokens), ch["number"], ch["sub"])  # nom contenant la requete
        else:
            continue
        if best is None or score < best[0]:
            best = (score, ch)
    return {"number": best[1]["number"], "name": best[1]["name"]} if best else None
