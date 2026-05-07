import sys
import unittest
from pathlib import Path
from tempfile import TemporaryDirectory

import yaml
from click.testing import CliRunner
from PIL import Image


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "cli" / "gang"))

from cli import cli  # noqa: E402
from core.image_pipeline import ImagePipeline  # noqa: E402


class ImageCommandTests(unittest.TestCase):
    def test_image_command_prints_processed_variants(self):
        runner = CliRunner()

        with runner.isolated_filesystem():
            config = {
                "build": {
                    "output": "./dist",
                    "content": "./content",
                    "templates": "./templates",
                    "public": "./public",
                },
                "images": {
                    "formats": ["webp"],
                    "widths": [50],
                    "quality": {"webp": 80},
                },
            }
            Path("gang.config.yml").write_text(yaml.safe_dump(config), encoding="utf-8")

            source_dir = Path("source")
            source_dir.mkdir()
            Image.new("RGB", (100, 50), color=(255, 0, 0)).save(source_dir / "sample.jpg")

            result = runner.invoke(cli, ["image", str(source_dir)], catch_exceptions=False)

            self.assertEqual(result.exit_code, 0, result.output)
            self.assertIn("Processed 1 images into 1 variants", result.output)
            self.assertIn("sample.jpg:", result.output)
            self.assertIn("50w webp", result.output)


class ImagePipelineTests(unittest.TestCase):
    def test_picture_html_uses_supplied_escaped_alt_text(self):
        with TemporaryDirectory() as tmp:
            pipeline = ImagePipeline(Path(tmp) / "public", Path(tmp) / "dist")
            pipeline._generate_crop = lambda image_path, width, focal_point: None
            pipeline._generate_formats = lambda image_path: {"jpg": "/assets/hero.jpg"}
            pipeline._generate_thumbhash = lambda image_path: None

            result = pipeline.process_image(
                Path("hero-image.jpg"),
                focal_point=(0.5, 0.5),
                alt_text='A "hero" & image',
            )

            self.assertIn('alt="A &quot;hero&quot; &amp; image"', result["html"])
            self.assertNotIn("TODO: Add alt text", result["html"])

    def test_picture_html_falls_back_to_readable_filename_alt_text(self):
        with TemporaryDirectory() as tmp:
            pipeline = ImagePipeline(Path(tmp) / "public", Path(tmp) / "dist")
            pipeline._generate_crop = lambda image_path, width, focal_point: None
            pipeline._generate_formats = lambda image_path: {"jpg": "/assets/featured-product.jpg"}
            pipeline._generate_thumbhash = lambda image_path: None

            result = pipeline.process_image(Path("featured_product.jpg"))

            self.assertIn('alt="featured product"', result["html"])
            self.assertNotIn("TODO: Add alt text", result["html"])


if __name__ == "__main__":
    unittest.main()
