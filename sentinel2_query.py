"""Query Sentinel-2 products on the Copernicus Data Space Ecosystem for
GeoJSON study areas and time windows, with optional download support.

Requires: requests
Platform API credentials (used by login) via environment variables:
    PLATFORM_USERNAME, PLATFORM_PASSWORD
Copernicus download credentials (only needed for downloads):
    COPERNICUS_CLIENT_ID, COPERNICUS_CLIENT_SECRET
"""

import json
import os
from datetime import datetime, timedelta, timezone

import requests

CATALOG_URL = "https://catalogue.dataspace.copernicus.eu/odata/v1/Products"
TOKEN_URL = (
    "https://identity.dataspace.copernicus.eu/auth/realms/CDSE"
    "/protocol/openid-connect/token"
)
DOWNLOAD_URL = "https://zipper.dataspace.copernicus.eu/odata/v1/Products"

SESSION = requests.Session()


def login(login_url: str, username: str | None = None, password: str | None = None) -> str:
    """Log in to the platform API with username/password sent as a JSON POST
    payload. The returned token (or session cookie) is stored on the shared
    SESSION, so all later calls (e.g. get_study_areas) stay authenticated.
    Credentials default to the PLATFORM_USERNAME / PLATFORM_PASSWORD env vars.
    Returns the access token, or an empty string for cookie-based sessions."""
    username = username if username is not None else os.environ["PLATFORM_USERNAME"]
    password = password if password is not None else os.environ["PLATFORM_PASSWORD"]
    resp = SESSION.post(login_url, json={"username": username, "password": password}, timeout=60)
    resp.raise_for_status()
    try:
        data = resp.json()
    except ValueError:
        data = {}
    token = data.get("access_token") or data.get("accessToken") or data.get("token")
    if token:
        SESSION.headers.update({"Authorization": f"Bearer {token}"})
    return token or ""


def geojson_to_wkt(geojson: dict) -> str:
    """Convert a GeoJSON Polygon/MultiPolygon (or Feature/FeatureCollection
    containing them) to a WKT string in SRID=4326."""
    geom = geojson.get("geometry", geojson)
    if geojson.get("type") == "FeatureCollection":
        coords = [f["geometry"]["coordinates"] for f in geojson["features"]]
        gtype = "MultiPolygon" if len(coords) > 1 else "Polygon"
        geom = {"type": gtype, "coordinates": coords}
    elif geojson.get("type") == "Feature":
        geom = geojson["geometry"]

    def ring(r):
        return "(" + ", ".join(f"{lon} {lat}" for lon, lat in r) + ")"

    if geom["type"] == "Polygon":
        return "POLYGON(" + ", ".join(ring(r) for r in geom["coordinates"]) + ")"
    if geom["type"] == "MultiPolygon":
        polys = ", ".join("(" + ", ".join(ring(r) for r in p) + ")" for p in geom["coordinates"])
        return "MULTIPOLYGON(" + polys + ")"
    raise ValueError(f"Unsupported geometry type: {geom['type']}")


def get_study_areas(api_url: str, headers: dict | None = None, params: dict | None = None) -> list[dict]:
    """Fetch GeoJSON study areas from the platform API using the
    authenticated SESSION (call login() first).
    Returns a list of GeoJSON dicts (Feature, FeatureCollection, or geometry)."""
    resp = SESSION.get(api_url, headers=headers or {}, params=params or {}, timeout=60)
    resp.raise_for_status()
    data = resp.json()
    if isinstance(data, dict) and data.get("type") == "FeatureCollection":
        return data["features"]
    if isinstance(data, list):
        return data
    return [data]


def _fmt(dt: datetime) -> str:
    return dt.astimezone(timezone.utc).strftime("%Y-%m-%dT%H:%M:%S.000Z")


