import os
import json
import geopandas as gpd
import requests
import rioxarray as riox
from shapely.geometry import box
from shapely.ops import unary_union
from tqdm import tqdm
from rioxarray.merge import merge_arrays
import urllib.request



class PlanetBasemapSource:
    def __init__(self, api_key, out_root, mosaic_name):
        self.api_key = os.getenv("PLANET_API_KEY")
        self.out_root = out_root
        self.mosaic_name = mosaic_name
        # self.cache_dir = quads_dir
        # os.makedirs(self.cache_dir, exist_ok=True)
        self.API_URL = "https://api.planet.com/basemaps/v1/mosaics"
        self.session = requests.Session()
        self.session.auth = (self.api_key, "")

    # ---------------------- Core Methods ----------------------

    def find_local_tiles(self, geom, quads_dir):
        """Return list of cached tiles overlapping a geometry."""
        local_tiles = []
        for fname in os.listdir(quads_dir):
            if not fname.endswith(".tif"):
                continue
            try:
                tile_path = os.path.join(quads_dir, fname)
                with riox.open_rasterio(tile_path) as r:
                    tile_bounds = box(*r.rio.bounds())
                if tile_bounds.intersects(geom):
                    local_tiles.append(tile_path)
            except Exception:
                continue
        return local_tiles

    def download_tiles_for_geometry(self, geom, quads_dir):
        """
        Downloads Planet quads intersecting a single AOI geometry.
        Returns a list of downloaded tile file paths.
        """
        # Bounding box as [minx, miny, maxx, maxy]
        bounds = geom.bounds
        string_bbox = ",".join(map(str, bounds))
        downloaded_files = []

        # 1️⃣ Look up mosaic ID (based on mosaic name)
        params = {"name__is": self.mosaic_name}
        res = self.session.get(self.API_URL, params=params)
        if res.status_code != 200:
            print(f"⚠️ Mosaic lookup failed: {res.text}")
            return []

        mosaics = res.json().get("mosaics", [])
        if not mosaics:
            print(f"⚠️ No mosaics found for name {self.mosaic_name}")
            return []

        mosaic_id = mosaics[0]["id"]

        # 2️⃣ Get quads within the geometry bbox
        search_params = {"bbox": string_bbox, "minimal": True}
        quads_url = f"{self.API_URL}/{mosaic_id}/quads"
        res = self.session.get(quads_url, params=search_params, stream=True)

        if res.status_code != 200:
            print(f"⚠️ Quad search failed: {res.text}")
            return []

        quads = res.json().get("items", [])
        if not quads:
            print("⚠️ No quads found for geometry.")
            return []

        # 3️⃣ Download each quad if not cached
        for item in quads:
            link = item["_links"]["download"]
            quad_id = item["id"]
            filename = os.path.join(quads_dir, f"{quad_id}.tif")

            if not os.path.isfile(filename):
                try:
                    urllib.request.urlretrieve(link, filename)
                    print(f"✅ Downloaded {quad_id}")
                except Exception as e:
                    print(f"⚠️ Failed to download {quad_id}: {e}")
                    continue

            downloaded_files.append(filename)

        return downloaded_files

    def clip_to_geometry(self, geom, out_path, quads_dir):
        """Merge overlapping tiles and clip to geometry."""
        # local_tiles = self.find_local_tiles(geom)
        # if not local_tiles:
        local_tiles = self.download_tiles_for_geometry(geom, quads_dir)
        rasters = [riox.open_rasterio(p) for p in local_tiles]
        merged = merge_arrays(rasters)                     # ✅ fixed merge
        merged = merged.rio.write_crs("EPSG:3857")
        geom_3857 = gpd.GeoSeries([geom], crs="EPSG:4326").to_crs(3857).iloc[0]
        clipped = merged.rio.clip([geom_3857], merged.rio.crs, drop=True)
        clipped.rio.to_raster(out_path)
        for r in rasters:
            r.close()
        return out_path

    def has_all_tiles(self, local_tiles, geom):
        """
        Return True if the union of cached tiles fully covers the AOI geometry.
        """
        if not local_tiles:
            return False
    
        try:
            tile_bounds = []
            for tile_path in local_tiles:
                with riox.open_rasterio(tile_path) as r:
                    tile_bounds.append(box(*r.rio.bounds()))
            merged = unary_union(tile_bounds)
            return merged.contains(geom)
        except Exception as e:
            print(f"⚠️ Error checking tile coverage: {e}")
            return False

