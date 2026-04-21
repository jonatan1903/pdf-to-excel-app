import logging
import re
import unicodedata
from dataclasses import dataclass
from datetime import timedelta
from typing import Iterator, List, Optional, Tuple

import fitz  # PyMuPDF
import pandas as pd

logging.basicConfig(level=logging.INFO, format="%(asctime)s - %(levelname)s - %(message)s")
logger = logging.getLogger(__name__)


@dataclass
class CaseRecord:
    raw_text: str = ""
    resolucion: Optional[str] = None
    encabezado: Optional[str] = None
    nombre: Optional[str] = None
    tipo_documento: Optional[str] = None
    numero_identificacion: Optional[str] = None
    articulo: Optional[str] = None
    cuantia_multa: Optional[str] = None
    fecha_inicial: Optional[pd.Timestamp] = None
    estado: str = "pendiente"
    error_msg: Optional[str] = None
    pagina_inicio: Optional[int] = None
    pagina_fin: Optional[int] = None


class PDFReader:
    """Lee el PDF en streaming (pagina por pagina) sin cargar todo en memoria."""

    def __init__(self, file_path: str):
        self.file_path = file_path

    def read_pages(self) -> Iterator[Tuple[int, str]]:
        try:
            with fitz.open(self.file_path) as doc:
                for page_idx in range(doc.page_count):
                    try:
                        page = doc.load_page(page_idx)
                        text = page.get_text("text")
                        if text is None:
                            logger.warning("Pagina %s sin texto (None).", page_idx + 1)
                            continue
                        yield page_idx + 1, text
                    except Exception:
                        logger.exception("Error leyendo la pagina %s.", page_idx + 1)
                        continue
        except Exception:
            logger.exception("No se pudo abrir el PDF: %s", self.file_path)
            raise


class TextNormalizer:
    """Normaliza texto para hacer la deteccion y extraccion mas tolerante."""

    SYMBOL_REPLACEMENTS = {
        "\u00a0": " ",
        "Nº": "N°",
        "N-": "N°",
    }

    @classmethod
    def normalize(cls, text: str) -> str:
        if not text:
            return ""

        normalized = text.replace("\r", " ").replace("\n", " ")
        for old, new in cls.SYMBOL_REPLACEMENTS.items():
            normalized = normalized.replace(old, new)

        # Estandariza variaciones de N + numero: N 123, N-123, N°123 -> N° 123.
        normalized = re.sub(
            r"\bN\s*[-.:]?\s*(?:RO\.?|O\.?|º|°)?\s*(?=\d)",
            "N° ",
            normalized,
            flags=re.IGNORECASE,
        )
        normalized = re.sub(r"\s+", " ", normalized)
        return normalized.strip().upper()


class CaseDetector:
    """Detecta inicio de casos tipo ORDEN DE POLICIA PPC N° 52370 o ORDEN DE NC- N° 58152."""

    CASE_START_PATTERN = re.compile(
        r"ORDEN\s+DE\s+(?:POLIC[IÍ]A\s+)?(?P<tipo>PPC|NC)\s*[-:]?\s*(?:N(?:RO|O|°|º)?\.?\s*)?(?P<num>\d{3,8})"
    )

    @classmethod
    def find_case_starts(cls, text: str) -> List[dict]:
        matches: List[dict] = []
        for match in cls.CASE_START_PATTERN.finditer(text):
            tipo = match.group("tipo")
            num = match.group("num")
            matches.append(
                {
                    "header": match.group(0).strip(),
                    "resolution": f"{tipo} {num}",
                    "start": match.start(),
                    "end": match.end(),
                }
            )
        return matches


