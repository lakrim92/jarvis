"""Commandes courantes traitees directement (sans LLM) : volume, son, chaines.

Le petit modele local est peu fiable sur ces phrases (il vise le volume du PC au lieu de celui de la
television, ou n'appelle aucun outil). Ici : reconnaissance par motifs, execution immediate.
"""
import random
import re
import time
import unicodedata
from pathlib import Path
from typing import Optional

import clock
import reminders
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


_FOLDERS = (
    (r"images?|photos?|pictures?", "Images", "tes images"),
    (r"telechargements?|downloads?", "Téléchargements", "tes téléchargements"),
    (r"documents?", "Documents", "tes documents"),
    (r"bureau", "Bureau", "ton bureau"),
    (r"musiques?", "Musique", "ta musique"),
    (r"videos?", "Vidéos", "tes vidéos"),
    (r"jarvis", "jarvis", "le dossier de Jarvis"),
    (r"personnel|home|maison", "", "ton dossier personnel"),
)


def _open_folder(t: str) -> Optional[str]:
    """« ouvre le dossier images », « affiche-moi mes téléchargements » : action directe (le petit modele
    annoncait parfois l'ouverture sans rien faire)."""
    verb = r"\b(?:ouvre|ouvrir|affiche|afficher|montre|montrer|va dans|va sur|lance)(?: moi)?\b"
    if not re.search(verb, t):
        return None
    for names, folder, label in _FOLDERS:
        explicit = rf"\b(?:dossier|repertoire)\s+(?:de |des |du |d |mes |les |le |la )?(?:{names})\b"
        direct = rf"{verb}\s+(?:mes |les |le |la |mon |ma )(?:{names}) $"
        if re.search(explicit, t) or re.search(direct, t):
            path = str(Path.home() / folder)
            result = dispatch_tool("open_path", {"path": path})
            return f"Voilà, j'ouvre {label}." if result.get("success") else f"Je n'ai pas réussi à ouvrir {label}."
    return None


# Ce que Whisper entend / ce que l'utilisateur dit -> nom exact de l'application (fichier .desktop)
_APP_OPEN = (
    (r"writer|\bword\b|traitement de texte", "LibreOffice Writer", "Writer"),
    (r"\bcalc\b|excel|tableur", "LibreOffice Calc", "Calc"),
    (r"impress|power ?point|presentation|diaporama", "LibreOffice Impress", "Impress"),
    (r"libre ?office|libre fils|libre offis|libre ofice|open office|\boffice\b", "LibreOffice Start Center", "LibreOffice"),
    (r"navigateur|internet|firefox|le web", "Firefox ESR", "Firefox"),
    (r"terminal|console", "Terminal", "le terminal"),
    (r"calculatrice|calculette", "Calculator", "la calculatrice"),
    (r"vlc|lecteur video", "VLC media player", "VLC"),
    (r"gestionnaire de fichiers|explorateur", "Files", "l'explorateur de fichiers"),
)


def _spreadsheet(t: str) -> Optional[str]:
    """« crée un tableau à quatre colonnes et dix lignes » -> fichier tableur ouvert dans Calc."""
    if not re.search(r"\b(cree|creer|fais|faire|genere|generer|prepare|construis|fabrique|ouvre|mets?)\b.*\b(tableau|tableur|feuille de calcul)\b", t):
        return None
    num = r"(\d+|[a-z]+(?: [a-z]+){0,2})"
    cols = re.search(rf"{num} colonnes?", t)
    rows = re.search(rf"{num} lignes?", t)
    n_cols = _to_int(cols.group(1)) if cols else None
    n_rows = _to_int(rows.group(1)) if rows else None
    if n_cols is None and n_rows is None:
        return None                     # pas de dimensions : « ouvre le tableur » est gere ailleurs
    result = dispatch_tool("create_spreadsheet", {"columns": n_cols or 3, "rows": n_rows or 10})
    if not result.get("success"):
        return "Je n'ai pas réussi à créer le tableau."
    return f"Voilà, j'ai créé un tableau de {result['columns']} colonnes et {result['rows']} lignes dans Calc. Il est dans ton dossier Documents."


def _to_int(s: str) -> Optional[int]:
    import reminders
    tokens = s.split()
    for size in range(min(3, len(tokens)), 0, -1):        # « quatre », « vingt et un » : dernier groupe de mots avant l'unite
        value = reminders.words_to_int(" ".join(tokens[-size:]))
        if value:
            return value
    return None


