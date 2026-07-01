"""Barcode Generation Utilities

This module provides comprehensive barcode generation utilities for the PIM system,
supporting various barcode formats commonly used in retail and logistics:

- EAN-13: European Article Number (13-digit, global standard)
- EAN-8: European Article Number (8-digit, for small products)
- UPC-A: Universal Product Code (12-digit, North America)
- Code 128: High-density alphanumeric barcode (logistics, shipping)
- Code 39: Alphanumeric barcode (industrial applications)
- ISBN-13: International Standard Book Number
- ISBN-10: Legacy book number format
- ISSN: International Standard Serial Number
- ITF (Interleaved 2 of 5): Used for ITF-14 packaging barcodes
- QR Code: 2D barcode for URLs, data storage, mobile scanning

Uses the python-barcode library for linear barcodes and qrcode library
for QR codes (both bundled with Frappe).

Integration with GS1 validation ensures GTIN check digits are correct
before barcode generation.

Note: frappe imports are deferred to function level to allow module
import without Frappe being available (e.g., for testing/verification).
"""

import io
import base64
from dataclasses import dataclass, field
from enum import Enum
from typing import Optional, Dict, Any, List, Union, Tuple
from pathlib import Path


class BarcodeFormat(Enum):
    """Supported barcode formats."""
    EAN13 = "ean13"
    EAN8 = "ean8"
    UPCA = "upca"
    CODE128 = "code128"
    CODE39 = "code39"
    ISBN13 = "isbn13"
    ISBN10 = "isbn10"
    ISSN = "issn"
    ITF = "itf"
    PZN = "pzn"  # Pharmazentralnummer (German pharmaceuticals)
    JAN = "jan"  # Japanese Article Number (same as EAN-13)
    QR = "qr"


class ImageFormat(Enum):
    """Supported output image formats."""
    SVG = "svg"
    PNG = "png"


class QRErrorCorrection(Enum):
    """QR code error correction levels."""
    LOW = "L"        # ~7% recovery
    MEDIUM = "M"     # ~15% recovery
    QUARTILE = "Q"   # ~25% recovery
    HIGH = "H"       # ~30% recovery


@dataclass
class BarcodeConfig:
    """Configuration for barcode generation."""
    format: BarcodeFormat = BarcodeFormat.EAN13
    image_format: ImageFormat = ImageFormat.SVG
    width: Optional[float] = None  # Module width in mm (None for default)
    height: Optional[float] = None  # Bar height in mm (None for default)
    include_text: bool = True  # Include human-readable text below barcode
    text_distance: float = 5.0  # Distance between bars and text in mm
    font_size: int = 10  # Font size for human-readable text
    quiet_zone: float = 6.5  # Quiet zone width in mm
    background: str = "white"  # Background color
    foreground: str = "black"  # Bar/module color
    dpi: int = 300  # DPI for PNG output

    def to_dict(self) -> Dict[str, Any]:
        """Convert to dictionary."""
        return {
            "format": self.format.value,
            "image_format": self.image_format.value,
            "width": self.width,
            "height": self.height,
            "include_text": self.include_text,
            "text_distance": self.text_distance,
            "font_size": self.font_size,
            "quiet_zone": self.quiet_zone,
            "background": self.background,
            "foreground": self.foreground,
            "dpi": self.dpi,
        }


@dataclass
class QRConfig:
    """Configuration for QR code generation."""
    version: Optional[int] = None  # QR version (1-40, None for auto)
    error_correction: QRErrorCorrection = QRErrorCorrection.MEDIUM
    box_size: int = 10  # Size of each box in pixels
    border: int = 4  # Border width in boxes
    fill_color: str = "black"  # Module color
    back_color: str = "white"  # Background color

    def to_dict(self) -> Dict[str, Any]:
        """Convert to dictionary."""
        return {
            "version": self.version,
            "error_correction": self.error_correction.value,
            "box_size": self.box_size,
            "border": self.border,
            "fill_color": self.fill_color,
            "back_color": self.back_color,
        }


@dataclass
class BarcodeResult:
    """Result of barcode generation."""
    success: bool
    data: str  # Input data used for generation
    format: str  # Barcode format used
    image_format: str  # Output image format
    image_data: Optional[bytes] = None  # Raw image bytes
    image_base64: Optional[str] = None  # Base64-encoded image
    svg_content: Optional[str] = None  # SVG content (for SVG format)
    file_path: Optional[str] = None  # Path if saved to file
    error: Optional[str] = None
    warnings: Optional[List[str]] = field(default_factory=list)

    def to_dict(self) -> Dict[str, Any]:
        """Convert to dictionary (excluding raw bytes)."""
        return {
            "success": self.success,
            "data": self.data,
            "format": self.format,
            "image_format": self.image_format,
            "image_base64": self.image_base64,
            "svg_content": self.svg_content,
            "file_path": self.file_path,
            "error": self.error,
            "warnings": self.warnings or [],
        }


