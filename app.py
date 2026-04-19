import logging
import os
import re
import tempfile
import uuid
from pathlib import Path
from typing import Any, Dict

from fastapi import BackgroundTasks, FastAPI, File, HTTPException, UploadFile
from fastapi.responses import FileResponse, HTMLResponse

from src.job_store import create_job, get_job, update_job
from src.jobs import process_pdf_job
from src.queue_service import job_queue
from src.storage import storage_client


logging.basicConfig(level=logging.INFO, format="%(asctime)s - %(levelname)s - %(message)s")
logger = logging.getLogger(__name__)

PDF_MIME_TYPE = "application/pdf"
EXCEL_MIME_TYPE = "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"

app = FastAPI(
    title="PDF to Excel Converter",
    description="Procesamiento asincrono de resoluciones PDF hacia Excel",
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


def _job_to_response(job: Dict[str, Any]) -> Dict[str, Any]:
    payload = {
        "job_id": job.get("job_id"),
        "status": job.get("status"),
        "original_filename": job.get("original_filename"),
        "output_filename": job.get("output_filename"),
        "created_at": job.get("created_at"),
        "updated_at": job.get("updated_at"),
        "total_cases": job.get("total_cases"),
        "valid_cases": job.get("valid_cases"),
        "error_cases": job.get("error_cases"),
        "error": job.get("error") or None,
    }
    if payload["status"] == "completed" and payload["job_id"]:
        payload["download_url"] = f"/jobs/{payload['job_id']}/download"
    return payload


@app.get("/", response_class=HTMLResponse)
def get_index() -> str:
    with open("index.html", "r", encoding="utf-8") as handle:
        return handle.read()


@app.get("/health")
def health() -> Dict[str, str]:
    return {"status": "ok"}


@app.post("/jobs")
async def create_processing_job(file: UploadFile = File(...)) -> Dict[str, Any]:
    if not file.filename:
        raise HTTPException(status_code=400, detail="Debe adjuntar un archivo PDF")
    if not file.filename.lower().endswith(".pdf"):
        raise HTTPException(status_code=400, detail="El archivo debe tener extension .pdf")

    job_id = str(uuid.uuid4())
    output_filename = _build_output_filename(file.filename)
    input_key = f"uploads/{job_id}.pdf"
    output_key = f"results/{job_id}.xlsx"

    temp_input_path = ""
    enqueued = False

    try:
        with tempfile.NamedTemporaryFile(delete=False, suffix=".pdf") as temp_input:
            temp_input_path = temp_input.name
            while True:
                chunk = await file.read(1024 * 1024)
                if not chunk:
                    break
                temp_input.write(chunk)

        storage_client.upload_file(temp_input_path, input_key, content_type=PDF_MIME_TYPE)
        create_job(
            job_id,
            original_filename=file.filename,
            output_filename=output_filename,
            input_key=input_key,
            output_key=output_key,
        )

        job_queue.enqueue(process_pdf_job, job_id, job_id=job_id)
        enqueued = True

        job = get_job(job_id)
        if not job:
            raise RuntimeError("No se pudo recuperar el job despues de crearlo")

        return _job_to_response(job)
    except Exception as exc:
        logger.exception("No se pudo crear job asincrono")
        existing_job = get_job(job_id)
        if existing_job:
            update_job(job_id, status="failed", error=str(exc))
        if not enqueued:
            try:
                storage_client.delete_key(input_key)
            except Exception:
                logger.warning("No se pudo eliminar input_key fallido: %s", input_key)
        raise HTTPException(status_code=500, detail="No fue posible crear el job de procesamiento")
    finally:
        await file.close()
        _safe_remove_file(temp_input_path)


@app.get("/jobs/{job_id}")
def get_job_status(job_id: str) -> Dict[str, Any]:
    job = get_job(job_id)
    if not job:
        raise HTTPException(status_code=404, detail="Job no encontrado")
    return _job_to_response(job)


@app.get("/jobs/{job_id}/download")
def download_job_result(job_id: str, background_tasks: BackgroundTasks):
    job = get_job(job_id)
    if not job:
        raise HTTPException(status_code=404, detail="Job no encontrado")

    if job.get("status") != "completed":
        raise HTTPException(status_code=409, detail="El job aun no esta completado")

    output_key = job.get("output_key")
    if not output_key:
        raise HTTPException(status_code=500, detail="No hay salida asociada para este job")

    with tempfile.NamedTemporaryFile(delete=False, suffix=".xlsx") as temp_output:
        temp_output_path = temp_output.name

    try:
        storage_client.download_file(output_key, temp_output_path)
    except Exception:
        _safe_remove_file(temp_output_path)
        logger.exception("No se pudo descargar resultado del storage para job %s", job_id)
        raise HTTPException(status_code=500, detail="No se pudo recuperar el archivo de salida")

    background_tasks.add_task(_safe_remove_file, temp_output_path)
    return FileResponse(
        path=temp_output_path,
        filename=job.get("output_filename") or "resultado_procesado.xlsx",
        media_type=EXCEL_MIME_TYPE,
    )


if __name__ == "__main__":
    import uvicorn

    uvicorn.run("app:app", host="0.0.0.0", port=8000, reload=True)
