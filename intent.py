"""Commandes courantes traitees directement (sans LLM) : volume, son, chaines.

Le petit modele local est peu fiable sur ces phrases (il vise le volume du PC au lieu de celui de la
television, ou n'appelle aucun outil). Ici : reconnaissance par motifs, execution immediate.
"""
import re
import unicodedata
from typing import Optional

from tools import dispatch_tool, freebox_remote

STEP = 5          # pas de volume de la television LG (sur 100)
PLAYER_STEPS = 3  # crans de volume du Player par demande

CHANNELS = {
    "tf1": 1, "france 2": 2, "france 3": 3, "canal+": 4, "canal plus": 4, "france 5": 5, "m6": 6, "arte": 7,
}

_PC_WORDS = ("ordinateur", " pc", "portable", "machine")
_TV_WORDS = (" tele ", " television ", " tv ", " lg ")
_UP = r"(augmente|monte|remonte|hausse|renforce|plus fort|plus haut)"
_DOWN = r"(baisse|diminue|reduis|descend|moins fort|moins haut|plus bas)"


_remote_display = None  # callback(visible: bool), branche par main.py


def register_remote_display(callback) -> None:
    global _remote_display
    _remote_display = callback


def _norm(text: str) -> str:
    text = unicodedata.normalize("NFD", text.lower())
    text = "".join(c for c in text if unicodedata.category(c) != "Mn")
    text = re.sub(r"[-'’,.!?]", " ", text)
    return " " + re.sub(r"\s+", " ", text).strip() + " "


def _tv_volume() -> Optional[int]:
    res = dispatch_tool("tv_control", {"action": "status"})
    return res.get("volume") if res.get("success") else None


def _volume(direction: str, level: Optional[int], target: str) -> str:
    """target: 'player' (defaut, c'est le volume qu'on entend), 'tv' (LG) ou 'pc'."""
    if target == "player":
        if level is not None:
            return ("Je ne peux pas régler le volume du Player à un niveau précis, seulement le monter ou le "
                    "baisser. Dis « volume de la télé à " + str(level) + " » pour la télé LG.")
        key = "VOLUMEUP" if direction == "up" else "VOLUMEDOWN"
        if freebox_remote.fb_button(key, PLAYER_STEPS).get("success"):
            return "Volume " + ("augmenté." if direction == "up" else "baissé.")
        target = "tv"  # Player injoignable -> television LG
    if target == "tv":
        current = _tv_volume()
        if current is not None:
            if level is None:
                level = current + STEP if direction == "up" else current - STEP
            level = max(0, min(100, level))
            res = dispatch_tool("tv_control", {"action": "set_volume", "value": str(level)})
            if res.get("success"):
                return f"Volume de la télé à {level}."
    # PC (demande explicite, ou rien d'autre de joignable)
    if level is not None:
        dispatch_tool("system_volume", {"action": "set", "level": level})
        return f"Volume de l'ordinateur à {level}."
    dispatch_tool("system_volume", {"action": direction})
    return "Volume de l'ordinateur " + ("augmenté." if direction == "up" else "baissé.")


def _mute(mute: bool, target: str) -> str:
    verb = "coupé" if mute else "rétabli"
    if target == "player":
        if freebox_remote.fb_button("MUTE").get("success"):
            return f"Son {verb} (touche muet du Player, elle bascule)."
        target = "tv"
    if target == "tv":
        res = dispatch_tool("tv_control", {"action": "mute" if mute else "unmute"})
        if res.get("success"):
            return f"Son de la télé {verb}."
    dispatch_tool("system_volume", {"action": "mute" if mute else "unmute"})
    return f"Son de l'ordinateur {verb}."


def try_fast_intent(text: str) -> Optional[str]:
    """Renvoie la reponse a dire si la phrase est une commande courante, sinon None (-> LLM)."""
    t = _norm(text)

    if _remote_display and re.search(r"telecommande", t):
        if re.search(r"\b(ferme|fermer|cache|cacher|masque|masquer|retire|enleve|efface|supprime)\b", t):
            _remote_display(False)
            return "Télécommande fermée."
        if re.search(r"\b(ouvre|ouvrir|affiche|afficher|montre|montrer)\b", t):
            _remote_display(True)
            return "Télécommande affichée."

    if any(w in t for w in _PC_WORDS):
        target = "pc"
    elif any(w in t for w in _TV_WORDS):
        target = "tv"
    else:
        target = "player"

    m = re.search(r" (?:volume|son) (?:.{0,25}? )?(?:a|sur|au niveau|de) (\d{1,3}) ", t)
    if m and re.search(r"(mets|met|regle|passe|monte|baisse|mettre)", t):
        return _volume("up", min(100, int(m.group(1))), target)

    if re.search(r" (coupe (le )?(son|volume)|mute|met(s)? (en )?sourdine|sourdine) ", t):
        return _mute(True, target)
    if re.search(r"(remets|retablis|reactive|reactives|remet) (le )?son", t):
        return _mute(False, target)

    if re.search(_DOWN + r".*\b(volume|son)\b|" + r"\b(volume|son)\b.*" + _DOWN + "|^ moins fort ", t):
        return _volume("down", None, target)
    if re.search(_UP + r".*\b(volume|son)\b|" + r"\b(volume|son)\b.*" + _UP + "|^ plus fort ", t):
        return _volume("up", None, target)

    if re.search(r"chaine (suivante|d apres|plus)|prochaine chaine", t):
        res = dispatch_tool("tv_control", {"action": "channel_up"})
        return "Chaîne suivante." if res.get("success") else "La Freebox ne répond pas."
    if re.search(r"chaine (precedente|d avant|moins)|derniere chaine|chaine d avant", t):
        res = dispatch_tool("tv_control", {"action": "channel_down"})
        return "Chaîne précédente." if res.get("success") else "La Freebox ne répond pas."

    m = re.search(r"(?:mets|met|passe|va|allume|affiche|change).{0,25}?(?:chaine )?(\d{1,3}) ", t)
    if m and ("chaine" in t or re.search(r"(mets|met|passe) (sur |a |la )?\d", t)):
        num = int(m.group(1))
        res = dispatch_tool("tv_control", {"action": "goto_channel", "value": str(num)})
        return f"Chaîne {num}." if res.get("success") else "La Freebox ne répond pas."

    for name, num in CHANNELS.items():
        if re.search(r"(mets|met|passe|va|affiche|regarder|regarde).{0,15} " + re.escape(name) + " ", t):
            res = dispatch_tool("tv_control", {"action": "goto_channel", "value": str(num)})
            return f"{name.upper() if len(name) <= 3 else name.title()}, chaîne {num}." \
                if res.get("success") else "La Freebox ne répond pas."
    return None
