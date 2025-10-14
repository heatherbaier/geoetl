import os, json, geopandas as gpd, rasterio
from shapely.geometry import shape
from rasterio.merge import merge
from geoetl.utils.registry import get_source
from geoetl.preprocess.clip import clip_raster_to_aoi

def download_and_clip(cfg):
    """
    Memory-efficient pipeline:
    iterate over imagery quads/scenes, clip them to overlapping AOIs,
    delete them once done, and record a quad→AOI mapping.
    """
    aoi_path = cfg["aoi"]["path"]
    sensor = cfg["catalog"]["sensor"]
    mosaic_name = cfg["catalog"]["composite"]
    out_root = cfg["output"]["root"]

    gdf = gpd.read_file(aoi_path).to_crs("EPSG:4326")
    source = get_source(sensor)
    items = source.list_items(aoi_path, mosaic_name)

    mapping = {}   # {quad_id: [AOI_IDs]}
    mapping_path = os.path.join(out_root, "quad_aoi_mapping.json")
    os.makedirs(out_root, exist_ok=True)

    for item in items:
        qid = item["id"]
        qgeom = shape(item["geometry"])  # GeoJSON footprint of quad
        overlaps = gdf[gdf.geometry.intersects(qgeom)]

        if overlaps.empty:
            continue

        # Record which AOIs overlap this quad
        mapping[qid] = overlaps.index.tolist()

        # Download once
        quad_path = source.download(item, os.path.join(out_root, "quads"))

        # Clip to each AOI
        for idx, row in overlaps.iterrows():
            out_path = os.path.join(out_root, "clips", f"{idx}_{sensor}.tif")
            clip_raster_to_aoi(quad_path, row.geometry, out_path)

        # Delete temporary quad
        os.remove(quad_path)

        # Periodically checkpoint mapping
        if len(mapping) % 25 == 0:
            with open(mapping_path, "w") as f:
                json.dump(mapping, f)

    with open(mapping_path, "w") as f:
        json.dump(mapping, f)
    return mapping
