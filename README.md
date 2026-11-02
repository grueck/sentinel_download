# sentinel_download

Query Sentinel-2 products on the Copernicus Data Space Ecosystem for GeoJSON
study areas and temporal windows, with optional download support.

## Setup

```bash
pip install -r requirements.txt
```

Platform API login (username/password, JSON POST) and Copernicus download
credentials are read from environment variables — never hardcode them:

```bash
export PLATFORM_USERNAME=...
export PLATFORM_PASSWORD=...
export COPERNICUS_CLIENT_ID=...        # downloads only
export COPERNICUS_CLIENT_SECRET=...    # downloads only
```

## Usage

```python
from sentinel2_query import login, get_study_areas, query_sentinel2, summarize, download_product

login("https://your-platform.example/api/login")  # session persists afterwards
areas = get_study_areas("https://your-platform.example/api/study-areas")
for area in areas:
    hits = query_sentinel2(area, "2024-06-01", "2024-08-31", cloud_cover_max=30)
    for row in summarize(hits):
        print(row)
    # download_product(hits[0]["Id"])
```

See `sentinel2_query.py` for all parameters (product type, cloud cover,
paging, collections).