# =============================================================================
# Format-specific validators
# =============================================================================

def _validate_for_format(data: str, barcode_format: BarcodeFormat) -> Tuple[bool, str, List[str]]:
    """Validate data for specific barcode format.

    Args:
        data: Data to encode
        barcode_format: Target barcode format

    Returns:
        Tuple of (is_valid, normalized_data, warnings)
    """
    warnings = []
    data = str(data).strip()

    if barcode_format == BarcodeFormat.EAN13:
        # EAN-13: 13 digits (or 12 digits + auto check digit)
        data = data.replace(" ", "").replace("-", "")
        if not data.isdigit():
            return False, data, ["EAN-13 must contain only digits"]
        if len(data) == 12:
            # Will add check digit
            from . import gs1_validation
            data = gs1_validation.create_gtin(data, 13)
            warnings.append("Check digit calculated and appended")
        elif len(data) != 13:
            return False, data, [f"EAN-13 must be 12 or 13 digits (got {len(data)})"]
        else:
            # Validate check digit
            from . import gs1_validation
            result = gs1_validation.validate_gtin13(data)
            if not result.is_valid:
                return False, data, result.errors

    elif barcode_format == BarcodeFormat.EAN8:
        # EAN-8: 8 digits (or 7 digits + auto check digit)
        data = data.replace(" ", "").replace("-", "")
        if not data.isdigit():
            return False, data, ["EAN-8 must contain only digits"]
        if len(data) == 7:
            from . import gs1_validation
            data = gs1_validation.create_gtin(data, 8)
            warnings.append("Check digit calculated and appended")
        elif len(data) != 8:
            return False, data, [f"EAN-8 must be 7 or 8 digits (got {len(data)})"]
        else:
            from . import gs1_validation
            result = gs1_validation.validate_gtin8(data)
            if not result.is_valid:
                return False, data, result.errors

    elif barcode_format == BarcodeFormat.UPCA:
        # UPC-A: 12 digits (or 11 digits + auto check digit)
        data = data.replace(" ", "").replace("-", "")
        if not data.isdigit():
            return False, data, ["UPC-A must contain only digits"]
        if len(data) == 11:
            from . import gs1_validation
            data = gs1_validation.create_gtin(data, 12)
            warnings.append("Check digit calculated and appended")
        elif len(data) != 12:
            return False, data, [f"UPC-A must be 11 or 12 digits (got {len(data)})"]
        else:
            from . import gs1_validation
            result = gs1_validation.validate_gtin12(data)
            if not result.is_valid:
                return False, data, result.errors

    elif barcode_format == BarcodeFormat.CODE128:
        # Code 128: Any ASCII characters
        if not all(32 <= ord(c) <= 126 for c in data):
            return False, data, ["Code 128 only supports ASCII characters (32-126)"]
        if len(data) == 0:
            return False, data, ["Code 128 data cannot be empty"]
        if len(data) > 80:
            warnings.append("Long data may result in a wide barcode")

    elif barcode_format == BarcodeFormat.CODE39:
        # Code 39: Uppercase letters, digits, and some special chars
        valid_chars = set("ABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789-. $/+%")
        data = data.upper()
        if not all(c in valid_chars for c in data):
            invalid = [c for c in data if c not in valid_chars]
            return False, data, [f"Code 39 contains invalid characters: {invalid}"]
        if len(data) == 0:
            return False, data, ["Code 39 data cannot be empty"]

    elif barcode_format == BarcodeFormat.ITF:
        # ITF: Even number of digits
        data = data.replace(" ", "").replace("-", "")
        if not data.isdigit():
            return False, data, ["ITF must contain only digits"]
        if len(data) % 2 != 0:
            data = "0" + data
            warnings.append("Padded with leading zero for even length")
        if len(data) < 2:
            return False, data, ["ITF must have at least 2 digits"]

    elif barcode_format == BarcodeFormat.ISBN13:
        # ISBN-13: 13 digits starting with 978 or 979
        data = data.replace(" ", "").replace("-", "")
        if not data.isdigit():
            return False, data, ["ISBN-13 must contain only digits"]
        if len(data) != 13:
            return False, data, [f"ISBN-13 must be 13 digits (got {len(data)})"]
        if not data.startswith(("978", "979")):
            return False, data, ["ISBN-13 must start with 978 or 979"]

    elif barcode_format == BarcodeFormat.ISBN10:
        # ISBN-10: 9 digits + check char (0-9 or X)
        data = data.replace(" ", "").replace("-", "").upper()
        if len(data) != 10:
            return False, data, [f"ISBN-10 must be 10 characters (got {len(data)})"]
        if not data[:9].isdigit():
            return False, data, ["ISBN-10 first 9 characters must be digits"]
        if data[9] not in "0123456789X":
            return False, data, ["ISBN-10 check character must be 0-9 or X"]

    elif barcode_format == BarcodeFormat.ISSN:
        # ISSN: 8 digits (7 digits + check)
        data = data.replace(" ", "").replace("-", "").upper()
        if len(data) != 8:
            return False, data, [f"ISSN must be 8 characters (got {len(data)})"]
        if not data[:7].isdigit():
            return False, data, ["ISSN first 7 characters must be digits"]
        if data[7] not in "0123456789X":
            return False, data, ["ISSN check character must be 0-9 or X"]

    elif barcode_format == BarcodeFormat.PZN:
        # PZN: 7 or 8 digits
        data = data.replace(" ", "").replace("-", "")
        if not data.isdigit():
            return False, data, ["PZN must contain only digits"]
        if len(data) not in (7, 8):
            return False, data, [f"PZN must be 7 or 8 digits (got {len(data)})"]

    elif barcode_format == BarcodeFormat.JAN:
        # JAN: Same as EAN-13
        return _validate_for_format(data, BarcodeFormat.EAN13)

    elif barcode_format == BarcodeFormat.QR:
        # QR: Any data
        if len(data) == 0:
            return False, data, ["QR code data cannot be empty"]
        if len(data) > 4296:  # Max for alphanumeric at version 40
            return False, data, ["QR code data exceeds maximum capacity"]

    return True, data, warnings


