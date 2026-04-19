import logging
import os
import re
import tempfile
from pathlib import Path
from typing import Dict

from fastapi import BackgroundTasks, FastAPI, File, HTTPException, UploadFile
from fastapi.responses import FileResponse, HTMLResponse

from src.pdf_processor import DocProcessingPipeline


logging.basicConfig(level=logging.INFO, format="%(asctime)s - %(levelname)s - %(message)s")
logger = logging.getLogger(__name__)

EXCEL_MIME_TYPE = "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"

app = FastAPI(
    title="PDF to Excel Converter",
    description="Procesamiento sincrono de resoluciones PDF hacia Excel",
)


def _safe_remove_file(path: str) -> None:
    if not path:
        return
    if os.path.exists(path):
        try:
            os.remove(path)
        except OSError:
            logger.exception("No se pudo eliminar archivo temporal: %s", path)


def _build_output_filename(original_filename: str) -> str:
    stem = Path(original_filename).stem or "resultado"
    safe_stem = re.sub(r"[^A-Za-z0-9_-]", "_", stem).strip("_") or "resultado"
    return f"{safe_stem}_procesado.xlsx"


@app.get("/", response_class=HTMLResponse)
def get_index() -> str:
    with open("index.html", "r", encoding="utf-8") as handle:
        return handle.read()


@app.get("/health")
def health() -> Dict[str, str]:
    return {"status": "ok"}


@app.post("/upload/")
async def upload_file(background_tasks: BackgroundTasks, file: UploadFile = File(...)):
    if not file.filename:
        raise HTTPException(status_code=400, detail="Debe adjuntar un archivo PDF")
    if not file.filename.lower().endswith(".pdf"):
        raise HTTPException(status_code=400, detail="El archivo debe tener extension .pdf")

    temp_input_path = ""
    temp_output_path = ""

    try:
        with tempfile.NamedTemporaryFile(delete=False, suffix=".pdf") as temp_input:
            temp_input_path = temp_input.name
            while True:
                chunk = await file.read(1024 * 1024)
                if not chunk:
                    break
                temp_input.write(chunk)

        with tempfile.NamedTemporaryFile(delete=False, suffix=".xlsx") as temp_output:
            temp_output_path = temp_output.name

        pipeline = DocProcessingPipeline(temp_input_path, temp_output_path)
        processed_records = pipeline.run()
        if not processed_records:
            _safe_remove_file(temp_output_path)
            raise HTTPException(status_code=422, detail="No se detectaron casos procesables en el PDF")

        valid_cases = sum(1 for record in processed_records if record.estado == "valido")
        logger.info(
            "Documento procesado: total=%s, validos=%s, con_error=%s",
            len(processed_records),
            valid_cases,
            len(processed_records) - valid_cases,
        )

        background_tasks.add_task(_safe_remove_file, temp_output_path)
        return FileResponse(
            path=temp_output_path,
            filename=_build_output_filename(file.filename),
            media_type=EXCEL_MIME_TYPE,
        )
    except HTTPException:
        _safe_remove_file(temp_output_path)
        raise
    except Exception:
        _safe_remove_file(temp_output_path)
        logger.exception("Fallo interno durante el procesamiento sincrono")
        raise HTTPException(status_code=500, detail="No fue posible procesar el PDF")
    finally:
        await file.close()
        _safe_remove_file(temp_input_path)


if __name__ == "__main__":
    import uvicorn

    uvicorn.run("app:app", host="0.0.0.0", port=8000, reload=True)
