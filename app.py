from flask import Flask, request, send_file, render_template_string
import pdfplumber
import pandas as pd
import re
import os

app = Flask(__name__)

HTML = """
<!DOCTYPE html>
<html>
<head>
    <title>Extractor PDF a Excel</title>
</head>
<body style="font-family: Arial; text-align:center; margin-top:50px;">
    <h2>Subir PDF</h2>
    <form method="POST" enctype="multipart/form-data">
        <input type="file" name="pdf" accept=".pdf" required><br><br>
        <button type="submit">Generar Excel</button>
    </form>
</body>
</html>
"""

@app.route("/", methods=["GET", "POST"])
def index():
    if request.method == "POST":
        archivo = request.files["pdf"]

        if not archivo:
            return "No se subió archivo"

        ruta_pdf = "temp.pdf"
        archivo.save(ruta_pdf)

        texto_paginas = []

        with pdfplumber.open(ruta_pdf) as pdf:
            for pagina in pdf.pages:
                texto = pagina.extract_text()
                if texto:
                    texto = texto.replace("\n", " ")
                    texto_paginas.append(texto)

        personas = []
        for i in range(0, len(texto_paginas), 3):
            personas.append(" ".join(texto_paginas[i:i+3]))

        datos = []

        for texto in personas:
            texto = re.sub(r"\s+", " ", texto)

            match_res = re.search(r"(PPC|NC)\s*N[°o]?\s*(\d+)", texto)
            resolucion = f"{match_res.group(1)}-{match_res.group(2)}" if match_res else None

            match_nombre = re.search(
                r"ciudadano.*?\)\s*([A-ZÁÉÍÓÚÑ\s]+?)\s+identificado",
                texto,
                re.IGNORECASE
            )
            nombre = match_nombre.group(1).strip() if match_nombre else None

            match_doc = re.search(
                r"(C[ÉE]DULA\s+DE\s+(CIUDADANIA|EXTRANJER[IÍ]A)|PASAPORTE).*?N[°o]?\s*(\d+)",
                texto,
                re.IGNORECASE
            )

            tipo_doc = match_doc.group(1) if match_doc else None
            identificacion = match_doc.group(3) if match_doc else None

            match_art = re.search(r"Art\.\s*(\d+)", texto)
            articulo = match_art.group(1) if match_art else None

            datos.append({
                "Resolución": resolucion,
                "Nombre": nombre,
                "Tipo Documento": tipo_doc,
                "Identificación": identificacion,
                "Artículo": articulo
            })

        df = pd.DataFrame(datos)
        salida = "resultado.xlsx"
        df.to_excel(salida, index=False)

        return send_file(salida, as_attachment=True)

    return render_template_string(HTML)

if __name__ == "__main__":
    app.run(debug=True)