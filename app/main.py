"""Command-line interface for the Dynamic Product Catalog Monitor."""

import typer

app = typer.Typer(
    name="dynamic-catalog-monitor",
    help="Monitor a dynamic product catalog and report changes.",
    no_args_is_help=True,
)


@app.command()
def scrape() -> None:
    """Collect the current product catalog."""
    typer.echo("Scraping is not implemented yet.")


@app.command()
def compare() -> None:
    """Compare collected catalog snapshots."""
    typer.echo("Comparison is not implemented yet.")


@app.command()
def export() -> None:
    """Export catalog results."""
    typer.echo("Export is not implemented yet.")


if __name__ == "__main__":
    app()
