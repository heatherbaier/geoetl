"""Tests for geoetl/config.py's validate_config -- the "fail fast, once,
before touching any AOI" pass run_pipeline() does up front.

Each case here traces back to a real failure mode in pipeline.py/mpc.py/
planet.py: either a cryptic deep-stack error (a plain KeyError from
cfg["params"]["uid_column"]), a config mistake that doesn't raise at all
(output.sub_root without sub_root_column fails every AOI silently inside
process_aoi_set's broad `except Exception`), or a typo that silently falls
back to a default instead of erroring (output.format: "PNG" wrong-case).
"""

import pytest

from geoetl.config import ConfigError, validate_config


def minimal_valid_cfg(tmp_path, aoi_file=None, sensor="mpc_sentinel2"):
    if aoi_file is None:
        aoi_file = tmp_path / "aois.geojson"
        aoi_file.write_text("{}")  # validate_config only checks existence, not content
    return {
        "aoi": {"path": str(aoi_file)},
        "output": {"root": str(tmp_path / "out")},
        "params": {"uid_column": "id", "label_column": "label", "dataset_name": "ds"},
        "catalog": {"sensor": sensor},
    }


# ---------------------------------------------------------------------------
# Top-level shape
# ---------------------------------------------------------------------------

def test_non_dict_config_is_rejected():
    with pytest.raises(ConfigError, match="must be a mapping"):
        validate_config(["not", "a", "dict"])


def test_a_valid_minimal_config_passes(tmp_path):
    validate_config(minimal_valid_cfg(tmp_path))  # must not raise


@pytest.mark.parametrize("top_key", ["aoi", "output", "params", "catalog"])
def test_missing_top_level_section_is_rejected(tmp_path, top_key):
    cfg = minimal_valid_cfg(tmp_path)
    del cfg[top_key]
    with pytest.raises(ConfigError, match="Missing required config key"):
        validate_config(cfg)


# ---------------------------------------------------------------------------
# aoi
# ---------------------------------------------------------------------------

def test_aoi_path_must_exist(tmp_path):
    cfg = minimal_valid_cfg(tmp_path)
    cfg["aoi"]["path"] = str(tmp_path / "does_not_exist.geojson")
    with pytest.raises(ConfigError, match="does not exist"):
        validate_config(cfg)


def test_aoi_path_must_be_a_non_empty_string(tmp_path):
    cfg = minimal_valid_cfg(tmp_path)
    cfg["aoi"]["path"] = ""
    with pytest.raises(ConfigError, match="non-empty string"):
        validate_config(cfg)


# ---------------------------------------------------------------------------
# output
# ---------------------------------------------------------------------------

def test_output_root_must_be_a_non_empty_string(tmp_path):
    cfg = minimal_valid_cfg(tmp_path)
    cfg["output"]["root"] = ""
    with pytest.raises(ConfigError, match="output.root"):
        validate_config(cfg)


def test_output_format_rejects_a_typo_instead_of_silently_defaulting(tmp_path):
    # run_pipeline's `"png" if cfg["output"].get("format","tif")=="png" else "tif"`
    # would otherwise silently treat "PNG" (wrong case) as "tif".
    cfg = minimal_valid_cfg(tmp_path)
    cfg["output"]["format"] = "PNG"
    with pytest.raises(ConfigError, match="output.format"):
        validate_config(cfg)


@pytest.mark.parametrize("fmt", ["tif", "png"])
def test_output_format_accepts_the_two_real_values(tmp_path, fmt):
    cfg = minimal_valid_cfg(tmp_path)
    cfg["output"]["format"] = fmt
    validate_config(cfg)


def test_png_scale_mode_rejects_unknown_values(tmp_path):
    cfg = minimal_valid_cfg(tmp_path)
    cfg["output"]["png_scale_mode"] = "atuo"  # typo
    with pytest.raises(ConfigError, match="png_scale_mode"):
        validate_config(cfg)


def test_png_scale_divisor_must_be_a_positive_number(tmp_path):
    cfg = minimal_valid_cfg(tmp_path)
    cfg["output"]["png_scale_divisor"] = 0
    with pytest.raises(ConfigError, match="png_scale_divisor"):
        validate_config(cfg)


def test_checkpoint_every_must_be_a_positive_int(tmp_path):
    cfg = minimal_valid_cfg(tmp_path)
    cfg["output"]["checkpoint_every"] = -5
    with pytest.raises(ConfigError, match="checkpoint_every"):
        validate_config(cfg)


def test_sub_root_without_sub_root_column_is_rejected(tmp_path):
    # Otherwise every AOI fails inside process_aoi_set's broad `except
    # Exception` on row[sub_root_column] -- a silently-empty dataset, not
    # a loud error.
    cfg = minimal_valid_cfg(tmp_path)
    cfg["output"]["sub_root"] = True
    with pytest.raises(ConfigError, match="sub_root_column"):
        validate_config(cfg)


def test_sub_root_with_a_column_is_fine(tmp_path):
    cfg = minimal_valid_cfg(tmp_path)
    cfg["output"]["sub_root"] = True
    cfg["output"]["sub_root_column"] = "region"
    validate_config(cfg)


# ---------------------------------------------------------------------------
# params
# ---------------------------------------------------------------------------

def test_uid_column_must_be_a_non_empty_string(tmp_path):
    cfg = minimal_valid_cfg(tmp_path)
    cfg["params"]["uid_column"] = ""
    with pytest.raises(ConfigError, match="uid_column"):
        validate_config(cfg)


