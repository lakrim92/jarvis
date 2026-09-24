"""Heure reelle de Jarvis : independante de l'horloge du PC (qui peut etre fausse ou non synchronisee).

On mesure l'ecart entre l'horloge du PC et des serveurs de temps (SNTP, sinon en-tete Date HTTPS), puis on
l'applique partout (interface, « quelle heure est-il », salutation, journaux). Si internet est indisponible,
on retombe sur l'horloge du PC (a jour de la derniere mesure connue).
"""
import datetime
import logging
import socket
import statistics
import struct
import threading
import time
import urllib.request
from email.utils import parsedate_to_datetime
from typing import Optional
from zoneinfo import ZoneInfo

log = logging.getLogger("jarvis.clock")

TIMEZONE = ZoneInfo("Europe/Paris")
NTP_HOSTS = ("time.cloudflare.com", "time.google.com", "pool.ntp.org")
HTTP_SOURCES = ("https://www.google.com", "https://cloudflare.com", "https://www.debian.org")
REFRESH_SECONDS = 30 * 60
MAX_DISAGREEMENT = 2.0        # les sources doivent s'accorder a 2 s pres

_offset = 0.0                 # secondes a ajouter a time.time() pour obtenir l'heure reelle
_synced = False
_lock = threading.Lock()


def _sntp(host: str, timeout: float = 2.0) -> float:
    """Ecart (serveur - PC) mesure par une requete NTP simple."""
    with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as s:
        s.settimeout(timeout)
        t0 = time.time()
        s.sendto(b"\x1b" + 47 * b"\0", (host, 123))
        data, _ = s.recvfrom(48)
        t1 = time.time()
    seconds, fraction = struct.unpack("!II", data[40:48])
    server = seconds - 2208988800 + fraction / 2 ** 32
    return server - (t0 + t1) / 2


def _http(url: str, timeout: float = 5.0) -> float:
    """Ecart (serveur - PC) d'apres l'en-tete Date HTTP (precision ~1 s)."""
    req = urllib.request.Request(url, method="HEAD", headers={"User-Agent": "Jarvis-clock"})
    t0 = time.time()
    with urllib.request.urlopen(req, timeout=timeout) as resp:
        t1 = time.time()
        date = parsedate_to_datetime(resp.headers["Date"])
    return date.timestamp() + 0.5 - (t0 + t1) / 2      # l'en-tete est tronquee a la seconde


def _measure() -> Optional[float]:
    offsets = []
    for host in NTP_HOSTS:
        try:
            offsets.append(_sntp(host))
        except Exception:
            continue
        if len(offsets) >= 2:
            break
    if len(offsets) < 2:
        for url in HTTP_SOURCES:
            try:
                offsets.append(_http(url))
            except Exception:
                continue
            if len(offsets) >= 2:
                break
    if not offsets:
        return None
    if len(offsets) >= 2 and max(offsets) - min(offsets) > MAX_DISAGREEMENT:
        log.warning("Sources de temps en desaccord (%s), mesure ignoree", [round(o, 1) for o in offsets])
        return None
    return statistics.median(offsets)


def sync() -> bool:
    """Mesure l'ecart avec l'heure reelle. Renvoie True si la mesure a reussi."""
    global _offset, _synced
    measured = _measure()
    if measured is None:
        log.warning("Heure reelle indisponible (pas d'internet ?) : horloge du PC utilisee")
        return False
    with _lock:
        _offset, _synced = measured, True
    if abs(measured) > 2:
        log.warning("L'horloge du PC est fausse de %.0f s (%+.1f h) : Jarvis utilise l'heure reelle",
                    measured, measured / 3600)
    else:
        log.info("Heure reelle synchronisee (ecart avec le PC : %.2f s)", measured)
    return True


def start_background_refresh() -> None:
    def loop():
        while True:
            time.sleep(REFRESH_SECONDS)
            sync()

    threading.Thread(target=loop, daemon=True, name="clock-refresh").start()


def timestamp(pc_time: Optional[float] = None) -> float:
    return (time.time() if pc_time is None else pc_time) + _offset


def now() -> datetime.datetime:
    """Date et heure reelles en heure de Paris."""
    return datetime.datetime.fromtimestamp(timestamp(), TIMEZONE)


def localtime(pc_time: Optional[float] = None) -> time.struct_time:
    """Equivalent de time.localtime() sur l'heure reelle (utilise aussi par les journaux)."""
    return datetime.datetime.fromtimestamp(timestamp(pc_time), TIMEZONE).timetuple()


def offset_seconds() -> float:
    return _offset


def is_synced() -> bool:
    return _synced


JOURS = ["lundi", "mardi", "mercredi", "jeudi", "vendredi", "samedi", "dimanche"]
MOIS = ["janvier", "février", "mars", "avril", "mai", "juin", "juillet", "août", "septembre", "octobre",
        "novembre", "décembre"]


def spoken_time() -> str:
    n = now()
    return f"Il est {n.hour} h {n.minute:02d}." if n.minute else f"Il est {n.hour} heures pile."


def spoken_date() -> str:
    n = now()
    day = "1er" if n.day == 1 else str(n.day)
    return f"Nous sommes {JOURS[n.weekday()]} {day} {MOIS[n.month - 1]} {n.year}."
