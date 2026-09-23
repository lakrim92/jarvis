"""Ouverture d'applications et de fichiers."""
import configparser
import difflib
import os
import re
import subprocess
from pathlib import Path

DESKTOP_DIRS = [
    Path("/usr/share/applications"),
    Path("/usr/local/share/applications"),
    Path.home() / ".local/share/applications",
]

_EXEC_FIELD_CODE_RE = re.compile(r"%[a-zA-Z]")


def _iter_desktop_entries():
    for directory in DESKTOP_DIRS:
        if not directory.is_dir():
            continue
        for entry in directory.glob("*.desktop"):
            try:
                parser = configparser.ConfigParser(interpolation=None)
                parser.read(entry, encoding="utf-8")
                if "Desktop Entry" not in parser:
                    continue
                section = parser["Desktop Entry"]
                if section.get("NoDisplay", "false").lower() == "true":
                    continue
                if section.get("Type", "Application") != "Application":
                    continue
                name = section.get("Name")
                exec_cmd = section.get("Exec")
                if not name or not exec_cmd:
                    continue
                yield name, exec_cmd
            except Exception:
                continue


def _find_best_app(query: str):
    query = query.strip().lower()
    entries = list(_iter_desktop_entries())
    names = [name for name, _ in entries]

    for name, exec_cmd in entries:
        if name.lower() == query:
            return name, exec_cmd

    substr_matches = [(n, e) for n, e in entries if query in n.lower()]
    if substr_matches:
        substr_matches.sort(key=lambda x: len(x[0]))
        return substr_matches[0]

    close = difflib.get_close_matches(query, names, n=1, cutoff=0.5)
    if close:
        for name, exec_cmd in entries:
            if name == close[0]:
                return name, exec_cmd
    return None, None


def open_application(name: str) -> dict:
    """Lance une application installee dont le nom se rapproche de `name`."""
    app_name, exec_cmd = _find_best_app(name)
    if not exec_cmd:
        return {"success": False, "error": f"Aucune application trouvee pour '{name}'."}

    clean_cmd = _EXEC_FIELD_CODE_RE.sub("", exec_cmd).strip()
    try:
        subprocess.Popen(
            clean_cmd,
            shell=True,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            start_new_session=True,
        )
        return {"success": True, "app": app_name}
    except Exception as exc:
        return {"success": False, "error": str(exc)}


def open_path(path: str) -> dict:
    """Ouvre un fichier ou un dossier avec l'application par defaut (xdg-open)."""
    expanded = os.path.expanduser(os.path.expandvars(path))
    target = Path(expanded)
    if not target.exists():
        # tente une recherche simple dans le home si le chemin exact n'existe pas
        matches = list(Path.home().rglob(target.name)) if target.name else []
        if matches:
            target = matches[0]
        else:
            return {"success": False, "error": f"Chemin introuvable : {path}"}
    try:
        subprocess.Popen(
            ["xdg-open", str(target)],
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            start_new_session=True,
        )
        return {"success": True, "path": str(target)}
    except Exception as exc:
        return {"success": False, "error": str(exc)}
