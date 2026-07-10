from docling.document_converter import DocumentConverter


def read_pdf(pdf_path: str) -> str:
    converter = DocumentConverter()
    result = converter.convert(pdf_path)
    return result.document.export_to_markdown()


def main():
    print("Hello from taxreader!")


if __name__ == "__main__":
    main()
