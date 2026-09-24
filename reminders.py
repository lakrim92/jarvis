"""Rappels, minuteurs et alarmes : comprehension de la phrase (heure, delai, message), stockage durable
(data/reminders.json : ils survivent a un redemarrage) et declenchement a l'heure REELLE (clock.py).

Conversation : si l'heure ou le message manque (« rappelle-moi quelque chose », « rappelle-moi de sortir le
linge »), Jarvis pose la question et attend la reponse (voir main._await_answer).
"""
import datetime
import json
import logging
import re
import threading
import time
import unicodedata
from pathlib import Path
from typing import Optional

import clock

log = logging.getLogger("jarvis.reminders")

STORE = Path(__file__).resolve().parent / "data" / "reminders.json"
PENDING_TTL = 90                 # secondes pendant lesquelles Jarvis attend la reponse a sa question

_lock = threading.Lock()
_items: list = []
_callback = None
_pending: Optional[dict] = None  # {"message": str|None, "when": datetime|None, "kind": str, "ts": float}

JOURS = ["lundi", "mardi", "mercredi", "jeudi", "vendredi", "samedi", "dimanche"]

# ---------------------------------------------------------------------------------------------- utilitaires
_UNITS = {"zero": 0, "un": 1, "une": 1, "deux": 2, "trois": 3, "quatre": 4, "cinq": 5, "six": 6, "sept": 7,
          "huit": 8, "neuf": 9, "dix": 10, "onze": 11, "douze": 12, "treize": 13, "quatorze": 14, "quinze": 15,
          "seize": 16, "vingt": 20, "vingts": 20, "trente": 30, "quarante": 40, "cinquante": 50, "soixante": 60}


def fold(text: str) -> str:
    """Minuscules sans accents, apostrophes/tirets/ponctuation -> espace ; MEME LONGUEUR que `text`
    (pour retrouver les portions correspondantes dans le texte d'origine)."""
    out = []
    for ch in text:
        base = unicodedata.normalize("NFD", ch)[0].lower()
        out.append(" " if base in "-'’.,!?;:«»\"" else base)
    return "".join(out)


def words_to_int(s: str) -> Optional[int]:
    s = s.strip()
    if s.isdigit():
        return int(s)
    toks = [t for t in s.split() if t != "et"]
    if not toks:
        return None
    total, i = 0, 0
    while i < len(toks):
        if toks[i] == "quatre" and i + 1 < len(toks) and toks[i + 1] in ("vingt", "vingts"):
            total += 80
            i += 2
            continue
        if toks[i] not in _UNITS:
            return None
        total += _UNITS[toks[i]]
        i += 1
    return total


def _fmt_hour(h: int, m: int) -> str:
    return f"{h} heures" if m == 0 else f"{h} h {m:02d}"


def spoken_when(due: datetime.datetime) -> str:
    now = clock.now()
    delta = (due - now).total_seconds()
    if delta < 90:
        return f"dans {max(int(round(delta)), 1)} secondes"
    if abs(delta - 3600) < 120:
        return "dans une heure"
    if delta < 90 * 60:
        return f"dans {int(round(delta / 60))} minutes"
    days = (due.date() - now.date()).days
    hour = _fmt_hour(due.hour, due.minute)
    if days == 0:
        return f"à {hour}"
    if days == 1:
        return f"demain à {hour}"
    if days < 7:
        return f"{JOURS[due.weekday()]} à {hour}"
    return f"le {due.day}/{due.month} à {hour}"


