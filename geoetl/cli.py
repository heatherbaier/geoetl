import typer
import yaml
from geoetl.pipelines.pipeline import run_pipeline

app = typer.Typer(help="GeoETL command-line interface")

@app.command()
def run(config: str = typer.Option(..., "--config", "-c", help="Path to YAML config file")):
    """Run the GeoETL imagery pipeline."""
    with open(config) as f:
        cfg = yaml.safe_load(f)
    run_pipeline(cfg)

if __name__ == "__main__":
    app()
