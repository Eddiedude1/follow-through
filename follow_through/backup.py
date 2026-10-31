import shutil
import time
from datetime import datetime, timezone
from pathlib import Path


def backup_once(db_path: str, dest_dir: str) -> str:
    if not Path(db_path).exists():
        raise FileNotFoundError(f"source database does not exist: {db_path}")

    timestamp = datetime.now(timezone.utc).strftime("%Y%m%d")
    dest_path = Path(dest_dir) / f"follow_through-{timestamp}.db"
    shutil.copyfile(db_path, dest_path)
    return str(dest_path)


def run_forever(db_path: str, dest_dir: str, interval_seconds: int = 86400) -> None:
    while True:
        backup_once(db_path, dest_dir)
        time.sleep(interval_seconds)


def main() -> None:
    from follow_through import config

    run_forever(config.DB_PATH, config.BACKUP_DEST_DIR)


if __name__ == "__main__":
    main()
