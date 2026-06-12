import os

# devconfig.bin.main reads DEVCONFIG_JAR at import time (Config class body).
# conftest is imported before test modules collect, so set it here; tests
# pass explicit jar paths or monkeypatch Config.jar_path themselves.
os.environ.setdefault("DEVCONFIG_JAR", "/nonexistent/jar.json")
