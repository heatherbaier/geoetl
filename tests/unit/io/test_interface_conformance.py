"""A new imagery source can silently violate the ImagerySource contract --
forget an abstract method (Python itself catches that, but only at
instantiation time, which for MPCSource means "after it's already opened a
live network connection in __init__") or quietly reimplement a method meant
to be shared. These tests catch both at import time, with no network calls
and no instantiation needed.
"""

from geoetl.io.mpc import MPCSource
from geoetl.io.planet import PlanetBasemapSource

CONCRETE_SOURCES = [MPCSource, PlanetBasemapSource]

# See docs/concepts.md: "both get has_all_tiles, write_chip, and the
# corrupt-cache check (is_valid_raster) for free from the shared base class
# rather than reimplementing them."
SHARED_METHODS = ["has_all_tiles", "write_chip", "is_valid_raster", "scan_local_tiles", "_get_png_divisor"]


def test_every_source_fully_implements_the_interface():
    for cls in CONCRETE_SOURCES:
        assert not cls.__abstractmethods__, (
            f"{cls.__name__} is missing implementations for: "
            f"{sorted(cls.__abstractmethods__)}"
        )


def test_shared_helpers_come_from_the_base_class_not_reimplemented():
    for cls in CONCRETE_SOURCES:
        for name in SHARED_METHODS:
            assert name not in cls.__dict__, (
                f"{cls.__name__} reimplements {name!r} instead of relying on "
                f"ImagerySource's shared implementation -- if this is "
                f"intentional, update docs/concepts.md's description of "
                f"what sources get 'for free'."
            )