# =============================================================================
# Barcode Generation Functions
# =============================================================================

def generate_barcode(
    data: str,
    barcode_format: Union[BarcodeFormat, str] = BarcodeFormat.EAN13,
    config: Optional[BarcodeConfig] = None,
    output_path: Optional[str] = None
) -> BarcodeResult:
    """Generate a barcode image.

    This is the main entry point for barcode generation. It supports various
    barcode formats and can output as SVG or PNG.

    Args:
        data: Data to encode in the barcode (GTIN, text, etc.)
        barcode_format: Barcode format to generate
        config: Optional configuration for barcode appearance
        output_path: Optional path to save the barcode image

    Returns:
        BarcodeResult with image data and metadata

    Example:
        >>> result = generate_barcode("4006381333931", BarcodeFormat.EAN13)
        >>> if result.success:
        ...     print(f"Generated {result.format} barcode")
        ...     # Use result.image_base64 for display
    """
    # Handle string format
    if isinstance(barcode_format, str):
        try:
            barcode_format = BarcodeFormat(barcode_format.lower())
        except ValueError:
            return BarcodeResult(
                success=False,
                data=data,
                format=barcode_format,
                image_format="",
                error=f"Unknown barcode format: {barcode_format}. Valid formats: {[f.value for f in BarcodeFormat]}"
            )

    # Use default config if not provided
    if config is None:
        config = BarcodeConfig(format=barcode_format)
    else:
        config.format = barcode_format

    # Validate data for format
    is_valid, normalized_data, messages = _validate_for_format(data, barcode_format)

    if not is_valid:
        return BarcodeResult(
            success=False,
            data=data,
            format=barcode_format.value,
            image_format=config.image_format.value,
            error="; ".join(messages)
        )

    warnings = messages if messages else []

    # Handle QR codes separately
    if barcode_format == BarcodeFormat.QR:
        return _generate_qr_code(normalized_data, config, output_path, warnings)

    # Generate linear barcode using python-barcode
    return _generate_linear_barcode(normalized_data, barcode_format, config, output_path, warnings)


