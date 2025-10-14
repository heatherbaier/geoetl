from shapely.ops import transform
import rioxarray as riox
import logging
import pyproj


def clip_raster_to_aoi(raster_path, aoi_geom, out_path):
    """Clip any raster to a polygon geometry and save to disk."""
    log = logging.getLogger("geoetl.clip")
    try:
        raster = riox.open_rasterio(raster_path)
    
        # Project AOI only if CRS differs (e.g., 4326 → 3857)
        if raster.rio.crs and raster.rio.crs.to_epsg() != 4326:
            project = pyproj.Transformer.from_crs("EPSG:4326", raster.rio.crs, always_xy=True).transform
            aoi_geom = transform(project, aoi_geom)
    
        clipped = raster.rio.clip([aoi_geom])
        clipped.rio.to_raster(out_path)
        log.info(f"Clipped → {out_path}")
        return out_path
    except Exception as e:
        log.error(f"Failed to clip {raster_path}: {e}")
