from .planet import PlanetBasemapSource

def get_source(sensor, cfg=None):
    """Factory method to get the appropriate imagery source."""
    if sensor.lower() == "planet":
        api_key = cfg["auth"]["api_key"]
        mosaic = cfg["catalog"]["composite"]
        out_root = cfg["output"]["root"]
        return PlanetBasemapSource(api_key, out_root, mosaic)
    elif sensor.lower() == "landsat":
        from .landsat import LandsatSource
        return LandsatSource(cfg)
    else:
        raise ValueError(f"Unknown sensor type: {sensor}")