def _generate_linear_barcode(
    data: str,
    barcode_format: BarcodeFormat,
    config: BarcodeConfig,
    output_path: Optional[str],
    warnings: List[str]
) -> BarcodeResult:
    """Generate a linear (1D) barcode using python-barcode library.

    Args:
        data: Validated data to encode
        barcode_format: Barcode format
        config: Barcode configuration
        output_path: Optional output path
        warnings: List of warnings to append to

    Returns:
        BarcodeResult
    """
    try:
        import barcode
        from barcode.writer import SVGWriter, ImageWriter
    except ImportError:
        return BarcodeResult(
            success=False,
            data=data,
            format=barcode_format.value,
            image_format=config.image_format.value,
            error="python-barcode library not installed. Run: pip install python-barcode"
        )

    # Map our format to python-barcode format name
    format_map = {
        BarcodeFormat.EAN13: "ean13",
        BarcodeFormat.EAN8: "ean8",
        BarcodeFormat.UPCA: "upca",
        BarcodeFormat.CODE128: "code128",
        BarcodeFormat.CODE39: "code39",
        BarcodeFormat.ISBN13: "isbn13",
        BarcodeFormat.ISBN10: "isbn10",
        BarcodeFormat.ISSN: "issn",
        BarcodeFormat.ITF: "itf",
        BarcodeFormat.PZN: "pzn",
        BarcodeFormat.JAN: "jan",
    }

    bc_format = format_map.get(barcode_format)
    if not bc_format:
        return BarcodeResult(
            success=False,
            data=data,
            format=barcode_format.value,
            image_format=config.image_format.value,
            error=f"Barcode format {barcode_format.value} not supported for linear barcodes"
        )

    try:
        # Get barcode class
        BarcodeClass = barcode.get_barcode_class(bc_format)

        # Create writer options
        writer_options = {
            "write_text": config.include_text,
            "text_distance": config.text_distance,
            "font_size": config.font_size,
            "quiet_zone": config.quiet_zone,
        }

        if config.width:
            writer_options["module_width"] = config.width
        if config.height:
            writer_options["module_height"] = config.height

        # For EAN/UPC formats with check digit, python-barcode expects data without check digit
        # because it calculates it internally
        bc_data = data
        if barcode_format in (BarcodeFormat.EAN13, BarcodeFormat.JAN):
            bc_data = data[:12]  # Remove check digit for EAN-13
        elif barcode_format == BarcodeFormat.EAN8:
            bc_data = data[:7]  # Remove check digit for EAN-8
        elif barcode_format == BarcodeFormat.UPCA:
            bc_data = data[:11]  # Remove check digit for UPC-A

        if config.image_format == ImageFormat.SVG:
            # Generate SVG
            writer = SVGWriter()
            bc = BarcodeClass(bc_data, writer=writer)

            # Generate to buffer
            buffer = io.BytesIO()
            bc.write(buffer, options=writer_options)
            buffer.seek(0)
            svg_content = buffer.getvalue().decode("utf-8")

            # Save to file if path provided
            file_path = None
            if output_path:
                output_path = str(output_path)
                if not output_path.endswith(".svg"):
                    output_path += ".svg"
                with open(output_path, "w") as f:
                    f.write(svg_content)
                file_path = output_path

            return BarcodeResult(
                success=True,
                data=data,
                format=barcode_format.value,
                image_format="svg",
                svg_content=svg_content,
                image_base64=base64.b64encode(svg_content.encode()).decode(),
                file_path=file_path,
                warnings=warnings if warnings else None
            )

        else:
            # Generate PNG
            try:
                writer = ImageWriter()
                writer.dpi = config.dpi
            except Exception:
                writer = ImageWriter()

            bc = BarcodeClass(bc_data, writer=writer)

            # Generate to buffer
            buffer = io.BytesIO()
            bc.write(buffer, options=writer_options)
            buffer.seek(0)
            image_data = buffer.getvalue()

            # Save to file if path provided
            file_path = None
            if output_path:
                output_path = str(output_path)
                if not output_path.endswith(".png"):
                    output_path += ".png"
                with open(output_path, "wb") as f:
                    f.write(image_data)
                file_path = output_path

            return BarcodeResult(
                success=True,
                data=data,
                format=barcode_format.value,
                image_format="png",
                image_data=image_data,
                image_base64=base64.b64encode(image_data).decode(),
                file_path=file_path,
                warnings=warnings if warnings else None
            )

    except Exception as e:
        return BarcodeResult(
            success=False,
            data=data,
            format=barcode_format.value,
            image_format=config.image_format.value,
            error=f"Barcode generation failed: {str(e)}"
        )


