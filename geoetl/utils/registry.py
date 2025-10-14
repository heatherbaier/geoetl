"""
geoetl/utils/registry.py
------------------------
Registry for linking sensor names to handler classes and storing
common sensor metadata (bands, resolution, etc.)
"""

import importlib

IMAGERY_REGISTRY = {
    "planet": "geoetl.io.planet.PlanetBasemapSource",
    "sentinel2": "geoetl.io.sentinel.SentinelSource",
    "landsat8": "geoetl.io.landsat.LandsatSource",
    "modis": "geoetl.io.modis.MODISSource",
    "gee": "geoetl.io.gee.GEESource",
    "local": "geoetl.io.local.LocalSource",
}

SENSOR_METADATA = {
    "planet":   {"resolution": 4,  "bands": ["red", "green", "blue", "nir"]},
    "sentinel2": {"resolution": 10, "bands": ["B02","B03","B04","B08"]},
    "landsat8": {"resolution": 30, "bands": ["B2","B3","B4","B5"]},
    "modis":    {"resolution": 250, "bands": ["NDVI","EVI"]},
    "gee":      {"resolution": None, "bands": []},
}

# def get_source(sensor: str, **kwargs):
#     """Return an initialized imagery source object given sensor key."""
#     if sensor not in IMAGERY_REGISTRY:
#         raise ValueError(f"Sensor '{sensor}' not registered in IMAGERY_REGISTRY")
#     module_path, class_name = IMAGERY_REGISTRY[sensor].rsplit(".", 1)
#     module = importlib.import_module(module_path)
#     cls = getattr(module, class_name)
#     return cls(**kwargs)

def get_source(sensor: str):
    if sensor == "planet":
        from geoetl.io.planet import PlanetBasemapSource
        return PlanetBasemapSource()
    else:
        raise ValueError(f"Unknown sensor: {sensor}")

def get_sensor_metadata(sensor: str):
    return SENSOR_METADATA.get(sensor, {})
