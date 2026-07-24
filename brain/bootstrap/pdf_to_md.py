#!/usr/bin/env python3
"""
pdf_to_md.py — Convierte PDFs de una carpeta a archivos Markdown.

Uso:
    python3 pdf_to_md.py                          # pdfs/ → md/  (en el mismo directorio)
    python3 pdf_to_md.py /ruta/pdfs               # carpeta origen personalizada
    python3 pdf_to_md.py /ruta/pdfs /ruta/salida  # origen y destino personalizados

Instalación de dependencias (una sola vez):
    pip3 install pdfplumber pytesseract pillow
    brew install poppler tesseract tesseract-lang
"""

import sys
import os
import re
import subprocess
from pathlib import Path

# ── dependencias opcionales ──────────────────────────────────────────────────
try:
    import pdfplumber
    HAS_PDFPLUMBER = True
except ImportError:
    HAS_PDFPLUMBER = False

try:
    import pytesseract
    from PIL import Image
    HAS_OCR = True
except ImportError:
    HAS_OCR = False


# ── helpers ──────────────────────────────────────────────────────────────────

def check_deps():
    """Verifica dependencias y avisa al usuario."""
    missing = []
    if not HAS_PDFPLUMBER:
        missing.append("pdfplumber  →  pip3 install pdfplumber")
    if not HAS_OCR:
        missing.append("pytesseract + pillow  →  pip3 install pytesseract pillow")

    # poppler (pdftotext, pdftoppm)
    if subprocess.run(["which", "pdftotext"], capture_output=True).returncode != 0:
        missing.append("poppler  →  brew install poppler")

    if missing:
        print("⚠️  Faltan dependencias:")
        for m in missing:
            print(f"   {m}")
        print()

    return len(missing) == 0


def is_scanned(pdf_path: Path) -> bool:
    """Devuelve True si el PDF no tiene texto extraíble (es un escán)."""
    result = subprocess.run(
        ["pdftotext", str(pdf_path), "-"],
        capture_output=True, text=True
    )
    text = result.stdout.strip()
    # Si hay menos de 50 caracteres en todo el doc, probablemente es escán
    return len(text) < 50


def extract_text_pdfplumber(pdf_path: Path) -> str:
    """Extrae texto usando pdfplumber (mejor para columnas y tablas)."""
    pages = []
    with pdfplumber.open(str(pdf_path)) as pdf:
        for i, page in enumerate(pdf.pages, 1):
            text = page.extract_text() or ""
            # Intentar extraer tablas si las hay
            tables = page.extract_tables()
            if tables:
                table_md = []
                for table in tables:
                    table_md.append(table_to_markdown(table))
                # Reemplazar sección de tabla en el texto si el texto ya la tiene
                # (simplificado: añadir tablas al final de la página)
                text = text + "\n\n" + "\n\n".join(table_md)
            pages.append(f"<!-- Página {i} -->\n\n{text.strip()}")
    return "\n\n---\n\n".join(pages)


def extract_text_pdftotext(pdf_path: Path) -> str:
    """Extrae texto con pdftotext (CLI, layout-preserving)."""
    result = subprocess.run(
        ["pdftotext", "-layout", str(pdf_path), "-"],
        capture_output=True, text=True
    )
    return result.stdout.strip()


def extract_text_ocr(pdf_path: Path) -> str:
    """Extrae texto de PDFs escaneados via OCR (pytesseract)."""
    if not HAS_OCR:
        return "[OCR no disponible — instala: pip3 install pytesseract pillow]"

    # Convertir páginas a imágenes con pdftoppm
    tmp_dir = Path("/tmp/pdf_to_md_ocr")
    tmp_dir.mkdir(exist_ok=True)
    prefix = str(tmp_dir / "page")

    subprocess.run(
        ["pdftoppm", "-jpeg", "-r", "200", str(pdf_path), prefix],
        capture_output=True
    )

    images = sorted(tmp_dir.glob("page-*.jpg")) + sorted(tmp_dir.glob("page-*.jpeg"))
    if not images:
        images = sorted(tmp_dir.glob("page*.jpg")) + sorted(tmp_dir.glob("page*.jpeg"))

    pages = []
    for i, img_path in enumerate(images, 1):
        img = Image.open(img_path)
        text = pytesseract.image_to_string(img, lang="spa+eng")
        pages.append(f"<!-- Página {i} (OCR) -->\n\n{text.strip()}")
        img_path.unlink()

    return "\n\n---\n\n".join(pages)