def _generate_qr_code(
    data: str,
    config: BarcodeConfig,
    output_path: Optional[str],
    warnings: List[str],
    qr_config: Optional[QRConfig] = None
) -> BarcodeResult:
    """Generate a QR code using qrcode library.

    Args:
        data: Data to encode
        config: Barcode configuration (for image format)
        output_path: Optional output path
        warnings: List of warnings
        qr_config: Optional QR-specific configuration

    Returns:
        BarcodeResult
    """
    try:
        import qrcode
        from qrcode.constants import ERROR_CORRECT_L, ERROR_CORRECT_M, ERROR_CORRECT_Q, ERROR_CORRECT_H
    except ImportError:
        return BarcodeResult(
            success=False,
            data=data,
            format="qr",
            image_format=config.image_format.value,
            error="qrcode library not installed. Run: pip install qrcode[pil]"
        )

    if qr_config is None:
        qr_config = QRConfig()

    # Map error correction level
    error_map = {
        QRErrorCorrection.LOW: ERROR_CORRECT_L,
        QRErrorCorrection.MEDIUM: ERROR_CORRECT_M,
        QRErrorCorrection.QUARTILE: ERROR_CORRECT_Q,
        QRErrorCorrection.HIGH: ERROR_CORRECT_H,
    }

    try:
        qr = qrcode.QRCode(
            version=qr_config.version,
            error_correction=error_map.get(qr_config.error_correction, ERROR_CORRECT_M),
            box_size=qr_config.box_size,
            border=qr_config.border,
        )

        qr.add_data(data)
        qr.make(fit=True)

        # Create image
        img = qr.make_image(
            fill_color=qr_config.fill_color,
            back_color=qr_config.back_color
        )

        if config.image_format == ImageFormat.SVG:
            # For SVG, we need to use a different approach
            # qrcode doesn't natively support SVG, so we'll create a simple SVG
            try:
                import qrcode.image.svg

                # Regenerate with SVG factory
                if qr_config.fill_color == "black" and qr_config.back_color == "white":
                    factory = qrcode.image.svg.SvgImage
                else:
                    factory = qrcode.image.svg.SvgPathImage

                qr_svg = qrcode.QRCode(
                    version=qr_config.version,
                    error_correction=error_map.get(qr_config.error_correction, ERROR_CORRECT_M),
                    box_size=qr_config.box_size,
                    border=qr_config.border,
                )
                qr_svg.add_data(data)
                qr_svg.make(fit=True)

                img_svg = qr_svg.make_image(image_factory=factory)

                buffer = io.BytesIO()
                img_svg.save(buffer)
                buffer.seek(0)
                svg_content = buffer.getvalue().decode("utf-8")

                file_path = None
                if output_path:
                    output_path = str(output_path)
                    if not output_path.endswith(".svg"):
                        output_path += ".svg"
                    with open(output_path, "w") as f:
                        f.write(svg_content)
                    file_path = output_path

                return BarcodeResult(
                    success=True,
                    data=data,
                    format="qr",
                    image_format="svg",
                    svg_content=svg_content,
                    image_base64=base64.b64encode(svg_content.encode()).decode(),
                    file_path=file_path,
                    warnings=warnings if warnings else None
                )

            except Exception:
                # Fall back to PNG
                warnings.append("SVG generation failed, falling back to PNG")
                config.image_format = ImageFormat.PNG

        # Generate PNG
        buffer = io.BytesIO()
        img.save(buffer, format="PNG")
        buffer.seek(0)
        image_data = buffer.getvalue()

        file_path = None
        if output_path:
            output_path = str(output_path)
            if not output_path.endswith(".png"):
                output_path += ".png"
            with open(output_path, "wb") as f:
                f.write(image_data)
            file_path = output_path

        return BarcodeResult(
            success=True,
            data=data,
            format="qr",
            image_format="png",
            image_data=image_data,
            image_base64=base64.b64encode(image_data).decode(),
            file_path=file_path,
            warnings=warnings if warnings else None
        )

    except Exception as e:
        return BarcodeResult(
            success=False,
            data=data,
            format="qr",
            image_format=config.image_format.value,
            error=f"QR code generation failed: {str(e)}"
        )


def generate_qr_code(
    data: str,
    config: Optional[QRConfig] = None,
    image_format: ImageFormat = ImageFormat.PNG,
    output_path: Optional[str] = None
) -> BarcodeResult:
    """Generate a QR code.

    Convenience function for QR code generation with QR-specific options.

    Args:
        data: Data to encode (URL, text, etc.)
        config: QR code configuration
        image_format: Output image format (PNG or SVG)
        output_path: Optional path to save the image

    Returns:
        BarcodeResult with QR code image

    Example:
        >>> result = generate_qr_code("https://example.com/product/12345")
        >>> if result.success:
        ...     # Use result.image_base64 to embed in HTML
        ...     img_tag = f'<img src="data:image/png;base64,{result.image_base64}">'
    """
    bc_config = BarcodeConfig(
        format=BarcodeFormat.QR,
        image_format=image_format
    )

    is_valid, normalized_data, messages = _validate_for_format(data, BarcodeFormat.QR)

    if not is_valid:
        return BarcodeResult(
            success=False,
            data=data,
            format="qr",
            image_format=image_format.value,
            error="; ".join(messages)
        )

    return _generate_qr_code(normalized_data, bc_config, output_path, messages, config)


# =============================================================================
# Convenience Functions for Common Formats
# =============================================================================

def generate_ean13(
    gtin: str,
    image_format: ImageFormat = ImageFormat.SVG,
    include_text: bool = True,
    output_path: Optional[str] = None
) -> BarcodeResult:
    """Generate an EAN-13 barcode.

    EAN-13 is the most common barcode format used worldwide for retail products.

    Args:
        gtin: 12 or 13 digit GTIN (check digit calculated if 12 digits)
        image_format: Output format (SVG or PNG)
        include_text: Include human-readable text
        output_path: Optional path to save barcode

    Returns:
        BarcodeResult

    Example:
        >>> result = generate_ean13("400638133393")  # 12 digits, check digit auto-added
        >>> result.data
        '4006381333931'
    """
    config = BarcodeConfig(
        format=BarcodeFormat.EAN13,
        image_format=image_format,
        include_text=include_text
    )
    return generate_barcode(gtin, BarcodeFormat.EAN13, config, output_path)