class CaseBuilder:
    """Construye casos por contenido, no por numero fijo de paginas."""

    def __init__(self):
        self.cases: List[CaseRecord] = []
        self._current_resolution: Optional[str] = None
        self._current_header: Optional[str] = None
        self._current_start_page: Optional[int] = None
        self._current_text_parts: List[str] = []
        self._last_page_seen: int = 0

    def _append_current_text(self, text: str):
        chunk = text.strip()
        if chunk:
            self._current_text_parts.append(chunk)

    def _close_current_case(self, end_page: int):
        if not self._current_resolution:
            return

        record = CaseRecord(
            raw_text=" ".join(self._current_text_parts).strip(),
            resolucion=self._current_resolution,
            encabezado=self._current_header,
            pagina_inicio=self._current_start_page,
            pagina_fin=end_page,
        )
        self.cases.append(record)

        self._current_resolution = None
        self._current_header = None
        self._current_start_page = None
        self._current_text_parts = []

    def process_text_chunk(self, page_number: int, text: str):
        self._last_page_seen = page_number
        detector_matches = CaseDetector.find_case_starts(text)

        if not detector_matches:
            if self._current_resolution:
                self._append_current_text(text)
            return

        # Si ya habia caso abierto, cerrarlo con el texto previo al siguiente encabezado.
        if self._current_resolution:
            prefix = text[: detector_matches[0]["start"]]
            match_is_near_page_start = detector_matches[0]["start"] < 1000
            if not match_is_near_page_start:
                self._append_current_text(prefix)
            end_page = page_number - 1 if match_is_near_page_start else page_number
            self._close_current_case(end_page)

        for idx, match_info in enumerate(detector_matches):
            # El encabezado con "Medellin fecha" suele estar antes de ORDEN DE...
            start = 0 if idx == 0 and match_info["start"] < 1000 else match_info["start"]
            has_next = idx < len(detector_matches) - 1
            next_start = detector_matches[idx + 1]["start"] if has_next else None
            segment = text[start:next_start] if has_next else text[start:]

            if has_next:
                self.cases.append(
                    CaseRecord(
                        raw_text=segment.strip(),
                        resolucion=match_info["resolution"],
                        encabezado=match_info["header"],
                        pagina_inicio=page_number,
                        pagina_fin=page_number,
                    )
                )
                continue

            # Ultimo caso encontrado en el chunk: queda abierto por si continua en paginas siguientes.
            self._current_resolution = match_info["resolution"]
            self._current_header = match_info["header"]
            self._current_start_page = page_number
            self._current_text_parts = []
            self._append_current_text(segment)

    def finish(self) -> List[CaseRecord]:
        if self._current_resolution:
            self._close_current_case(self._last_page_seen)
        return self.cases


