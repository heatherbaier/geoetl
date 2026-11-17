"""
SUPERSEDED for AZ/GA/CA/PA going forward -- see
uswealth-geoai/pipeline_configs/generate_download_config.py, which does
the same thing but writes its generated configs into that project repo
(so replicating the paper only ever needs uswealth-geoai cloned +
`pip install -r requirements.txt` there, not a `cd` into this repo) and
reads a merged registry that also covers sail's per-state settings. Kept
here, and still functional, only because AZ isn't migrated to that merged
registry yet -- see that script's/uswealth-geoai's
pipeline_configs/state_registry.yml's TODOs. Don't add new states here;
add them to uswealth-geoai's registry instead.

Generate a ready-to-launch geoetl download config from --state/--year/
--quarter, instead of hand-copying a YAML file (and re-typing the shapefile
path, band list, cloud_cover_max, uid/label columns, and the output.root/
dataset_name naming) for every run -- the same copy-paste path that
produced configs/tlags/az/az_q2_2017.yml's start_date: "2017-03-31" (should
be "2017-04-01", one day into Q1 -- every other Q2 config in this repo uses
04-01; that file is left as-is here since it may already have imagery
downloaded under it, but don't copy it as a template).

Per-state settings that must stay IDENTICAL across every quarter/year for
that state (the AOI shapefile path, the label column) come from
scripts/state_registry.yml (kept next to this script, not under configs/ --
configs/ holds real per-run download configs that are committed as a record
of what was actually downloaded, but the registry is hand-maintained shared
metadata) -- fill that in once per state, using the real shapefile path
once it's on disk (not a guess: AZ's is tl_2019_04_tract_wi.shp, which
already shows the naming isn't just "tl_2019_<state fips>_tract.shp"), and
every config generated for that state reuses it automatically.

Everything else that's identical across EVERY state and quarter --
catalog.sensor, catalog.bands (the full 12-band S2 list, matching what
sail's dataloader/band-stats scripts expect for in_channels=12),
cloud_cover_max, mask_clouds, auth.mpc_api_key, output.sub_root,
params.uid_column -- is hardcoded below as FIXED_CATALOG/FIXED_OUTPUT/
FIXED_PARAMS, taken from the real, currently-downloading AZ allbands
configs, not guessed.

The quarter date ranges are calendar quarters and don't depend on the
state, only the year -- QUARTER_DATES below.

output.root and params.dataset_name are built from state+year+quarter
using the exact convention AZ's real configs already use (verified against
every committed az_q*_2016.yml/az_q*_2017.yml): e.g.
  /data/hbaier/new_data/tlag/az_imagery/q1_2016_s2_allbands/
  az_2016_q1_s2_allbands
Older committed configs for other states (ca_imagery/..._s2/,
imagery/..._s2/ for oh) predate this convention (no bands list, no
"_allbands" suffix, and in ca/oh's case label_column: NAME rather than a
wealth column) -- new configs always use the current AZ convention, which
is why ca/oh aren't pre-filled in state_registry.yml even though they
already have older configs on disk.

Also writes a matching SLURM job file (next to the .yml) that runs
`geoetl --config <that config>`. The SLURM directives (nodes, GPU/CPU
count, walltime, partition/QOS, module load, conda env, working directory)
are a fixed template taken from a real job file that's already worked on
ASU RC (ohio21dl, at this repo's root) -- only the job name, config path,
and output/error filenames vary per run.

Usage:
    python generate_download_config.py --state az --year 2018 --quarter 1
    # writes configs/tlags/az/az_q1_2018.yml AND az_q1_2018.sh

    python generate_download_config.py --state az --year 2018 --quarter 1 --launch
    # generates both files AND immediately runs `sbatch <job file>`
"""

import argparse
import os
import subprocess

import yaml

JOB_TEMPLATE = """#!/bin/bash
#SBATCH -N {nodes}            # number of nodes
#SBATCH -G {gpus}
#SBATCH -c {cpus}            # number of cores
#SBATCH -t {walltime}   # time in d-hh:mm:ss
#SBATCH -p {partition}      # partition
#SBATCH -q {qos}       # QOS
#SBATCH -J {dataset_name}
#SBATCH -o slurm.{dataset_name}.%j.out # file to save job's STDOUT (%j = JobId)
#SBATCH -e slurm.{dataset_name}.%j.err # file to save job's STDERR (%j = JobId)
#SBATCH --mail-type=ALL # Send an e-mail when a job starts, stops, or fails
#SBATCH --mail-user="%u@asu.edu"
#SBATCH --export=NONE   # Purge the job-submitting shell environment

#Load required software
module load mamba/latest

#Activate our environment
source activate {conda_env}

#Change to the directory of our script
cd {repo_dir}

#Run the software/python script
geoetl --config {config_path}
"""

# Calendar quarters -- same for every year, every state.
QUARTER_DATES = {
    1: ("{year}-01-01", "{year}-03-31"),
    2: ("{year}-04-01", "{year}-06-30"),
    3: ("{year}-07-01", "{year}-09-30"),
    4: ("{year}-10-01", "{year}-12-31"),
}