def generate_ean8(
    gtin: str,
    image_format: ImageFormat = ImageFormat.SVG,
    include_text: bool = True,
    output_path: Optional[str] = None
) -> BarcodeResult:
    """Generate an EAN-8 barcode.

    EAN-8 is used for small products where space is limited.

    Args:
        gtin: 7 or 8 digit GTIN-8 (check digit calculated if 7 digits)
        image_format: Output format
        include_text: Include human-readable text
        output_path: Optional path to save barcode

    Returns:
        BarcodeResult
    """
    config = BarcodeConfig(
        format=BarcodeFormat.EAN8,
        image_format=image_format,
        include_text=include_text
    )
    return generate_barcode(gtin, BarcodeFormat.EAN8, config, output_path)


def generate_upca(
    upc: str,
    image_format: ImageFormat = ImageFormat.SVG,
    include_text: bool = True,
    output_path: Optional[str] = None
) -> BarcodeResult:
    """Generate a UPC-A barcode.

    UPC-A is the 12-digit barcode format used primarily in North America.

    Args:
        upc: 11 or 12 digit UPC (check digit calculated if 11 digits)
        image_format: Output format
        include_text: Include human-readable text
        output_path: Optional path to save barcode

    Returns:
        BarcodeResult
    """
    config = BarcodeConfig(
        format=BarcodeFormat.UPCA,
        image_format=image_format,
        include_text=include_text
    )
    return generate_barcode(upc, BarcodeFormat.UPCA, config, output_path)


def generate_code128(
    data: str,
    image_format: ImageFormat = ImageFormat.SVG,
    include_text: bool = True,
    output_path: Optional[str] = None
) -> BarcodeResult:
    """Generate a Code 128 barcode.

    Code 128 is a high-density barcode used for alphanumeric data in
    logistics, shipping, and inventory management.

    Args:
        data: ASCII text to encode
        image_format: Output format
        include_text: Include human-readable text
        output_path: Optional path to save barcode

    Returns:
        BarcodeResult

    Example:
        >>> result = generate_code128("SHIP-12345-A")
    """
    config = BarcodeConfig(
        format=BarcodeFormat.CODE128,
        image_format=image_format,
        include_text=include_text
    )
    return generate_barcode(data, BarcodeFormat.CODE128, config, output_path)


def generate_code39(
    data: str,
    image_format: ImageFormat = ImageFormat.SVG,
    include_text: bool = True,
    output_path: Optional[str] = None
) -> BarcodeResult:
    """Generate a Code 39 barcode.

    Code 39 is used in industrial applications. Supports uppercase letters,
    digits, and special characters (-, ., $, /, +, %, space).

    Args:
        data: Text to encode (will be converted to uppercase)
        image_format: Output format
        include_text: Include human-readable text
        output_path: Optional path to save barcode

    Returns:
        BarcodeResult
    """
    config = BarcodeConfig(
        format=BarcodeFormat.CODE39,
        image_format=image_format,
        include_text=include_text
    )
    return generate_barcode(data, BarcodeFormat.CODE39, config, output_path)


def generate_itf14(
    gtin14: str,
    image_format: ImageFormat = ImageFormat.SVG,
    include_text: bool = True,
    output_path: Optional[str] = None
) -> BarcodeResult:
    """Generate an ITF-14 barcode.

    ITF-14 (Interleaved 2 of 5) is used for GTIN-14 on outer packaging
    like cases and pallets.

    Args:
        gtin14: 14-digit GTIN-14
        image_format: Output format
        include_text: Include human-readable text
        output_path: Optional path to save barcode

    Returns:
        BarcodeResult
    """
    config = BarcodeConfig(
        format=BarcodeFormat.ITF,
        image_format=image_format,
        include_text=include_text
    )
    return generate_barcode(gtin14, BarcodeFormat.ITF, config, output_path)


# =============================================================================
# Batch Generation
# =============================================================================

def generate_barcodes_batch(
    items: List[Dict[str, Any]],
    default_format: BarcodeFormat = BarcodeFormat.EAN13,
    default_image_format: ImageFormat = ImageFormat.SVG
) -> List[BarcodeResult]:
    """Generate multiple barcodes in batch.

    Args:
        items: List of dicts with 'data' and optional 'format', 'config', 'output_path'
        default_format: Default barcode format if not specified per item
        default_image_format: Default image format if not specified per item

    Returns:
        List of BarcodeResults

    Example:
        >>> items = [
        ...     {"data": "4006381333931", "format": "ean13"},
        ...     {"data": "SHIP-001", "format": "code128"},
        ...     {"data": "https://example.com", "format": "qr"},
        ... ]
        >>> results = generate_barcodes_batch(items)
    """
    results = []

    for item in items:
        data = item.get("data", "")
        fmt = item.get("format", default_format)

        if isinstance(fmt, str):
            try:
                fmt = BarcodeFormat(fmt.lower())
            except ValueError:
                results.append(BarcodeResult(
                    success=False,
                    data=data,
                    format=fmt,
                    image_format=default_image_format.value,
                    error=f"Unknown format: {fmt}"
                ))
                continue

        config = item.get("config")
        if config is None:
            img_fmt = item.get("image_format", default_image_format)
            if isinstance(img_fmt, str):
                try:
                    img_fmt = ImageFormat(img_fmt.lower())
                except ValueError:
                    img_fmt = default_image_format
            config = BarcodeConfig(format=fmt, image_format=img_fmt)

        output_path = item.get("output_path")

        result = generate_barcode(data, fmt, config, output_path)
        results.append(result)

    return results


