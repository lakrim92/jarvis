"""Tri automatique de fichiers dans un dossier (par type)."""
import os
import shutil
from pathlib import Path

CATEGORIES = {
    "Images": {".jpg", ".jpeg", ".png", ".gif", ".bmp", ".svg", ".webp", ".heic", ".tiff", ".ico"},
    "Documents": {".pdf", ".doc", ".docx", ".odt", ".txt", ".rtf", ".xls", ".xlsx", ".ods",
                  ".ppt", ".pptx", ".odp", ".csv", ".md"},
    "Videos": {".mp4", ".mkv", ".avi", ".mov", ".webm", ".flv", ".wmv"},
    "Audio": {".mp3", ".wav", ".flac", ".ogg", ".m4a", ".aac"},
    "Archives": {".zip", ".rar", ".7z", ".tar", ".gz", ".bz2", ".xz"},
    "Installateurs": {".deb", ".rpm", ".appimage", ".exe", ".msi", ".sh", ".run", ".iso"},
}

_COMMON_DIRS = {
    "telechargements": "Downloads", "téléchargements": "Downloads", "downloads": "Downloads",
    "images": "Pictures", "photos": "Pictures", "pictures": "Pictures",
    "documents": "Documents", "bureau": "Desktop", "desktop": "Desktop",
    "videos": "Videos", "vidéos": "Videos", "musique": "Music", "music": "Music",
}


def _resolve_folder(folder: str) -> Path:
    expanded = os.path.expanduser(os.path.expandvars(folder)).strip()
    path = Path(expanded)
    if path.is_dir():
        return path
    key = expanded.strip("/\\ ").lower()
    if key in _COMMON_DIRS:
        candidate = Path.home() / _COMMON_DIRS[key]
        if candidate.is_dir():
            return candidate
    raise FileNotFoundError(f"Dossier introuvable : {folder}")


def _category_for(ext: str) -> str:
    ext = ext.lower()
    for category, extensions in CATEGORIES.items():
        if ext in extensions:
            return category
    return "Autres"


def organize_folder(folder: str, mode: str = "type") -> dict:
    """Trie les fichiers en vrac d'un dossier dans des sous-dossiers par type
    (Images, Documents, Videos, Audio, Archives, Installateurs, Autres).
    Ne touche pas aux sous-dossiers existants ni aux fichiers caches."""
    try:
        target = _resolve_folder(folder)
        moved = {}
        skipped = 0

        for entry in list(target.iterdir()):
            if entry.is_dir():
                continue
            if entry.name.startswith("."):
                continue
            if entry.parent.name in CATEGORIES:
                continue

            category = _category_for(entry.suffix)
            dest_dir = target / category
            dest_dir.mkdir(exist_ok=True)

            dest_path = dest_dir / entry.name
            if dest_path.exists():
                stem, suffix = entry.stem, entry.suffix
                i = 1
                while dest_path.exists():
                    dest_path = dest_dir / f"{stem} ({i}){suffix}"
                    i += 1

            try:
                shutil.move(str(entry), str(dest_path))
                moved[category] = moved.get(category, 0) + 1
            except Exception:
                skipped += 1

        return {
            "success": True,
            "folder": str(target),
            "moved_by_category": moved,
            "total_moved": sum(moved.values()),
            "skipped": skipped,
        }
    except Exception as exc:
        return {"success": False, "error": str(exc)}
