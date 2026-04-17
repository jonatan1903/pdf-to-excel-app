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

            # Procesamiento progresivo: leemos y analizamos de a pequeños bloques
            for i in range(total_paginas):
                texto = pdf[i].get_text()
                if texto:
                    texto_bloque.append(texto.replace("\n", " "))

                # Según tu lógica, cada persona toma 3 páginas. 
                # Procesamos el bloque actual y liberamos la memoria inmediatamente.
                if (i + 1) % 3 == 0 or i == total_paginas - 1:
                    texto_unido = " ".join(texto_bloque)
                    texto_unido = re.sub(r"\s+", " ", texto_unido) # Limpiar hiper-espaciado

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

                    # 4. Artículo (solo después de la palabra "CONSIDERANDO")
                    match_cons = re.search(r"CONSIDERANDO", texto_unido, re.IGNORECASE)
                    # Si encuentra "CONSIDERANDO", busca el artículo solo en el texto que le sigue
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

                    # Liberar memoria de variables del bloque pasado
                    texto_bloque = []
                    del texto_unido
                
                # Cada 150 páginas forzamos al servidor a limpiar profundamente la memoria (Garbage Collector)
                if (i + 1) % 150 == 0:
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