# =============================================================================
# Product Barcode Generation (Frappe Integration)
# =============================================================================

def generate_product_barcode(product_name: str, barcode_format: str = "ean13") -> Dict[str, Any]:
    """Generate a barcode for a Product Master document.

    This function integrates with Frappe to fetch product data and generate
    the appropriate barcode.

    Args:
        product_name: Name/ID of the Product Master document
        barcode_format: Barcode format to generate

    Returns:
        Dict with barcode result
    """
    import frappe

    try:
        # Get product document
        product = frappe.get_doc("Product Master", product_name)

        # Get barcode/GTIN from product
        gtin = product.get("barcode") or product.get("gtin")
        if not gtin:
            return {
                "success": False,
                "error": f"Product {product_name} does not have a barcode/GTIN"
            }

        # Determine format
        try:
            fmt = BarcodeFormat(barcode_format.lower())
        except ValueError:
            return {
                "success": False,
                "error": f"Unknown barcode format: {barcode_format}"
            }

        # Generate barcode
        result = generate_barcode(gtin, fmt)

        return result.to_dict()

    except frappe.DoesNotExistError:
        return {
            "success": False,
            "error": f"Product {product_name} not found"
        }
    except Exception as e:
        return {
            "success": False,
            "error": str(e)
        }


def save_barcode_to_file(product_name: str, barcode_format: str = "ean13") -> Dict[str, Any]:
    """Generate and save a barcode as a Frappe File attachment.

    Args:
        product_name: Name/ID of the Product Master document
        barcode_format: Barcode format to generate

    Returns:
        Dict with file URL and metadata
    """
    import frappe

    try:
        # Get product
        product = frappe.get_doc("Product Master", product_name)
        gtin = product.get("barcode") or product.get("gtin")

        if not gtin:
            return {
                "success": False,
                "error": f"Product {product_name} does not have a barcode/GTIN"
            }

        # Generate barcode as PNG (better for file storage)
        fmt = BarcodeFormat(barcode_format.lower())
        config = BarcodeConfig(format=fmt, image_format=ImageFormat.PNG)
        result = generate_barcode(gtin, fmt, config)

        if not result.success:
            return {"success": False, "error": result.error}

        # Create Frappe File
        file_name = f"barcode_{product_name}_{barcode_format}.png"

        file_doc = frappe.get_doc({
            "doctype": "File",
            "file_name": file_name,
            "content": result.image_data,
            "attached_to_doctype": "Product Master",
            "attached_to_name": product_name,
            "is_private": 0
        })
        file_doc.save()

        return {
            "success": True,
            "file_url": file_doc.file_url,
            "file_name": file_doc.file_name,
            "file_doc_name": file_doc.name,
            "barcode_format": barcode_format,
            "gtin": gtin
        }

    except Exception as e:
        return {
            "success": False,
            "error": str(e)
        }


# =============================================================================
# Utility Functions
# =============================================================================

def get_supported_formats() -> List[Dict[str, str]]:
    """Get list of supported barcode formats.

    Returns:
        List of dicts with format info
    """
    formats = [
        {"value": "ean13", "label": "EAN-13", "description": "13-digit European Article Number"},
        {"value": "ean8", "label": "EAN-8", "description": "8-digit EAN for small products"},
        {"value": "upca", "label": "UPC-A", "description": "12-digit Universal Product Code"},
        {"value": "code128", "label": "Code 128", "description": "High-density alphanumeric barcode"},
        {"value": "code39", "label": "Code 39", "description": "Alphanumeric barcode for industrial use"},
        {"value": "isbn13", "label": "ISBN-13", "description": "13-digit book identifier"},
        {"value": "isbn10", "label": "ISBN-10", "description": "Legacy 10-digit book identifier"},
        {"value": "issn", "label": "ISSN", "description": "International Standard Serial Number"},
        {"value": "itf", "label": "ITF", "description": "Interleaved 2 of 5 for packaging"},
        {"value": "pzn", "label": "PZN", "description": "German pharmaceutical number"},
        {"value": "qr", "label": "QR Code", "description": "2D barcode for URLs and data"},
    ]
    return formats


def get_image_formats() -> List[Dict[str, str]]:
    """Get list of supported image output formats.

    Returns:
        List of dicts with format info
    """
    return [
        {"value": "svg", "label": "SVG", "description": "Scalable Vector Graphics (recommended for print)"},
        {"value": "png", "label": "PNG", "description": "Portable Network Graphics (raster image)"},
    ]


