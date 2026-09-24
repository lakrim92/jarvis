"""Declaration des outils exposes au LLM (function calling Ollama) + dispatch."""
from . import apps, web, system, organize, lg_tv, freebox_remote, freebox_channels


def _dispatch_tv_control(args: dict) -> dict:
    action = args.get("action")
    value = args.get("value")
    if action == "set_volume":
        return lg_tv.tv_set_volume(int(value))
    if action == "volume_up":
        return lg_tv.tv_volume_step("up")
    if action == "volume_down":
        return lg_tv.tv_volume_step("down")
    if action == "mute":
        return lg_tv.tv_mute(True)
    if action == "unmute":
        return lg_tv.tv_mute(False)
    if action == "power_off":
        return lg_tv.tv_power_off()
    if action == "launch_app":
        return lg_tv.tv_launch_app(value)
    if action == "channel_up":
        return freebox_remote.fb_button("CHANNELUP", int(value or 1))
    if action == "channel_down":
        return freebox_remote.fb_button("CHANNELDOWN", int(value or 1))
    if action == "goto_channel":
        if str(value).strip().isdigit():
            return freebox_remote.fb_goto_channel(value)
        channel = freebox_channels.find_channel(str(value))
        if not channel:
            return {"success": False, "error": f"Chaine introuvable dans la liste de la Freebox : {value}"}
        result = freebox_remote.fb_goto_channel(channel["number"])
        return {**result, "name": channel["name"]}
    if action == "button":
        return freebox_remote.fb_button(value, int(args.get("repeat", 1)))
    if action == "status":
        return lg_tv.tv_status()
    return {"success": False, "error": f"Action TV inconnue : {action}"}


