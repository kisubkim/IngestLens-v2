import io

from fastapi.testclient import TestClient
from PIL import Image

from app.config import settings
from app.main import app

from .test_purge import LOCAL, _ingest


def _img(png: bytes) -> Image.Image:
    return Image.open(io.BytesIO(png)).convert("RGB")


def test_chunk_preview_highlights_the_chunk_page(sample_pdf):
    with TestClient(app, client=LOCAL) as client:
        doc_id, run = _ingest(client, sample_pdf, "sample.pdf")
        chunks = client.get(f"/api/runs/{run['id']}/chunks").json()["items"]
        table = next(c for c in chunks if "table" in c["element_types"])
        page = table["pages"][0]

        res = client.get(f"/api/chunks/{table['id']}/preview.png?dpi=60")
        assert res.status_code == 200 and res.headers["content-type"] == "image/png"
        highlighted = _img(res.content)
        plain = _img(client.get(f"/api/documents/{doc_id}/pages/{page}.png?dpi=60").content)
        assert highlighted.size == plain.size
        assert highlighted.tobytes() != plain.tobytes()  # the highlight changed pixels
        assert (settings.data_dir / "pages" / doc_id / f"chunk_{table['id']}_{page}_60.png").exists()

        plain_png = client.get(f"/api/chunks/{table['id']}/preview.png?dpi=60&highlight=false")
        assert _img(plain_png.content).tobytes() == plain.tobytes()

        other = next(p for p in range(6) if p not in table["pages"])
        assert client.get(f"/api/chunks/{table['id']}/preview.png?page={other}").status_code == 404
        assert client.get("/api/chunks/no-such-chunk/preview.png").status_code == 404

        client.delete(f"/api/documents/{doc_id}")
        assert not (settings.data_dir / "pages" / doc_id).exists()  # cached previews go with the document