# =============================================================================
# API Endpoints
# =============================================================================

def api_generate_barcode(
    data: str,
    format: str = "ean13",
    image_format: str = "svg",
    include_text: bool = True
) -> Dict[str, Any]:
    """API endpoint for barcode generation.

    Usage from JavaScript:
        frappe.call({
            method: 'frappe_pim.pim.utils.barcode_generator.api_generate_barcode',
            args: {
                data: '4006381333931',
                format: 'ean13',
                image_format: 'svg'
            },
            callback: function(r) {
                if (r.message.success) {
                    // Use r.message.image_base64 or r.message.svg_content
                }
            }
        });

    Args:
        data: Data to encode in barcode
        format: Barcode format (ean13, upca, code128, qr, etc.)
        image_format: Output image format (svg or png)
        include_text: Include human-readable text

    Returns:
        Dict with barcode result
    """
    try:
        bc_format = BarcodeFormat(format.lower())
    except ValueError:
        return {
            "success": False,
            "error": f"Unknown format: {format}. Valid formats: {[f.value for f in BarcodeFormat]}"
        }

    try:
        img_format = ImageFormat(image_format.lower())
    except ValueError:
        return {
            "success": False,
            "error": f"Unknown image format: {image_format}. Valid formats: svg, png"
        }

    config = BarcodeConfig(
        format=bc_format,
        image_format=img_format,
        include_text=include_text
    )

    result = generate_barcode(data, bc_format, config)
    return result.to_dict()


def api_generate_qr(
    data: str,
    error_correction: str = "M",
    box_size: int = 10,
    border: int = 4,
    image_format: str = "png"
) -> Dict[str, Any]:
    """API endpoint for QR code generation.

    Args:
        data: Data to encode (URL, text, etc.)
        error_correction: Error correction level (L, M, Q, H)
        box_size: Size of each module in pixels
        border: Border width in modules
        image_format: Output format (svg or png)

    Returns:
        Dict with QR code result
    """
    try:
        ec_level = QRErrorCorrection(error_correction.upper())
    except ValueError:
        return {
            "success": False,
            "error": f"Invalid error correction level: {error_correction}. Valid: L, M, Q, H"
        }

    try:
        img_format = ImageFormat(image_format.lower())
    except ValueError:
        img_format = ImageFormat.PNG

    qr_config = QRConfig(
        error_correction=ec_level,
        box_size=box_size,
        border=border
    )

    result = generate_qr_code(data, qr_config, img_format)
    return result.to_dict()


def api_generate_product_barcode(
    product_name: str,
    format: str = "ean13"
) -> Dict[str, Any]:
    """API endpoint for generating barcode from Product Master.

    Args:
        product_name: Product Master document name
        format: Barcode format

    Returns:
        Dict with barcode result
    """
    return generate_product_barcode(product_name, format)


def api_save_product_barcode(
    product_name: str,
    format: str = "ean13"
) -> Dict[str, Any]:
    """API endpoint for saving product barcode as file attachment.

    Args:
        product_name: Product Master document name
        format: Barcode format

    Returns:
        Dict with file info
    """
    return save_barcode_to_file(product_name, format)


def api_get_supported_formats() -> Dict[str, Any]:
    """API endpoint for getting supported barcode formats.

    Returns:
        Dict with format lists
    """
    return {
        "barcode_formats": get_supported_formats(),
        "image_formats": get_image_formats()
    }


# =============================================================================
# Whitelisted Functions for Frappe API
# =============================================================================

_WHITELISTED_METHODS = [
    "frappe_pim.pim.utils.barcode_generator.api_generate_barcode",
    "frappe_pim.pim.utils.barcode_generator.api_generate_qr",
    "frappe_pim.pim.utils.barcode_generator.api_generate_product_barcode",
    "frappe_pim.pim.utils.barcode_generator.api_save_product_barcode",
    "frappe_pim.pim.utils.barcode_generator.api_get_supported_formats",
]


def _wrap_for_whitelist():
    """Apply frappe.whitelist() decorator at runtime.

    This allows the module to be imported without frappe being available.
    """
    try:
        import frappe

        global api_generate_barcode, api_generate_qr, api_generate_product_barcode
        global api_save_product_barcode, api_get_supported_formats

        api_generate_barcode = frappe.whitelist()(api_generate_barcode)
        api_generate_qr = frappe.whitelist()(api_generate_qr)
        api_generate_product_barcode = frappe.whitelist()(api_generate_product_barcode)
        api_save_product_barcode = frappe.whitelist()(api_save_product_barcode)
        api_get_supported_formats = frappe.whitelist(allow_guest=True)(api_get_supported_formats)
    except ImportError:
        pass


# Apply whitelist decorators when module is loaded in Frappe context
_wrap_for_whitelist()
