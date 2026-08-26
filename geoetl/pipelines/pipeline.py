from geoetl.io import get_source
from geoetl.utils.jsonio import update_json
import geopandas as gpd
import json
import os

def run_pipeline(cfg):
    gdf = gpd.read_file(cfg["aoi"]["path"])
    out_dir = cfg["output"]["root"]
    label_col = cfg["params"]["label_column"]
    uid_column = cfg["params"]["uid_column"]
    ds_name = cfg["params"]["dataset_name"]
    source = get_source(cfg["catalog"]["sensor"], cfg)
    sub_root = cfg["output"].get("sub_root")
    sub_root_column = cfg["output"].get("sub_root_column")

    chips_root = os.path.join(out_dir, "chips")
    quads_root = os.path.join(out_dir, "quads")
    os.makedirs(chips_root, exist_ok=True)
    os.makedirs(quads_root, exist_ok=True)

    labels_path = os.path.join(out_dir, ds_name + "_ys.json")
    coords_path = os.path.join(out_dir, ds_name + "_coords.json")

    for path in [labels_path, coords_path]:
        if not os.path.exists(path):
            with open(path, "w") as f:
                json.dump({}, f)

    with open(labels_path) as f:
        labels = json.load(f)
    with open(coords_path) as f:
        coords = json.load(f)

    mapping_path = os.path.join(out_dir, "aoi_mapping.json")
    checkpoint_every = cfg["output"].get("checkpoint_every", 25)

    # 🧩 define the reusable AOI loop
    def process_aoi_set(chips_root_dir, quads_root_dir, temporal_tag=None):

        for idx, row in gdf.iterrows():

            aoi_id = None
            try:

                if sub_root:
                    sr = str(row[sub_root_column])
                    chips_dir = os.path.join(chips_root_dir, sr)
                    quads_dir = os.path.join(quads_root_dir, sr)
                    os.makedirs(chips_dir, exist_ok=True)
                    os.makedirs(quads_dir, exist_ok=True)
                else:
                    chips_dir = chips_root_dir
                    quads_dir = quads_root_dir

                aoi_id = str(row[uid_column])
                label = row[label_col] if label_col else None
                clip_path = os.path.join(chips_dir, f"{aoi_id}.tif")

                if os.path.exists(clip_path):
                    print(f"Skipping {aoi_id} (already processed)")
                    continue

                local_tiles = source.find_local_tiles(row.geometry, quads_dir)
                if not source.has_all_tiles(local_tiles, row.geometry):
                    source.download_tiles_for_geometry(row.geometry, quads_dir)

                source.clip_to_geometry(row.geometry, clip_path, quads_dir)

                update_json(mapping_path, aoi_id, {
                    "label": label,
                    "tiles_used": [os.path.basename(t) for t in local_tiles],
                    "output": clip_path,
                    "status": "complete"
                })

                # 🌍 store temporal or static label structure
                if temporal_tag:
                    # initialize if not present
                    if aoi_id not in labels:
                        labels[aoi_id] = {"chips": [], "label": label}

                    # append chip for this temporal slice
                    if clip_path not in labels[aoi_id]["chips"]:
                        labels[aoi_id]["chips"].append(clip_path)

                else:
                    # static (old) style
                    labels[clip_path] = label

                coords[clip_path] = [row.geometry.centroid.x, row.geometry.centroid.y]

                if idx % checkpoint_every == 0:
                    with open(coords_path, "w") as f:
                        json.dump(coords, f)
                    with open(labels_path, "w") as f:
                        json.dump(labels, f)

            except Exception as e:
                print(f"⚠️ Error on AOI {aoi_id if aoi_id is not None else idx}: {e}")
                continue

    # 🕓 temporal logic
    temporal_cfg = cfg.get("temporal", {})
    if temporal_cfg.get("enabled", False):
        years = temporal_cfg.get("years", [])
        steps = temporal_cfg.get("steps", [])
        cadence = temporal_cfg.get("cadence", "monthly")

        for year in years:
            for step in steps:
                step_label = f"{year}_{cadence[0]}{str(step).zfill(2)}"
                chips_dir = os.path.join(chips_root, step_label)
                quads_dir = os.path.join(quads_root, step_label)
                os.makedirs(chips_dir, exist_ok=True)
                os.makedirs(quads_dir, exist_ok=True)

                # update Planet source for this time slice
                source.set_time_filter(year=year, steps=[step], cadence=cadence)
                print(f"⏳ Processing {step_label}...")

                # pass temporal_tag so we know to use nested JSON format
                process_aoi_set(chips_dir, quads_dir, temporal_tag=step_label)

    else:
        # static fallback
        process_aoi_set(chips_root, quads_root)

    # ✅ final write
    with open(labels_path, "w") as f:
        json.dump(labels, f, indent=2)
    with open(coords_path, "w") as f:
        json.dump(coords, f, indent=2)


