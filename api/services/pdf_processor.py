from typing import Dict, Any
from pathlib import Path

from magic_pdf.data.data_reader_writer import FileBasedDataWriter, FileBasedDataReader
from magic_pdf.data.dataset import PymuDocDataset
from magic_pdf.model.doc_analyze_by_custom_model import doc_analyze
from magic_pdf.config.enums import SupportedPdfParseMethod


class PDFProcessorConfig:
    """Configuration for PDF processing"""

    def __init__(self, output_dir: str = "output"):
        self.output_dir = Path(output_dir)
        self.image_dir = self.output_dir / "images"
        self.md_dir = self.output_dir

    def ensure_directories(self):
        """Create necessary directories"""
        self.image_dir.mkdir(parents=True, exist_ok=True)
        self.md_dir.mkdir(parents=True, exist_ok=True)


class PDFProcessorResult:
    """Container for PDF processing results"""

    def __init__(self):
        self.filename: str = ""
        self.pages: int = 0
        self.markdown_content: str = ""
        self.content_list: Any = None
        self.middle_json: Any = None
        self.model_inference_result: Any = None
        self.processing_time: float = 0.0
        self.file_size: int = 0
        self.output_files: Dict[str, str] = {}
        self.image_files: Dict[str, str] = {}
        self.parse_method: str = ""


class PDFProcessor:
    """Main PDF processing service using MinERU"""

    def __init__(self, config: PDFProcessorConfig):
        self.config = config
        self.config.ensure_directories()

    def process_pdf_bytes(
        self, pdf_bytes: bytes, filename: str, progress_callback=None
    ) -> PDFProcessorResult:
        """
        Process PDF from bytes data

        Args:
            pdf_bytes: PDF file content as bytes
            filename: Original filename
            progress_callback: Optional callback function for progress updates

        Returns:
            PDFProcessorResult containing all processing results
        """
        import time

        start_time = time.time()

        def update_progress(progress: float, stage: str):
            if progress_callback:
                progress_callback(progress, stage)

        result = PDFProcessorResult()
        result.filename = filename
        result.file_size = len(pdf_bytes)

        name_without_suff = Path(filename).stem

        update_progress(0.35, "Setting up data writers")
        # Setup writers
        image_writer = FileBasedDataWriter(str(self.config.image_dir))
        md_writer = FileBasedDataWriter(str(self.config.md_dir))

        update_progress(0.4, "Creating PDF dataset")
        # Create dataset instance
        ds = PymuDocDataset(pdf_bytes)
        result.pages = len(ds)

        update_progress(0.45, "Classifying PDF type")
        # Determine parse method and process
        if ds.classify() == SupportedPdfParseMethod.OCR:
            result.parse_method = "OCR"
            update_progress(0.5, "Applying OCR analysis")
            infer_result = ds.apply(doc_analyze, ocr=True)
            update_progress(0.65, "Processing OCR pipeline")
            pipe_result = infer_result.pipe_ocr_mode(image_writer)
        else:
            result.parse_method = "TXT"
            update_progress(0.5, "Applying text analysis")
            infer_result = ds.apply(doc_analyze, ocr=False)
            update_progress(0.65, "Processing text pipeline")
            pipe_result = infer_result.pipe_txt_mode(image_writer)

        # Generate output files
        image_dir_name = self.config.image_dir.name

        update_progress(0.7, "Extracting model inference results")
        # Model inference result
        result.model_inference_result = infer_result.get_infer_res()

        update_progress(0.75, "Generating visualization files")
        # Generate visualization files
        model_pdf_path = self.config.md_dir / f"{name_without_suff}_model.pdf"
        layout_pdf_path = self.config.md_dir / f"{name_without_suff}_layout.pdf"
        spans_pdf_path = self.config.md_dir / f"{name_without_suff}_spans.pdf"

        infer_result.draw_model(str(model_pdf_path))
        pipe_result.draw_layout(str(layout_pdf_path))
        pipe_result.draw_span(str(spans_pdf_path))

        update_progress(0.8, "Extracting content and markdown")
        # Get content results
        result.markdown_content = pipe_result.get_markdown(image_dir_name)
        result.content_list = pipe_result.get_content_list(image_dir_name)
        result.middle_json = pipe_result.get_middle_json()

        update_progress(0.85, "Saving results to files")
        # Dump results to files
        md_file_path = f"{name_without_suff}.md"
        content_list_file_path = f"{name_without_suff}_content_list.json"
        middle_json_file_path = f"{name_without_suff}_middle.json"

        pipe_result.dump_md(md_writer, md_file_path, image_dir_name)
        pipe_result.dump_content_list(md_writer, content_list_file_path, image_dir_name)
        pipe_result.dump_middle_json(md_writer, middle_json_file_path)

        # Record output files
        result.output_files = {
            "markdown": str(self.config.md_dir / md_file_path),
            "content_list": str(self.config.md_dir / content_list_file_path),
            "middle_json": str(self.config.md_dir / middle_json_file_path),
            "model_pdf": str(model_pdf_path),
            "layout_pdf": str(layout_pdf_path),
            "spans_pdf": str(spans_pdf_path),
        }

        update_progress(0.9, "Collecting image files")
        # Collect image files
        result.image_files = {}
        if self.config.image_dir.exists():
            for image_file in self.config.image_dir.iterdir():
                if image_file.is_file() and image_file.suffix.lower() in [
                    ".jpg",
                    ".jpeg",
                    ".png",
                    ".gif",
                    ".webp",
                    ".svg",
                    ".bmp",
                    ".tiff",
                ]:
                    result.image_files[image_file.stem] = str(image_file)

        result.processing_time = time.time() - start_time

        return result

    def process_pdf_file(self, file_path: str) -> PDFProcessorResult:
        """
        Process PDF from file path

        Args:
            file_path: Path to PDF file

        Returns:
            PDFProcessorResult containing all processing results
        """
        reader = FileBasedDataReader("")
        pdf_bytes = reader.read(file_path)
        filename = Path(file_path).name

        return self.process_pdf_bytes(pdf_bytes, filename)


def create_pdf_processor(output_dir: str = None) -> PDFProcessor:
    """Factory function to create PDF processor with default config"""
    if output_dir is None:
        output_dir = "output"

    config = PDFProcessorConfig(output_dir)
    return PDFProcessor(config)
