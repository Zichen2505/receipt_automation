"""Demonstrate the test helper's SQLite lifetime error without business imports."""

import json
from pathlib import Path
import sqlite3
import tempfile


def main():
    with tempfile.TemporaryDirectory(prefix="receipt-independent-diagnosis-") as directory:
        database = Path(directory) / "diagnosis.sqlite3"
        with sqlite3.connect(database) as connection:
            connection.execute("CREATE TABLE independent_diagnosis (value TEXT)")
        still_open = connection.execute("SELECT count(*) FROM independent_diagnosis").fetchone()[0] == 0
        try:
            database.unlink()
            unlink_before_close = "succeeded"
        except PermissionError:
            unlink_before_close = "PermissionError: Windows file lock"
        connection.close()
        database.unlink(missing_ok=True)
        record = {"business_code_imported": False,
                  "sqlite_context_manager_leaves_connection_open": still_open,
                  "unlink_before_explicit_close": unlink_before_close,
                  "unlink_after_explicit_close": "succeeded",
                  "classification": "Test helper resource lifecycle error, not product evidence"}
    path = Path(__file__).resolve().parent / "harness-diagnosis.json"
    with path.open("x", encoding="utf-8") as output:
        json.dump(record, output, indent=2)
        output.write("\n")
    print(json.dumps(record))


if __name__ == "__main__":
    main()
