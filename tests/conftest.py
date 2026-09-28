import os
import sys
import tempfile

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
FIXTURE = os.path.join(ROOT, "tests", "fixtures", "values.json")
sys.path.insert(0, os.path.join(ROOT, "app"))
sys.path.insert(0, os.path.join(ROOT, "tool"))

# main.py builds a module-level app on import; keep it away from data/draft.db.
_tmp = tempfile.mkdtemp(prefix="low-test-")
os.environ["LOW_DB"] = os.path.join(_tmp, "import.db")
os.environ["LOW_VALUES"] = FIXTURE

import pytest  # noqa: E402


@pytest.fixture
def values_path():
    return FIXTURE


@pytest.fixture
def make_client(tmp_path):
    from fastapi.testclient import TestClient
    import main

    apps = []

    def factory(values=FIXTURE, db=None):
        app = main.create_app(db_path=str(db or tmp_path / "draft.db"), values_path=values,
                              headshots=str(tmp_path / "headshots"))
        apps.append(app)
        return TestClient(app)

    yield factory
    for a in apps:
        a.state.store.close()


@pytest.fixture
def client(make_client):
    return make_client()
