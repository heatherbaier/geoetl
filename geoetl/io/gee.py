import os
import ee
import requests
import geopandas as gpd
import rioxarray as riox
from shapely.geometry import box, mapping
from shapely.ops import unary_union
from rioxarray.merge import merge_arrays


# ---------------------------------------------------------------------------
# Sensor configs — extend this dict to add new sensors
# ---------------------------------------------------------------------------
SENSOR_CONFIGS = {
    "landsat8": {
        "collection": "LANDSAT/LC08/C02/T1_L2",
        "bands": ["SR_B7", "SR_B6", "SR_B5", "SR_B4", "SR_B3", "SR_B2"],   # R, G, B
        "scale": 30,
        "scale_factor": 0.0000275,
        "offset": -0.2,
    },
    "landsat5": {
        "collection": "LANDSAT/LT05/C02/T1_L2",
        "bands": ["SR_B7", "SR_B5", "SR_B4", "SR_B3", "SR_B2", "SR_B1"],   # R, G, B
        "scale": 30,
        "scale_factor": 0.0000275,
        "offset": -0.2,
    },
    "sentinel2": {
        "collection": "COPERNICUS/S2_SR_HARMONIZED",
        "bands": ["B4", "B3", "B2"],             # R, G, B
        "scale": 10,
        "scale_factor": 0.0001,
        "offset": 0.0,
    },
}


