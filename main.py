import os
import argparse
from src.pdf_processor import DocProcessingPipeline

def main():
    parser = argparse.ArgumentParser(description="Procesador de PDFs gigantes")
    parser.add_argument("--input", "-i", type=str, required=True, help="Ruta al archivo PDF de entrada")
    parser.add_argument("--output", "-o", type=str, required=False, default="output_report.xlsx", help="Ruta de exportación del Excel")

    args = parser.parse_args()

    if not os.path.exists(args.input):
        print(f"Error: El archivo {args.input} no existe.")
        return

    pipeline = DocProcessingPipeline(args.input, args.output)
    pipeline.run()

if __name__ == "__main__":
    main()
