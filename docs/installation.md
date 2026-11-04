# Installation

## Requirements

- Python 3.9 or later
- A Microsoft Planetary Computer subscription key (optional — anonymous
  access works for moderate volumes) and/or a
  [Planet Labs](https://www.planet.com/) API key, depending on which
  sources you plan to use

## Install from source

geoetl isn't on PyPI yet, so install it directly from GitHub:

```bash
git clone https://github.com/heatherbaier/geoetl.git
cd geoetl
pip install -e .
```

The `-e` (editable) install is recommended even if you don't plan to
modify geoetl itself: it means a `git pull` to get a newer version takes
effect immediately, with no reinstall step.

This pulls in geoetl's full dependency set — `typer`, `geopandas`,
`rioxarray`, `odc-stac`, `pystac-client`, `planetary-computer`, and a few
others — so expect it to take a minute or two, particularly for the
geospatial stack (GDAL-backed packages like `rioxarray` are not small).

:::{note}
If you only need `earthengine-api` for the experimental AlphaEarth source
(not wired into the CLI by default), install the optional extra instead:
`pip install -e ".[alpha-earth]"`. Most users don't need this.
:::

## Verify the install

```bash
geoetl --help
```

If that prints usage information instead of a `command not found` or
import error, you're ready to run a config (Quickstart guide coming
soon).

## Set up authentication

### Microsoft Planetary Computer

No credentials are required to get started — anonymous access works for
moderate request volumes. For higher throughput, set a subscription key
as an environment variable:

```bash
export PC_SDK_SUBSCRIPTION_KEY=your-key-here
```

or put it directly in a config's `auth.mpc_api_key`.

### Planet Labs

A Planet API key is required for the `planet` source:

```bash
export PLANET_API_KEY=your-key-here
```

Config files can also reference `${PLANET_API_KEY}` inline under
`auth.api_key` — geoetl expands `${VAR}` placeholders from the
environment at load time, so the key itself never needs to be written
into a config file.