def _open_app(t: str) -> Optional[str]:
    """« ouvre LibreOffice », « lance le navigateur » : lancement direct."""
    m = re.search(r"\b(?:ouvre|ouvrir|lance|lancer|demarre|demarrer)(?: moi)?\b(.*)$", t)
    if not m or re.search(r"dossier|repertoire|fichier |telecommande", t):
        return None
    target = " ".join(re.sub(r"\b(?:le|la|l|les|un|une|mon|ma|s il te plait|application|appli|programme|logiciel)\b", " ",
                             m.group(1)).split())
    if not target:
        return None
    for pattern, app, label in _APP_OPEN:
        if re.search(pattern, target):
            result = dispatch_tool("open_application", {"name": app})
            return f"Voilà, j'ouvre {label}." if result.get("success") else f"Je n'ai pas réussi à ouvrir {label}."
    return None


_APP_ALIASES = {"navigateur": "firefox", "internet": "firefox", "firefox": "firefox", "chrome": "chrome",
                "explorateur": "", "fichiers": ""}


def _close_window(t: str) -> Optional[str]:
    """« ferme le dossier », « ferme le dossier images », « ferme firefox »."""
    m = re.search(r"\b(?:ferme|fermer|quitte|quitter)(?: moi)?\b(.*)$", t)
    if not m or "telecommande" in t or "jarvis" in t:
        return None
    target = re.sub(r"\b(?:le|la|l|les|mon|ma|mes|cette|ce|cet|de|des|du|d|s il te plait|application|appli|programme|fenetre|"
                    r"fenetres|windows?)\b", " ", m.group(1))
    target = " ".join(target.split())
    if re.search(r"tele|freebox|player|ecran|ordinateur|session|volet|porte|lumiere|son\b|musique en cours", target):
        return None                                         # pas une fenetre : on laisse les autres regles / le modele
    if re.fullmatch(r"(?:dossiers?|repertoires?|explorateur|explorateur de fichiers|gestionnaire de fichiers|fichiers|)", target):
        if not target and "fenetre" not in m.group(1):
            return None                                     # « ferme » tout seul : trop vague
        if not target:
            return None                                     # « ferme la fenetre » : laquelle ?
        result = dispatch_tool("close_window", {"folders": True})
        return "C'est fermé." if result.get("success") else "Je ne vois aucun dossier ouvert."
    target = re.sub(r"^(?:dossiers?|repertoires?) ", "", target)
    for names, folder, label in _FOLDERS:
        if re.fullmatch(names, target):
            title = folder or Path.home().name
            result = dispatch_tool("close_window", {"name": title, "folders": True})
            return "C'est fermé." if result.get("success") else f"Je ne vois pas {label} ouvert."
    if target in _APP_ALIASES or re.fullmatch(r"[a-z0-9 ]{3,30}", target):
        query = _APP_ALIASES.get(target, target)
        result = dispatch_tool("close_window", {"name": query})
        return "C'est fermé." if result.get("success") else f"Je ne trouve pas de fenêtre « {target} » ouverte."
    return None


def try_fast_intent(text: str) -> Optional[str]:
    """Renvoie la reponse a dire si la phrase est une commande courante, sinon None (-> LLM).
    Une phrase composee (« mets la chaine 6 et baisse le volume ») est executee clause par clause."""
    reminder = reminders.handle(text)          # avant le decoupage : « rappelle-moi de X et de Y » est une seule demande
    if reminder is not None:
        return reminder
    table = _spreadsheet(_norm(text))          # « 4 colonnes et 10 lignes » : ne pas couper sur le « et »
    if table is not None:
        return table
    clauses = [c.strip(" ,.!?") for c in re.split(r"\s*,?\s+(?:et puis|et|puis|ensuite|apres)\s+", text.strip(), flags=re.I)]
    clauses = [c for c in clauses if c]
    if len(clauses) < 2:
        return _fast_single(text)
    first = _fast_single(clauses[0])
    if first is None:
        return _fast_single(text)       # pas une phrase composee de commandes : traitement normal
    replies = [first]
    for clause in clauses[1:]:
        reply = _fast_single(clause)
        if reply is None:
            replies.append(f"Par contre je n'ai pas compris : {clause}.")
        else:
            replies.append(reply)
    return " ".join(r for r in replies if r)


def _fast_single(text: str) -> Optional[str]:
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

    folder = _open_folder(t)
    if folder is not None:
        return folder
    opening = _open_app(t)
    if opening is not None:
        return opening
    closing = _close_window(t)
    if closing is not None:
        return closing

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
