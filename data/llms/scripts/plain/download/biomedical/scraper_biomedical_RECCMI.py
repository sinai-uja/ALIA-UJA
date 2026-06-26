"""
Convert a directory of PDF files into a Parquet dataset.

Features:
- Extracts text from all manually downloaded PDF files in a directory.
- Creates a tabular dataset with document IDs and content.
- Adds a configurable clinical section label.
- Exports the result to a Parquet file.

Usage:
    python pdf_to_parquet.py
"""

from pathlib import Path

import pandas as pd
import pdfplumber


PDF_DIRECTORY = Path("data/pdfs")
OUTPUT_FILE = Path("data/output.parquet")
CLINICAL_SECTION = "Internal Medicine"


def extract_text_from_pdf(pdf_path: Path) -> str:
    """Extract all text from a PDF file."""
    text_parts = []

    with pdfplumber.open(pdf_path) as pdf:
        for page in pdf.pages:
            text_parts.append(page.extract_text() or "")

    return "".join(text_parts)


def build_dataset(pdf_directory: Path) -> pd.DataFrame:
    """Build a DataFrame from all PDFs in a directory."""
    records = []

    for pdf_file in sorted(pdf_directory.glob("*.pdf")):
        records.append(
            {
                "id": pdf_file.stem,
                "text": extract_text_from_pdf(pdf_file),
                "clinical_section": CLINICAL_SECTION,
            }
        )

    return pd.DataFrame(records)


def main() -> None:
    """Run the PDF-to-Parquet conversion process."""
    dataframe = build_dataset(PDF_DIRECTORY)
    OUTPUT_FILE.parent.mkdir(parents=True, exist_ok=True)

    dataframe.to_parquet(
        OUTPUT_FILE,
        engine="pyarrow",
        index=False,
    )

    print(f"Parquet file created successfully: {OUTPUT_FILE}")


if __name__ == "__main__":
    main()
