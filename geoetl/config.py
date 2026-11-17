"""
geoetl/config.py
-----------------
Config validation, run once up front by run_pipeline() before any AOI is
touched -- the same "fail fast, once" principle pipeline.py already applies
to the PNG band-count check, extended to the config as a whole.

Without this, a misconfiguration doesn't necessarily raise at all: it can
instead surface as every single AOI silently failing inside
process_aoi_set()'s broad `except Exception` (e.g. output.sub_root=true
with no sub_root_column -- a KeyError per AOI, swallowed, looking like an
empty dataset rather than a config error), or as a typo quietly falling
back to a default instead of erroring (e.g. output.format: "PNG" with the
wrong case silently behaves as "tif" -- see _validate_output below).
"""

from geoetl.io import KNOWN_SENSORS


class ConfigError(ValueError):
    """A config is malformed in a way that would fail later, less clearly."""


def _get(cfg, *path):
    """Fetch a nested config value, or raise ConfigError naming the
    missing dotted path."""
    node = cfg
    for key in path:
        if not isinstance(node, dict) or key not in node:
            raise ConfigError(f"Missing required config key: '{'.'.join(path)}'")
        node = node[key]
    return node


def validate_config(cfg):
    """Raise ConfigError on the first problem found. Returns None otherwise."""
    if not isinstance(cfg, dict):
        raise ConfigError(f"Config must be a mapping, got {type(cfg).__name__}")

    _validate_aoi(cfg)
    _validate_output(cfg)
    _validate_params(cfg)
    sensor = _validate_catalog(cfg)
    _validate_auth(cfg, sensor)
    _validate_temporal(cfg)


def _validate_aoi(cfg):
    import os

    path = _get(cfg, "aoi", "path")
    if not isinstance(path, str) or not path:
        raise ConfigError("'aoi.path' must be a non-empty string")
    if not os.path.isfile(path):
        raise ConfigError(f"'aoi.path' does not exist: {path!r}")


def _validate_output(cfg):
    root = _get(cfg, "output", "root")
    if not isinstance(root, str) or not root:
        raise ConfigError("'output.root' must be a non-empty string")

    output = cfg["output"]

    fmt = output.get("format", "tif")
    if fmt not in ("tif", "png"):
        raise ConfigError(
            f"'output.format' must be 'tif' or 'png', got {fmt!r}. A typo "
            f"here silently falls back to 'tif' rather than erroring, so "
            f"it's rejected outright instead."
        )

    scale_mode = output.get("png_scale_mode", "fixed")
    if scale_mode not in ("fixed", "auto"):
        raise ConfigError(
            f"'output.png_scale_mode' must be 'fixed' or 'auto', got {scale_mode!r}"
        )

    divisor = output.get("png_scale_divisor", 257)
    if not isinstance(divisor, (int, float)) or isinstance(divisor, bool) or divisor <= 0:
        raise ConfigError(f"'output.png_scale_divisor' must be a positive number, got {divisor!r}")

    checkpoint_every = output.get("checkpoint_every", 25)
    if not isinstance(checkpoint_every, int) or isinstance(checkpoint_every, bool) or checkpoint_every <= 0:
        raise ConfigError(f"'output.checkpoint_every' must be a positive integer, got {checkpoint_every!r}")

    sub_root = output.get("sub_root")
    if sub_root:
        sub_root_column = output.get("sub_root_column")
        if not isinstance(sub_root_column, str) or not sub_root_column:
            raise ConfigError(
                "'output.sub_root' is set but 'output.sub_root_column' is "
                "missing -- every AOI would fail at row[sub_root_column] "
                "and the run would silently produce an empty dataset "
                "instead of erroring up front."
            )


def _validate_params(cfg):
    _get(cfg, "params", "uid_column")
    uid_column = cfg["params"]["uid_column"]
    if not isinstance(uid_column, str) or not uid_column:
        raise ConfigError("'params.uid_column' must be a non-empty string")

    dataset_name = _get(cfg, "params", "dataset_name")
    if not isinstance(dataset_name, str) or not dataset_name:
        raise ConfigError("'params.dataset_name' must be a non-empty string")

    # label_column is allowed to be None (no labels yet -- see README), but
    # the key itself must be present so pipeline.py's cfg["params"]["label_column"]
    # doesn't KeyError.
    _get(cfg, "params", "label_column")


def _validate_catalog(cfg):
    sensor = _get(cfg, "catalog", "sensor")
    if not isinstance(sensor, str):
        raise ConfigError(f"'catalog.sensor' must be a string, got {type(sensor).__name__}")

    sensor_lower = sensor.lower()
    if sensor_lower not in KNOWN_SENSORS:
        raise ConfigError(
            f"'catalog.sensor' must be one of {list(KNOWN_SENSORS)}, got {sensor!r}"
        )

    if sensor_lower.startswith("mpc_"):
        bands = cfg.get("catalog", {}).get("bands")
        # Deliberately stricter than MPCSource's own constructor check: an
        # empty list there is silently ignored (mpc.py's `if bands:` guard
        # is falsy for `[]`, so its own "must be non-empty" check never
        # actually runs for the one case its message describes -- see
        # TESTING_PLAN.md §6). Catching it here means an empty override
        # fails loudly instead of quietly using the sensor's default bands.
        if bands is not None and (not isinstance(bands, list) or len(bands) == 0):
            raise ConfigError(
                f"'catalog.bands' must be a non-empty list when set, got {bands!r}"
            )

    return sensor_lower


def _validate_auth(cfg, sensor_lower):
    if sensor_lower != "planet":
        return
    api_key = cfg.get("auth", {}).get("api_key")
    if not isinstance(api_key, str) or not api_key:
        raise ConfigError(
            "'auth.api_key' is required (non-empty) for catalog.sensor='planet'. "
            "If it's set via ${PLANET_API_KEY}, check that the environment "
            "variable is actually set -- an unset one expands to ''."
        )


def _validate_temporal(cfg):
    temporal = cfg.get("temporal", {})
    if not temporal.get("enabled", False):
        return

    years = temporal.get("years")
    if not isinstance(years, list) or len(years) == 0:
        raise ConfigError("'temporal.years' must be a non-empty list when temporal.enabled is true")

    steps = temporal.get("steps")
    if not isinstance(steps, list) or len(steps) == 0:
        raise ConfigError("'temporal.steps' must be a non-empty list when temporal.enabled is true")

    cadence = temporal.get("cadence", "monthly")
    if cadence not in ("monthly", "quarterly"):
        raise ConfigError(f"'temporal.cadence' must be 'monthly' or 'quarterly', got {cadence!r}")