class FieldExtractor:
    """Extrae campos con regex tolerantes a variaciones de formato."""

    MESES = {
        "ENERO": 1,
        "FEBRERO": 2,
        "MARZO": 3,
        "ABRIL": 4,
        "MAYO": 5,
        "JUNIO": 6,
        "JULIO": 7,
        "AGOSTO": 8,
        "SEPTIEMBRE": 9,
        "SETIEMBRE": 9,
        "OCTUBRE": 10,
        "NOVIEMBRE": 11,
        "DICIEMBRE": 12,
    }

    DOC_TYPES_PATTERN = (
        r"DOCUMENTO\s+DE\s+IDENTIFICACI[ÓO]N\s+EXTRANJERO"
        r"|C[ÉE]DULA\s+DE\s+CIUDADAN[IÍ]A"
        r"|C\.?\s*C\.?"
        r"|TARJETA\s+DE\s+IDENTIDAD"
        r"|T\.?\s*I\.?"
        r"|C[ÉE]DULA\s+DE\s+EXTRANJER[IÍ]A"
        r"|C\.?\s*E\.?"
        r"|DNI"
        r"|PASAPORTE"
        r"|RUT"
        r"|RUC"
    )

    NAME_PATTERNS = [
        re.compile(
            r"\bCIUDADAN[OA]\s*\(?A\)?\s+([A-ZÁÉÍÓÚÑ][A-ZÁÉÍÓÚÑ°'\- ]{8,100}?)(?=,?\s+IDENTIFICAD[OA]|,?\s+PORTADOR|,?\s+QUIEN|,?\s+CON\s+(?:CEDULA|C\.?\s*C|TARJETA|DNI|CE|PASAPORTE|DOCUMENTO))"
        ),
        re.compile(
            r"\bA\s+NOMBRE\s+DE\s+([A-ZÁÉÍÓÚÑ][A-ZÁÉÍÓÚÑ°'\- ]{8,100}?)(?=,|\.|\s+IDENTIFICAD[OA])"
        ),
        re.compile(
            r"\bINFRACTOR(?:A)?\s*[:\-]\s*([A-ZÁÉÍÓÚÑ][A-ZÁÉÍÓÚÑ°'\- ]{8,100}?)(?=,|\.|\s+IDENTIFICAD[OA])"
        ),
    ]

    DOC_ID_PATTERNS = [
        re.compile(
            rf"\bIDENTIFICAD[OA]\s*\(?A\)?\s*(?:CON\s+)?(?P<doc>{DOC_TYPES_PATTERN})\s*(?:N(?:RO|O|°|º)?\.?\s*)?(?P<id>[A-Z0-9\.\-]{{1,25}})"
        ),
        re.compile(
            rf"\b(?P<doc>{DOC_TYPES_PATTERN})\s*(?:N(?:RO|O|°|º)?\.?\s*)?(?P<id>[A-Z0-9\.\-]{{1,25}})"
        ),
    ]

    ARTICLE_PATTERNS = [
        re.compile(r"\bESTATUIDO\s+EN\s+EL\s+ART\.?\s*(\d+[A-Z]?)"),
        re.compile(r"\bART\.?\s*(\d+[A-Z]?)\s*[\-–—]\s*COMPORTAMIENTOS"),
        re.compile(r"\bART[IÍ]CULO\s+(\d+[A-Z]?)"),
        re.compile(r"\bART\.?\s*(\d+[A-Z]?)"),
    ]

    FINE_VALUE_PATTERNS = [
        re.compile(r"\bEQUIVALE\s+A\s*\(?\s*\$?\s*([\d\.,]+)"),
        re.compile(r"\bPOR\s+VALOR\s+DE\s*\(?\s*\$?\s*([\d\.,]+)"),
        re.compile(r"\bVALOR\s+DE\s+LA\s+MULTA\s*[:\-]?\s*\$?\s*([\d\.,]+)"),
    ]

    DATE_PATTERN = re.compile(
        r"\bMEDELLIN\s+(\d{1,2})\s*/\s*([A-Z]+)\s*/\s*(\d{4})"
    )

    INVALID_NAME_TOKENS = {
        "IDENTIFICADO",
        "IDENTIFICADA",
        "CEDULA",
        "CIUDADANIA",
        "ART",
        "ARTICULO",
        "LEY",
    }

    @classmethod
    def _normalize_doc_type(cls, raw_doc: str) -> str:
        key = "".join(
            char
            for char in unicodedata.normalize("NFD", raw_doc)
            if unicodedata.category(char) != "Mn"
        )
        key = key.replace(" ", "").replace(".", "")
        mapping = {
            "DOCUMENTODEIDENTIFICACIONEXTRANJERO": "CE",
            "CEDULADECIUDADANIA": "CC",
            "CC": "CC",
            "TARJETADEIDENTIDAD": "TI",
            "TI": "TI",
            "CEDULADEEXTRANJERIA": "CE",
            "CE": "CE",
            "DNI": "DNI",
            "PASAPORTE": "PASAPORTE",
            "RUT": "RUT",
            "RUC": "RUC",
        }
        return mapping.get(key, raw_doc.strip())

    @classmethod
    def _sanitize_id(cls, doc_type: str, raw_id: str) -> str:
        if doc_type in {"CC", "TI", "CE", "DNI", "RUT", "RUC"}:
            cleaned = re.sub(r"[^0-9]", "", raw_id)
            return cleaned
        return re.sub(r"[^A-Z0-9]", "", raw_id)

    @classmethod
    def _looks_like_name(cls, candidate: str) -> bool:
        tokens = [token for token in candidate.split(" ") if token]
        if len(tokens) < 2:
            return False
        if set(tokens) & cls.INVALID_NAME_TOKENS:
            return False
        return True

    @classmethod
    def _extract_name(cls, text: str) -> Optional[str]:
        for pattern in cls.NAME_PATTERNS:
            match = pattern.search(text)
            if not match:
                continue
            candidate = re.sub(r"\s+", " ", match.group(1)).strip(" ,.;:-")
            # OCR frecuente: MOREN° -> MORENO, CAN° -> CANO.
            candidate = candidate.replace("°", "O").replace("º", "O")
            if cls._looks_like_name(candidate):
                return candidate
        return None

    @classmethod
    def _extract_doc_and_id(cls, text: str) -> Tuple[Optional[str], Optional[str]]:
        for pattern in cls.DOC_ID_PATTERNS:
            match = pattern.search(text)
            if not match:
                continue
            doc_type = cls._normalize_doc_type(match.group("doc"))
            doc_id = cls._sanitize_id(doc_type, match.group("id"))
            if doc_id == "0":
                return doc_type, doc_id
            if len(doc_id) >= 5:
                return doc_type, doc_id
            if doc_type:
                return doc_type, None
        return None, None

    @classmethod
    def _extract_article(cls, text: str) -> Optional[str]:
        for pattern in cls.ARTICLE_PATTERNS:
            match = pattern.search(text)
            if match:
                return f"ART. {match.group(1)}"
        return None

    @staticmethod
    def _strip_accents(text: str) -> str:
        return "".join(
            char
            for char in unicodedata.normalize("NFD", text)
            if unicodedata.category(char) != "Mn"
        )

    @classmethod
    def _extract_fine_value(cls, text: str) -> Optional[str]:
        for pattern in cls.FINE_VALUE_PATTERNS:
            match = pattern.search(text)
            if match:
                cleaned = re.sub(r"\D", "", match.group(1))
                return cleaned or None
        return None

    @classmethod
    def _extract_initial_date(cls, text: str) -> Optional[pd.Timestamp]:
        normalized_text = cls._strip_accents(text)
        match = cls.DATE_PATTERN.search(normalized_text)
        if not match:
            return None

        month_name = cls._strip_accents(match.group(2))
        month = cls.MESES.get(month_name)
        if not month:
            return None

        return pd.Timestamp(
            year=int(match.group(3)),
            month=month,
            day=int(match.group(1)),
        )

    @classmethod
    def extract_fields(cls, record: CaseRecord) -> CaseRecord:
        text = record.raw_text or ""
        record.nombre = cls._extract_name(text)
        record.tipo_documento, record.numero_identificacion = cls._extract_doc_and_id(text)
        record.articulo = cls._extract_article(text)
        record.cuantia_multa = cls._extract_fine_value(text)
        record.fecha_inicial = cls._extract_initial_date(text)
        return record


