from flask import Flask, request, send_file, render_template
import fitz  # PyMuPDF
import pandas as pd
import re
import os
import io
import gc

app = Flask(__name__)

@app.route("/", methods=["GET", "POST"])
def index():
    if request.method == "POST":
        archivo = request.files["pdf"]

        if not archivo:
            return "No se subió archivo"

        datos = []
        pdf_bytes = archivo.read()

        # Abrimos el documento completo desde memoria
        with fitz.open(stream=pdf_bytes, filetype="pdf") as pdf:
            total_paginas = len(pdf)
            texto_bloque = []

            # Extraemos TODO el texto primero
            for i in range(total_paginas):
                texto = pdf[i].get_text()
                if texto:
                    texto_bloque.append(texto.replace("\n", " "))
            
            texto_doc_completo = " ".join(texto_bloque)
            texto_doc_completo = re.sub(r"\s+", " ", texto_doc_completo) # Limpiar hiper-espaciado

            # Separar el documento por cada "POR MEDIO DE LA CUAL SE IMPONE UNA MEDIDA CORRECTIVA"
            # (?=...) asegura que dejemos esa frase al inicio de cada bloque en lugar de borrarla
            bloques = re.split(r"(?=POR MEDIO DE LA CUAL SE IMPONE UNA MEDIDA CORRECTIVA)", texto_doc_completo, flags=re.IGNORECASE)

            for texto_unido in bloques:
                # Ignorar bloques que no sean una resolución o sean basura del inicio
                if len(texto_unido.strip()) < 100 or not re.search(r"POR MEDIO DE LA CUAL SE IMPONE", texto_unido, re.IGNORECASE):
                    continue

                # EXPRESIONES REGULARES ROBUSTAS (toleran más variaciones y errores de OCR)
                # 1. Resolución
                match_res = re.search(r"(?:PPC|NC|RESOLUCI[OÓ]N)[\s:.\-]*N?[°o]?\s*(\d+)-?(\d+)?", texto_unido, re.IGNORECASE)
                if match_res:
                    resolucion = f"{match_res.group(1)}" + (f"-{match_res.group(2)}" if match_res.group(2) else "")
                else:
                    resolucion = None

                # 2. Nombre
                match_nombre = re.search(
                    r"(?:ciudadano|señor[aeos]?|contribuyente).*?(?:\)|[:]|al?)\s+([A-ZÁÉÍÓÚÑ\s]{4,50}?)\s+(?:identificad[oa]|con\s+c[ée]dula|C\.C\.|TITULAR)",
                    texto_unido,
                    re.IGNORECASE
                )
                nombre = match_nombre.group(1).strip() if match_nombre else None

                # 3. Tipo y Número de Documento (Limpia puntos en los números)
                match_doc = re.search(
                    r"(C[ÉE]DULA\s+DE\s+CIUDADAN[IÍ]A|C\.C\.|C[ÉE]DULA|NIT|PASAPORTE|C[ÉE]DULA\s+DE\s+EXTRANJER[IÍ]A)[\s.:\-]*N?[°o]?\s*([\d\.]+)",
                    texto_unido,
                    re.IGNORECASE
                )
                tipo_doc = match_doc.group(1).upper() if match_doc else None
                if match_doc:
                    identificacion = match_doc.group(2).replace(".", "").strip() # Quitar puntos de miles
                else:
                    identificacion = None

                # 4. Artículo (Anclado a la palabra "ESTATUIDO" que va después del CONSIDERANDO)
                match_estatuido = re.search(r"ESTATUIDO", texto_unido, re.IGNORECASE)
                
                if match_estatuido:
                    # Si encuentra "ESTATUIDO", recorta el texto desde ahí en adelante
                    texto_busqueda_art = texto_unido[match_estatuido.end():]
                else:
                    # Respaldo: Si por alguna razón de escaneo no lee "ESTATUIDO", usa "CONSIDERANDO"
                    match_cons = re.search(r"CONSIDERANDO", texto_unido, re.IGNORECASE)
                    texto_busqueda_art = texto_unido[match_cons.end():] if match_cons else texto_unido
                
                match_art = re.search(r"(?:Art[ií]culo|Art\.)\s*(\d+)", texto_busqueda_art, re.IGNORECASE)
                articulo = match_art.group(1) if match_art else None

                # Guardar y limpiar
                datos.append({
                    "Resolución": resolucion,
                    "Nombre": nombre,
                    "Tipo Documento": tipo_doc,
                    "Identificación": identificacion,
                    "Artículo": articulo
                })

                # Limpieza de memoria en el ciclo
                del texto_unido
            
            # Limpieza profunda manual al terminar de extraer
            gc.collect()

        df = pd.DataFrame(datos)
        
        # Guardamos el Excel en memoria en lugar de disco
        output = io.BytesIO()
        df.to_excel(output, index=False)
        output.seek(0)

        return send_file(
            output, 
            as_attachment=True, 
            download_name="resultado.xlsx",
            mimetype="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
        )

    return render_template("index.html")

if __name__ == "__main__":
    app.run(debug=True)