"""Recherche web (sans cle API, via DuckDuckGo)."""
import urllib.request
import urllib.parse
import json


def web_search(query: str, num_results: int = 5) -> dict:
    """Recherche sur le web et renvoie titres/extraits/urls."""
    try:
        from duckduckgo_search import DDGS
        with DDGS() as ddgs:
            results = list(ddgs.text(query, max_results=num_results))
        if not results:
            return {"success": True, "results": [], "note": "Aucun resultat."}
        cleaned = [
            {
                "title": r.get("title", ""),
                "url": r.get("href", ""),
                "snippet": r.get("body", ""),
            }
            for r in results
        ]
        return {"success": True, "results": cleaned}
    except Exception as exc:
        return {"success": False, "error": str(exc)}


def _geocode(place: str) -> dict:
    url = "https://nominatim.openstreetmap.org/search?" + urllib.parse.urlencode(
        {"q": place, "format": "json", "limit": 1}
    )
    req = urllib.request.Request(url, headers={"User-Agent": "JarvisAssistant/1.0"})
    with urllib.request.urlopen(req, timeout=8) as resp:
        results = json.loads(resp.read().decode("utf-8"))
    if not results:
        raise ValueError(f"Lieu introuvable : {place}")
    return {
        "name": results[0].get("display_name", place),
        "lat": float(results[0]["lat"]),
        "lon": float(results[0]["lon"]),
    }


def get_distance(origin: str, destination: str) -> dict:
    """Calcule la distance routiere reelle (et la duree de trajet) entre deux lieux.
    Utilise TOUJOURS cet outil pour une question de distance/kilometrage entre deux endroits :
    ne jamais estimer une distance de memoire, le calcul mental de distances geographiques
    n'est pas fiable."""
    try:
        orig = _geocode(origin)
        dest = _geocode(destination)
        url = (
            f"https://router.project-osrm.org/route/v1/driving/"
            f"{orig['lon']},{orig['lat']};{dest['lon']},{dest['lat']}?overview=false"
        )
        req = urllib.request.Request(url, headers={"User-Agent": "JarvisAssistant/1.0"})
        with urllib.request.urlopen(req, timeout=10) as resp:
            data = json.loads(resp.read().decode("utf-8"))
        if data.get("code") != "Ok" or not data.get("routes"):
            raise ValueError("Aucun itineraire trouve.")
        route = data["routes"][0]
        distance_km = route["distance"] / 1000
        duration_h = route["duration"] / 3600
        return {
            "success": True,
            "origin": orig["name"],
            "destination": dest["name"],
            "distance_km_route": round(distance_km, 1),
            "duration_hours_driving": round(duration_h, 1),
        }
    except Exception as exc:
        return {"success": False, "error": str(exc)}


def get_weather(city: str = "") -> dict:
    """Meteo actuelle via wttr.in, sans cle API."""
    try:
        location = urllib.parse.quote(city) if city else ""
        url = f"https://wttr.in/{location}?format=j1"
        req = urllib.request.Request(url, headers={"User-Agent": "curl/8.0"})
        with urllib.request.urlopen(req, timeout=6) as resp:
            data = json.loads(resp.read().decode("utf-8"))
        current = data["current_condition"][0]
        area = data.get("nearest_area", [{}])[0]
        area_name = area.get("areaName", [{}])[0].get("value", city or "ta position")
        return {
            "success": True,
            "location": area_name,
            "temperature_c": current.get("temp_C"),
            "feels_like_c": current.get("FeelsLikeC"),
            "description": current.get("lang_fr", current.get("weatherDesc"))[0].get("value"),
            "humidity_pct": current.get("humidity"),
            "wind_kmph": current.get("windspeedKmph"),
        }
    except Exception as exc:
        return {"success": False, "error": str(exc)}