class Validator:
    """Valida consistencia minima para auditar registros incompletos."""

    @staticmethod
    def validate(record: CaseRecord) -> CaseRecord:
        zero_id = bool(record.numero_identificacion) and bool(
            re.fullmatch(r"0+", str(record.numero_identificacion).strip())
        )

        missing_fields = []
        if not record.resolucion:
            missing_fields.append("Resolucion")
        if not record.nombre:
            missing_fields.append("Nombre")
        if not record.tipo_documento:
            missing_fields.append("Tipo documento")
        if not record.numero_identificacion:
            missing_fields.append("ID")
        if not record.articulo:
            missing_fields.append("Articulo")

        errors = []
        if missing_fields:
            errors.append(f"Faltan campos: {', '.join(missing_fields)}")
        if zero_id:
            errors.append("Documento de identificacion en cero (0) en fuente")

        if errors:
            record.estado = "con error"
            record.error_msg = " | ".join(errors)
        else:
            record.estado = "valido"
            record.error_msg = None
        return record


class ExcelExporter:
    """Exporta resultados a Excel con el formato requerido por el cargue."""

    COLUMNS = [
        "numero_de_orden",
        "identificación",
        "nombre",
        "aviso",
        "resolución",
        "tipo_renta_titulos",
        "vigencia",
        "cuantia_multa",
        "no_folios",
        "Abogado_Responsable",
        "visor_list_tipo_persona",
        "entregado",
        "fecha_entrega",
        "visor_list_regimen",
        "fecha_notif_pres_dec",
        "numero_de_imagenes",
        "carpeta",
        "estado",
        "caja",
        "fecha_inicial",
        "fecha_final",
        "otro",
        "orden_de_caja",
        "id_pdf",
    ]

    def __init__(self, output_path: str):
        self.output_path = output_path

    @staticmethod
    def _format_date(date_value: Optional[pd.Timestamp]) -> Optional[str]:
        if date_value is None:
            return None
        return f"{date_value.day}/{date_value.month}/{date_value.year}"

    @staticmethod
    def _folio_count(record: CaseRecord) -> Optional[int]:
        if record.pagina_inicio is None or record.pagina_fin is None:
            return None
        return max(record.pagina_fin - record.pagina_inicio + 1, 1)

    def export(self, records: List[CaseRecord]):
        data = []
        for numero_orden, record in enumerate(records, start=1):
            no_folios = self._folio_count(record)
            fecha_notif = (
                record.fecha_inicial + timedelta(days=1)
                if record.fecha_inicial is not None
                else None
            )

            data.append({
                "numero_de_orden": numero_orden,
                "identificación": record.numero_identificacion,
                "nombre": record.nombre,
                "aviso": "",
                "resolución": record.resolucion,
                "tipo_renta_titulos": "Multas de gobierno",
                "vigencia": "SIN VIGENCIA",
                "cuantia_multa": record.cuantia_multa,
                "no_folios": no_folios,
                "Abogado_Responsable": "",
                "visor_list_tipo_persona": "Natural",
                "entregado": "",
                "fecha_entrega": "",
                "visor_list_regimen": "No aplica",
                "fecha_notif_pres_dec": self._format_date(fecha_notif),
                "numero_de_imagenes": no_folios + 1 if no_folios is not None else None,
                "carpeta": "",
                "estado": "",
                "caja": "",
                "fecha_inicial": self._format_date(record.fecha_inicial),
                "fecha_final": "",
                "otro": "EXP",
                "orden_de_caja": "",
                "id_pdf": "",
            })

        df = pd.DataFrame(data, columns=self.COLUMNS)
        try:
            df.to_excel(self.output_path, index=False)
            logger.info(
                "Reporte exportado exitosamente a %s (%s registros)",
                self.output_path,
                len(data),
            )
        except Exception:
            logger.exception("Error exportando a Excel: %s", self.output_path)


