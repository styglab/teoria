"""Optional RapidOCR integration. Models and scores differ from kordoc's engine."""

from __future__ import annotations

import base64
import io

from PIL import Image

from .models import Block, Diagnostic, ParseError, ParseOptions, ParseResult, SourceRef


def recognize(image, part: str, page: int | None = None, scale: float = 1.0) -> list[Block]:
    try:
        from rapidocr import LangRec, ModelType, OCRVersion, RapidOCR
    except ImportError as error:
        raise ParseError("MISSING_DEPENDENCY", "Install teoria-docparse[ocr] for OCR") from error
    import numpy as np

    engine = RapidOCR(
        params={
            "Rec.lang_type": LangRec.KOREAN,
            "Rec.model_type": ModelType.MOBILE,
            "Rec.ocr_version": OCRVersion.PPOCRV5,
            "EngineConfig.onnxruntime.intra_op_num_threads": 2,
            "EngineConfig.onnxruntime.inter_op_num_threads": 2,
        }
    )
    result = engine(np.asarray(image.convert("RGB")))
    blocks = []
    if result.txts is not None:
        for box, text, score in zip(result.boxes, result.txts, result.scores):
            left, top = float(min(p[0] for p in box) / scale), float(min(p[1] for p in box) / scale)
            right, bottom = float(max(p[0] for p in box) / scale), float(max(p[1] for p in box) / scale)
            ref = SourceRef(
                part,
                f"ocr:confidence={float(score):.6f}",
                page,
                (left, top, right, bottom),
                "top_left",
                "pt" if page else "px",
            )
            blocks.append(Block("paragraph", str(text), source=ref))
    return blocks


def parse_image(data: bytes, options: ParseOptions) -> ParseResult:
    with Image.open(io.BytesIO(data)) as image:
        if image.width * image.height > 100_000_000:
            raise ParseError("RESOURCE_LIMIT", "Image pixel budget exceeded")
        ref = SourceRef(
            "image", bbox=(0, 0, image.width, image.height), coordinate_system="top_left", unit="px"
        )
        result = ParseResult(False, image.format.lower() if image.format else "image", error_code="NEEDS_OCR")
        block = Block("image", source=ref)
        if options.images:
            block.image_data = base64.b64encode(data).decode()
            block.mime_type = Image.MIME.get(image.format)
        result.blocks = [block]
        if options.ocr:
            result.blocks.extend(recognize(image, "image"))
            result.success = any(b.text for b in result.blocks)
            result.error_code = None if result.success else "EMPTY_OCR"
        else:
            result.warnings.append(Diagnostic("NEEDS_OCR", "Image input requires OCR", ref))
        return result


def ocr_pdf_page(data: bytes, page_number: int, options: ParseOptions) -> list[Block]:
    import pymupdf

    with pymupdf.open(stream=data, filetype="pdf") as document:
        page = document[page_number - 1]
        pixmap = page.get_pixmap(matrix=pymupdf.Matrix(2, 2), alpha=False, colorspace=pymupdf.csRGB)
        image = Image.frombytes("RGB", (pixmap.width, pixmap.height), pixmap.samples)
        return recognize(image, "pdf", page_number, scale=2)
