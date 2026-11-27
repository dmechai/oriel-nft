import hashlib
import io
import json
import posixpath
import os
import shutil
import tempfile
import zipfile

os.environ.setdefault("ORIEL_DATA", tempfile.mkdtemp(prefix="oriel-pytest-"))

import httpx
import pytest
from fastapi.testclient import TestClient

from server import service
from server.combo import CollectionError, generate_combos
from server.images import alpha_ratio, remove_chroma
from server.main import app
from server.provider import ProviderClient, ProviderError
from server.settings import data_dir
from PIL import Image


@pytest.fixture(autouse=True)
def fresh_data():
    root = data_dir()
    if root.exists():
        shutil.rmtree(root)
    service.reset_db()
    yield


def test_rules_refuse_to_pad_duplicates():
    categories = [
        {"id": "bg", "values": [{"id": "a", "approved": True, "asset_id": "1", "weight": 1}]},
        {"id": "hat", "values": [{"id": "b", "approved": True, "asset_id": "2", "weight": 1}]},
    ]
    with pytest.raises(CollectionError, match="不会用重复图凑数"):
        generate_combos(categories, [], 4, 3)


def test_chroma_removes_screen():
    image = Image.new("RGBA", (8, 8), (0, 255, 80, 255))
    cleared = remove_chroma(image)
    assert alpha_ratio(cleared, transparent=True) > 0.9


def test_sample_collection_exports_without_secrets():
    client = TestClient(app)
    created = client.post("/api/sample-project", json={"count": 100})
    assert created.status_code == 200, created.text
    project = created.json()
    assert project["nft_count"] == 100
    exported = client.post(f"/api/projects/{project['id']}/export")
    assert exported.status_code == 200
    with zipfile.ZipFile(io.BytesIO(exported.content)) as archive:
        assert archive.testzip() is None
        assert len(archive.namelist()) == 202
        images, combinations = set(), set()
        for token in range(1, 101):
            metadata = json.loads(archive.read(f"metadata/{token}.json"))
            path = posixpath.normpath(posixpath.join("metadata", metadata["image"]))
            assert path == f"images/{token}.png"
            with Image.open(io.BytesIO(archive.read(path))) as image:
                assert image.format == "PNG"
                assert image.size == (640, 640)
                images.add(hashlib.sha256(image.convert("RGBA").tobytes()).digest())
            combinations.add(tuple(sorted((item["trait_type"], item["value"]) for item in metadata["attributes"])))
        assert len(images) == len(combinations) == 100
        assert json.loads(archive.read("summary/rarity.json"))["total"] == 100
        manifest = archive.read("summary/manifest.json")
        assert json.loads(manifest)["count"] == 100
        assert b"api_key" not in manifest and b"secret" not in manifest.lower()


def test_provider_key_is_not_returned():
    client = TestClient(app)
    response = client.post(
        "/api/providers",
        json={"name": "本地", "base_url": "http://127.0.0.1:9/v1", "api_key": "sk-test-secret", "is_default": True},
    )
    assert response.status_code == 200
    body = response.json()
    assert "sk-test-secret" not in json.dumps(body)
    assert body["has_key"] is True


def test_trial_gate_and_failed_render_preserve_existing_collection(monkeypatch):
    client = TestClient(app)
    project = client.post("/api/sample-project", json={"count": 4}).json()
    project_id = project["id"]
    before = client.get(f"/api/projects/{project_id}/nfts").json()["items"]
    service.generate_trial(project_id, lambda *_: None)
    with pytest.raises(CollectionError, match="确认当前素材"):
        service.mint_collection(project_id, 4, lambda *_: None)
    assert client.post(f"/api/projects/{project_id}/trial/approve").json()["trial"]["approved"]
    monkeypatch.setattr(service, "render_choice", lambda *_: Image.new("RGBA", (32, 32)))
    with pytest.raises(CollectionError, match="像素完全一致"):
        service.mint_collection(project_id, 4, lambda *_: None)
    assert client.get(f"/api/projects/{project_id}/nfts").json()["items"] == before
    contract = {**project["style_contract"], "lighting": "新光照"}
    result = client.put(f"/api/projects/{project_id}/contract", json=contract).json()
    assert not result["trial"]["approved"]
    assert all(not value["approved"] for cat in result["plan"]["categories"] for value in cat["values"])


def test_required_reference_edit_never_falls_back(monkeypatch):
    client = ProviderClient({"base_url": "http://localhost/v1", "api_key_enc": "", "image_model": "generator", "edit_model": "editor"})
    calls = []

    def request(method, path, **kwargs):
        calls.append(path)
        if path == "/images/edits":
            assert kwargs["data"]["model"] == "editor"
            assert kwargs["files"]["image"][1] == b"reference"
            return httpx.Response(404, json={"error": {"message": "unsupported"}})
        assert kwargs["json"]["model"] == "generator"
        return httpx.Response(200, json={"data": [{"b64_json": "aW1hZ2U="}]})

    monkeypatch.setattr(client, "_request", request)
    with pytest.raises(ProviderError, match="不支持参考图编辑"):
        client.image_from_reference("prompt", "1024x1024", b"reference", require_reference=True)
    assert calls == ["/images/edits"]
    assert client.image_from_reference("prompt", "1024x1024", b"reference") == (b"image", False)
