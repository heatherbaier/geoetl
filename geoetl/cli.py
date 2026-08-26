import os
import re
import typer
import yaml
from geoetl.pipelines.pipeline import run_pipeline

app = typer.Typer(help="GeoETL command-line interface")

_ENV_VAR_RE = re.compile(r"\$\{(\w+)\}")


def _expand_env_vars(value):
    """Recursively replace ${VAR} placeholders with os.environ values.

    A placeholder whose variable isn't set expands to "" (rather than being
    left as the literal "${VAR}" text) so callers can use plain falsy
    checks (`value or default`) to fall back cleanly.
    """
    if isinstance(value, str):
        return _ENV_VAR_RE.sub(lambda m: os.environ.get(m.group(1), ""), value)
    if isinstance(value, dict):
        return {k: _expand_env_vars(v) for k, v in value.items()}
    if isinstance(value, list):
        return [_expand_env_vars(v) for v in value]
    return value


@app.command()
def run(config: str = typer.Option(..., "--config", "-c", help="Path to YAML config file")):
    """Run the GeoETL imagery pipeline."""
    with open(config) as f:
        cfg = yaml.safe_load(f)
    cfg = _expand_env_vars(cfg)
    run_pipeline(cfg)

if __name__ == "__main__":
    app()
