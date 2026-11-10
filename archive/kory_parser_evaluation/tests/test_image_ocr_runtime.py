"""Image OCR engine reuse, page orientation and source-coordinate contracts."""

import sys
import threading
from concurrent.futures import ThreadPoolExecutor
from types import SimpleNamespace

import pytest
from PIL import Image

from kory_parser import ocr


@pytest.fixture
def engines(monkeypatch):
    created = []

    class Engine:
        def __init__(self, params):
            self.params = params
            self.owner = threading.get_ident()
            created.append(self)

        def __call__(self, image, use_det=True, use_cls=True, use_rec=True):
            assert self.owner == threading.get_ident()
            if not use_rec:
                w, h = image.size
                return SimpleNamespace(boxes=[[(0, 0), (w, 0), (w, h), (0, h)]])
            if not use_det:
                return SimpleNamespace(scores=[0.99 if image.getpixel((0, 0)) == (255, 0, 0) else 0.1])
            return SimpleNamespace(txts=["본문"], boxes=[[(2, 3), (12, 3), (12, 9), (2, 9)]], scores=[0.99])

    monkeypatch.setitem(
        sys.modules,
        "rapidocr",
        SimpleNamespace(
            RapidOCR=Engine,
            LangRec=SimpleNamespace(KOREAN="korean"),
            ModelType=SimpleNamespace(MOBILE="mobile"),
            OCRVersion=SimpleNamespace(PPOCRV4="v4", PPOCRV5="v5"),
        ),
    )
    monkeypatch.setitem(sys.modules, "numpy", SimpleNamespace(asarray=lambda x: x))
    monkeypatch.setattr(ocr, "_IMAGE_STATE", threading.local(), raising=False)
    return created


def picture():
    image = Image.new("RGB", (40, 20), "blue")
    for x in range(40):
        for y in range(10):
            image.putpixel((x, y), (255, 0, 0))
    return image


def test_image_engine_is_reused_within_one_thread(engines):
    ocr.recognize(picture(), "image")
    ocr.recognize(picture(), "image")
    assert len(engines) == 1


def test_image_models_and_threads_are_explicitly_bounded(engines):
    ocr.recognize(picture(), "image")
    params = engines[0].params
    assert params["Det.ocr_version"] == "v4" and params["Det.model_type"] == "mobile"
    assert params["Rec.ocr_version"] == "v5" and params["Rec.lang_type"] == "korean"
    assert params["EngineConfig.onnxruntime.intra_op_num_threads"] == 8


def test_rotated_page_maps_recognized_regions_back_to_original_pixels(engines):
    upright = ocr.recognize(picture(), "image")[0]
    rotated = ocr.recognize(picture().transpose(Image.Transpose.ROTATE_180), "image")[0]
    assert upright.text == rotated.text == "본문"
    assert upright.source.bbox == (2.0, 3.0, 12.0, 9.0)
    assert rotated.source.bbox == (28.0, 11.0, 38.0, 17.0)
    assert rotated.source.unit == "px"


def test_pdf_engine_configuration_and_point_coordinates_are_preserved(engines):
    block = ocr.recognize(picture(), "pdf", page=2, scale=2)[0]
    assert engines[0].params["EngineConfig.onnxruntime.intra_op_num_threads"] == 2
    assert "Det.ocr_version" not in engines[0].params
    assert block.source.page == 2 and block.source.unit == "pt"
    assert block.source.bbox == (1.0, 1.5, 6.0, 4.5)


def test_each_worker_thread_owns_its_engine(engines):
    barrier = threading.Barrier(2)

    def work():
        barrier.wait(timeout=5)
        return [ocr.recognize(picture(), "image")[0].text for _ in range(2)]

    with ThreadPoolExecutor(max_workers=2) as pool:
        futures = [pool.submit(work) for _ in range(2)]
        assert [f.result(timeout=10) for f in futures] == [["본문", "본문"], ["본문", "본문"]]
    assert len(engines) == 2 and len({e.owner for e in engines}) == 2
