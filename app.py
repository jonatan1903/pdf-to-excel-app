from datetime import timedelta
import gc
import io
import re

from flask import Flask, request, send_file, render_template
import fitz  # PyMuPDF
import pandas as pd


app = Flask(__name__)

MESES = {
    "enero": 1,
    "febrero": 2,
    "marzo": 3,
    "abril": 4,
    "mayo": 5,
    "junio": 6,
    "julio": 7,
    "agosto": 8,
    "septiembre": 9,
    "setiembre": 9,
    "octubre": 10,
    "noviembre": 11,
    "diciembre": 12,
}

COLUMNAS_EXCEL = [
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


def limpiar_texto(texto):
    return re.sub(r"\s+", " ", texto.replace("\n", " ")).strip()


def formatear_fecha(fecha):
    if not fecha:
        return None
    return f"{fecha.day}/{fecha.month}/{fecha.year}"


def extraer_fecha_medellin(texto):
    match_fecha = re.search(
        r"Medell[ií]n\s+(\d{1,2})\s*/\s*([A-Za-zÁÉÍÓÚáéíóúÑñ]+)\s*/\s*(\d{4})",
        texto,
        re.IGNORECASE,
    )
    if not match_fecha:
        return None

    dia = int(match_fecha.group(1))
    mes = MESES.get(match_fecha.group(2).lower())
    anio = int(match_fecha.group(3))
    if not mes:
        return None

    return pd.Timestamp(year=anio, month=mes, day=dia).date()


def extraer_bloques_por_persona(pdf):
    bloques = []
    bloque_actual = None
    inicio_resolucion = re.compile(
        r"POR MEDIO DE LA CUAL SE IMPONE UNA MEDIDA CORRECTIVA",
        re.IGNORECASE,
    )

    for indice_pagina in range(len(pdf)):
        texto = pdf[indice_pagina].get_text()
        if not texto:
            continue

        texto_limpio = limpiar_texto(texto)
        if inicio_resolucion.search(texto_limpio):
            if bloque_actual:
                bloques.append(bloque_actual)
            bloque_actual = {
                "pagina_inicio": indice_pagina + 1,
                "textos": [texto_limpio],
            }
        elif bloque_actual:
            bloque_actual["textos"].append(texto_limpio)

    if bloque_actual:
        bloques.append(bloque_actual)

    return bloques


@app.route("/", methods=["GET", "POST"])
def index():
    if request.method == "POST":
        archivo = request.files["pdf"]

        if not archivo:
            return "No se subió archivo"

        datos = []
        pdf_bytes = archivo.read()

        # Abrimos el documento completo desde memoria.
        with fitz.open(stream=pdf_bytes, filetype="pdf") as pdf:
            bloques = extraer_bloques_por_persona(pdf)

            for numero_orden, bloque in enumerate(bloques, start=1):
                texto_unido = " ".join(bloque["textos"])
                no_folios = len(bloque["textos"])

                if len(texto_unido.strip()) < 100 or not re.search(
                    r"POR MEDIO DE LA CUAL SE IMPONE",
                    texto_unido,
                    re.IGNORECASE,
                ):
                    continue

                # 1. Resolución
                match_res = re.search(
                    r"\b(PPC|NC|RESOLUCI[ÓO]N)\b[\s:.\-]*N?[°o]?\s*(\d+)-?(\d+)?",
                    texto_unido,
                    re.IGNORECASE,
                )
                if match_res:
                    prefijo_resolucion = match_res.group(1).upper()
                    numero_resolucion = f"{match_res.group(2)}" + (
                        f"-{match_res.group(3)}" if match_res.group(3) else ""
                    )
                    resolucion = f"{prefijo_resolucion} {numero_resolucion}"
                else:
                    resolucion = None

                # 2. Nombre
                match_nombre = re.search(
                    r"(?:ciudadano|señor[aeos]?|contribuyente).*?(?:\)|[:]|al?)\s+([A-ZÁÉÍÓÚÑ\s]{4,50}?)\s+(?:identificad[oa]|con\s+c[ée]dula|C\.C\.|TITULAR)",
                    texto_unido,
                    re.IGNORECASE,
                )
                nombre = match_nombre.group(1).strip() if match_nombre else None

                # 3. Tipo y número de documento. Se conserva la extracción existente.
                match_doc = re.search(
                    r"(C[ÉE]DULA\s+DE\s+CIUDADAN[IÍ]A|C\.C\.|C[ÉE]DULA|NIT|PASAPORTE|C[ÉE]DULA\s+DE\s+EXTRANJER[IÍ]A)[\s.:\-]*N?[°o]?\s*([\d\.]+)",
                    texto_unido,
                    re.IGNORECASE,
                )
                tipo_doc = match_doc.group(1).upper() if match_doc else None
                if match_doc:
                    identificacion = match_doc.group(2).replace(".", "").strip()
                else:
                    identificacion = None

                # 4. Valor de la multa
                match_multa = re.search(
                    r"por\s+valor\s+de\s*\(?\s*\$?\s*([\d.,]+)",
                    texto_unido,
                    re.IGNORECASE,
                )
                cuantia_multa = re.sub(r"\D", "", match_multa.group(1)) if match_multa else None

                # 5. Fechas
                fecha_inicial = extraer_fecha_medellin(texto_unido)
                fecha_notif_pres_dec = fecha_inicial + timedelta(days=1) if fecha_inicial else None

                # 6. Artículo. Queda calculado para respetar la lógica previa, aunque ya no se exporta.
                match_estatuido = re.search(r"ESTATUIDO", texto_unido, re.IGNORECASE)
                if match_estatuido:
                    texto_busqueda_art = texto_unido[match_estatuido.end():]
                else:
                    match_cons = re.search(r"CONSIDERANDO", texto_unido, re.IGNORECASE)
                    texto_busqueda_art = texto_unido[match_cons.end():] if match_cons else texto_unido

                match_art = re.search(r"(?:Artículo|Art\.)\s*(\d+)", texto_busqueda_art, re.IGNORECASE)
                articulo = match_art.group(1) if match_art else None
                _ = (tipo_doc, articulo)

                datos.append({
                    "numero_de_orden": numero_orden,
                    "identificación": identificacion,
                    "nombre": nombre,
                    "aviso": "",
                    "resolución": resolucion,
                    "tipo_renta_titulos": "Multas de gobierno",
                    "vigencia": "SIN VIGENCIA",
                    "cuantia_multa": cuantia_multa,
                    "no_folios": no_folios,
                    "Abogado_Responsable": "",
                    "visor_list_tipo_persona": "Natural",
                    "entregado": "",
                    "fecha_entrega": "",
                    "visor_list_regimen": "No aplica",
                    "fecha_notif_pres_dec": formatear_fecha(fecha_notif_pres_dec),
                    "numero_de_imagenes": no_folios + 1,
                    "carpeta": "",
                    "estado": "",
                    "caja": "",
                    "fecha_inicial": formatear_fecha(fecha_inicial),
                    "fecha_final": "",
                    "otro": "EXP",
                    "orden_de_caja": "",
                    "id_pdf": "",
                })

                del texto_unido

            gc.collect()

        df = pd.DataFrame(datos, columns=COLUMNAS_EXCEL)

        output = io.BytesIO()
        df.to_excel(output, index=False)
        output.seek(0)

        return send_file(
            output,
            as_attachment=True,
            download_name="resultado.xlsx",
            mimetype="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        )

    return render_template("index.html")


if __name__ == "__main__":
    app.run(debug=True)