def query_sentinel2(
    geojson: dict,
    start: datetime | str,
    end: datetime | str,
    collection: str = "SENTINEL-2",
    product_type: str | None = "S2MSI2A",
    cloud_cover_max: int = 100,
    top: int = 100,
) -> list[dict]:
    """Query the Copernicus catalog for Sentinel-2 products intersecting the
    given GeoJSON within [start, end]. Returns the raw product list."""
    if isinstance(start, str):
        start = datetime.fromisoformat(start)
    if isinstance(end, str):
        end = datetime.fromisoformat(end)

    wkt = geojson_to_wkt(geojson)
    filters = [
        f"Collection/Name eq '{collection}'",
        f"OData.CSC.Intersects(area=geography'SRID=4326;{wkt}')",
        f"ContentDate/Start ge {_fmt(start)}",
        f"ContentDate/Start lt {_fmt(end + timedelta(days=1))}",
    ]
    if product_type:
        filters.append(f"Attributes/OData.CSC.StringAttribute/any(att:att/Name eq 'productType' and att/OData.CSC.StringAttribute/Value eq '{product_type}')")
    if cloud_cover_max < 100:
        filters.append(
            "Attributes/OData.CSC.DoubleAttribute/any(att:att/Name eq 'cloudCover' "
            f"and att/OData.CSC.DoubleAttribute/Value le {cloud_cover_max})"
        )

    products: list[dict] = []
    skip = 0
    while True:
        params = {
            "$filter": " and ".join(filters),
            "$orderby": "ContentDate/Start desc",
            "$top": min(top, 1000),
            "$skip": skip,
            "$expand": "Attributes",
        }
        resp = SESSION.get(CATALOG_URL, params=params, timeout=120)
        resp.raise_for_status()
        batch = resp.json().get("value", [])
        products.extend(batch)
        if len(batch) < params["$top"]:
            break
        skip += params["$top"]
    return products


def get_token() -> str:
    """OAuth2 client-credentials token for the Data Space download service."""
    resp = requests.post(
        TOKEN_URL,
        data={
            "grant_type": "client_credentials",
            "client_id": os.environ["COPERNICUS_CLIENT_ID"],
            "client_secret": os.environ["COPERNICUS_CLIENT_SECRET"],
        },
        timeout=60,
    )
    resp.raise_for_status()
    return resp.json()["access_token"]


def download_product(product_id: str, out_dir: str = "downloads") -> str:
    """Download one product (as zip) by its catalog product id."""
    os.makedirs(out_dir, exist_ok=True)
    token = get_token()
    resp = SESSION.get(
        f"{DOWNLOAD_URL}({product_id})/$value",
        headers={"Authorization": f"Bearer {token}"},
        stream=True,
        timeout=600,
    )
    resp.raise_for_status()
    path = os.path.join(out_dir, f"{product_id}.zip")
    with open(path, "wb") as fh:
        for chunk in resp.iter_content(chunk_size=1 << 20):
            fh.write(chunk)
    return path


def summarize(products: list[dict]) -> list[dict]:
    """Flatten catalog products into a compact summary."""
    out = []
    for p in products:
        attrs = {a["Name"]: a.get("Value") for a in p.get("Attributes", [])}
        out.append({
            "id": p["Id"],
            "name": p["Name"],
            "start": p["ContentDate"]["Start"],
            "cloudCover": attrs.get("cloudCover"),
            "productType": attrs.get("productType"),
        })
    return out


if __name__ == "__main__":
    import sys

    login(os.environ["PLATFORM_LOGIN_URL"])
    areas = get_study_areas(os.environ["PLATFORM_STUDY_AREAS_URL"])
    study_area = areas[0] if areas else json.loads(sys.argv[1]) if len(sys.argv) > 1 else {
        "type": "Polygon",
        "coordinates": [[[23.0, 37.5], [24.0, 37.5], [24.0, 38.5], [23.0, 38.5], [23.0, 37.5]]],
    }
    start, end = "2024-06-01", "2024-08-31"

    hits = query_sentinel2(study_area, start, end, cloud_cover_max=30)
    for row in summarize(hits):
        print(row)
