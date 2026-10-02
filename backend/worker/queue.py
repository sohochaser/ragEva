"""Shared Huey queue for durable evaluation tasks."""

from huey import SqliteHuey

from backend.config import Settings

settings = Settings.from_env()
settings.data_dir.mkdir(parents=True, exist_ok=True)
huey = SqliteHuey("rageva", filename=str(settings.data_dir / "queue.sqlite3"))


@huey.task()
def score_run_task(run_id: str) -> None:
    from backend.worker.run_processor import process_run

    process_run(run_id, settings.data_dir)