def table_to_markdown(table: list) -> str:
    """Convierte una tabla de pdfplumber a formato Markdown."""
    if not table or not table[0]:
        return ""

    # Limpiar celdas
    def clean(cell):
        if cell is None:
            return ""
        return str(cell).replace("\n", " ").strip()

    rows = [[clean(cell) for cell in row] for row in table]
    col_widths = [max(len(row[i]) for row in rows) for i in range(len(rows[0]))]

    def fmt_row(row):
        return "| " + " | ".join(
            cell.ljust(col_widths[i]) for i, cell in enumerate(row)
        ) + " |"

    header = fmt_row(rows[0])
    sep = "| " + " | ".join("-" * w for w in col_widths) + " |"
    body = "\n".join(fmt_row(r) for r in rows[1:])

    return f"{header}\n{sep}\n{body}"


def text_to_markdown(raw_text: str, title: str) -> str:
    """
    Limpia y estructura el texto plano como Markdown básico.
    Detecta líneas que parecen headings por su brevedad y mayúsculas.
    """
    lines = raw_text.splitlines()
    md_lines = [f"# {title}\n"]

    for line in lines:
        stripped = line.strip()

        if not stripped:
            md_lines.append("")
            continue

        # Línea corta en MAYÚSCULAS o Title Case → probable heading
        if len(stripped) < 80 and (stripped.isupper() or re.match(r'^[A-ZÁÉÍÓÚÑ][^.!?]*$', stripped)):
            if len(stripped.split()) <= 8:
                md_lines.append(f"\n## {stripped}\n")
                continue

        # Listas numéricas: "1. Item" o "1) Item"
        if re.match(r'^\d+[\.\)]\s+', stripped):
            md_lines.append(stripped)
            continue

        # Listas con guión o bullet
        if re.match(r'^[-•*]\s+', stripped):
            item = re.sub(r'^[-•*]\s+', '- ', stripped)
            md_lines.append(item)
            continue

        md_lines.append(stripped)

    # Colapsar múltiples líneas en blanco
    result = re.sub(r'\n{3,}', '\n\n', "\n".join(md_lines))
    return result.strip() + "\n"


def convert_pdf(pdf_path: Path, output_dir: Path) -> bool:
    """
    Convierte un PDF a Markdown. Devuelve True si tuvo éxito.
    Estrategia: pdfplumber → pdftotext → OCR.
    """
    title = pdf_path.stem.replace("_", " ").replace("-", " ").title()
    out_path = output_dir / (pdf_path.stem + ".md")

    print(f"  {'📄'} {pdf_path.name}", end=" ... ", flush=True)

    scanned = is_scanned(pdf_path)

    if scanned:
        print("(escaneado, usando OCR)", end=" ", flush=True)
        raw = extract_text_ocr(pdf_path)
    elif HAS_PDFPLUMBER:
        raw = extract_text_pdfplumber(pdf_path)
    else:
        raw = extract_text_pdftotext(pdf_path)

    if not raw.strip():
        print("⚠️  sin texto extraído")
        return False

    md_content = text_to_markdown(raw, title)

    out_path.write_text(md_content, encoding="utf-8")
    print(f"✅  → {out_path.name}")
    return True


# ── main ─────────────────────────────────────────────────────────────────────

def main():
    # Argumentos
    args = sys.argv[1:]
    if len(args) == 0:
        input_dir  = Path.cwd() / "pdfs"
        output_dir = Path.cwd() / "md"
    elif len(args) == 1:
        input_dir  = Path(args[0]).expanduser().resolve()
        output_dir = input_dir.parent / "md"
    else:
        input_dir  = Path(args[0]).expanduser().resolve()
        output_dir = Path(args[1]).expanduser().resolve()

    print(f"\n📂 Origen : {input_dir}")
    print(f"📁 Destino: {output_dir}\n")

    if not input_dir.exists():
        print(f"❌ La carpeta de origen no existe: {input_dir}")
        sys.exit(1)

    pdfs = sorted(input_dir.glob("*.pdf")) + sorted(input_dir.glob("*.PDF"))
    if not pdfs:
        print("⚠️  No se encontraron archivos PDF en la carpeta.")
        sys.exit(0)

    print(f"🔍 {len(pdfs)} PDF(s) encontrado(s)\n")

    # Verificar deps (advertir pero no bloquear si hay alternativas)
    check_deps()

    output_dir.mkdir(parents=True, exist_ok=True)

    ok = 0
    for pdf in pdfs:
        try:
            if convert_pdf(pdf, output_dir):
                ok += 1
        except Exception as e:
            print(f"❌  Error: {e}")

    print(f"\n✨ Listo — {ok}/{len(pdfs)} archivos convertidos → {output_dir}")


if __name__ == "__main__":
    main()