# Identical across every state/quarter config currently in configs/tlags/
# (verified: cloud_cover_max, mask_clouds, mpc_api_key, sensor, uid_column
# are the same in every committed config; the band list matches AZ's
# current "_allbands" configs, the only ones actually training against
# in_channels=12 right now).
FIXED_CATALOG = {
    "sensor": "mpc_sentinel2",
    "cloud_cover_max": 30,
    "mask_clouds": False,
    "bands": ["B01", "B02", "B03", "B04", "B05", "B06", "B07",
              "B08", "B8A", "B09", "B11", "B12"],
}
FIXED_OUTPUT = {"sub_root": False}
FIXED_UID_COLUMN = "GEOID"

REPO_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
REGISTRY_PATH = os.path.join(os.path.dirname(os.path.abspath(__file__)), "state_registry.yml")


def load_registry(path=REGISTRY_PATH):
    with open(path) as f:
        return yaml.safe_load(f)


def resolve_state_settings(state, registry, registry_path=REGISTRY_PATH):
    if state not in registry:
        raise SystemExit(f"--state {state!r} not in {registry_path} "
                          f"(known states: {sorted(registry)})")
    st = registry[state]
    required = ["shp_path", "label_column"]
    missing = [k for k in required if st.get(k) is None]
    if missing:
        raise SystemExit(
            f"--state {state!r} is missing required settings in {registry_path}: "
            f"{missing}. Fill these in (the real shapefile path once it's on "
            f"disk, and which tract column to pull labels from) before "
            f"generating configs for {state}."
        )
    return st


def build_config(state, year, quarter, registry):
    st = resolve_state_settings(state, registry)
    start_tmpl, end_tmpl = QUARTER_DATES[quarter]

    output_root = f"/data/hbaier/new_data/tlag/{state}_imagery/q{quarter}_{year}_s2_allbands/"
    dataset_name = f"{state}_{year}_q{quarter}_s2_allbands"

    cfg = {
        "aoi": {"path": st["shp_path"]},
        "catalog": {
            "sensor": FIXED_CATALOG["sensor"],
            "start_date": start_tmpl.format(year=year),
            "end_date": end_tmpl.format(year=year),
            "cloud_cover_max": FIXED_CATALOG["cloud_cover_max"],
            "mask_clouds": FIXED_CATALOG["mask_clouds"],
            "bands": FIXED_CATALOG["bands"],
        },
        "auth": {"mpc_api_key": None},
        "output": {
            "root": output_root,
            "sub_root": FIXED_OUTPUT["sub_root"],
        },
        "params": {
            "uid_column": FIXED_UID_COLUMN,
            "label_column": st["label_column"],
            "dataset_name": dataset_name,
        },
    }
    return cfg, dataset_name


def write_job_file(job_path, dataset_name, config_path, nodes, gpus, cpus,
                    walltime, partition, qos, conda_env, repo_dir):
    content = JOB_TEMPLATE.format(
        nodes=nodes, gpus=gpus, cpus=cpus, walltime=walltime,
        partition=partition, qos=qos, dataset_name=dataset_name,
        conda_env=conda_env, repo_dir=repo_dir, config_path=config_path,
    )
    with open(job_path, "w") as f:
        f.write(content)


def main():
    p = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("--state", required=True)
    p.add_argument("--year", required=True, type=int)
    p.add_argument("--quarter", required=True, type=int, choices=[1, 2, 3, 4])
    p.add_argument("--out", default=None,
                    help="Default: configs/tlags/<state>/<state>_q<quarter>_<year>.yml")
    p.add_argument("--job-out", default=None, help="Default: same path as --out, with .sh instead of .yml")
    p.add_argument("--no-job-file", action="store_true", help="Skip writing the SLURM job file")
    p.add_argument("--nodes", default="1")
    p.add_argument("--gpus", default="0")
    p.add_argument("--cpus", default="8")
    p.add_argument("--walltime", default="144:00:00")
    p.add_argument("--partition", default="public")
    p.add_argument("--qos", default="public")
    p.add_argument("--conda-env", default="geomain")
    p.add_argument("--repo-dir", default="/home/hbaier/packages/geoetl")
    p.add_argument("--launch", action="store_true",
                    help="Run `sbatch <job file>` immediately after writing it (requires the job file, i.e. not --no-job-file)")
    args = p.parse_args()

    registry = load_registry()
    cfg, dataset_name = build_config(args.state, args.year, args.quarter, registry)

    out_path = args.out or os.path.join(
        REPO_ROOT, "configs", "tlags", args.state,
        f"{args.state}_q{args.quarter}_{args.year}.yml"
    )
    os.makedirs(os.path.dirname(out_path), exist_ok=True)
    with open(out_path, "w") as f:
        yaml.safe_dump(cfg, f, sort_keys=False)
    print(f"Wrote {out_path}")
    print(f"dataset_name: {dataset_name}")

    job_path = None
    if not args.no_job_file:
        job_path = args.job_out or os.path.splitext(out_path)[0] + ".sh"
        write_job_file(job_path, dataset_name, out_path, args.nodes, args.gpus,
                        args.cpus, args.walltime, args.partition, args.qos,
                        args.conda_env, args.repo_dir)
        print(f"Wrote {job_path}")
        print(f"\n  sbatch {job_path}\n")
    else:
        print(f"\n  geoetl --config {out_path}\n")

    if args.launch:
        if job_path is None:
            raise SystemExit("--launch requires a job file -- drop --no-job-file")
        subprocess.run(["sbatch", job_path], check=True)


if __name__ == "__main__":
    main()
