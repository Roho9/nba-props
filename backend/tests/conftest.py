import os
import tempfile

# Tests never touch the real database.
_tmp = tempfile.mkdtemp()
os.environ["DATABASE_URL"] = f"sqlite:///{_tmp}/test.sqlite3"
os.environ["ESPN_ENABLED"] = "false"