class DocProcessingPipeline:
    """Orquestador principal del pipeline desacoplado."""

    def __init__(self, pdf_path: str, output_path: str):
        self.reader = PDFReader(pdf_path)
        self.normalizer = TextNormalizer()
        self.builder = CaseBuilder()
        self.exporter = ExcelExporter(output_path)

    def run(self) -> List[CaseRecord]:
        logger.info("Iniciando procesamiento de: %s", self.reader.file_path)

        try:
            for page_number, raw_chunk in self.reader.read_pages():
                clean_chunk = self.normalizer.normalize(raw_chunk)
                if not clean_chunk:
                    logger.warning("Pagina %s sin texto util tras normalizacion.", page_number)
                    continue
                self.builder.process_text_chunk(page_number, clean_chunk)
        except Exception:
            logger.exception("Falla critica en lectura o normalizacion.")
            self.exporter.export([])
            return []

        cases = self.builder.finish()
        logger.info("Se detectaron %s casos.", len(cases))

        processed_cases: List[CaseRecord] = []
        for case in cases:
            try:
                extracted = FieldExtractor.extract_fields(case)
                validated = Validator.validate(extracted)
                processed_cases.append(validated)
            except Exception:
                logger.exception("Error procesando caso %s.", case.resolucion)
                case.estado = "con error"
                case.error_msg = "Fallo interno en extraccion o validacion"
                processed_cases.append(case)

        self.exporter.export(processed_cases)
        logger.info("Procesamiento finalizado.")
        return processed_cases

