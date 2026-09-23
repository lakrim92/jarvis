"""Declaration des outils exposes au LLM (function calling Ollama) + dispatch."""
from . import apps, web, system, organize

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
    "open_path": lambda args: apps.open_path(args["path"]),
    "web_search": lambda args: web.web_search(args["query"], args.get("num_results", 5)),
    "get_distance": lambda args: web.get_distance(args["origin"], args["destination"]),
    "organize_folder": lambda args: organize.organize_folder(args["folder"]),
    "get_weather": lambda args: web.get_weather(args.get("city", "")),
    "system_volume": lambda args: system.system_volume(args["action"], args.get("level")),
    "system_brightness": lambda args: system.system_brightness(args["action"], args.get("level")),
    "lock_screen": lambda args: system.lock_screen(),
    "take_screenshot": lambda args: system.take_screenshot(),
    "get_datetime": lambda args: system.get_datetime(),
    "set_reminder": lambda args: system.set_reminder(args["seconds"], args["message"]),
}


def dispatch_tool(name: str, arguments: dict) -> dict:
    handler = _DISPATCH.get(name)
    if not handler:
        return {"success": False, "error": f"Outil inconnu : {name}"}
    try:
        return handler(arguments or {})
    except Exception as exc:
        return {"success": False, "error": str(exc)}
