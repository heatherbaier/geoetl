from geoetl.io import get_source
from geoetl.utils.jsonio import update_json
import geopandas as gpd
import json
import os

def run_pipeline(cfg):
    gdf = gpd.read_file(cfg["aoi"]["path"])
    out_dir = cfg["output"]["root"]
    label_col = cfg["params"]["label_column"]
    source = get_source(cfg["catalog"]["sensor"], cfg)
    uid_column = cfg["params"]["uid_column"]
    label_col = cfg["params"]["label_column"]
    ds_name = cfg["params"]["dataset_name"]
    sub_root = cfg["output"]["sub_root"]
    sub_root_column = cfg["output"]["sub_root_column"]


    # Create the JSON files for labels and coords
    labels_path = os.path.join(out_dir, ds_name + "_labels.json")
    coords_path = os.path.join(out_dir, ds_name + "_coords.json")

    
    if not os.path.exists(labels_path):
        with open(labels_path, "w") as f:
            json.dump({}, f)
        labels = {}
    else:
        with open(labels_path, "r") as f:
            labels = json.load(f)

    
    if not os.path.exists(coords_path):
        with open(coords_path, "w") as f:
            json.dump({}, f)     
        coords = {}
    else:
        with open(coords_path, "r") as f:
            coords = json.load(f)

    
    # Create the JSON files for labels and coords
    chips_dir = os.path.join(out_dir, "chips")
    quads_dir = os.path.join(out_dir, "quads")
    
    if not os.path.isdir(chips_dir):
        os.mkdir(chips_dir)

    if not os.path.exists(quads_dir):
        os.mkdir(quads_dir)             
    
    # gdf = gdf.sample(10)

    mapping_path = os.path.join(out_dir, "aoi_mapping.json")

    for idx, row in gdf.iterrows():

        try:

            if sub_root:
    
                sr = row[sub_root_column]
    
                chips_dir = os.path.join(out_dir, "chips", sr)
                quads_dir = os.path.join(out_dir, "quads", sr)
    
                if not os.path.isdir(chips_dir):
                    os.mkdir(chips_dir)
                
                if not os.path.exists(quads_dir):
                    os.mkdir(quads_dir)       
    
            aoi_id = row[uid_column]
            label = row[label_col] if label_col else None
    
            # Define output paths
            clip_path = os.path.join(chips_dir, f"{aoi_id}.tif")
    
            # Skip if already processed
            if os.path.exists(clip_path):
                print(f"Skipping {aoi_id} (already processed)")
                continue
    
            # 1) Check which quads intersect locally cached tiles
            local_tiles = source.find_local_tiles(row.geometry, quads_dir)
    
            # 2) If missing tiles, query + download just what's needed
            if not source.has_all_tiles(local_tiles, row.geometry):
                new_tiles = source.download_tiles_for_geometry(row.geometry, quads_dir)
    
            # 3) Clip (merge local+new)
            clipped = source.clip_to_geometry(row.geometry, clip_path, quads_dir)
    
            # 4) Log progress
            update_json(mapping_path, aoi_id, {
                "label": label,
                "tiles_used": [t["id"] for t in local_tiles],
                "output": clip_path,
                "status": "complete"
            })
            
            labels[clip_path] = row[label_col]
            coords[clip_path] = [row.geometry.centroid.x, row.geometry.centroid.y]
    
            # Every 5 iterations (for example), flush to disk
            if idx % 1 == 0:
                
                with open(coords_path, "w") as f:
                    json.dump(coords, f)#, indent=2)
    
                with open(labels_path, "w") as f:
                    json.dump(labels, f)#, indent=2)

        except:
            pass