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
    Calcule la distance routière via Google Routes API.
    Retourne la distance en kilomètres ou None si aucun
    itinéraire n'est disponible.
    """

    if not GOOGLE_API_KEY:
        raise RuntimeError("GOOGLE_API_KEY manquante dans .env")

    url = "https://routes.googleapis.com/directions/v2:computeRoutes"

    headers = {
        "Content-Type": "application/json",
        "X-Goog-Api-Key": GOOGLE_API_KEY,
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
        "regionCode": "fr",
    }

    print(f"[GOOGLE][DEBUG] Calcul : {origin} -> {destination}")

    try:
        response = requests.post(
            url,
            headers=headers,
            json=body,
            timeout=20,
        )

        print("[GOOGLE][DEBUG] HTTP status:", response.status_code)

        if response.status_code != 200:
            print("[GOOGLE][ERROR] Réponse API:", response.text[:1500])
            return None

        data = response.json()
        routes = data.get("routes", [])

        if not routes:
            print("[GOOGLE][WARNING] Aucun itinéraire trouvé")
            print("[GOOGLE][DEBUG] Réponse:", data)
            return None

        meters = routes[0].get("distanceMeters")

        if meters is None:
            print("[GOOGLE][WARNING] distanceMeters absent")
            return None

        km = round(float(meters) / 1000.0, 2)

        print(f"[GOOGLE][SUCCESS] Distance : {km} km")

        return km

    except requests.exceptions.RequestException as e:
        print("[GOOGLE][ERROR] Problème réseau :", repr(e))
        return None

    except (ValueError, TypeError, KeyError) as e:
        print("[GOOGLE][ERROR] Réponse invalide :", repr(e))
        return None


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
