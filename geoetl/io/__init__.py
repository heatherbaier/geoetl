# from .planet import PlanetBasemapSource
# from .gee import GEESource
# from .alpha_earth import AlphaEarthSource


# def get_source(sensor, cfg=None):
#     """Factory method to get the appropriate imagery source."""
#     sensor_lower = sensor.lower()

#     if sensor_lower == "planet":
#         api_key = cfg["auth"]["api_key"]
#         mosaic = cfg["catalog"]["composite"]
#         out_root = cfg["output"]["root"]
#         return PlanetBasemapSource(api_key, out_root, mosaic)

#     elif sensor_lower in ("landsat5", "landsat8", "sentinel2"):
#         out_root = cfg["output"]["root"]
#         year = cfg.get("catalog", {}).get("year", 2020)
#         month = cfg.get("catalog", {}).get("month", None)
#         ee_project = cfg.get("auth", {}).get("ee_project", None)
#         start_date = cfg.get("catalog", {}).get("start_date", None)
#         end_date = cfg.get("catalog", {}).get("end_date", None)
#         return GEESource(
#             out_root=out_root,
#             sensor=sensor_lower,
#             year=year,
#             month=month,
#             ee_project=ee_project,
#             start_date=start_date,
#             end_date=end_date,
#         )

#     elif sensor_lower == "alpha_earth":
#         out_root = cfg["output"]["root"]
#         years = cfg.get("temporal", {}).get("years", [])
#         ee_project = cfg.get("auth", {}).get("ee_project", None)
#         scale = cfg.get("temporal", {}).get("scale", 10)
#         if not years:
#             raise ValueError(
#                 "AlphaEarth requires at least one year in config under "
#                 "temporal.years (e.g. years: [2022, 2023])"
#             )
#         return AlphaEarthSource(
#             out_root=out_root,
#             years=years,
#             ee_project=ee_project,
#             scale=scale,
#         )

#     else:
#         raise ValueError(f"Unknown sensor type: {sensor}")



from .planet import PlanetBasemapSource
# from .gee import GEESource
# from .alpha_earth import AlphaEarthSource
from .mpc import MPCSource


def get_source(sensor, cfg=None):
    """Factory method to get the appropriate imagery source."""
    sensor_lower = sensor.lower()

    if sensor_lower == "planet":
        api_key = cfg["auth"]["api_key"]
        mosaic = cfg["catalog"]["composite"]
        out_root = cfg["output"]["root"]
        return PlanetBasemapSource(api_key, out_root, mosaic)

    # elif sensor_lower in ("landsat5", "landsat8", "sentinel2"):
    #     out_root = cfg["output"]["root"]
    #     year = cfg.get("catalog", {}).get("year", 2020)
    #     month = cfg.get("catalog", {}).get("month", None)
    #     ee_project = cfg.get("auth", {}).get("ee_project", None)
    #     start_date = cfg.get("catalog", {}).get("start_date", None)
    #     end_date = cfg.get("catalog", {}).get("end_date", None)
    #     return GEESource(
    #         out_root=out_root,
    #         sensor=sensor_lower,
    #         year=year,
    #         month=month,
    #         ee_project=ee_project,
    #         start_date=start_date,
    #         end_date=end_date,
    #     )

    # elif sensor_lower == "alpha_earth":
    #     out_root = cfg["output"]["root"]
    #     years = cfg.get("temporal", {}).get("years", [])
    #     ee_project = cfg.get("auth", {}).get("ee_project", None)
    #     scale = cfg.get("temporal", {}).get("scale", 10)
    #     if not years:
    #         raise ValueError(
    #             "AlphaEarth requires at least one year in config under "
    #             "temporal.years (e.g. years: [2022, 2023])"
    #         )
    #     return AlphaEarthSource(
    #         out_root=out_root,
    #         years=years,
    #         ee_project=ee_project,
    #         scale=scale,
    #     )

    elif sensor_lower in ("mpc_sentinel2", "mpc_landsat8", "mpc_landsat5"):
        out_root = cfg["output"]["root"]
        # Strip the "mpc_" prefix to get the sensor name MPCSource expects.
        mpc_sensor = sensor_lower.replace("mpc_", "")
        year = cfg.get("catalog", {}).get("year", 2020)
        month = cfg.get("catalog", {}).get("month", None)
        start_date = cfg.get("catalog", {}).get("start_date", None)
        end_date = cfg.get("catalog", {}).get("end_date", None)
        cloud_cover_max = cfg.get("catalog", {}).get("cloud_cover_max", 20)
        api_key = cfg.get("auth", {}).get("mpc_api_key", None)
        mask_clouds = cfg.get("catalog", {}).get("mask_clouds", True)
        return MPCSource(
            out_root=out_root,
            sensor=mpc_sensor,
            year=year,
            month=month,
            cloud_cover_max=cloud_cover_max,
            start_date=start_date,
            end_date=end_date,
            api_key=api_key,
            mask_clouds=mask_clouds,
        )

    else:
        raise ValueError(f"Unknown sensor type: {sensor}")