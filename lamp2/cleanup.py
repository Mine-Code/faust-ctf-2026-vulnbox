import os
import time
from pathlib import Path

import pymysql


STORAGE_PATH = Path(os.environ.get("STORAGE_PATH", "/storage"))


def clean_once():
    connection = pymysql.connect(
        host=os.environ.get("DB_HOST", "mariadb"),
        user="root",
        password=os.environ.get("MARIADB_ROOT_PASSWORD", "root"),
        database=os.environ.get("DB_NAME", "lamp"),
        autocommit=True,
    )
    try:
        with connection.cursor() as cursor:
            cursor.execute(
                "DELETE FROM ships WHERE created < DATE_SUB(NOW(), INTERVAL 90 MINUTE)"
            )
    finally:
        connection.close()

    cutoff = time.time() - 90 * 60
    if STORAGE_PATH.is_dir():
        for path in STORAGE_PATH.iterdir():
            if path.is_file() and path.stat().st_mtime < cutoff:
                path.unlink()


if __name__ == "__main__":
    while True:
        clean_once()
        time.sleep(5 * 60)