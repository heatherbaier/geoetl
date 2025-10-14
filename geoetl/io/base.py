"""
geoetl/io/base.py
-----------------
Abstract base class defining a common interface for all imagery sources
(Planet, Sentinel, Landsat, MODIS, GEE, etc.)
"""

from abc import ABC, abstractmethod
from typing import Any, Dict, List, Optional
from shapely.geometry import shape

class ImagerySource(ABC):
    """Abstract base class for all imagery source connectors."""

    def __init__(self, api_key: Optional[str] = None, **kwargs):
        self.api_key = api_key
        self.params = kwargs

    # ---- REQUIRED METHODS --------------------------------------------------

    @abstractmethod
    def list_items(self, aoi: Any, start_date: str, end_date: str, **kwargs) -> List[Dict]:
        """
        Return list of available image scenes/quads/STAC items covering the AOI.

        Returns: list of dicts with at least:
            {
                "id": str,
                "geometry": GeoJSON,
                "date": str,
                "download_url": str,
                "metadata": {...}
            }
        """
        raise NotImplementedError

    @abstractmethod
    def download(self, item: Dict, out_dir: str) -> str:
        """Download a scene or quad to disk. Return local filepath."""
        raise NotImplementedError

    @abstractmethod
    def load(self, item_path: str):
        """Open downloaded imagery as a Rasterio Dataset or rioxarray DataArray."""
        raise NotImplementedError

    @abstractmethod
    def metadata(self, item: Dict) -> Dict[str, Any]:
        """Return standardized metadata for this item (sensor, date, bands, resolution)."""
        raise NotImplementedError

    # ---- OPTIONAL UTILS ----------------------------------------------------

    def standardize_geometry(self, geom: Dict) -> Dict:
        """Ensure geometry is valid GeoJSON dict."""
        if hasattr(geom, "__geo_interface__"):
            return geom.__geo_interface__
        elif isinstance(geom, dict):
            shape(geom)  # validate
            return geom
        else:
            raise ValueError("Invalid geometry format for AOI")
