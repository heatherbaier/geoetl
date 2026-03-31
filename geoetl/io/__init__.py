from .planet import PlanetBasemapSource
from .gee import GEESource


def get_source(sensor, cfg=None):
    """Factory method to get the appropriate imagery source."""

    sensor_lower = sensor.lower()

    if sensor_lower == "planet":
        api_key = cfg["auth"]["api_key"]
        mosaic = cfg["catalog"]["composite"]
        out_root = cfg["output"]["root"]
        return PlanetBasemapSource(api_key, out_root, mosaic)

    elif sensor_lower in ("landsat5", "landsat8", "sentinel2"):
        from .gee import GEESource
        out_root = cfg["output"]["root"]
        year = cfg.get("catalog", {}).get("year", 2020)
        month = cfg.get("catalog", {}).get("month", None)
        ee_project = cfg.get("auth", {}).get("ee_project", None)
        start_date = cfg.get("catalog", {}).get("start_date", None)
        end_date = cfg.get("catalog", {}).get("end_date", None)
        return GEESource(
            out_root=out_root,
            sensor=sensor_lower,
            year=year,
            month=month,
            ee_project=ee_project,
            start_date = start_date,
            end_date = end_date
        )

    else:
        raise ValueError(f"Unknown sensor type: {sensor}")