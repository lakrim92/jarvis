"""Telecommande de la Freebox Player (Android TV Remote, reseau local) : chaines, chiffres, navigation.

Une connexion persistante est gardee dans un thread dedie, pour que chaque touche parte instantanement.
"""
import asyncio
import json
import threading
from pathlib import Path

SECRETS = Path(__file__).resolve().parent.parent / ".secrets"
CERT, KEY, CONF = SECRETS / "atv_cert.pem", SECRETS / "atv_key.pem", SECRETS / "freebox_player.json"

# Noms simples (pour le LLM) -> touche Android.
BUTTONS = {
    "UP": "DPAD_UP", "DOWN": "DPAD_DOWN", "LEFT": "DPAD_LEFT", "RIGHT": "DPAD_RIGHT",
    "ENTER": "DPAD_CENTER", "BACK": "BACK", "HOME": "HOME", "MENU": "MENU", "INFO": "INFO",
    "GUIDE": "GUIDE", "TV": "TV", "CHANNELUP": "CHANNEL_UP", "CHANNELDOWN": "CHANNEL_DOWN",
    "PLAYPAUSE": "MEDIA_PLAY_PAUSE", "VOLUMEUP": "VOLUME_UP", "VOLUMEDOWN": "VOLUME_DOWN", "MUTE": "VOLUME_MUTE",
}

# Jamais envoyees : le Player s'eteindrait completement (plus joignable, impossible a rallumer a distance).
FORBIDDEN = {"POWER", "SLEEP", "SOFT_SLEEP", "TV_POWER", "STB_POWER", "AVR_POWER", "WAKEUP", "SOFT_SLEEP"}


class _Session:
    def __init__(self):
        self._loop = None
        self._remote = None
        self._start_lock = threading.Lock()

    def _ensure_loop(self):
        with self._start_lock:
            if self._loop is None:
                self._loop = asyncio.new_event_loop()
                threading.Thread(target=self._loop.run_forever, daemon=True, name="freebox-remote").start()

    async def _get_remote(self):
        from androidtvremote2 import AndroidTVRemote

        if self._remote is not None:
            return self._remote
        if not CONF.exists():
            raise FileNotFoundError("Freebox Player non appairee (lance setup/pair_freebox_remote.py).")
        host = json.loads(CONF.read_text())["host"]
        remote = AndroidTVRemote("Jarvis", str(CERT), str(KEY), host)
        await remote.async_generate_cert_if_missing()
        await remote.async_connect()
        remote.keep_reconnecting()
        self._remote = remote
        return remote

    async def _send(self, keys, delay):
        for attempt in (1, 2):
            try:
                remote = await self._get_remote()
                for key in keys:
                    remote.send_key_command(key)
                    if len(keys) > 1:
                        await asyncio.sleep(delay)
                return
            except Exception:
                if self._remote is not None:
                    try:
                        self._remote.disconnect()
                    except Exception:
                        pass
                    self._remote = None
                if attempt == 2:
                    raise

    async def _status(self):
        remote = await self._get_remote()
        return {"is_on": remote.is_on, "current_app": remote.current_app}

    def run(self, coro, timeout=10):
        self._ensure_loop()
        return asyncio.run_coroutine_threadsafe(coro, self._loop).result(timeout)

    def send(self, keys, delay=0.4):
        return self.run(self._send(list(keys), delay), timeout=10 + len(keys))

    def status(self):
        return self.run(self._status())


_session = _Session()
_UNREACHABLE = "Freebox Player injoignable ou eteinte"
_action_callback = None


def register_action_callback(callback) -> None:
    """Appele (depuis le thread appelant) a chaque touche envoyee au Player, pour afficher la telecommande."""
    global _action_callback
    _action_callback = callback


def _notify() -> None:
    if _action_callback:
        try:
            _action_callback()
        except Exception:
            pass


def fb_key(key: str, repeat: int = 1) -> dict:
    """Envoie une touche Android brute (ex: 'PROG_RED', 'MEDIA_STOP', '5') au Player."""
    key = (key or "").upper().strip()
    if key in FORBIDDEN:
        return {"success": False, "error": "Touche d'extinction interdite (le Player ne pourrait plus etre rallume)."}
    repeat = max(1, min(int(repeat), 20))
    _notify()
    try:
        _session.send([key] * repeat)
        return {"success": True, "button": key, "repeat": repeat}
    except ValueError:
        return {"success": False, "error": f"Touche inconnue : {key}"}
    except Exception as exc:
        return {"success": False, "error": f"{_UNREACHABLE} ({exc})"}


def fb_button(name: str, repeat: int = 1) -> dict:
    """Envoie une touche par son nom simple (CHANNELUP, ENTER, HOME...) ou son nom Android."""
    name = (name or "").upper().replace("_", "").strip()
    return fb_key(BUTTONS.get(name, name), repeat)


def fb_goto_channel(number) -> dict:
    """Passe a un numero de chaine precis en tapant les chiffres."""
    digits = "".join(ch for ch in str(number) if ch.isdigit())
    if not digits or len(digits) > 3:
        return {"success": False, "error": f"Numero de chaine invalide : {number}"}
    _notify()
    try:
        _session.send(list(digits), delay=0.5)
        return {"success": True, "channel": int(digits)}
    except Exception as exc:
        return {"success": False, "error": f"{_UNREACHABLE} ({exc})"}


def fb_status() -> dict:
    try:
        return {"success": True, **_session.status()}
    except Exception as exc:
        return {"success": False, "error": f"{_UNREACHABLE} ({exc})"}
