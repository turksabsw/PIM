"""Partner Submission Media DocType Controller

Child table for tracking media file uploads in partner submissions.
Each row represents a single media file (image, video, document) proposed by the partner.
"""

import frappe
from frappe.model.document import Document


class PartnerSubmissionMedia(Document):
    """Controller for Partner Submission Media child table.

    Tracks individual media file uploads with per-file approval capability.
    """

    def validate(self):
        """Validate the media entry."""
        self.validate_file()
        self.detect_media_type()
        self.extract_file_info()

    def validate_file(self):
        """Validate that file is provided."""
        if not self.file:
            frappe.throw("File is required")

    def detect_media_type(self):
        """Auto-detect media type from file extension."""
        if not self.file:
            return

        file_lower = self.file.lower()

        if file_lower.endswith(('.jpg', '.jpeg', '.png', '.gif', '.webp', '.bmp', '.svg', '.tiff')):
            self.media_type = "Image"
        elif file_lower.endswith(('.mp4', '.avi', '.mov', '.wmv', '.flv', '.webm', '.mkv')):
            self.media_type = "Video"
        elif file_lower.endswith(('.pdf', '.doc', '.docx', '.xls', '.xlsx', '.ppt', '.pptx', '.txt')):
            self.media_type = "Document"
        else:
            self.media_type = "Other"

    def extract_file_info(self):
        """Extract file information (size, dimensions)."""
        if not self.file:
            return

        try:
            # Get file doc if it exists
            file_url = self.file
            if file_url.startswith("/files/"):
                file_doc = frappe.get_all(
                    "File",
                    filters={"file_url": file_url},
                    fields=["file_size", "file_name"],
                    limit=1
                )
                if file_doc:
                    self.file_size = file_doc[0].get("file_size")
                    if not self.file_name:
                        self.file_name = file_doc[0].get("file_name")

            # Extract dimensions for images
            if self.media_type == "Image" and self.file_size:
                self._extract_image_dimensions()

        except Exception:
            pass  # Non-critical, don't fail on file info extraction

    def _extract_image_dimensions(self):
        """Extract image dimensions using PIL."""
        try:
            from PIL import Image
            import io

            # Get file content
            file_path = frappe.get_site_path("public", self.file.lstrip("/"))

            with Image.open(file_path) as img:
                width, height = img.size
                self.dimensions = f"{width}x{height}"
        except Exception:
            pass  # Image processing not available or file not accessible

    def approve(self):
        """Mark this media as approved."""
        self.approval_status = "Approved"

    def reject(self, note: str = None):
        """Mark this media as rejected.

        Args:
            note: Optional reviewer note explaining rejection
        """
        self.approval_status = "Rejected"
        if note:
            self.reviewer_note = note

    def is_valid_image(self) -> bool:
        """Check if file is a valid image.

        Returns:
            bool: True if valid image
        """
        if self.media_type != "Image":
            return False

        if not self.file:
            return False

        valid_extensions = ('.jpg', '.jpeg', '.png', '.gif', '.webp', '.bmp', '.svg', '.tiff')
        return self.file.lower().endswith(valid_extensions)

    def meets_size_requirements(
        self,
        min_width: int = 0,
        min_height: int = 0,
        max_file_size: int = 0
    ) -> dict:
        """Check if media meets size requirements.

        Args:
            min_width: Minimum width in pixels (0 to skip)
            min_height: Minimum height in pixels (0 to skip)
            max_file_size: Maximum file size in bytes (0 to skip)

        Returns:
            dict: {meets: bool, issues: list}
        """
        issues = []

        # Check file size
        if max_file_size > 0 and self.file_size:
            if self.file_size > max_file_size:
                issues.append(f"File size ({self.file_size} bytes) exceeds maximum ({max_file_size} bytes)")

        # Check dimensions
        if self.dimensions and (min_width > 0 or min_height > 0):
            try:
                width, height = map(int, self.dimensions.split('x'))
                if min_width > 0 and width < min_width:
                    issues.append(f"Width ({width}px) is less than minimum ({min_width}px)")
                if min_height > 0 and height < min_height:
                    issues.append(f"Height ({height}px) is less than minimum ({min_height}px)")
            except ValueError:
                pass

        return {
            "meets": len(issues) == 0,
            "issues": issues
        }
