"""Testovi na privremenoj bazi — nikad ne diraju stvarnu."""
import os, tempfile, pathlib

_tmp = pathlib.Path(tempfile.mkdtemp(prefix="ponude_test_")) / "test.db"
os.environ["DATABASE_URL"] = "sqlite:///" + str(_tmp).replace("\\", "/")
os.environ["ADMIN_PASSWORD"] = "admin"
os.environ["AI_DEMO"] = "1"
