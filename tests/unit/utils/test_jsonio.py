import json

from geoetl.utils.jsonio import update_json


def test_creates_file_if_missing(tmp_path):
    path = str(tmp_path / "data.json")
    update_json(path, "aoi_1", {"status": "complete"})

    assert json.loads(open(path).read()) == {"aoi_1": {"status": "complete"}}


def test_updates_existing_key_and_preserves_others(tmp_path):
    path = str(tmp_path / "data.json")
    update_json(path, "aoi_1", {"status": "complete"})
    update_json(path, "aoi_2", {"status": "complete"})
    update_json(path, "aoi_1", {"status": "rebuilt"})

    data = json.loads(open(path).read())
    assert data["aoi_1"] == {"status": "rebuilt"}
    assert data["aoi_2"] == {"status": "complete"}


def test_recovers_from_corrupt_existing_file(tmp_path):
    path = tmp_path / "data.json"
    path.write_text("{not valid json")

    update_json(str(path), "aoi_1", {"status": "complete"})

    assert json.loads(path.read_text()) == {"aoi_1": {"status": "complete"}}


def test_does_not_leave_a_tmp_file_behind(tmp_path):
    path = tmp_path / "data.json"
    update_json(str(path), "aoi_1", {"status": "complete"})

    assert not (tmp_path / "data.json.tmp").exists()
