from pathlib import Path
import shutil
import tempfile

from fastapi import BackgroundTasks, FastAPI, File, Form, HTTPException, UploadFile
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles

from .pdf_tools import add_bookmarks_from_toc

BASE_DIR = Path(__file__).resolve().parent
STATIC_DIR = BASE_DIR / "static"
MAX_FILE_SIZE = 100 * 1024 * 1024  # 100 MB

app = FastAPI(title="PDF Bookmark Maker", version="1.0.0")
app.mount("/static", StaticFiles(directory=STATIC_DIR), name="static")


@app.get("/")
def index():
    return FileResponse(STATIC_DIR / "index.html")


@app.post("/api/process")
async def process_pdf(
    background_tasks: BackgroundTasks,
    file: UploadFile = File(...),
    hierarchy: bool = Form(True),
):
    if not file.filename:
        raise HTTPException(status_code=400, detail="No se ha seleccionado ningún archivo.")
    if not file.filename.lower().endswith(".pdf"):
        raise HTTPException(status_code=400, detail="El archivo debe ser un PDF.")

    tmp_dir = Path(tempfile.mkdtemp(prefix="pdf-bookmarks-"))
    tmp_path = tmp_dir / "input.pdf"
    out_path = tmp_dir / "output.pdf"

    try:
        total = 0
        with tmp_path.open("wb") as f:
            while True:
                chunk = await file.read(1024 * 1024)
                if not chunk:
                    break
                total += len(chunk)
                if total > MAX_FILE_SIZE:
                    raise HTTPException(status_code=413, detail="El PDF supera el límite de 100 MB.")
                f.write(chunk)

        try:
            result = add_bookmarks_from_toc(tmp_path, out_path, infer_hierarchy=hierarchy)
        except ValueError as exc:
            raise HTTPException(status_code=422, detail=str(exc)) from exc
        except Exception as exc:
            raise HTTPException(status_code=500, detail=f"No se pudo procesar el PDF: {exc}") from exc

        background_tasks.add_task(shutil.rmtree, tmp_dir, True)
        return FileResponse(
            out_path,
            media_type="application/pdf",
            filename=result["filename"],
            headers={
                "X-Bookmark-Count": str(result["bookmark_count"]),
                "X-PDF-Pages": str(result["page_count"]),
                "X-Toc-Pages": str(result["toc_pages"]),
            },
            background=background_tasks,
        )
    except Exception:
        shutil.rmtree(tmp_dir, ignore_errors=True)
        raise