class GEESource:
    """
    Downloads Landsat 8 or Sentinel-2 SR composites from Google Earth Engine.
    Replicates the PlanetBasemapSource interface so the existing pipeline
    script works without modification.

    Parameters
    ----------
    out_root : str
        Root directory for output chips and quads (tiles).
    sensor : str
        One of 'landsat' or 'sentinel2'.
    year : int
        Year for the temporal composite.
    month : int or None
        Month (1-12) for a monthly composite. If None, uses full-year median.
    ee_project : str or None
        GEE project ID for ee.Initialize(). If None, uses default credentials.
    """

    def __init__(self, out_root, sensor="landsat", year=2020, month=None, ee_project=None, start_date = None, end_date = None):
        self.out_root = out_root
        self.sensor = sensor.lower()
        self.year = year
        self.month = month
        self.ee_project = ee_project
        self.start_date = start_date
        self.end_date = end_date

        if self.sensor not in SENSOR_CONFIGS:
            raise ValueError(f"Unknown sensor '{sensor}'. Choose from: {list(SENSOR_CONFIGS.keys())}")

        self.cfg = SENSOR_CONFIGS[self.sensor]

        # Initialise Earth Engine once
        # try:
        #     if ee_project:
        #         ee.Initialize(project=ee_project)
        #     else:
        ee.Initialize()
        # except Exception:
        #     ee.Authenticate()
        #     if ee_project:
        #         ee.Initialize(project=ee_project)
        #     else:
        #         ee.Initialize()

    # ------------------------------------------------------------------
    # set_time_filter — mirrors PlanetBasemapSource.set_time_filter
    # ------------------------------------------------------------------

    def set_time_filter(self, year=None, steps=None, cadence="monthly"):
        """
        Update the temporal window.  Called by the pipeline for each
        year/step combination when temporal mode is enabled.

        cadence='monthly',  steps=[8]  → year=year, month=8
        cadence='quarterly', steps=[3] → year=year, month=7 (Q3 start)
        """
        if not year:
            return

        if not steps or len(steps) == 0:
            raise ValueError("At least one temporal step must be provided.")

        self.year = year
        cadence = cadence.lower().strip()
        step = steps[0]

        if cadence == "monthly":
            self.month = int(step)
        elif cadence == "quarterly":
            # Map quarter to start month
            self.month = {1: 1, 2: 4, 3: 7, 4: 10}[int(step)]
        else:
            raise ValueError(f"Unsupported cadence: {cadence}")

        print(f"🕓 GEESource time filter set to: {self.year}-{self.month} ({cadence})")

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------


    # def _build_date_range(self):
    #     """Return (start_date, end_date) strings for the current time filter."""
    #     year = self.year
    #     month = self.month

    #     if month is None:
    #         return f"{year}-01-01", f"{year}-12-31"

    #     # End of month
    #     import calendar
    #     last_day = calendar.monthrange(year, month)[1]
    #     start = f"{year}-{str(month).zfill(2)}-01"
    #     end = f"{year}-{str(month).zfill(2)}-{last_day}"
    #     return start, end


    def _build_date_range(self):
        """Return (start_date, end_date) strings for the current time filter."""
        # Explicit date range takes priority
        if hasattr(self, 'start_date') and self.start_date:
            print("Returning here!!")
            return self.start_date, self.end_date
    
        year = self.year
        month = self.month
    
        if month is None:
            return f"{year}-01-01", f"{year}-12-31"
    
        import calendar
        last_day = calendar.monthrange(year, month)[1]
        start = f"{year}-{str(month).zfill(2)}-01"
        end = f"{year}-{str(month).zfill(2)}-{last_day}"
        return start, end


    def _build_composite(self, geom_ee):
        """Build a cloud-free median composite clipped to geom_ee."""
        start, end = self._build_date_range()
        cfg = self.cfg

        collection = (
            ee.ImageCollection(cfg["collection"])
            .filterDate(start, end)
            .filterBounds(geom_ee)
        )

        # Cloud masking
        # if self.sensor == "landsat":
        #     def mask_landsat_clouds(img):
        #         qa = img.select("QA_PIXEL")
        #         mask = qa.bitwiseAnd(1 << 3).eq(0).And(qa.bitwiseAnd(1 << 5).eq(0))
        #         return img.updateMask(mask)
        #     collection = collection.map(mask_landsat_clouds)


        if self.sensor == "landsat8":
            def mask_landsat_clouds(img):
                qa = img.select("QA_PIXEL")
                mask = qa.bitwiseAnd(1 << 3).eq(0).And(qa.bitwiseAnd(1 << 5).eq(0))
                return img.updateMask(mask)
            collection = collection.map(mask_landsat_clouds)
        
        elif self.sensor == "landsat5":
            # def mask_landsat5_clouds(img):
            #     qa = img.select("QA_PIXEL")
            #     # Bit 3 = cloud shadow, Bit 4 = snow, Bit 6 = cloud
            #     # Less aggressive than L8 mask — just remove high confidence cloud
            #     mask = qa.bitwiseAnd(1 << 6).eq(0)
            #     return img.updateMask(mask)
            # collection = collection.map(mask_landsat5_clouds)
            def mask_landsat_clouds(img):
                qa = img.select("QA_PIXEL")
                mask = qa.bitwiseAnd(1 << 3).eq(0).And(qa.bitwiseAnd(1 << 5).eq(0))
                return img.updateMask(mask)
            collection = collection.map(mask_landsat_clouds)


            
        
        elif self.sensor == "sentinel2":
            def mask_s2_clouds(img):
                scl = img.select("SCL")
                mask = scl.neq(3).And(scl.neq(8)).And(scl.neq(9)).And(scl.neq(10))
                return img.updateMask(mask)
            collection = collection.map(mask_s2_clouds)



        size = collection.size().getInfo()
        print(f"📦 Collection size for {start} to {end}: {size} images")
        if size == 0:
            raise RuntimeError(f"No images found in {cfg['collection']} for {start} to {end}")
            

        composite = collection.select(cfg["bands"]).median()

        # Apply scale factor to get reflectance in [0, 1]
        composite = composite.multiply(cfg["scale_factor"]).add(cfg["offset"])

        # Rescale to uint16 for GeoTIFF export (multiply by 10000)
        composite = composite.multiply(10000).toUint16()

        return composite

    def _tile_path(self, geom):
        """Generate a deterministic tile filename from geometry centroid."""
        c = geom.centroid
        tag = f"{self.sensor}_{self.year}_{self.month}_{c.x:.4f}_{c.y:.4f}"
        tag = tag.replace("-", "n").replace(".", "p")
        return tag + ".tif"

    def _geom_to_ee(self, geom):
        """Convert shapely geometry to ee.Geometry (WGS84)."""
        return ee.Geometry(mapping(geom))

    # ------------------------------------------------------------------
    # Public interface — mirrors PlanetBasemapSource
    # ------------------------------------------------------------------

    def find_local_tiles(self, geom, quads_dir):
        """
        Return list of cached GeoTIFF paths that overlap geom.
        Mirrors PlanetBasemapSource.find_local_tiles.
        """
        local_tiles = []
        if not os.path.isdir(quads_dir):
            return local_tiles

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

    def has_all_tiles(self, local_tiles, geom):
        """
        Return True if cached tiles fully cover geom.
        Mirrors PlanetBasemapSource.has_all_tiles.
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

    def download_tiles_for_geometry(self, geom, quads_dir):
        """
        Download a GEE composite tile covering geom and save to quads_dir.
        Returns list of downloaded tile paths.
        Mirrors PlanetBasemapSource.download_tiles_for_geometry.

        Note: GEE composites are continuous surfaces so there is only ever
        one 'tile' per geometry — the bounding box composite.
        """
        os.makedirs(quads_dir, exist_ok=True)

        fname = self._tile_path(geom)
        tile_path = os.path.join(quads_dir, fname)

        if os.path.isfile(tile_path):
            print(f"✅ Tile already cached: {fname}")
            return [tile_path]

        geom_ee = self._geom_to_ee(geom)
        composite = self._build_composite(geom_ee)

        try:
            url = composite.getDownloadURL({
                "region": geom_ee,
                "scale": self.cfg["scale"],
                "format": "GEO_TIFF",
                "crs": "EPSG:4326",
            })
        except Exception as e:
            print(f"⚠️ GEE URL generation failed: {e}")
            return []

        try:
            response = requests.get(url, stream=True, timeout=120)
            if response.status_code != 200:
                print(f"⚠️ GEE download failed ({response.status_code}): {response.text[:200]}")
                return []

            with open(tile_path, "wb") as f:
                for chunk in response.iter_content(chunk_size=8192):
                    f.write(chunk)

            print(f"✅ Downloaded GEE tile: {fname}")
            return [tile_path]

        except Exception as e:
            print(f"⚠️ Failed to save tile {fname}: {e}")
            return []

    def clip_to_geometry(self, geom, out_path, quads_dir):
        """
        Clip the cached tile to geom and write to out_path.
        Mirrors PlanetBasemapSource.clip_to_geometry.

        For GEE the tile is already sized to the AOI bounding box so
        this is mostly a CRS-safe clip to the exact geometry boundary.
        """
        local_tiles = self.find_local_tiles(geom, quads_dir)

        if not local_tiles:
            local_tiles = self.download_tiles_for_geometry(geom, quads_dir)

        if not local_tiles:
            raise RuntimeError(f"No tiles available for geometry at {geom.centroid}")

        rasters = [riox.open_rasterio(p) for p in local_tiles]
        merged = merge_arrays(rasters) if len(rasters) > 1 else rasters[0]
        merged = merged.rio.write_crs("EPSG:4326")

        geom_gdf = gpd.GeoSeries([geom], crs="EPSG:4326")
        clipped = merged.rio.clip(geom_gdf.geometry, geom_gdf.crs, drop=True)

        os.makedirs(os.path.dirname(out_path), exist_ok=True)
        clipped.rio.to_raster(out_path)

        for r in rasters:
            r.close()

        return out_path
