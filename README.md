# PDF to Excel (Web Service Unico)

Aplicacion para procesar PDFs institucionales y descargar un Excel resultado desde la misma peticion HTTP.

## Arquitectura

- FastAPI en un solo servicio web.
- Sin Redis.
- Sin worker.
- Sin almacenamiento externo obligatorio.

## Endpoints

- `GET /`
  - Interfaz web para subir el PDF.
- `POST /upload/`
  - Recibe `multipart/form-data` con campo `file`.
  - Procesa el PDF de forma sincronica y devuelve el Excel para descarga.
- `GET /health`
  - Healthcheck del servicio.

## Variables de entorno

No hay variables obligatorias para ejecutar el proyecto.

## Ejecucion local

1. Instalar dependencias:

```bash
pip install -r requirements.txt
```

2. Levantar API:

```bash
uvicorn app:app --reload
```

3. Abrir en navegador:

```text
http://127.0.0.1:8000
```

## Despliegue en Render

`render.yaml` esta preparado para crear solo un Web Service.

Pasos:

1. Subir repositorio a GitHub.
2. En Render, crear servicio desde el repo (o Blueprint).
3. Confirmar rama `main` y desplegar.

## Limitacion esperada

El procesamiento es sincronico: el usuario espera la respuesta mientras se genera el Excel.
Para cargas muy altas o concurrencia elevada, conviene volver a una arquitectura con cola y worker.
