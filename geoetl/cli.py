import os
import re
import sys
import typer
import yaml
from geoetl.pipelines.pipeline import run_pipeline

# Python fully block-buffers stdout/stderr when they're not a terminal (e.g.
# redirected to a SLURM log file) -- print() output sits in memory until the
# buffer fills or the process exits cleanly. A SIGKILL from an OOM killer
# never lets that flush happen, so anything still buffered at the moment of
# death is silently lost, including diagnostics that would explain the kill.
# Line-buffer so every print reaches disk immediately.
sys.stdout.reconfigure(line_buffering=True)
sys.stderr.reconfigure(line_buffering=True)

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
