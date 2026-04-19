# PDF to Excel (Async for Render)

Aplicacion para procesar PDFs institucionales grandes y exportar resultados a Excel.

## Arquitectura

- Web API (FastAPI): recibe PDF, crea job y expone estado/descarga.
- Worker (RQ): procesa el PDF en segundo plano.
- Redis: cola y estado de jobs.
- Storage:
  - `local` para desarrollo.
  - `s3` para Render/produccion (S3, R2 u otro endpoint compatible).

## Endpoints

- `POST /jobs`
  - Recibe `multipart/form-data` con campo `file` (PDF).
  - Responde con `job_id` y estado inicial `queued`.
- `GET /jobs/{job_id}`
  - Devuelve estado: `queued`, `processing`, `completed`, `failed`.
- `GET /jobs/{job_id}/download`
  - Descarga el Excel cuando el job esta `completed`.
- `GET /health`
  - Healthcheck para plataforma.

## Variables de entorno

Copiar `.env.example` y ajustar segun entorno.

### Minimo para local

- `REDIS_URL=redis://localhost:6379/0`
- `STORAGE_BACKEND=local`
- `LOCAL_STORAGE_DIR=./storage`

### Minimo para Render

- `REDIS_URL` (inyectado desde keyvalue)
- `STORAGE_BACKEND=s3`
- `S3_BUCKET`
- `S3_REGION` (si aplica)
- `S3_ENDPOINT_URL` (si usas R2 u otro proveedor)
- `AWS_ACCESS_KEY_ID`
- `AWS_SECRET_ACCESS_KEY`

## Ejecucion local

1. Instalar dependencias:

```bash
pip install -r requirements.txt
```

2. Levantar Redis local (docker):

```bash
docker run --name redis-pdf -p 6379:6379 -d redis:7
```

3. Levantar API:

```bash
uvicorn app:app --reload
```

4. Levantar worker en otra terminal:

```bash
python worker.py
```

## Despliegue en Render

El archivo `render.yaml` crea:

- Servicio web: `pdf-to-excel-web`
- Servicio worker: `pdf-to-excel-worker`
- Key-Value Redis: `pdf-to-excel-redis`

Pasos:

1. Subir repositorio a GitHub.
2. En Render, crear Blueprint desde el repo.
3. Completar variables `sync: false` (S3/R2).
4. Deploy.

## Nota operativa

En Render no uses almacenamiento local para resultados finales cuando tengas web y worker separados.
Usa siempre `STORAGE_BACKEND=s3` para compartir archivos entre servicios.
