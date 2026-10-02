"""Extract text from DOCX and text-based PDF uploads."""

from io import BytesIO
from zipfile import BadZipFile

from docx import Document
from docx.opc.exceptions import PackageNotFoundError
from docx.oxml.exceptions import InvalidXmlError
from docx.table import Table
from lxml.etree import XMLSyntaxError
from pypdf import PdfReader
from pypdf.errors import PyPdfError

from backend.domain.document_collections import DocumentTextError


def extract_document_text(filename: str, content: bytes) -> str:
    if filename.lower().endswith(".docx"):
        try:
            document = Document(BytesIO(content))
            blocks: list[str] = []
            for item in document.iter_inner_content():
                if isinstance(item, Table):
                    blocks.extend(
                        "\t".join(cell.text.strip() for cell in row.cells) for row in item.rows
                    )
                else:
                    blocks.append(item.text)
            text = "\n".join(blocks).strip()
        except (
            BadZipFile,
            PackageNotFoundError,
            InvalidXmlError,
            XMLSyntaxError,
            ValueError,
            KeyError,
        ) as exc:
            raise DocumentTextError("invalid_docx", "DOCX 文件损坏或格式无效") from exc
    elif filename.lower().endswith(".pdf"):
        try:
            reader = PdfReader(BytesIO(content), strict=True)
            if reader.is_encrypted:
                raise DocumentTextError("protected_pdf", "受保护的 PDF 不支持导入")
            text = "\n\n".join((page.extract_text() or "").strip() for page in reader.pages).strip()
        except PyPdfError as exc:
            raise DocumentTextError("invalid_pdf", "PDF 文件损坏或格式无效") from exc
    else:
        raise DocumentTextError("unsupported_format", "不支持的文件类型")

    if not text:
        raise DocumentTextError("no_extractable_text", "文件没有可提取文本")
    return text
