"""Commandes courantes traitees directement (sans LLM) : volume, son, chaines.

Le petit modele local est peu fiable sur ces phrases (il vise le volume du PC au lieu de celui de la
television, ou n'appelle aucun outil). Ici : reconnaissance par motifs, execution immediate.
"""
import random
import re
import time
import unicodedata
from typing import Optional

import clock
from tools import dispatch_tool, freebox_channels



def _v(*variants: str) -> str:
    return random.choice(variants)


_UP_REPLIES = ("Volume augmenté.", "Voilà, un peu plus fort.", "C'est fait, je monte le son.")
_DOWN_REPLIES = ("Volume baissé.", "Voilà, un peu moins fort.", "C'est fait, je baisse le son.")

STEP = 5          # pas de volume de la television LG (sur 100)
PLAYER_STEPS = 3  # crans de volume du Player par demande

# Mots trop generiques pour etre pris pour un nom de chaine.
_NOT_CHANNELS = {"son", "volume", "musique", "video", "film", "tele", "television", "tv", "radio", "info", "sport"}
_PC_WORDS = ("ordinateur", " pc", "portable", "machine")
_TV_WORDS = (" tele ", " television ", " tv ", " lg ")
_UP = r"(augmente|monte|remonte|hausse|renforce|plus fort|plus haut)"
_DOWN = r"(baisse|diminue|reduis|descend|moins fort|moins haut|plus bas)"


_remote_display = None  # callback(visible: bool), branche par main.py
_session = None         # callback("stop" | "sleep"), branche par main.py
_voice = None           # callback(kind, arg) -> reponse, branche par main.py (gestion des voix)


def register_voice_callback(callback) -> None:
    global _voice
    _voice = callback


def register_session_callback(callback) -> None:
    global _session
    _session = callback


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
        res = dispatch_tool("tv_control", {"action": "button", "value": key, "repeat": PLAYER_STEPS})
        if res.get("success"):
            return _v(*(_UP_REPLIES if direction == "up" else _DOWN_REPLIES))
        target = "tv"  # Player injoignable -> television LG
    if target == "tv":
        current = _tv_volume()
        if current is not None:
            if level is None:
                level = current + STEP if direction == "up" else current - STEP
            level = max(0, min(100, level))
            res = dispatch_tool("tv_control", {"action": "set_volume", "value": str(level), "previous": current})
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
        if dispatch_tool("tv_control", {"action": "button", "value": "MUTE"}).get("success"):
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

    if _session:
        if re.search(r"\btais toi\b|\bca suffit\b|\barrete de parler\b|\bchut\b|"
                     r"^ (?:jarvis )?(?:silence|stop|arrete|tais toi)(?: jarvis)? $", t):
            _session("stop")
            return ""
        if re.search(r"\bau revoir\b|\bbonne nuit\b|\ba plus tard\b|\ba bientot\b|\ba demain\b|\bciao\b|\bbye\b|"
                     r"^ (?:jarvis )?a plus(?: jarvis)? $", t):
            _session("sleep")
            hour = clock.now().hour
            if "bonne nuit" in t or hour >= 21 or hour < 5:
                return _v("Bonne nuit !", "Bonne nuit, à demain.", "Dors bien !")
            return _v("Au revoir, à tout à l'heure !", "À bientôt !", "Je reste dans mon coin, appelle-moi quand tu veux.")

    # Heure et date : reponse directe sur l'heure REELLE (l'horloge du PC peut etre fausse).
    if re.search(r"\bquelle heure\b|\bl heure qu il est\b|\bl heure actuelle\b|\bdis moi l heure\b", t):
        return clock.spoken_time()
    if re.search(r"\bquel jour (?:sommes|est on|on est|est il)\b|\bquelle est la date\b|\bon est le combien\b|"
                 r"\bla date d aujourd hui\b|\bquel jour on est\b", t):
        return clock.spoken_date()

    if _voice:
        who = re.search(r"\bvoix\s+(?:de|d['’]|pour)\s*([\wÀ-ÿ-]+)", text, re.I)
        name = who.group(1).strip().title() if who else None
        if re.search(r"\b(enregistre|apprends|memorise|ajoute|reconnais|mets a jour|actualise)\b.*\b(voix|empreinte vocale)\b", t):
            if re.search(r"\b(ma voix|mon empreinte|ma propre voix|la mienne)\b", t) or re.search(r"mets a jour|actualise", t):
                return _voice("enroll", None)
            return _voice("enroll", name) if name else _voice("enroll_who", None)
        if re.search(r"(quelles?|combien de|liste (des|les)) voix|qui reconnais tu|qui connais tu", t):
            return _voice("list", None)
        if re.search(r"\b(supprime|efface|oublie|retire)\b.*\bvoix\b", t) and name:
            return _voice("remove", name)
        if re.search(r"\b(desactive|arrete|coupe|suspends)\b.*\b(reconnaissance|verification)\b.*\b(voix|vocale)\b", t):
            return _voice("pause", None)
        if re.search(r"\b(reactive|remets|active|relance)\b.*\b(reconnaissance|verification)\b.*\b(voix|vocale)\b", t):
            return _voice("resume", None)

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

    # Le micro capte aussi la television : on cherche la commande n'importe ou dans la phrase.
    if re.search(r"chaine (precedente|d avant|moins|en dessous|du dessous)|derniere chaine|la precedente|"
                 r"(baisse|descends?|diminue|recule|reviens? (a|sur))( de| la| une| a la)? chaine", t):
        res = dispatch_tool("tv_control", {"action": "channel_down"})
        return _v("Chaîne précédente.", "Je reviens en arrière.", "Hop, la précédente.") if res.get("success") \
            else "La Freebox ne répond pas."
    if re.search(r"chaine (suivante|d apres|plus|au dessus|du dessus)|prochaine chaine|la suivante|^ zappe "
                 r"(change|changer|zappe|zapper|monte|augmente|avance|passe)( de| la| une| a la)? chaine\b(?! \d)", t):
        res = dispatch_tool("tv_control", {"action": "channel_up"})
        return _v("Chaîne suivante.", "On passe à la suivante.", "Hop, la chaîne suivante.") if res.get("success") \
            else "La Freebox ne répond pas."

    m = re.search(r"\b(?:numero|chaine|canal|programme) (\d{1,3})\b", t)
    if m:
        num = int(m.group(1))
        res = dispatch_tool("tv_control", {"action": "goto_channel", "value": str(num)})
        return _v(f"Chaîne {num}.", f"Je mets la {num}.") if res.get("success") else "La Freebox ne répond pas."

    m = re.search(
        r"^ (?:mets|met|mettre|passe|passer|va|aller|affiche|afficher|regarde|regarder|lance|bascule|change|zappe)"
        r" (?:(?:moi|sur|a|en|la|le|les|l|chaine|de|pour|voir) )*(.+?)"
        r"(?: (?:s il te plait|s il vous plait|stp|svp|maintenant))? $", t)
    if m and m.group(1) not in _NOT_CHANNELS:
        channel = freebox_channels.find_channel(m.group(1))
        if channel:
            res = dispatch_tool("tv_control", {"action": "goto_channel", "value": str(channel["number"]),
                                               "name": channel["name"]})
            if res.get("success"):
                return _v(f"{channel['name']}, chaîne {channel['number']}.", f"C'est parti pour {channel['name']}.",
                          f"Je mets {channel['name']}.")
            return "La Freebox ne répond pas."
    return None
