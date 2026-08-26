import os
import geopandas as gpd
import requests
import rioxarray as riox
from rioxarray.merge import merge_arrays
import urllib.request

from geoetl.io.base import ImagerySource


class PlanetBasemapSource(ImagerySource):
    def __init__(self, api_key, out_root, mosaic_name):
        self.api_key = api_key or os.getenv("PLANET_API_KEY")
        self.out_root = out_root
        self.mosaic_name = mosaic_name
        # self.cache_dir = quads_dir
        # os.makedirs(self.cache_dir, exist_ok=True)
        self.API_URL = "https://api.planet.com/basemaps/v1/mosaics"
        self.session = requests.Session()
        self.session.auth = (self.api_key, "")



    def set_time_filter(self, year=None, steps=None, cadence="monthly"):
        """
        Dynamically set Planet mosaic name using year + step (month or quarter),
        depending on cadence.
    
        Examples:
            cadence='monthly',  steps=[8]  → global_monthly_2025_08_mosaic
            cadence='quarterly', steps=[3] → global_quarterly_2022q3_mosaic
        """
        if not year:
            return  # static imagery, no temporal filtering
    
        if not steps or len(steps) == 0:
            raise ValueError("At least one temporal step (month or quarter) must be provided.")
    
        cadence = cadence.lower().strip()
        step = steps[0]  # For now we handle one time slice at a time in the pipeline
    
        if cadence == "monthly":
            step_str = str(step).zfill(2)
            self.mosaic_name = f"global_monthly_{year}_{step_str}_mosaic"
    
        elif cadence == "quarterly":
            self.mosaic_name = f"global_quarterly_{year}q{int(step)}_mosaic"
    
        else:
            raise ValueError(f"Unsupported cadence: {cadence}")
    
        print(f"🕓 Set mosaic to: {self.mosaic_name}")


    
    
            

    # ---------------------- Core Methods ----------------------

    def find_local_tiles(self, geom, quads_dir):
        """Return list of cached quads overlapping a geometry."""
        return self.scan_local_tiles(quads_dir, geom)

    def download_tiles_for_geometry(self, geom, quads_dir):
        """
        Downloads Planet quads intersecting a single AOI geometry.
        Returns a list of downloaded tile file paths.
        """
        os.makedirs(quads_dir, exist_ok=True)

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

            if os.path.isfile(filename) and not self.is_valid_raster(filename):
                # Left truncated by an earlier interrupted download -- discard
                # and re-fetch instead of treating this quad as permanently
                # cached-but-broken.
                print(f"⚠️ Cached quad {quad_id} is invalid, re-downloading")
                os.remove(filename)

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
        local_tiles = self.find_local_tiles(geom, quads_dir)
        if not local_tiles:
            local_tiles = self.download_tiles_for_geometry(geom, quads_dir)
        if not local_tiles:
            raise RuntimeError(
                f"No Planet quads available for geometry at {geom.centroid}"
            )

        rasters = [riox.open_rasterio(p) for p in local_tiles]
        try:
            merged = merge_arrays(rasters)
            merged = merged.rio.write_crs("EPSG:3857")
            geom_3857 = gpd.GeoSeries([geom], crs="EPSG:4326").to_crs(3857).iloc[0]
            clipped = merged.rio.clip([geom_3857], merged.rio.crs, drop=True)
            clipped.rio.to_raster(out_path)
        finally:
            for r in rasters:
                r.close()
        return out_path

    # has_all_tiles(local_tiles, geom) is inherited from ImagerySource.

