from __future__ import annotations

import tempfile
import unittest
from io import BytesIO
from pathlib import Path

from PIL import Image

from order_worker.sites.namdo_registration import PRODUCT_IMAGE_SIZE, _normalize_product_image


class NamdoRegistrationImageTests(unittest.TestCase):
    def test_normalizes_landscape_size_chart_to_square_without_cropping(self):
        source = Image.new("RGB", (800, 472), "red")
        source_buffer = BytesIO()
        source.save(source_buffer, format="JPEG")

        with tempfile.TemporaryDirectory() as temp_dir:
            target = Path(temp_dir) / "size.jpg"
            _normalize_product_image(source_buffer.getvalue(), target)

            with Image.open(target) as result:
                self.assertEqual(result.size, (PRODUCT_IMAGE_SIZE, PRODUCT_IMAGE_SIZE))
                self.assertGreater(result.getpixel((500, 500))[0], 200)
                self.assertGreater(min(result.getpixel((500, 50))), 240)

    def test_normalizes_transparent_png_on_white_background(self):
        source = Image.new("RGBA", (600, 600), (0, 0, 255, 128))
        source_buffer = BytesIO()
        source.save(source_buffer, format="PNG")

        with tempfile.TemporaryDirectory() as temp_dir:
            target = Path(temp_dir) / "product.jpg"
            _normalize_product_image(source_buffer.getvalue(), target)

            with Image.open(target) as result:
                self.assertEqual(result.mode, "RGB")
                self.assertEqual(result.size, (PRODUCT_IMAGE_SIZE, PRODUCT_IMAGE_SIZE))


if __name__ == "__main__":
    unittest.main()
