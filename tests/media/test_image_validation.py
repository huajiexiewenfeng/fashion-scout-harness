import pytest
from fashion_scout.domain import ScoutError
from fashion_scout.media.images import validate_image, disk_gate
from tests.t2_helpers import png


def test_decode_hash_and_pixel_limit(tmp_path):
    path=tmp_path/"image"
    path.write_bytes(png())
    value=validate_image(path,1024,100)
    assert (value["format"],value["width"],value["height"])==("PNG",8,9)
    with pytest.raises(ScoutError) as error:
        validate_image(path,1024,50)
    assert error.value.code=="IMAGE_PIXEL_LIMIT"
    with pytest.raises(ScoutError):
        validate_image(path,1,100)


def test_200_html_not_an_image(tmp_path):
    path=tmp_path/"image"
    path.write_text("<html>denied</html>")
    with pytest.raises(ScoutError) as error:
        validate_image(path,1024,100)
    assert error.value.code=="IMAGE_INVALID"


def test_disk_reserve_stops_before_download(tmp_path,monkeypatch):
    import shutil
    from types import SimpleNamespace
    monkeypatch.setattr(shutil,"disk_usage",lambda path:SimpleNamespace(free=100))
    with pytest.raises(ScoutError) as error:
        disk_gate(SimpleNamespace(root=tmp_path,media=tmp_path),90,20)
    assert error.value.code=="DISK_RESERVE"
