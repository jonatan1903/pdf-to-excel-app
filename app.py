import os
import tempfile
import logging
from fastapi import FastAPI, UploadFile, File, BackgroundTasks, HTTPException
from fastapi.responses import FileResponse, HTMLResponse

from src.pdf_processor import DocProcessingPipeline

# Configure logger
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

app = FastAPI(title="PDF to Excel Converter", description="Procesa resoluciones en PDF a Excel")

def cleanup_files(*file_paths):
    """Elimina los archivos temporales después de enviar la respuesta."""
    for path in file_paths:
        if os.path.exists(path):
            try:
                os.remove(path)
                logger.info(f"Archivo temporal eliminado: {path}")
            except Exception as e:
                logger.error(f"Error eliminando archivo {path}: {e}")

@app.get("/", response_class=HTMLResponse)
def get_index():
    with open("index.html", "r", encoding="utf-8") as f:
        html_content = f.read()
    return html_content

@app.post("/upload/")
async def upload_file(background_tasks: BackgroundTasks, file: UploadFile = File(...)):
    """Recibe un PDF, lo procesa y devuelve un archivo Excel para descargar."""

    if not file.filename:
        raise HTTPException(status_code=400, detail="Debe adjuntar un archivo PDF")
    if not file.filename.lower().endswith(".pdf"):
        raise HTTPException(status_code=400, detail="El archivo debe tener extension .pdf")

    # Guardar en disco por chunks para no cargar archivos grandes en memoria.
    with tempfile.NamedTemporaryFile(delete=False, suffix=".pdf") as tmp_in:
        while True:
            chunk = await file.read(1024 * 1024)
            if not chunk:
                break
            tmp_in.write(chunk)
        tmp_in_path = tmp_in.name

    logger.info(f"Documento temporal guardado en: {tmp_in_path}")
    
    # Archivo temporal de salida para el Excel
    tmp_out_path = tmp_in_path.replace(".pdf", "_report.xlsx")

    try:
        # Ejecutar el pipeline de procesamiento
        pipeline = DocProcessingPipeline(tmp_in_path, tmp_out_path)
        processed_records = pipeline.run()
        if not processed_records:
            raise HTTPException(status_code=422, detail="No se detectaron casos procesables en el PDF")
        if not os.path.exists(tmp_out_path):
            raise HTTPException(status_code=500, detail="No se genero el archivo de salida")

        validos = sum(1 for record in processed_records if record.estado == "valido")
        logger.info(
            "Documento procesado: %s casos, %s validos, %s con error",
            len(processed_records),
            validos,
            len(processed_records) - validos,
        )

        # Configurar la tarea de limpieza en segundo plano (se ejecuta tras el FileResponse)
        background_tasks.add_task(cleanup_files, tmp_in_path, tmp_out_path)

        # Devolver el archivo Excel generado
        return FileResponse(
            path=tmp_out_path, 
            filename=file.filename.replace(".pdf", "_procesado.xlsx"),
            media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
        )
    except HTTPException:
        cleanup_files(tmp_in_path, tmp_out_path)
        raise
    except Exception as e:
        logger.error(f"Error procesando documento: {e}")
        cleanup_files(tmp_in_path, tmp_out_path)
        raise HTTPException(status_code=500, detail="Fallo interno durante el procesamiento")
    finally:
        await file.close()

if __name__ == "__main__":
    import uvicorn
    uvicorn.run("app:app", host="0.0.0.0", port=8000, reload=True)
