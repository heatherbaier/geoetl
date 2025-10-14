import os
import json
import geopandas as gpd
import rasterio
import logging              # ← ADD THIS LINE
from shapely.geometry import shape
from rasterio.merge import merge

from geoetl.utils.logging import setup_logging
from geoetl.utils.registry import get_source
from geoetl.preprocess.clip import clip_raster_to_aoi

def run_pipeline(cfg):
    setup_logging()
    log = logging.getLogger("geoetl")

    aoi_path = cfg["aoi"]["path"]
    sensor = cfg["catalog"]["sensor"]
    mosaic_name = cfg["catalog"]["composite"]
    out_root = cfg["output"]["root"]
    uid_column = cfg["params"]["uid_column"]
    label_column = cfg["params"]["label_column"]
    ds_name = cfg["params"]["dataset_name"]

    
    gdf = gpd.read_file(aoi_path).to_crs("EPSG:4326")[0:5]
    os.makedirs(out_root, exist_ok=True)
    os.makedirs(os.path.join(out_root, "clips"), exist_ok=True)
    os.makedirs(os.path.join(out_root, "quads"), exist_ok=True)

    source = get_source(sensor)
    all_quads = source.list_items(aoi_path, mosaic_name)
    log.info(f"Found {len(all_quads)} quads from Planet API")


    # Create the JSON files for labels and coords
    labels_path = os.path.join(out_root, ds_name + "_labels.json")
    coords_path = os.path.join(out_root, ds_name + "_coords.json")
    
    if not os.path.exists(labels_path):
        with open(labels_path, "w") as f:
            json.dump({}, f)

    if not os.path.exists(coords_path):
        with open(coords_path, "w") as f:
            json.dump({}, f)        

    # Pre-convert quads to shapely for fast spatial filtering
    for q in all_quads:
        q["geom"] = shape(q["geometry"])

    labels = {}
    coords = {}
    for aoi_idx, row in gdf.iterrows():
        aoi_geom = row.geometry
        aoi_id = row.get(uid_column, aoi_idx)
        log.info(f"Processing AOI {aoi_id}")

        # find quads overlapping AOI
        overlaps = [q for q in all_quads if q["geom"].intersects(aoi_geom)]
        if not overlaps:
            log.warning(f"No quads found for AOI {aoi_id}")
            continue

        # Download and open all quads
        quad_paths = []
        for item in overlaps:
            fpath = source.download(item, os.path.join(out_root, "quads"))
            quad_paths.append(fpath)

        # Merge overlapping quads
        src_files = [rasterio.open(p) for p in quad_paths]
        mosaic, transform = merge(src_files)
        meta = src_files[0].meta.copy()
        meta.update({
            "driver": "GTiff",
            "height": mosaic.shape[1],
            "width": mosaic.shape[2],
            "transform": transform
        })

        merged_path = os.path.join(out_root, "quads", f"merged_{aoi_id}.tif")
        with rasterio.open(merged_path, "w", **meta) as dest:
            dest.write(mosaic)

        for src in src_files:
            src.close()

        # Clip merged raster to AOI
        clip_out = os.path.join(os.getcwd(), out_root, "clips", f"{sensor}_{aoi_id}.tif")
        clip_raster_to_aoi(merged_path, aoi_geom, clip_out)

        # Delete quads and merged raster to save space
        for fp in quad_paths + [merged_path]:
            try:
                os.remove(fp)
            except FileNotFoundError:
                pass

        log.info(f"✅ AOI {aoi_id} complete, clipped image saved to {clip_out}")

        labels[clip_out] = row[label_column]
        coords[clip_out] = [row.geometry.centroid.x, row.geometry.centroid.y]
        
        # Every 5 iterations (for example), flush to disk
        if aoi_idx % 1 == 0:
            
            with open(coords_path, "w") as f:
                json.dump(coords, f)#, indent=2)

            with open(labels_path, "w") as f:
                json.dump(labels, f)#, indent=2)