def test_dataset_name_must_be_a_non_empty_string(tmp_path):
    cfg = minimal_valid_cfg(tmp_path)
    cfg["params"]["dataset_name"] = ""
    with pytest.raises(ConfigError, match="dataset_name"):
        validate_config(cfg)


def test_label_column_key_must_be_present_but_may_be_none(tmp_path):
    # README explicitly documents "set to null if no labels yet" -- the
    # *value* None is fine, but the key itself must exist.
    cfg = minimal_valid_cfg(tmp_path)
    cfg["params"]["label_column"] = None
    validate_config(cfg)

    del cfg["params"]["label_column"]
    with pytest.raises(ConfigError, match="label_column"):
        validate_config(cfg)


# ---------------------------------------------------------------------------
# catalog
# ---------------------------------------------------------------------------

def test_sensor_must_be_a_string(tmp_path):
    cfg = minimal_valid_cfg(tmp_path)
    cfg["catalog"]["sensor"] = 123
    with pytest.raises(ConfigError, match="catalog.sensor.*must be a string"):
        validate_config(cfg)


def test_unknown_sensor_is_rejected(tmp_path):
    cfg = minimal_valid_cfg(tmp_path, sensor="not_a_real_sensor")
    with pytest.raises(ConfigError, match="catalog.sensor"):
        validate_config(cfg)


@pytest.mark.parametrize(
    "sensor", ["planet", "mpc_sentinel2", "mpc_landsat8", "mpc_landsat5", "MPC_SENTINEL2"]
)
def test_every_known_sensor_is_accepted_case_insensitively(tmp_path, sensor):
    cfg = minimal_valid_cfg(tmp_path, sensor=sensor)
    if sensor.lower() == "planet":
        cfg["auth"] = {"api_key": "a-real-key"}
    validate_config(cfg)


def test_empty_bands_override_is_rejected_for_mpc_sensors(tmp_path):
    # mpc.py's own constructor check for this is unreachable dead code for
    # an empty list (see TESTING_PLAN.md §6) -- validate_config catches it
    # here instead, before a source is ever constructed.
    cfg = minimal_valid_cfg(tmp_path, sensor="mpc_sentinel2")
    cfg["catalog"]["bands"] = []
    with pytest.raises(ConfigError, match="catalog.bands"):
        validate_config(cfg)


def test_non_list_bands_override_is_rejected_for_mpc_sensors(tmp_path):
    cfg = minimal_valid_cfg(tmp_path, sensor="mpc_sentinel2")
    cfg["catalog"]["bands"] = "B04"
    with pytest.raises(ConfigError, match="catalog.bands"):
        validate_config(cfg)


def test_a_real_bands_override_is_accepted(tmp_path):
    cfg = minimal_valid_cfg(tmp_path, sensor="mpc_sentinel2")
    cfg["catalog"]["bands"] = ["B04", "B03", "B02", "B08"]
    validate_config(cfg)


# ---------------------------------------------------------------------------
# auth
# ---------------------------------------------------------------------------

def test_planet_requires_an_api_key(tmp_path):
    cfg = minimal_valid_cfg(tmp_path, sensor="planet")
    with pytest.raises(ConfigError, match="auth.api_key"):
        validate_config(cfg)


def test_planet_rejects_an_empty_api_key(tmp_path):
    # Mirrors an unset ${PLANET_API_KEY} env var, which cli._expand_env_vars
    # expands to "" rather than leaving the placeholder literal.
    cfg = minimal_valid_cfg(tmp_path, sensor="planet")
    cfg["auth"] = {"api_key": ""}
    with pytest.raises(ConfigError, match="auth.api_key"):
        validate_config(cfg)


def test_mpc_sensors_do_not_require_auth(tmp_path):
    cfg = minimal_valid_cfg(tmp_path, sensor="mpc_sentinel2")
    validate_config(cfg)  # no "auth" key at all -- anonymous MPC access is fine


# ---------------------------------------------------------------------------
# temporal
# ---------------------------------------------------------------------------

def test_temporal_disabled_skips_validation_entirely(tmp_path):
    cfg = minimal_valid_cfg(tmp_path)
    cfg["temporal"] = {"enabled": False}  # years/steps missing -- fine, not enabled
    validate_config(cfg)


def test_temporal_enabled_requires_non_empty_years(tmp_path):
    cfg = minimal_valid_cfg(tmp_path)
    cfg["temporal"] = {"enabled": True, "years": [], "steps": [1]}
    with pytest.raises(ConfigError, match="temporal.years"):
        validate_config(cfg)


def test_temporal_enabled_requires_non_empty_steps(tmp_path):
    cfg = minimal_valid_cfg(tmp_path)
    cfg["temporal"] = {"enabled": True, "years": [2020], "steps": []}
    with pytest.raises(ConfigError, match="temporal.steps"):
        validate_config(cfg)


def test_temporal_cadence_rejects_unknown_values(tmp_path):
    cfg = minimal_valid_cfg(tmp_path)
    cfg["temporal"] = {"enabled": True, "years": [2020], "steps": [1], "cadence": "yearly"}
    with pytest.raises(ConfigError, match="temporal.cadence"):
        validate_config(cfg)


def test_temporal_enabled_with_everything_valid_passes(tmp_path):
    cfg = minimal_valid_cfg(tmp_path)
    cfg["temporal"] = {"enabled": True, "years": [2020, 2021], "steps": [1, 2], "cadence": "quarterly"}
    validate_config(cfg)
