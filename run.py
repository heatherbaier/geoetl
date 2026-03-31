import yaml
import typer
from geoetl.pipelines.pipeline import run_pipeline

app = typer.Typer()

@app.command()
def run(config: str = typer.Option(..., "--config")):
    with open(config) as f:
        cfg = yaml.safe_load(f)
    run_pipeline(cfg)

if __name__ == "__main__":
    app()