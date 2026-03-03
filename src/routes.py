# src/routes.py
import os
import math
import requests
from dotenv import load_dotenv

load_dotenv()

GOOGLE_API_KEY = os.getenv("GOOGLE_API_KEY")


# ----------------------------
# 1) GOOGLE ROUTES (routier)
# ----------------------------
def driving_km(origin: str, destination: str) -> float | None:
    """
    Distance routière via Google Routes API (computeRoutes).
    Retourne km (float) ou None si impossible.
    Nécessite GOOGLE_API_KEY dans .env.
    """
    if not GOOGLE_API_KEY:
        raise RuntimeError("GOOGLE_API_KEY manquante dans .env")

    url = "https://routes.googleapis.com/directions/v2:computeRoutes"

    headers = {
        "Content-Type": "application/json",
        "X-Goog-Api-Key": GOOGLE_API_KEY,
        # On ne récupère que la distance -> plus léger
        "X-Goog-FieldMask": "routes.distanceMeters",
    }

    body = {
        "origin": {"address": origin},
        "destination": {"address": destination},
        "travelMode": "DRIVE",
        "routingPreference": "TRAFFIC_UNAWARE",
        "computeAlternativeRoutes": False,
        "languageCode": "fr-FR",
        "units": "METRIC",
    }

    r = requests.post(url, headers=headers, json=body, timeout=20)

    if r.status_code != 200:
        # utile pour debug
        # print("Routes API error:", r.status_code, r.text)
        return None

    data = r.json()
    routes = data.get("routes") or []
    if not routes:
        return None

    meters = routes[0].get("distanceMeters")
    if meters is None:
        return None

    return round(meters / 1000.0, 2)


# ----------------------------
# 2) GEOCODING (train/avion)
# ----------------------------
def geocode_place(place_name: str) -> tuple[float, float] | None:
    """
    Retourne (lat, lon) via Google Geocoding API.
    Nécessite GOOGLE_API_KEY.
    """
    if not GOOGLE_API_KEY:
        return None

    url = "https://maps.googleapis.com/maps/api/geocode/json"
    params = {"address": f"{place_name}, France", "key": GOOGLE_API_KEY}
    r = requests.get(url, params=params, timeout=20)
    data = r.json()

    if data.get("status") != "OK":
        return None

    results = data.get("results") or []
    if not results:
        return None

    loc = results[0]["geometry"]["location"]
    return (loc["lat"], loc["lng"])


# ----------------------------
# 3) HAVERSINE (vol d’oiseau)
# ----------------------------
def haversine_km(a: tuple[float, float], b: tuple[float, float]) -> float:
    lat1, lon1 = a
    lat2, lon2 = b

    # radians
    phi1 = math.radians(lat1)
    phi2 = math.radians(lat2)
    dphi = math.radians(lat2 - lat1)
    dlambda = math.radians(lon2 - lon1)

    R = 6371.0
    h = (math.sin(dphi / 2) ** 2 +
         math.cos(phi1) * math.cos(phi2) * (math.sin(dlambda / 2) ** 2))
    d = 2 * R * math.asin(math.sqrt(h))
    return round(d, 2)
