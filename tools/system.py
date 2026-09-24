"""Controle systeme : volume, luminosite, verrouillage, capture d'ecran, rappels."""
import shutil
import subprocess
import threading
from datetime import datetime, timedelta

import clock

# Callback branche par main.py pour notifier (voix + GUI) quand un rappel se declenche.
_reminder_callback = None


def register_reminder_callback(callback) -> None:
    global _reminder_callback
    _reminder_callback = callback


def _run(cmd: list) -> subprocess.CompletedProcess:
    return subprocess.run(cmd, capture_output=True, text=True, timeout=5)


def system_volume(action: str, level: int = None) -> dict:
    """action: 'set' | 'up' | 'down' | 'mute' | 'unmute'. level: 0-100 pour 'set'."""
    if not shutil.which("pactl"):
        return {"success": False, "error": "pactl non disponible."}
    sink = "@DEFAULT_SINK@"
    try:
        if action == "set" and level is not None:
            level = max(0, min(100, int(level)))
            _run(["pactl", "set-sink-volume", sink, f"{level}%"])
        elif action == "up":
            _run(["pactl", "set-sink-volume", sink, "+5%"])
        elif action == "down":
            _run(["pactl", "set-sink-volume", sink, "-5%"])
        elif action == "mute":
            _run(["pactl", "set-sink-mute", sink, "1"])
        elif action == "unmute":
            _run(["pactl", "set-sink-mute", sink, "0"])
        else:
            return {"success": False, "error": f"Action volume inconnue : {action}"}
        return {"success": True, "action": action}
    except Exception as exc:
        return {"success": False, "error": str(exc)}


def system_brightness(action: str, level: int = None) -> dict:
    """action: 'set' | 'up' | 'down'. level: 0-100 pour 'set'."""
    if not shutil.which("brightnessctl"):
        return {"success": False, "error": "brightnessctl non disponible."}
    try:
        if action == "set" and level is not None:
            level = max(1, min(100, int(level)))
            _run(["brightnessctl", "set", f"{level}%"])
        elif action == "up":
            _run(["brightnessctl", "set", "+10%"])
        elif action == "down":
            _run(["brightnessctl", "set", "10%-"])
        else:
            return {"success": False, "error": f"Action luminosite inconnue : {action}"}
        return {"success": True, "action": action}
    except Exception as exc:
        return {"success": False, "error": str(exc)}


def lock_screen() -> dict:
    for cmd in (["cinnamon-screensaver-command", "-l"], ["loginctl", "lock-session"], ["xdg-screensaver", "lock"]):
        if shutil.which(cmd[0]):
            try:
                subprocess.Popen(cmd, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
                return {"success": True}
            except Exception:
                continue
    return {"success": False, "error": "Aucun outil de verrouillage trouve."}


def take_screenshot() -> dict:
    try:
        import mss
        from pathlib import Path
        out_dir = Path.home() / "Pictures" / "Jarvis"
        out_dir.mkdir(parents=True, exist_ok=True)
        filename = out_dir / f"capture_{datetime.now():%Y%m%d_%H%M%S}.png"
        with mss.mss() as sct:
            sct.shot(output=str(filename))
        return {"success": True, "path": str(filename)}
    except Exception as exc:
        return {"success": False, "error": str(exc)}


def get_datetime() -> dict:
    now = clock.now()
    jours = ["lundi", "mardi", "mercredi", "jeudi", "vendredi", "samedi", "dimanche"]
    return {
        "success": True,
        "iso": now.isoformat(timespec="seconds"),
        "human": f"{jours[now.weekday()]} {now.day:02d}/{now.month:02d}/{now.year} a {now:%H:%M}",
    }


def set_reminder(seconds: int, message: str) -> dict:
    """Programme un rappel qui sera annonce dans `seconds` secondes."""
    try:
        seconds = int(seconds)
        if seconds <= 0:
            return {"success": False, "error": "La duree doit etre positive."}

        def fire():
            if _reminder_callback:
                _reminder_callback(message)

        threading.Timer(seconds, fire).start()
        trigger_at = clock.now() + timedelta(seconds=seconds)
        return {"success": True, "message": message, "trigger_at": trigger_at.strftime("%H:%M:%S")}
    except Exception as exc:
        return {"success": False, "error": str(exc)}
