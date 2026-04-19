import logging
import tempfile
from pathlib import Path

from src.job_store import get_job, update_job
from src.pdf_processor import DocProcessingPipeline
from src.storage import storage_client


logger = logging.getLogger(__name__)
EXCEL_MIME_TYPE = "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"


def process_pdf_job(job_id: str) -> None:
    job = get_job(job_id)
    if not job:
        raise ValueError(f"Job not found in store: {job_id}")

    input_key = job.get("input_key")
    output_key = job.get("output_key")
    if not input_key or not output_key:
        raise ValueError("Job does not have input_key/output_key")

    update_job(job_id, status="processing", error="")

    try:
        with tempfile.TemporaryDirectory(prefix=f"job_{job_id}_") as temp_dir:
            input_path = Path(temp_dir) / "input.pdf"
            output_path = Path(temp_dir) / "output.xlsx"

            storage_client.download_file(input_key, str(input_path))
            pipeline = DocProcessingPipeline(str(input_path), str(output_path))
            records = pipeline.run()

            if not records:
                raise ValueError("No se detectaron casos procesables en el PDF")

            storage_client.upload_file(
                str(output_path),
                output_key,
                content_type=EXCEL_MIME_TYPE,
            )

        total_cases = len(records)
        valid_cases = sum(1 for record in records if record.estado == "valido")
        error_cases = total_cases - valid_cases

        update_job(
            job_id,
            status="completed",
            total_cases=total_cases,
            valid_cases=valid_cases,
            error_cases=error_cases,
            error="",
        )
        logger.info(
            "Job %s completado: total=%s, validos=%s, con_error=%s",
            job_id,
            total_cases,
            valid_cases,
            error_cases,
        )
    except Exception as exc:
        update_job(job_id, status="failed", error=str(exc))
        logger.exception("Job %s fallo.", job_id)
        raise