TOOLS_SCHEMA = [
    {
        "type": "function",
        "function": {
            "name": "open_application",
            "description": "Ouvre/lance une application installee sur l'ordinateur (ex: 'firefox', 'nautilus', 'gimp').",
            "parameters": {
                "type": "object",
                "properties": {
                    "name": {"type": "string", "description": "Nom de l'application a lancer."}
                },
                "required": ["name"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "create_spreadsheet",
            "description": "Cree un tableau (fichier tableur .xlsx dans Documents) avec un nombre de colonnes et de lignes, "
                           "puis l'ouvre dans LibreOffice Calc. A utiliser pour toute demande de creation de tableau.",
            "parameters": {
                "type": "object",
                "properties": {
                    "columns": {"type": "integer", "description": "Nombre de colonnes."},
                    "rows": {"type": "integer", "description": "Nombre de lignes (hors en-tete)."},
                    "headers": {"type": "array", "items": {"type": "string"}, "description": "Titres des colonnes (optionnel)."},
                    "title": {"type": "string", "description": "Nom du fichier (optionnel)."},
                },
                "required": ["columns", "rows"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "close_window",
            "description": "Ferme une fenetre ouverte (application ou dossier) d'apres son nom. "
                           "Pour fermer les fenetres de dossiers : folders=true.",
            "parameters": {
                "type": "object",
                "properties": {
                    "name": {"type": "string", "description": "Nom de l'application ou du dossier a fermer."},
                    "folders": {"type": "boolean", "description": "true pour fermer des fenetres de dossiers."},
                },
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "open_path",
            "description": "Ouvre un fichier ou un dossier avec l'application par defaut (equivalent d'un double-clic).",
            "parameters": {
                "type": "object",
                "properties": {
                    "path": {"type": "string", "description": "Chemin du fichier ou dossier a ouvrir."}
                },
                "required": ["path"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "web_search",
            "description": "Fait une recherche sur le web et renvoie les resultats (titre, url, extrait) a resumer pour l'utilisateur.",
            "parameters": {
                "type": "object",
                "properties": {
                    "query": {"type": "string", "description": "Termes de recherche."},
                    "num_results": {"type": "integer", "description": "Nombre de resultats souhaites (defaut 5)."},
                },
                "required": ["query"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "get_distance",
            "description": "Calcule la distance routiere reelle et la duree de trajet entre deux lieux (villes, adresses). "
                           "A utiliser SYSTEMATIQUEMENT pour toute question de distance/kilometrage : ne jamais estimer une distance de memoire.",
            "parameters": {
                "type": "object",
                "properties": {
                    "origin": {"type": "string", "description": "Lieu de depart."},
                    "destination": {"type": "string", "description": "Lieu d'arrivee."},
                },
                "required": ["origin", "destination"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "organize_folder",
            "description": "Trie automatiquement les fichiers en vrac d'un dossier (ex: Telechargements, Images) "
                           "dans des sous-dossiers par type (Images, Documents, Videos, Audio, Archives, Installateurs, Autres). "
                           "A utiliser quand l'utilisateur demande de ranger/trier/organiser un dossier.",
            "parameters": {
                "type": "object",
                "properties": {
                    "folder": {"type": "string", "description": "Nom ou chemin du dossier a trier (ex: 'Telechargements', 'Images', '~/Downloads')."}
                },
                "required": ["folder"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "tv_control",
            "description": "Controle la television LG (volume TV, son, extinction, applications TV comme Netflix) et la Freebox "
                           "Player (changer de chaine : suivante, precedente ou numero precis ; navigation) quand tout "
                           "est deja allume. "
                           "Ne peut PAS allumer la TV ni la Freebox depuis l'etat eteint.",
            "parameters": {
                "type": "object",
                "properties": {
                    "action": {
                        "type": "string",
                        "enum": ["set_volume", "volume_up", "volume_down", "mute", "unmute",
                                 "power_off", "launch_app", "channel_up", "channel_down",
                                 "goto_channel", "button", "status"],
                    },
                    "value": {
                        "type": "string",
                        "description": "Pour 'set_volume' : niveau 0-100. Pour 'launch_app' : nom de l'application. "
                                       "Pour 'channel_up'/'channel_down' : nombre de chaines a sauter (defaut 1). "
                                       "Pour 'goto_channel' : nom (ex: 'Paris Premiere', 'BFM TV') ou numero de chaine. "
                                       "Pour 'button' (Freebox) : UP, DOWN, LEFT, RIGHT, ENTER, BACK, HOME, MENU, INFO, GUIDE, TV, VOLUMEUP, VOLUMEDOWN, MUTE (volume du Player = celui qu'on entend).",
                    },
                },
                "required": ["action"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "get_weather",
            "description": "Donne la meteo actuelle pour une ville (ou la position par defaut si vide).",
            "parameters": {
                "type": "object",
                "properties": {
                    "city": {"type": "string", "description": "Nom de la ville. Laisser vide pour la position par defaut."}
                },
                "required": [],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "system_volume",
            "description": "Controle le volume sonore du systeme.",
            "parameters": {
                "type": "object",
                "properties": {
                    "action": {"type": "string", "enum": ["set", "up", "down", "mute", "unmute"]},
                    "level": {"type": "integer", "description": "Niveau cible 0-100, uniquement pour action='set'."},
                },
                "required": ["action"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "system_brightness",
            "description": "Controle la luminosite de l'ecran.",
            "parameters": {
                "type": "object",
                "properties": {
                    "action": {"type": "string", "enum": ["set", "up", "down"]},
                    "level": {"type": "integer", "description": "Niveau cible 0-100, uniquement pour action='set'."},
                },
                "required": ["action"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "lock_screen",
            "description": "Verrouille l'ecran de l'ordinateur.",
            "parameters": {"type": "object", "properties": {}, "required": []},
        },
    },
    {
        "type": "function",
        "function": {
            "name": "take_screenshot",
            "description": "Prend une capture d'ecran et l'enregistre dans le dossier Images/Jarvis.",
            "parameters": {"type": "object", "properties": {}, "required": []},
        },
    },
    {
        "type": "function",
        "function": {
            "name": "get_datetime",
            "description": "Renvoie la date et l'heure actuelles.",
            "parameters": {"type": "object", "properties": {}, "required": []},
        },
    },
    {
        "type": "function",
        "function": {
            "name": "set_reminder",
            "description": "Programme un rappel/minuteur qui sera annonce a voix haute apres un delai donne.",
            "parameters": {
                "type": "object",
                "properties": {
                    "seconds": {"type": "integer", "description": "Delai en secondes avant l'annonce du rappel."},
                    "message": {"type": "string", "description": "Le message du rappel a annoncer."},
                },
                "required": ["seconds", "message"],
            },
        },
    },
]

_DISPATCH = {
    "open_application": lambda args: apps.open_application(args["name"]),
    "create_spreadsheet": lambda args: apps.create_spreadsheet(
        args.get("columns", 3), args.get("rows", 10), args.get("headers"), args.get("title", "")),
    "close_window": lambda args: apps.close_window(args.get("name", ""), bool(args.get("folders", False))),
    "open_path": lambda args: apps.open_path(args["path"]),
    "web_search": lambda args: web.web_search(args["query"], args.get("num_results", 5)),
    "get_distance": lambda args: web.get_distance(args["origin"], args["destination"]),
    "organize_folder": lambda args: organize.organize_folder(args["folder"]),
    "tv_control": lambda args: _dispatch_tv_control(args),
    "get_weather": lambda args: web.get_weather(args.get("city", "")),
    "system_volume": lambda args: system.system_volume(args["action"], args.get("level")),
    "system_brightness": lambda args: system.system_brightness(args["action"], args.get("level")),
    "lock_screen": lambda args: system.lock_screen(),
    "take_screenshot": lambda args: system.take_screenshot(),
    "get_datetime": lambda args: system.get_datetime(),
    "set_reminder": lambda args: system.set_reminder(args["seconds"], args["message"]),
}


_dispatch_hook = None


def set_dispatch_hook(callback) -> None:
    """callback(nom_outil, arguments, resultat) : appele apres chaque outil execute (journal d'apprentissage)."""
    global _dispatch_hook
    _dispatch_hook = callback


def dispatch_tool(name: str, arguments: dict) -> dict:
    handler = _DISPATCH.get(name)
    if not handler:
        result = {"success": False, "error": f"Outil inconnu : {name}"}
    else:
        try:
            result = handler(arguments or {})
        except Exception as exc:
            result = {"success": False, "error": str(exc)}
    if _dispatch_hook:
        try:
            _dispatch_hook(name, arguments or {}, result)
        except Exception:
            pass
    return result
