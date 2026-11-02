# sentinel_download

Query Sentinel-2 products on the Copernicus Data Space Ecosystem for GeoJSON
study areas and temporal windows, with optional download support.

## Setup

```bash
pip install -r requirements.txt
```

For downloads only, register an app at
[Copernicus Data Space](https://dataspace.copernicus.eu/) and export:

```bash
export COPERNICUS_CLIENT_ID=...
export COPERNICUS_CLIENT_SECRET=...
```

## Usage

```python
from sentinel2_query import get_study_areas, query_sentinel2, summarize, download_product

areas = get_study_areas("https://your-platform.example/api/study-areas",
                        headers={"Authorization": "Bearer <token>"})
for area in areas:
    hits = query_sentinel2(area, "2024-06-01", "2024-08-31", cloud_cover_max=30)
    for row in summarize(hits):
        print(row)
    # download_product(hits[0]["Id"])
```

See `sentinel2_query.py` for all parameters (product type, cloud cover,
paging, collections).
