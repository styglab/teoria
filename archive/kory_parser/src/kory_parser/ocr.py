"""Optional RapidOCR integration. Models and scores differ from kordoc's engine."""

from __future__ import annotations

import base64
import io
from threading import local

from PIL import Image

from .models import Block, Diagnostic, ParseError, ParseOptions, ParseResult, SourceRef
from .ocr_punctuation import quote_word_boxes, restore_image_corner_quotes
from .ocr_punctuation import restore_image_quotes as _restore_image_quotes

_IMAGE_STATE = local()


def _image_engine():
    engine = getattr(_IMAGE_STATE, "engine", None)
    if engine is None:
        from rapidocr import LangRec, ModelType, OCRVersion, RapidOCR

        class ImageOCREngine(RapidOCR):
            def calc_word_boxes(self, images, boxes, recognition):
                return quote_word_boxes(super().calc_word_boxes, images, boxes, recognition)

        engine = ImageOCREngine(
            params={
                "Global.return_word_box": True,
                "Global.return_single_char_box": True,
                "Det.ocr_version": OCRVersion.PPOCRV4,
                "Det.model_type": ModelType.MOBILE,
                "Rec.lang_type": LangRec.KOREAN,
                "Rec.model_type": ModelType.MOBILE,
                "Rec.ocr_version": OCRVersion.PPOCRV5,
                "EngineConfig.onnxruntime.intra_op_num_threads": 8,
                "EngineConfig.onnxruntime.inter_op_num_threads": 2,
            }
        )
        _IMAGE_STATE.engine = engine
    return engine


def _image_ocr(image):
    """Choose one page orientation from Korean recognition, not per-line flips."""
    import numpy as np

    engine = _image_engine()
    image = image.convert("RGB")
    detected = engine(np.asarray(image), use_det=True, use_cls=False, use_rec=False)
    boxes = [] if detected.boxes is None else list(detected.boxes)
    boxes.sort(key=lambda b: (min(float(p[1]) for p in b), min(float(p[0]) for p in b)))
    eligible = [
        b
        for b in boxes
        if max(p[0] for p in b) - min(p[0] for p in b) >= 2 * (max(p[1] for p in b) - min(p[1] for p in b))
    ]
    samples = eligible or boxes
    confidence = [0.0, 0.0]
    for index in sorted({0, len(samples) // 2, len(samples) - 1}) if samples else []:
        box = samples[index]
        crop = image.crop(
            (min(p[0] for p in box), min(p[1] for p in box), max(p[0] for p in box), max(p[1] for p in box))
        )
        for direction in (0, 1):
            probe = crop if not direction else crop.transpose(Image.Transpose.ROTATE_180)
            result = engine(np.asarray(probe), use_det=False, use_cls=False, use_rec=True)
            scores = result.scores
            if scores is not None and len(scores):
                confidence[direction] += sum(float(score) for score in scores) / len(scores)
    flipped = confidence[1] > confidence[0]
    oriented = image.transpose(Image.Transpose.ROTATE_180) if flipped else image
    result = engine(np.asarray(oriented), use_det=True, use_cls=False, use_rec=True)
    _restore_image_quotes(oriented, result)
    restore_image_corner_quotes(oriented, result)
    if flipped and result.boxes is not None:
        result.boxes = np.asarray(
            [[[image.width - x, image.height - y] for x, y in box] for box in result.boxes]
        )
    return result


def recognize(image, part: str, page: int | None = None, scale: float = 1.0) -> list[Block]:
    try:
        from rapidocr import LangRec, ModelType, OCRVersion, RapidOCR
    except ImportError as error:
        raise ParseError("MISSING_DEPENDENCY", "Install kory-parser[ocr] for OCR") from error
    import numpy as np

    if part == "image":
        result = _image_ocr(image)
    else:
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
