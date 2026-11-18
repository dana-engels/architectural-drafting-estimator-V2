"""Run the estimator with a temporary database and fictional inputs."""
import os
from pathlib import Path
from tempfile import TemporaryDirectory

from app import create_app


def create_demo_app(database):
    app = create_app(database)
    app.config["DEMO_MODE"] = True
    return app


if __name__ == "__main__":
    with TemporaryDirectory(prefix="drafting-estimator-demo-") as directory:
        app = create_demo_app(Path(directory) / "demo.sqlite3")
        app.run(host="127.0.0.1", port=int(os.environ.get("PORT", "5051")))
