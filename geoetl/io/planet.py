import os
import requests
import urllib
import geopandas as gpd
from shapely.geometry import box, shape

API_URL = "https://api.planet.com/basemaps/v1/mosaics"

class PlanetBasemapSource:
    """
    Planet Basemaps imagery source.
    Provides list of quads (footprints) with metadata and download URLs.
    """

    def __init__(self, api_key=None):
        self.api_key = api_key or os.getenv("PLANET_API_KEY")
        if not self.api_key:
            raise EnvironmentError("PLANET_API_KEY not found. Export or include in config.")

    def list_items(self, aoi_path, mosaic_name):
        """List Planet Basemap quads overlapping AOI bbox with metadata."""
        gdf = gpd.read_file(aoi_path).to_crs("EPSG:4326")
        bbox = ",".join(map(str, gdf.total_bounds))

        # Get mosaic ID
        res = requests.get(API_URL, params={"name__is": mosaic_name}, auth=(self.api_key, ""))
        res.raise_for_status()
        mosaics = res.json().get("mosaics", [])
        if not mosaics:
            raise ValueError(f"No Planet mosaic found matching name '{mosaic_name}'")
        mosaic_id = mosaics[0]["id"]

        # List quads within AOI bounding box
        quads_url = f"{API_URL}/{mosaic_id}/quads"
        quads = []
        page_url = quads_url
        params = {"bbox": bbox, "minimal": False}

        while page_url:
            r = requests.get(page_url, params=params, auth=(self.api_key, ""))
            r.raise_for_status()
            data = r.json()
            for item in data.get("items", []):
                # Planet returns bbox, not geometry — build a shapely Polygon manually
                bbox = item.get("bbox")
                if bbox is None:
                    continue  # skip malformed entries
        
                geom = box(bbox[0], bbox[1], bbox[2], bbox[3])
                quads.append({
                    "id": item["id"],
                    "geometry": geom.__geo_interface__,  # for GeoJSON compatibility
                    "download_url": item["_links"]["download"]
                })
            page_url = data.get("_links", {}).get("_next")

        return quads

    def download(self, item, out_dir):
        """Download one Planet quad GeoTIFF."""
        os.makedirs(out_dir, exist_ok=True)
        fid = item["id"]
        fpath = os.path.join(out_dir, f"{fid}.tiff")
        if os.path.exists(fpath):
            return fpath

        link = item["download_url"]
        urllib.request.urlretrieve(link, fpath)
        return fpath