def spoken_duration(seconds: int) -> str:
    if seconds < 120:
        return f"{seconds} secondes"
    if seconds < 90 * 60 and seconds % 3600:
        return f"{round(seconds / 60)} minutes"
    hours, rest = divmod(seconds // 60, 60)
    return f"{hours} heures" if not rest else f"{hours} h {rest:02d}"


def personalize(message: str) -> str:
    """« téléphoner à mes amis » -> « téléphoner à tes amis » (c'est Jarvis qui parle a l'utilisateur)."""
    for pat, rep in ((r"\bmes\b", "tes"), (r"\bmon\b", "ton"), (r"\bma\b", "ta"), (r"\bmoi\b", "toi"),
                     (r"\bm['’]", "t'"), (r"\bme\b", "te"), (r"\bje\b", "tu"), (r"\bj['’]", "tu ")):
        message = re.sub(pat, rep, message, flags=re.I)
    return message


# ---------------------------------------------------------------------------------------------- comprehension du temps
_NUMW = "|".join(sorted(_UNITS, key=len, reverse=True))
_NUM = rf"(?:\d+|(?<![a-z])(?:{_NUMW})(?![a-z])(?: (?:et )?(?:{_NUMW})(?![a-z])){{0,3}})"
_UNIT_SECONDS = {"seconde": 1, "minute": 60, "heure": 3600, "jour": 86400}


def _duration(f: str, need_dans: bool = True):
    """Delai relatif -> (secondes, (debut, fin)) ou None."""
    prefix = r"\bdans\s+" if need_dans else r"(?:\bdans\s+|\bde\s+|\bpour\s+|\b)"
    m = re.search(prefix + r"un quart d heure\b", f)
    if m:
        return 900, m.span()
    m = re.search(prefix + r"(?:une )?demi heure\b", f)
    if m:
        return 1800, m.span()
    m = re.search(prefix + rf"({_NUM}) (heures?|h) et (demie?|quart)\b", f)
    if m and words_to_int(m.group(1)) is not None:
        return words_to_int(m.group(1)) * 3600 + (1800 if m.group(3).startswith("demi") else 900), m.span()
    m = re.search(prefix + rf"({_NUM}) (?:heures?|h) ?(\d{{1,2}})\b", f)
    if m and words_to_int(m.group(1)) is not None and not need_dans:
        return words_to_int(m.group(1)) * 3600 + int(m.group(2)) * 60, m.span()
    m = re.search(prefix + rf"({_NUM}) (secondes?|minutes?|heures?|jours?|min|sec)\b", f)
    if m:
        n = words_to_int(m.group(1))
        if n is not None:
            unit = {"min": "minute", "sec": "seconde"}.get(m.group(2), m.group(2).rstrip("s"))
            return n * _UNIT_SECONDS[unit], m.span()
    return None


def _clock_time(f: str):
    """Heure explicite -> (h, m, span) ou None. Gere « 18h30 », « 18 heures », « midi », « minuit », « six heures et demie »."""
    m = re.search(r"\b(midi|minuit)\b(?: et (demi|quart))?", f)
    if m:
        h = 12 if m.group(1) == "midi" else 0
        return h, {"demi": 30, "quart": 15}.get(m.group(2), 0), m.span()
    m = re.search(rf"\b(?:a|vers)\s+({_NUM}) ?(?:heures?|h)(?![a-z])(?: ?(\d{{1,2}})\b| et (demie?|quart)\b| moins le quart\b)?", f)
    if m:
        h = words_to_int(m.group(1))
        if h is not None and 0 <= h <= 24:
            if m.group(2):
                return h % 24, int(m.group(2)), m.span()
            if m.group(3):
                return h % 24, 30 if m.group(3).startswith("demi") else 15, m.span()
            if "moins le quart" in m.group(0):
                return (h - 1) % 24, 45, m.span()
            return h % 24, 0, m.span()
    return None


def parse_when(f: str, now: datetime.datetime):
    """(datetime, [spans]) ou None."""
    rel = _duration(f)
    if rel:
        secs, span = rel
        return now + datetime.timedelta(seconds=secs), [span]

    spans, day_offset, part, weekday = [], None, None, None
    m = re.search(r"\bapres demain\b", f)
    if m:
        day_offset = 2
    else:
        m = re.search(r"\bdemain\b", f)
        if m:
            day_offset = 1
    if m and day_offset is not None:
        spans.append(m.span())
    if day_offset is None:
        m = re.search(r"\b(?:ce|cet) (soir|matin|apres midi)\b|\baujourd hui\b", f)
        if m:
            day_offset = 0
            spans.append(m.span())
            if m.group(1):
                part = m.group(1)
    if day_offset is None:
        for i, jour in enumerate(JOURS):
            m = re.search(rf"\b{jour}(?: prochain)?\b", f)
            if m:
                weekday = i
                spans.append(m.span())
                break
    m = re.search(r"\b(?:du |de l |au |le |en )?(matin|soir|apres midi)\b", f)
    if m and (day_offset is not None or weekday is not None or _clock_time(f)):
        part = part or m.group(1)
        spans.append(m.span())

    ct = _clock_time(f)
    if ct is None and day_offset is None and weekday is None:
        return None
    if ct:
        hour, minute, span = ct
        spans.append(span)
    else:
        hour, minute = {"matin": 9, "apres midi": 15, "soir": 20}.get(part, 9), 0

    if hour <= 11 and part in ("soir", "apres midi"):
        hour += 12
    base = now.replace(second=0, microsecond=0)
    if day_offset is not None:
        target = (base + datetime.timedelta(days=day_offset)).replace(hour=hour, minute=minute)
    elif weekday is not None:
        ahead = (weekday - now.weekday()) % 7
        target = (base + datetime.timedelta(days=ahead)).replace(hour=hour, minute=minute)
        if target <= now:
            target += datetime.timedelta(days=7)
    else:
        target = base.replace(hour=hour, minute=minute)
        if target <= now and hour <= 12 and part is None:      # « à six heures » a 14 h -> 18 h
            alt = target + datetime.timedelta(hours=12)
            if alt > now:
                target = alt
        if target <= now:
            target += datetime.timedelta(days=1)
    return target, spans


# ---------------------------------------------------------------------------------------------- stockage / declenchement
def _save() -> None:
    STORE.parent.mkdir(parents=True, exist_ok=True)
    STORE.write_text(json.dumps(_items, ensure_ascii=False))


def _load() -> None:
    global _items
    try:
        _items = json.loads(STORE.read_text())
    except Exception:
        _items = []


def add(due_ts: float, message: str, kind: str = "reminder") -> dict:
    with _lock:
        item = {"id": int(time.time() * 1000), "due": due_ts, "message": message, "kind": kind}
        _items.append(item)
        _items.sort(key=lambda r: r["due"])
        _save()
    return item


def pending_list() -> list:
    with _lock:
        return list(_items)


def cancel_all() -> int:
    with _lock:
        n = len(_items)
        _items.clear()
        _save()
    return n


def spoken_text(item: dict, late: float = 0.0) -> str:
    if item["kind"] == "timer":
        text = f"Ton minuteur de {item['message']} est terminé."
    elif item["kind"] == "alarm":
        text = "C'est l'heure de te réveiller !" if item["message"] == "réveil" else f"C'est l'heure : {personalize(item['message'])}."
    else:
        text = f"Rappel : {personalize(item['message'])}."
    if late > 180:
        text = f"Je n'ai pas pu te le dire à l'heure : {text[0].lower() + text[1:]}"
    return text


def start(callback) -> None:
    """Lance la surveillance ; `callback(texte_a_dire)` est appele (depuis un thread) a l'heure du rappel."""
    global _callback
    _callback = callback
    _load()

    def loop():
        while True:
            time.sleep(1.0)
            now = clock.timestamp()
            with _lock:
                due = [r for r in _items if r["due"] <= now]
                if due:
                    _items[:] = [r for r in _items if r["due"] > now]
                    _save()
            for r in due:
                try:
                    _callback(spoken_text(r, now - r["due"]))
                except Exception:
                    log.exception("Rappel non delivre")

    threading.Thread(target=loop, daemon=True, name="reminders").start()
    log.info("Rappels : %d en attente", len(_items))


# ---------------------------------------------------------------------------------------------- conversation
_PLACEHOLDER = re.compile(r"^(?:quelque chose|un truc|ca|une chose|quelquechose)$")
_TRIGGER = re.compile(
    r"\b(?:rappelle|rappeler|rappel)\s*(?:moi|toi)?\b|\bfais moi penser\b|\bpenser a\b|\bn oublie pas\b|"
    r"\bprevien(?:s)? moi\b|\breveille moi\b|\b(?:minuteur|minuterie|timer|alarme|reveil)\b|\bchronometre\b")
_CANCEL = re.compile(r"\b(annule|supprime|efface|enleve|retire|oublie)\b.*\b(rappels?|minuteurs?|alarmes?|timers?|reveils?)\b")
_LIST = re.compile(r"\b(quels?|liste|montre|dis moi)\b.*\b(rappels?|minuteurs?|alarmes?)\b|\bmes (rappels|alarmes|minuteurs)\b|"
                   r"\bcombien de temps (?:reste|il reste)\b")
_GIVE_UP = re.compile(r"\b(laisse tomber|tant pis|annule|oublie|non merci|finalement non|stop|cancel|rien|aucun|aucune|"
                      r"pas de rappel|pas la peine|pas besoin|ca ira|plus la peine)\b")


def _clean_message(orig: str, f: str, spans: list, trigger_span) -> str:
    keep = [True] * len(orig)
    for a, b in list(spans) + [trigger_span]:
        for i in range(a, min(b, len(orig))):
            keep[i] = False
    text = "".join(c for c, k in zip(orig, keep) if k)
    text = re.sub(r"\bs['’ ]?il (?:te|vous) pla[iî]t\b", " ", text, flags=re.I)
    text = re.sub(r"^\W*(?:jarvis|hey jarvis)\W*", "", text.strip(), flags=re.I)
    text = re.sub(r"\s+", " ", text).strip(" ,.;:!?-")
    text = re.sub(r"^(?:de\s+|d['’]\s*|que\s+|qu['’]\s*|pour\s+|à\s+|a\s+|le fait de\s+)", "", text, flags=re.I).strip(" ,.;:!?-")
    if _PLACEHOLDER.match(fold(text).strip()):
        return ""
    return text


def _create(kind: str, message: str, due: datetime.datetime) -> str:
    add(due.timestamp(), message, kind)
    when = spoken_when(due)
    if kind == "timer":
        return f"C'est parti, minuteur de {message}."
    if kind == "alarm":
        return f"Alarme réglée {when}." if message == "réveil" else f"C'est noté, {when} : {personalize(message)}."
    return f"C'est noté, je te rappellerai {when} : {personalize(message)}."


def _ask_time(message: str, kind: str) -> str:
    global _pending
    _pending = {"message": message, "when": None, "kind": kind, "ts": time.time()}
    return "D'accord. Pour quand ? Par exemple dans dix minutes, ou demain à neuf heures ?"


def _ask_message(when: datetime.datetime) -> str:
    global _pending
    _pending = {"message": None, "when": when, "kind": "reminder", "ts": time.time()}
    return f"D'accord, {spoken_when(when)}. De quoi dois-je te rappeler ?"


_UNSURE = re.compile(r"\bje (?:ne )?(?:sais|saurais) (?:pas|plus)\b|\bsais pas\b|\baucune idee\b|\bpeu importe\b|\bn importe\b|"
                     r"\bcomme tu veux\b|\bchoisis\b|\ba toi de voir\b|\btu decides\b|\bje ne me rappelle plus\b")
_YES = re.compile(r"^ ?(?:oui|ouais|ok|d accord|bien sur|volontiers|vas y|c est bon|parfait|avec plaisir|yes|ca marche|pourquoi pas)\b")
_NO = re.compile(r"^ ?(?:non|nan|nope|pas vraiment|pas comme ca)\b")
DEFAULT_MESSAGE = "c'est l'heure de ton rappel"


def _propose(p: dict, due: datetime.datetime, message: str, lead: str) -> str:
    global _pending
    _pending = dict(p, ts=time.time(), proposal={"kind": p["kind"], "message": message, "due": due})
    return f"{lead} Je te propose {spoken_when(due)}, ça te va ?"


def _handle_pending(text: str) -> Optional[str]:
    global _pending
    p, _pending = _pending, None
    f = fold(text)
    now = clock.now()

    if p.get("proposal"):                       # Jarvis a propose quelque chose : oui / non / autre heure
        pr = p["proposal"]
        if _YES.search(f) and not _NO.search(f):
            return _create(pr["kind"], pr["message"], pr["due"])
        if _NO.search(f) and not parse_when(f, now):
            _pending = dict(p, ts=time.time(), proposal=None)
            return "D'accord. Alors dis-moi quand : par exemple dans une heure, ou demain matin ?"
        p = dict(p, proposal=None)
    if _GIVE_UP.search(f):
        return "D'accord, j'annule."

    def retry(hint: str) -> str:
        global _pending
        if p.get("retried"):
            return "Pas de souci, on laisse tomber pour l'instant. Redis-moi quand tu veux."
        _pending = dict(p, ts=time.time(), retried=True)
        return f"Je n'ai pas bien saisi. {hint}"

    if p.get("timer"):                          # « pour combien de temps ? »
        dur = _duration(f, need_dans=False)
        if dur:
            return _create("timer", spoken_duration(dur[0]), now + datetime.timedelta(seconds=dur[0]))
        if _UNSURE.search(f):
            return _propose(p, now + datetime.timedelta(minutes=10), spoken_duration(600), "Pas de souci.")
        return retry("Dis-moi une durée, par exemple cinq minutes ou une heure.")

    if p.get("need_message_first"):             # « de quoi ? » (ni message ni heure au depart)
        if _UNSURE.search(f):
            _pending = {"message": DEFAULT_MESSAGE, "when": None, "kind": "reminder", "ts": time.time()}
            return "Pas de souci, je te dirai simplement que c'est l'heure. Pour quand ?"
        parsed = parse_when(f, now)
        message = _clean_message(text, f, parsed[1] if parsed else [], (0, 0))
        if parsed and not message:
            return _ask_message(parsed[0])
        message = message or text.strip(" .!?")
        return _create("reminder", message, parsed[0]) if parsed else _ask_time(message, "reminder")

    if p["when"] is None:                       # « pour quand ? »
        parsed = parse_when(f, now)
        if parsed:
            return _create(p["kind"], p["message"], parsed[0])
        if _UNSURE.search(f):
            if p["kind"] == "alarm":
                tomorrow = (now + datetime.timedelta(days=1)).replace(hour=7, minute=0, second=0, microsecond=0)
                return _propose(p, tomorrow, p["message"], "Pas de souci.")
            return _propose(p, now + datetime.timedelta(hours=1), p["message"], "Pas de souci.")
        return retry("Tu peux me dire par exemple « dans une heure » ou « demain à neuf heures » ?")

    if _UNSURE.search(f):                       # « de quoi ? » -> pas d'idee : rappel sans message
        return _create(p["kind"], DEFAULT_MESSAGE, p["when"])
    message = _clean_message(text, f, [], (0, 0)) or text.strip(" .!?")
    return _create(p["kind"], message, p["when"])


def handle(text: str) -> Optional[str]:
    """Renvoie la reponse si `text` concerne les rappels/minuteurs/alarmes, sinon None."""
    global _pending
    if _pending is not None:
        if time.time() - _pending["ts"] > PENDING_TTL:
            _pending = None
        else:
            return _handle_pending(text)

    f = fold(text)
    if _CANCEL.search(f):
        n = cancel_all()
        return "J'ai tout annulé." if n else "Il n'y avait aucun rappel en attente."
    if _LIST.search(f):
        items = pending_list()
        if not items:
            return "Tu n'as aucun rappel ni minuteur en attente."
        parts = []
        for r in items[:5]:
            when = spoken_when(datetime.datetime.fromtimestamp(r["due"], clock.TIMEZONE))
            what = f"minuteur de {r['message']}" if r["kind"] == "timer" else personalize(r["message"])
            parts.append(f"{what}, {when}")
        return "Tu as : " + " ; ".join(parts) + "."

    m = _TRIGGER.search(f)
    if not m:
        return None
    now = clock.now()
    word = m.group(0)
    if re.search(r"\b(minuteur|minuterie|timer|chronometre)\b", word):
        dur = _duration(f, need_dans=False)
        if not dur:
            return _ask_duration()
        secs = dur[0]
        return _create("timer", spoken_duration(secs), now + datetime.timedelta(seconds=secs))

    kind = "alarm" if re.search(r"\b(alarme|reveil|reveille moi)\b", word) else "reminder"
    parsed = parse_when(f, now)
    spans = parsed[1] if parsed else []
    if kind == "alarm":
        message = "réveil"
    else:
        message = _clean_message(text, f, spans, m.span())
    if parsed is None:
        if kind == "alarm":
            return _ask_time("réveil", "alarm")
        return _ask_time(message, "reminder") if message else _ask_message_or_time()
    if not message:
        return _ask_message(parsed[0])
    return _create(kind, message, parsed[0])


def _ask_duration() -> str:
    global _pending
    _pending = {"message": "", "when": None, "kind": "timer", "ts": time.time(), "timer": True}
    return "Pour combien de temps, le minuteur ?"


def _ask_message_or_time() -> str:
    global _pending
    _pending = {"message": None, "when": None, "kind": "reminder", "ts": time.time(), "need_message_first": True}
    return "Bien sûr. De quoi dois-je te rappeler ?"
