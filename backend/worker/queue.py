"""Shared Huey queue; task handlers are added with later stories."""

from huey import SqliteHuey

from backend.config import Settings

settings = Settings.from_env()
settings.data_dir.mkdir(parents=True, exist_ok=True)
huey = SqliteHuey("rageva", filename=str(settings.data_dir / "queue.sqlite3"))
