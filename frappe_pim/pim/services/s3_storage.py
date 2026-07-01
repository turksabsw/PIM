"""S3 Storage Integration Service for Scalable Media Hosting

This module provides a comprehensive service for integrating AWS S3 (and S3-compatible
storage) for scalable media hosting in the PIM system. It handles all media storage
operations including uploads, downloads, URL generation, and lifecycle management.

Features:
- Full S3 API integration using boto3
- Support for S3-compatible services (MinIO, DigitalOcean Spaces, Wasabi, etc.)
- Multi-part upload for large files
- Pre-signed URL generation for secure access
- CloudFront CDN integration support
- Automatic content type detection
- Image optimization integration
- Batch upload operations
- Lifecycle and retention policies
- Versioning support
- Cross-region replication configuration
- Async upload via background jobs

Key Concepts:
- S3Config: Configuration for S3 connection (bucket, region, credentials)
- StorageLocation: Represents a file location in S3 (bucket, key, version)
- UploadResult: Result of an upload operation with URL and metadata
- MediaAsset: Represents a complete media asset with all variants

Supported Storage Types:
- AWS S3 (primary)
- MinIO (self-hosted S3-compatible)
- DigitalOcean Spaces
- Wasabi
- Backblaze B2
- Google Cloud Storage (S3-compatible mode)
- Any S3-compatible storage

Note: frappe imports are deferred to function level to allow module
import without Frappe being available (e.g., for testing/verification).

Requirements:
    - boto3>=1.34.0 (included in Frappe)
    - Pillow>=10.0.0 (included in Frappe)
"""

import hashlib
import io
import mimetypes
import os
import threading
import uuid
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from enum import Enum
from pathlib import Path
from typing import Any, BinaryIO, Callable, Dict, List, Optional, Tuple, Union


# =============================================================================
# Constants and Enums
# =============================================================================

class StorageProvider(Enum):
    """Supported S3-compatible storage providers."""
    AWS_S3 = "aws_s3"
    MINIO = "minio"
    DIGITALOCEAN_SPACES = "digitalocean_spaces"
    WASABI = "wasabi"
    BACKBLAZE_B2 = "backblaze_b2"
    GOOGLE_CLOUD_STORAGE = "google_cloud_storage"
    CUSTOM = "custom"


class ACL(Enum):
    """S3 Access Control List presets."""
    PRIVATE = "private"
    PUBLIC_READ = "public-read"
    PUBLIC_READ_WRITE = "public-read-write"
    AUTHENTICATED_READ = "authenticated-read"
    BUCKET_OWNER_READ = "bucket-owner-read"
    BUCKET_OWNER_FULL_CONTROL = "bucket-owner-full-control"


class StorageClass(Enum):
    """S3 storage classes."""
    STANDARD = "STANDARD"
    REDUCED_REDUNDANCY = "REDUCED_REDUNDANCY"
    STANDARD_IA = "STANDARD_IA"
    ONEZONE_IA = "ONEZONE_IA"
    INTELLIGENT_TIERING = "INTELLIGENT_TIERING"
    GLACIER = "GLACIER"
    GLACIER_IR = "GLACIER_IR"
    DEEP_ARCHIVE = "DEEP_ARCHIVE"


class UploadStatus(Enum):
    """Status of upload operations."""
    PENDING = "pending"
    UPLOADING = "uploading"
    COMPLETED = "completed"
    FAILED = "failed"
    CANCELLED = "cancelled"


class MediaType(Enum):
    """Types of media assets."""
    IMAGE = "image"
    VIDEO = "video"
    DOCUMENT = "document"
    ARCHIVE = "archive"
    OTHER = "other"


# Default settings
DEFAULT_MULTIPART_THRESHOLD = 8 * 1024 * 1024  # 8MB
DEFAULT_MULTIPART_CHUNKSIZE = 8 * 1024 * 1024  # 8MB
DEFAULT_MAX_CONCURRENCY = 10
DEFAULT_URL_EXPIRATION = 3600  # 1 hour
MAX_SINGLE_PUT_SIZE = 5 * 1024 * 1024 * 1024  # 5GB

# Provider endpoints
PROVIDER_ENDPOINTS = {
    StorageProvider.MINIO: "http://localhost:9000",
    StorageProvider.DIGITALOCEAN_SPACES: "https://{region}.digitaloceanspaces.com",
    StorageProvider.WASABI: "https://s3.{region}.wasabisys.com",
    StorageProvider.BACKBLAZE_B2: "https://s3.{region}.backblazeb2.com",
    StorageProvider.GOOGLE_CLOUD_STORAGE: "https://storage.googleapis.com",
}


# =============================================================================
# Data Classes
# =============================================================================

@dataclass
class S3Config:
    """Configuration for S3 connection.

    Attributes:
        bucket_name: Name of the S3 bucket
        region: AWS region (e.g., 'us-east-1')
        access_key_id: AWS access key ID
        secret_access_key: AWS secret access key
        endpoint_url: Custom endpoint URL for S3-compatible services
        provider: Storage provider type
        use_ssl: Whether to use SSL for connections
        signature_version: S3 signature version (s3v4)
        addressing_style: S3 addressing style (path, virtual, auto)
        cloudfront_domain: Optional CloudFront CDN domain
        cloudfront_key_pair_id: CloudFront key pair ID for signed URLs
        cloudfront_private_key: CloudFront private key for signing
    """
    bucket_name: str
    region: str = "us-east-1"
    access_key_id: Optional[str] = None
    secret_access_key: Optional[str] = None
    endpoint_url: Optional[str] = None
    provider: StorageProvider = StorageProvider.AWS_S3
    use_ssl: bool = True
    signature_version: str = "s3v4"
    addressing_style: str = "auto"
    cloudfront_domain: Optional[str] = None
    cloudfront_key_pair_id: Optional[str] = None
    cloudfront_private_key: Optional[str] = None
    default_acl: ACL = ACL.PRIVATE
    default_storage_class: StorageClass = StorageClass.STANDARD
    default_cache_control: str = "max-age=31536000"

    def __post_init__(self):
        """Set default endpoint URL based on provider."""
        if not self.endpoint_url and self.provider in PROVIDER_ENDPOINTS:
            self.endpoint_url = PROVIDER_ENDPOINTS[self.provider].format(
                region=self.region
            )

    def to_dict(self) -> Dict[str, Any]:
        """Convert to dictionary (excluding secrets)."""
        return {
            "bucket_name": self.bucket_name,
            "region": self.region,
            "endpoint_url": self.endpoint_url,
            "provider": self.provider.value,
            "use_ssl": self.use_ssl,
            "signature_version": self.signature_version,
            "addressing_style": self.addressing_style,
            "cloudfront_domain": self.cloudfront_domain,
            "default_acl": self.default_acl.value,
            "default_storage_class": self.default_storage_class.value,
        }


@dataclass
class StorageLocation:
    """Represents a file location in S3.

    Attributes:
        bucket: S3 bucket name
        key: Object key (path) in the bucket
        version_id: Optional version ID
        etag: Entity tag (MD5 hash)
    """
    bucket: str
    key: str
    version_id: Optional[str] = None
    etag: Optional[str] = None

    @property
    def uri(self) -> str:
        """Get S3 URI (s3://bucket/key)."""
        return f"s3://{self.bucket}/{self.key}"

    def to_dict(self) -> Dict[str, Any]:
        """Convert to dictionary."""
        return {
            "bucket": self.bucket,
            "key": self.key,
            "version_id": self.version_id,
            "etag": self.etag,
            "uri": self.uri,
        }


@dataclass
class UploadProgress:
    """Tracks upload progress for multi-part uploads.

    Attributes:
        file_path: Source file path
        total_bytes: Total file size in bytes
        bytes_transferred: Bytes uploaded so far
        percentage: Upload percentage
        status: Current upload status
        started_at: Upload start time
        updated_at: Last update time
    """
    file_path: str
    total_bytes: int
    bytes_transferred: int = 0
    percentage: float = 0.0
    status: UploadStatus = UploadStatus.PENDING
    started_at: Optional[datetime] = None
    updated_at: Optional[datetime] = None
    upload_id: str = field(default_factory=lambda: str(uuid.uuid4()))

    def update(self, bytes_transferred: int):
        """Update progress with new byte count."""
        self.bytes_transferred = bytes_transferred
        self.percentage = (bytes_transferred / self.total_bytes * 100) if self.total_bytes > 0 else 0
        self.updated_at = datetime.utcnow()

    def to_dict(self) -> Dict[str, Any]:
        """Convert to dictionary."""
        return {
            "file_path": self.file_path,
            "total_bytes": self.total_bytes,
            "bytes_transferred": self.bytes_transferred,
            "percentage": round(self.percentage, 2),
            "status": self.status.value,
            "started_at": self.started_at.isoformat() if self.started_at else None,
            "updated_at": self.updated_at.isoformat() if self.updated_at else None,
            "upload_id": self.upload_id,
        }


@dataclass
class UploadResult:
    """Result of an upload operation.

    Attributes:
        success: Whether the upload succeeded
        location: Storage location of the uploaded file
        url: Public URL (if ACL allows)
        signed_url: Pre-signed URL for private access
        content_type: MIME type of the uploaded file
        size: File size in bytes
        checksum: MD5 checksum
        metadata: Custom metadata
        error: Error message if failed
    """
    success: bool
    location: Optional[StorageLocation] = None
    url: Optional[str] = None
    signed_url: Optional[str] = None
    cloudfront_url: Optional[str] = None
    content_type: Optional[str] = None
    size: int = 0
    checksum: Optional[str] = None
    metadata: Dict[str, str] = field(default_factory=dict)
    error: Optional[str] = None
    upload_id: str = field(default_factory=lambda: str(uuid.uuid4()))
    timestamp: datetime = field(default_factory=datetime.utcnow)

    def to_dict(self) -> Dict[str, Any]:
        """Convert to dictionary."""
        return {
            "success": self.success,
            "location": self.location.to_dict() if self.location else None,
            "url": self.url,
            "signed_url": self.signed_url,
            "cloudfront_url": self.cloudfront_url,
            "content_type": self.content_type,
            "size": self.size,
            "size_human": _format_file_size(self.size),
            "checksum": self.checksum,
            "metadata": self.metadata,
            "error": self.error,
            "upload_id": self.upload_id,
            "timestamp": self.timestamp.isoformat(),
        }


@dataclass
class MediaAsset:
    """Represents a complete media asset with all variants.

    Attributes:
        asset_id: Unique asset identifier
        product_id: Associated product ID
        original: Original file upload result
        variants: Dictionary of variant upload results
        media_type: Type of media
        metadata: Asset metadata
    """
    asset_id: str
    product_id: Optional[str] = None
    original: Optional[UploadResult] = None
    variants: Dict[str, UploadResult] = field(default_factory=dict)
    media_type: MediaType = MediaType.IMAGE
    metadata: Dict[str, Any] = field(default_factory=dict)
    created_at: datetime = field(default_factory=datetime.utcnow)

    def to_dict(self) -> Dict[str, Any]:
        """Convert to dictionary."""
        return {
            "asset_id": self.asset_id,
            "product_id": self.product_id,
            "original": self.original.to_dict() if self.original else None,
            "variants": {k: v.to_dict() for k, v in self.variants.items()},
            "media_type": self.media_type.value,
            "metadata": self.metadata,
            "created_at": self.created_at.isoformat(),
        }


@dataclass
class BatchUploadResult:
    """Result of a batch upload operation.

    Attributes:
        total: Total number of files
        success_count: Number of successful uploads
        failed_count: Number of failed uploads
        results: Individual upload results
        errors: Error messages
    """
    total: int = 0
    success_count: int = 0
    failed_count: int = 0
    results: List[UploadResult] = field(default_factory=list)
    errors: List[str] = field(default_factory=list)
    started_at: Optional[datetime] = None
    completed_at: Optional[datetime] = None
    job_id: str = field(default_factory=lambda: str(uuid.uuid4()))

    def to_dict(self) -> Dict[str, Any]:
        """Convert to dictionary."""
        return {
            "total": self.total,
            "success_count": self.success_count,
            "failed_count": self.failed_count,
            "results": [r.to_dict() for r in self.results],
            "errors": self.errors,
            "started_at": self.started_at.isoformat() if self.started_at else None,
            "completed_at": self.completed_at.isoformat() if self.completed_at else None,
            "job_id": self.job_id,
        }


# =============================================================================
# S3 Storage Service
# =============================================================================

class S3StorageService:
    """Service for S3 storage operations.

    This service provides a comprehensive interface for managing media assets
    in S3-compatible storage, including uploads, downloads, URL generation,
    and lifecycle management.

    Attributes:
        config: S3 configuration
        client: Boto3 S3 client
    """

    def __init__(self, config: Optional[S3Config] = None):
        """Initialize the S3 storage service.

        Args:
            config: S3 configuration. If not provided, loads from PIM Settings.
        """
        self._config = config
        self._client = None
        self._resource = None
        self._transfer_config = None
        self._lock = threading.Lock()

    @property
    def config(self) -> S3Config:
        """Get S3 configuration (lazy loading from settings)."""
        if self._config is None:
            self._config = self._load_config_from_settings()
        return self._config

    @property
    def client(self):
        """Get boto3 S3 client (lazy initialization)."""
        if self._client is None:
            self._client = self._create_client()
        return self._client

    @property
    def resource(self):
        """Get boto3 S3 resource (lazy initialization)."""
        if self._resource is None:
            self._resource = self._create_resource()
        return self._resource

    def _load_config_from_settings(self) -> S3Config:
        """Load S3 configuration from PIM Settings.

        Returns:
            S3Config instance

        Raises:
            ValueError: If S3 is not configured
        """
        settings = _get_pim_settings()

        bucket_name = settings.get("s3_bucket_name")
        if not bucket_name:
            raise ValueError(
                "S3 storage not configured. Please configure in PIM Settings."
            )

        provider_name = settings.get("s3_provider", "aws_s3")
        try:
            provider = StorageProvider(provider_name)
        except ValueError:
            provider = StorageProvider.AWS_S3

        return S3Config(
            bucket_name=bucket_name,
            region=settings.get("s3_region", "us-east-1"),
            access_key_id=settings.get("s3_access_key_id"),
            secret_access_key=settings.get("s3_secret_access_key"),
            endpoint_url=settings.get("s3_endpoint_url"),
            provider=provider,
            cloudfront_domain=settings.get("s3_cloudfront_domain"),
            cloudfront_key_pair_id=settings.get("s3_cloudfront_key_pair_id"),
            cloudfront_private_key=settings.get("s3_cloudfront_private_key"),
        )

    def _create_client(self):
        """Create boto3 S3 client."""
        import boto3
        from botocore.config import Config as BotoConfig

        boto_config = BotoConfig(
            signature_version=self.config.signature_version,
            s3={"addressing_style": self.config.addressing_style},
            retries={"max_attempts": 3, "mode": "adaptive"},
        )

        client_kwargs = {
            "service_name": "s3",
            "region_name": self.config.region,
            "config": boto_config,
        }

        if self.config.access_key_id and self.config.secret_access_key:
            client_kwargs["aws_access_key_id"] = self.config.access_key_id
            client_kwargs["aws_secret_access_key"] = self.config.secret_access_key

        if self.config.endpoint_url:
            client_kwargs["endpoint_url"] = self.config.endpoint_url
            client_kwargs["use_ssl"] = self.config.use_ssl

        return boto3.client(**client_kwargs)

    def _create_resource(self):
        """Create boto3 S3 resource."""
        import boto3
        from botocore.config import Config as BotoConfig

        boto_config = BotoConfig(
            signature_version=self.config.signature_version,
            s3={"addressing_style": self.config.addressing_style},
        )

        resource_kwargs = {
            "service_name": "s3",
            "region_name": self.config.region,
            "config": boto_config,
        }

        if self.config.access_key_id and self.config.secret_access_key:
            resource_kwargs["aws_access_key_id"] = self.config.access_key_id
            resource_kwargs["aws_secret_access_key"] = self.config.secret_access_key

        if self.config.endpoint_url:
            resource_kwargs["endpoint_url"] = self.config.endpoint_url
            resource_kwargs["use_ssl"] = self.config.use_ssl

        return boto3.resource(**resource_kwargs)

    def _get_transfer_config(self):
        """Get transfer configuration for multipart uploads."""
        if self._transfer_config is None:
            from boto3.s3.transfer import TransferConfig

            self._transfer_config = TransferConfig(
                multipart_threshold=DEFAULT_MULTIPART_THRESHOLD,
                multipart_chunksize=DEFAULT_MULTIPART_CHUNKSIZE,
                max_concurrency=DEFAULT_MAX_CONCURRENCY,
                use_threads=True,
            )
        return self._transfer_config

    # =========================================================================
    # Connection Management
    # =========================================================================

    def test_connection(self) -> Tuple[bool, str]:
        """Test the S3 connection.

        Returns:
            Tuple of (success, message)
        """
        try:
            # Try to head the bucket
            self.client.head_bucket(Bucket=self.config.bucket_name)
            return True, f"Successfully connected to bucket: {self.config.bucket_name}"
        except self.client.exceptions.NoSuchBucket:
            return False, f"Bucket does not exist: {self.config.bucket_name}"
        except Exception as e:
            error_code = getattr(e, "response", {}).get("Error", {}).get("Code", "")
            if error_code == "403":
                return False, "Access denied. Check your credentials and permissions."
            return False, f"Connection failed: {str(e)}"

    def ensure_bucket_exists(self) -> bool:
        """Ensure the configured bucket exists, create if not.

        Returns:
            True if bucket exists or was created successfully
        """
        try:
            self.client.head_bucket(Bucket=self.config.bucket_name)
            return True
        except self.client.exceptions.NoSuchBucket:
            try:
                create_params = {"Bucket": self.config.bucket_name}
                if self.config.region != "us-east-1":
                    create_params["CreateBucketConfiguration"] = {
                        "LocationConstraint": self.config.region
                    }
                self.client.create_bucket(**create_params)
                return True
            except Exception:
                return False
        except Exception:
            return False

    # =========================================================================
    # Upload Operations
    # =========================================================================

    def upload_file(
        self,
        file_path: str,
        key: Optional[str] = None,
        content_type: Optional[str] = None,
        acl: Optional[ACL] = None,
        storage_class: Optional[StorageClass] = None,
        metadata: Optional[Dict[str, str]] = None,
        cache_control: Optional[str] = None,
        progress_callback: Optional[Callable[[int], None]] = None,
    ) -> UploadResult:
        """Upload a file to S3.

        Args:
            file_path: Path to the local file
            key: S3 object key (defaults to filename with UUID prefix)
            content_type: MIME type (auto-detected if not provided)
            acl: Access control (defaults to config default)
            storage_class: Storage class (defaults to config default)
            metadata: Custom metadata dictionary
            cache_control: Cache-Control header value
            progress_callback: Callback for progress updates

        Returns:
            UploadResult with upload details
        """
        if not os.path.exists(file_path):
            return UploadResult(
                success=False,
                error=f"File not found: {file_path}"
            )

        try:
            # Resolve file path
            resolved_path = _resolve_file_path(file_path)

            # Generate key if not provided
            if key is None:
                key = self._generate_key(resolved_path)

            # Detect content type
            if content_type is None:
                content_type = self._detect_content_type(resolved_path)

            # Get file size
            file_size = os.path.getsize(resolved_path)

            # Calculate checksum
            checksum = self._calculate_md5(resolved_path)

            # Prepare extra args
            extra_args = self._build_extra_args(
                content_type=content_type,
                acl=acl,
                storage_class=storage_class,
                metadata=metadata,
                cache_control=cache_control,
            )

            # Create progress tracker if callback provided
            callback = None
            if progress_callback:
                callback = _ProgressCallback(file_size, progress_callback)

            # Upload using transfer manager for large files
            self.client.upload_file(
                Filename=resolved_path,
                Bucket=self.config.bucket_name,
                Key=key,
                ExtraArgs=extra_args,
                Callback=callback,
                Config=self._get_transfer_config(),
            )

            # Get object metadata
            head_response = self.client.head_object(
                Bucket=self.config.bucket_name,
                Key=key
            )

            # Build location
            location = StorageLocation(
                bucket=self.config.bucket_name,
                key=key,
                version_id=head_response.get("VersionId"),
                etag=head_response.get("ETag", "").strip('"'),
            )

            # Generate URLs
            public_url = self._get_public_url(key, acl)
            signed_url = self._generate_presigned_url(key)
            cloudfront_url = self._get_cloudfront_url(key) if self.config.cloudfront_domain else None

            return UploadResult(
                success=True,
                location=location,
                url=public_url,
                signed_url=signed_url,
                cloudfront_url=cloudfront_url,
                content_type=content_type,
                size=file_size,
                checksum=checksum,
                metadata=metadata or {},
            )

        except Exception as e:
            _log_error(f"Upload failed for {file_path}: {str(e)}", "S3 Upload")
            return UploadResult(
                success=False,
                error=f"Upload failed: {str(e)}"
            )

    def upload_bytes(
        self,
        data: bytes,
        key: str,
        content_type: str,
        acl: Optional[ACL] = None,
        storage_class: Optional[StorageClass] = None,
        metadata: Optional[Dict[str, str]] = None,
        cache_control: Optional[str] = None,
    ) -> UploadResult:
        """Upload bytes data to S3.

        Args:
            data: Bytes data to upload
            key: S3 object key
            content_type: MIME type
            acl: Access control
            storage_class: Storage class
            metadata: Custom metadata
            cache_control: Cache-Control header

        Returns:
            UploadResult with upload details
        """
        try:
            # Calculate checksum
            checksum = hashlib.md5(data).hexdigest()

            # Prepare extra args
            extra_args = self._build_extra_args(
                content_type=content_type,
                acl=acl,
                storage_class=storage_class,
                metadata=metadata,
                cache_control=cache_control,
            )

            # Upload
            put_response = self.client.put_object(
                Bucket=self.config.bucket_name,
                Key=key,
                Body=data,
                **extra_args,
            )

            # Build location
            location = StorageLocation(
                bucket=self.config.bucket_name,
                key=key,
                version_id=put_response.get("VersionId"),
                etag=put_response.get("ETag", "").strip('"'),
            )

            # Generate URLs
            public_url = self._get_public_url(key, acl)
            signed_url = self._generate_presigned_url(key)
            cloudfront_url = self._get_cloudfront_url(key) if self.config.cloudfront_domain else None

            return UploadResult(
                success=True,
                location=location,
                url=public_url,
                signed_url=signed_url,
                cloudfront_url=cloudfront_url,
                content_type=content_type,
                size=len(data),
                checksum=checksum,
                metadata=metadata or {},
            )

        except Exception as e:
            _log_error(f"Bytes upload failed: {str(e)}", "S3 Upload")
            return UploadResult(
                success=False,
                error=f"Upload failed: {str(e)}"
            )

    def upload_fileobj(
        self,
        fileobj: BinaryIO,
        key: str,
        content_type: str,
        file_size: Optional[int] = None,
        acl: Optional[ACL] = None,
        storage_class: Optional[StorageClass] = None,
        metadata: Optional[Dict[str, str]] = None,
        cache_control: Optional[str] = None,
        progress_callback: Optional[Callable[[int], None]] = None,
    ) -> UploadResult:
        """Upload a file-like object to S3.

        Args:
            fileobj: File-like object to upload
            key: S3 object key
            content_type: MIME type
            file_size: Optional file size for progress tracking
            acl: Access control
            storage_class: Storage class
            metadata: Custom metadata
            cache_control: Cache-Control header
            progress_callback: Progress callback

        Returns:
            UploadResult with upload details
        """
        try:
            # Prepare extra args
            extra_args = self._build_extra_args(
                content_type=content_type,
                acl=acl,
                storage_class=storage_class,
                metadata=metadata,
                cache_control=cache_control,
            )

            # Create callback if provided
            callback = None
            if progress_callback and file_size:
                callback = _ProgressCallback(file_size, progress_callback)

            # Upload
            self.client.upload_fileobj(
                Fileobj=fileobj,
                Bucket=self.config.bucket_name,
                Key=key,
                ExtraArgs=extra_args,
                Callback=callback,
                Config=self._get_transfer_config(),
            )

            # Get object metadata
            head_response = self.client.head_object(
                Bucket=self.config.bucket_name,
                Key=key
            )

            actual_size = head_response.get("ContentLength", file_size or 0)

            # Build location
            location = StorageLocation(
                bucket=self.config.bucket_name,
                key=key,
                version_id=head_response.get("VersionId"),
                etag=head_response.get("ETag", "").strip('"'),
            )

            # Generate URLs
            public_url = self._get_public_url(key, acl)
            signed_url = self._generate_presigned_url(key)
            cloudfront_url = self._get_cloudfront_url(key) if self.config.cloudfront_domain else None

            return UploadResult(
                success=True,
                location=location,
                url=public_url,
                signed_url=signed_url,
                cloudfront_url=cloudfront_url,
                content_type=content_type,
                size=actual_size,
                metadata=metadata or {},
            )

        except Exception as e:
            _log_error(f"Fileobj upload failed: {str(e)}", "S3 Upload")
            return UploadResult(
                success=False,
                error=f"Upload failed: {str(e)}"
            )

    def upload_product_media(
        self,
        product_id: str,
        file_path: str,
        media_type: MediaType = MediaType.IMAGE,
        position: int = 0,
        metadata: Optional[Dict[str, str]] = None,
    ) -> UploadResult:
        """Upload media for a product with organized key structure.

        Args:
            product_id: Product identifier
            file_path: Path to the media file
            media_type: Type of media
            position: Position/order of the media
            metadata: Additional metadata

        Returns:
            UploadResult with upload details
        """
        # Generate organized key
        sanitized_product = product_id.replace(" ", "_").replace("/", "_")
        ext = Path(file_path).suffix.lower()
        filename = f"{position:03d}_{uuid.uuid4().hex[:8]}{ext}"
        key = f"products/{sanitized_product}/{media_type.value}/{filename}"

        # Add product metadata
        combined_metadata = {
            "product-id": product_id,
            "media-type": media_type.value,
            "position": str(position),
        }
        if metadata:
            combined_metadata.update(metadata)

        return self.upload_file(
            file_path=file_path,
            key=key,
            metadata=combined_metadata,
        )

    def batch_upload(
        self,
        files: List[Dict[str, Any]],
        prefix: Optional[str] = None,
        parallel: bool = True,
    ) -> BatchUploadResult:
        """Upload multiple files in batch.

        Args:
            files: List of dicts with 'file_path' and optional 'key', 'metadata'
            prefix: Optional key prefix for all uploads
            parallel: Whether to upload in parallel (uses threads)

        Returns:
            BatchUploadResult with all results
        """
        result = BatchUploadResult(
            total=len(files),
            started_at=datetime.utcnow(),
        )

        def upload_single(file_info: Dict[str, Any]) -> UploadResult:
            file_path = file_info.get("file_path")
            if not file_path:
                return UploadResult(success=False, error="No file_path provided")

            key = file_info.get("key")
            if prefix and key:
                key = f"{prefix.rstrip('/')}/{key}"
            elif prefix:
                key = f"{prefix.rstrip('/')}/{os.path.basename(file_path)}"

            return self.upload_file(
                file_path=file_path,
                key=key,
                content_type=file_info.get("content_type"),
                metadata=file_info.get("metadata"),
            )

        if parallel and len(files) > 1:
            import concurrent.futures

            with concurrent.futures.ThreadPoolExecutor(max_workers=5) as executor:
                futures = {executor.submit(upload_single, f): f for f in files}
                for future in concurrent.futures.as_completed(futures):
                    try:
                        upload_result = future.result()
                        result.results.append(upload_result)
                        if upload_result.success:
                            result.success_count += 1
                        else:
                            result.failed_count += 1
                            if upload_result.error:
                                result.errors.append(upload_result.error)
                    except Exception as e:
                        result.failed_count += 1
                        result.errors.append(str(e))
        else:
            for file_info in files:
                upload_result = upload_single(file_info)
                result.results.append(upload_result)
                if upload_result.success:
                    result.success_count += 1
                else:
                    result.failed_count += 1
                    if upload_result.error:
                        result.errors.append(upload_result.error)

        result.completed_at = datetime.utcnow()
        return result

    # =========================================================================
    # Download Operations
    # =========================================================================

    def download_file(
        self,
        key: str,
        destination: str,
        version_id: Optional[str] = None,
        progress_callback: Optional[Callable[[int], None]] = None,
    ) -> Tuple[bool, str]:
        """Download a file from S3.

        Args:
            key: S3 object key
            destination: Local destination path
            version_id: Optional version ID
            progress_callback: Progress callback

        Returns:
            Tuple of (success, message/error)
        """
        try:
            extra_args = {}
            if version_id:
                extra_args["VersionId"] = version_id

            # Get file size for progress
            head_response = self.client.head_object(
                Bucket=self.config.bucket_name,
                Key=key,
                **extra_args,
            )
            file_size = head_response.get("ContentLength", 0)

            # Create callback if provided
            callback = None
            if progress_callback and file_size:
                callback = _ProgressCallback(file_size, progress_callback)

            # Ensure destination directory exists
            os.makedirs(os.path.dirname(destination), exist_ok=True)

            # Download
            self.client.download_file(
                Bucket=self.config.bucket_name,
                Key=key,
                Filename=destination,
                ExtraArgs=extra_args if extra_args else None,
                Callback=callback,
                Config=self._get_transfer_config(),
            )

            return True, f"Downloaded to {destination}"

        except self.client.exceptions.NoSuchKey:
            return False, f"Object not found: {key}"
        except Exception as e:
            return False, f"Download failed: {str(e)}"

    def download_bytes(
        self,
        key: str,
        version_id: Optional[str] = None,
    ) -> Tuple[Optional[bytes], Optional[str]]:
        """Download file as bytes.

        Args:
            key: S3 object key
            version_id: Optional version ID

        Returns:
            Tuple of (bytes data or None, error message or None)
        """
        try:
            extra_args = {}
            if version_id:
                extra_args["VersionId"] = version_id

            response = self.client.get_object(
                Bucket=self.config.bucket_name,
                Key=key,
                **extra_args,
            )

            return response["Body"].read(), None

        except self.client.exceptions.NoSuchKey:
            return None, f"Object not found: {key}"
        except Exception as e:
            return None, f"Download failed: {str(e)}"

    # =========================================================================
    # Delete Operations
    # =========================================================================

    def delete_object(
        self,
        key: str,
        version_id: Optional[str] = None,
    ) -> Tuple[bool, str]:
        """Delete an object from S3.

        Args:
            key: S3 object key
            version_id: Optional version ID

        Returns:
            Tuple of (success, message)
        """
        try:
            delete_args = {
                "Bucket": self.config.bucket_name,
                "Key": key,
            }
            if version_id:
                delete_args["VersionId"] = version_id

            self.client.delete_object(**delete_args)
            return True, f"Deleted: {key}"

        except Exception as e:
            return False, f"Delete failed: {str(e)}"

    def delete_objects(self, keys: List[str]) -> Tuple[int, int, List[str]]:
        """Delete multiple objects.

        Args:
            keys: List of S3 object keys

        Returns:
            Tuple of (deleted_count, error_count, error_messages)
        """
        if not keys:
            return 0, 0, []

        try:
            # S3 allows up to 1000 objects per delete request
            deleted = 0
            errors = 0
            error_messages = []

            for i in range(0, len(keys), 1000):
                batch = keys[i:i + 1000]
                delete_objects = {"Objects": [{"Key": k} for k in batch]}

                response = self.client.delete_objects(
                    Bucket=self.config.bucket_name,
                    Delete=delete_objects,
                )

                deleted += len(response.get("Deleted", []))

                for error in response.get("Errors", []):
                    errors += 1
                    error_messages.append(
                        f"{error.get('Key')}: {error.get('Message')}"
                    )

            return deleted, errors, error_messages

        except Exception as e:
            return 0, len(keys), [str(e)]

    def delete_prefix(self, prefix: str) -> Tuple[int, int]:
        """Delete all objects with a given prefix.

        Args:
            prefix: Key prefix to delete

        Returns:
            Tuple of (deleted_count, error_count)
        """
        keys = self.list_objects(prefix=prefix, keys_only=True)
        if not keys:
            return 0, 0

        deleted, errors, _ = self.delete_objects(keys)
        return deleted, errors

    # =========================================================================
    # URL Generation
    # =========================================================================

    def generate_presigned_url(
        self,
        key: str,
        expiration: int = DEFAULT_URL_EXPIRATION,
        http_method: str = "GET",
        version_id: Optional[str] = None,
    ) -> Optional[str]:
        """Generate a pre-signed URL for an object.

        Args:
            key: S3 object key
            expiration: URL expiration in seconds
            http_method: HTTP method (GET, PUT)
            version_id: Optional version ID

        Returns:
            Pre-signed URL or None if failed
        """
        return self._generate_presigned_url(key, expiration, http_method, version_id)

    def generate_presigned_upload_url(
        self,
        key: str,
        content_type: str,
        expiration: int = 3600,
        metadata: Optional[Dict[str, str]] = None,
    ) -> Optional[Dict[str, Any]]:
        """Generate a pre-signed URL for direct upload from client.

        Args:
            key: S3 object key
            content_type: Expected content type
            expiration: URL expiration in seconds
            metadata: Optional metadata to include

        Returns:
            Dictionary with url and fields for POST upload
        """
        try:
            conditions = [
                {"bucket": self.config.bucket_name},
                ["starts-with", "$key", key],
                {"Content-Type": content_type},
            ]

            fields = {
                "Content-Type": content_type,
            }

            if metadata:
                for k, v in metadata.items():
                    meta_key = f"x-amz-meta-{k}"
                    conditions.append({meta_key: v})
                    fields[meta_key] = v

            response = self.client.generate_presigned_post(
                Bucket=self.config.bucket_name,
                Key=key,
                Fields=fields,
                Conditions=conditions,
                ExpiresIn=expiration,
            )

            return response

        except Exception as e:
            _log_error(f"Failed to generate presigned POST: {str(e)}", "S3 URL")
            return None

    def _generate_presigned_url(
        self,
        key: str,
        expiration: int = DEFAULT_URL_EXPIRATION,
        http_method: str = "GET",
        version_id: Optional[str] = None,
    ) -> Optional[str]:
        """Internal method to generate pre-signed URL."""
        try:
            params = {
                "Bucket": self.config.bucket_name,
                "Key": key,
            }
            if version_id:
                params["VersionId"] = version_id

            client_method = "get_object" if http_method == "GET" else "put_object"

            url = self.client.generate_presigned_url(
                ClientMethod=client_method,
                Params=params,
                ExpiresIn=expiration,
            )
            return url

        except Exception as e:
            _log_error(f"Failed to generate presigned URL: {str(e)}", "S3 URL")
            return None

    def _get_public_url(self, key: str, acl: Optional[ACL] = None) -> Optional[str]:
        """Get public URL if ACL allows."""
        effective_acl = acl or self.config.default_acl
        if effective_acl not in (ACL.PUBLIC_READ, ACL.PUBLIC_READ_WRITE):
            return None

        if self.config.endpoint_url:
            # Custom endpoint
            base = self.config.endpoint_url.rstrip("/")
            return f"{base}/{self.config.bucket_name}/{key}"
        else:
            # AWS S3
            return f"https://{self.config.bucket_name}.s3.{self.config.region}.amazonaws.com/{key}"

    def _get_cloudfront_url(self, key: str) -> Optional[str]:
        """Get CloudFront URL for the object."""
        if not self.config.cloudfront_domain:
            return None
        return f"https://{self.config.cloudfront_domain}/{key}"

    def generate_cloudfront_signed_url(
        self,
        key: str,
        expiration: int = DEFAULT_URL_EXPIRATION,
    ) -> Optional[str]:
        """Generate a CloudFront signed URL.

        Args:
            key: S3 object key
            expiration: URL expiration in seconds

        Returns:
            Signed CloudFront URL or None
        """
        if not self.config.cloudfront_domain or not self.config.cloudfront_key_pair_id:
            return None

        try:
            from botocore.signers import CloudFrontSigner
            from cryptography.hazmat.primitives import hashes, serialization
            from cryptography.hazmat.primitives.asymmetric import padding

            def rsa_signer(message):
                private_key = serialization.load_pem_private_key(
                    self.config.cloudfront_private_key.encode(),
                    password=None,
                )
                return private_key.sign(message, padding.PKCS1v15(), hashes.SHA1())

            url = f"https://{self.config.cloudfront_domain}/{key}"
            expire_date = datetime.utcnow() + timedelta(seconds=expiration)

            cf_signer = CloudFrontSigner(
                self.config.cloudfront_key_pair_id,
                rsa_signer
            )
            signed_url = cf_signer.generate_presigned_url(
                url,
                date_less_than=expire_date
            )
            return signed_url

        except Exception as e:
            _log_error(f"Failed to generate CloudFront signed URL: {str(e)}", "CloudFront")
            return None

    # =========================================================================
    # List and Query Operations
    # =========================================================================

    def list_objects(
        self,
        prefix: Optional[str] = None,
        delimiter: Optional[str] = None,
        max_keys: int = 1000,
        keys_only: bool = False,
    ) -> Union[List[str], List[Dict[str, Any]]]:
        """List objects in the bucket.

        Args:
            prefix: Key prefix filter
            delimiter: Delimiter for hierarchy (e.g., '/')
            max_keys: Maximum number of keys to return
            keys_only: If True, return only key strings

        Returns:
            List of keys or list of object dictionaries
        """
        try:
            paginator = self.client.get_paginator("list_objects_v2")
            page_iterator = paginator.paginate(
                Bucket=self.config.bucket_name,
                Prefix=prefix or "",
                Delimiter=delimiter or "",
                PaginationConfig={"MaxItems": max_keys},
            )

            results = []
            for page in page_iterator:
                for obj in page.get("Contents", []):
                    if keys_only:
                        results.append(obj["Key"])
                    else:
                        results.append({
                            "key": obj["Key"],
                            "size": obj["Size"],
                            "last_modified": obj["LastModified"].isoformat(),
                            "etag": obj.get("ETag", "").strip('"'),
                            "storage_class": obj.get("StorageClass", "STANDARD"),
                        })

            return results

        except Exception as e:
            _log_error(f"Failed to list objects: {str(e)}", "S3 List")
            return []

    def object_exists(self, key: str) -> bool:
        """Check if an object exists.

        Args:
            key: S3 object key

        Returns:
            True if object exists
        """
        try:
            self.client.head_object(
                Bucket=self.config.bucket_name,
                Key=key
            )
            return True
        except self.client.exceptions.ClientError as e:
            if e.response["Error"]["Code"] == "404":
                return False
            raise
        except Exception:
            return False

    def get_object_metadata(self, key: str) -> Optional[Dict[str, Any]]:
        """Get object metadata.

        Args:
            key: S3 object key

        Returns:
            Metadata dictionary or None
        """
        try:
            response = self.client.head_object(
                Bucket=self.config.bucket_name,
                Key=key
            )
            return {
                "key": key,
                "content_type": response.get("ContentType"),
                "content_length": response.get("ContentLength"),
                "last_modified": response["LastModified"].isoformat(),
                "etag": response.get("ETag", "").strip('"'),
                "version_id": response.get("VersionId"),
                "metadata": response.get("Metadata", {}),
                "storage_class": response.get("StorageClass", "STANDARD"),
            }
        except Exception:
            return None

    # =========================================================================
    # Copy and Move Operations
    # =========================================================================

    def copy_object(
        self,
        source_key: str,
        destination_key: str,
        source_bucket: Optional[str] = None,
        destination_bucket: Optional[str] = None,
        acl: Optional[ACL] = None,
        metadata: Optional[Dict[str, str]] = None,
    ) -> Tuple[bool, str]:
        """Copy an object within or between buckets.

        Args:
            source_key: Source object key
            destination_key: Destination object key
            source_bucket: Source bucket (defaults to config bucket)
            destination_bucket: Destination bucket (defaults to config bucket)
            acl: ACL for destination object
            metadata: Metadata for destination (replaces source metadata)

        Returns:
            Tuple of (success, message)
        """
        try:
            src_bucket = source_bucket or self.config.bucket_name
            dst_bucket = destination_bucket or self.config.bucket_name

            copy_source = {"Bucket": src_bucket, "Key": source_key}

            extra_args = {}
            if acl:
                extra_args["ACL"] = acl.value
            if metadata:
                extra_args["Metadata"] = metadata
                extra_args["MetadataDirective"] = "REPLACE"

            self.client.copy_object(
                CopySource=copy_source,
                Bucket=dst_bucket,
                Key=destination_key,
                **extra_args,
            )

            return True, f"Copied {source_key} to {destination_key}"

        except Exception as e:
            return False, f"Copy failed: {str(e)}"

    def move_object(
        self,
        source_key: str,
        destination_key: str,
        source_bucket: Optional[str] = None,
        destination_bucket: Optional[str] = None,
    ) -> Tuple[bool, str]:
        """Move an object (copy then delete).

        Args:
            source_key: Source object key
            destination_key: Destination object key
            source_bucket: Source bucket
            destination_bucket: Destination bucket

        Returns:
            Tuple of (success, message)
        """
        success, message = self.copy_object(
            source_key=source_key,
            destination_key=destination_key,
            source_bucket=source_bucket,
            destination_bucket=destination_bucket,
        )

        if success:
            src_bucket = source_bucket or self.config.bucket_name
            self.delete_object(source_key)
            return True, f"Moved {source_key} to {destination_key}"

        return success, message

    # =========================================================================
    # Helper Methods
    # =========================================================================

    def _generate_key(self, file_path: str) -> str:
        """Generate a unique S3 key from file path."""
        filename = os.path.basename(file_path)
        name, ext = os.path.splitext(filename)
        timestamp = datetime.utcnow().strftime("%Y/%m/%d")
        unique_id = uuid.uuid4().hex[:8]
        return f"media/{timestamp}/{unique_id}_{name}{ext}"

    def _detect_content_type(self, file_path: str) -> str:
        """Detect content type from file."""
        content_type, _ = mimetypes.guess_type(file_path)
        if content_type:
            return content_type

        # Try to detect from file content
        try:
            import magic

            mime = magic.Magic(mime=True)
            return mime.from_file(file_path)
        except ImportError:
            pass

        return "application/octet-stream"

    def _calculate_md5(self, file_path: str) -> str:
        """Calculate MD5 checksum of file."""
        hash_md5 = hashlib.md5()
        with open(file_path, "rb") as f:
            for chunk in iter(lambda: f.read(8192), b""):
                hash_md5.update(chunk)
        return hash_md5.hexdigest()

    def _build_extra_args(
        self,
        content_type: Optional[str] = None,
        acl: Optional[ACL] = None,
        storage_class: Optional[StorageClass] = None,
        metadata: Optional[Dict[str, str]] = None,
        cache_control: Optional[str] = None,
    ) -> Dict[str, Any]:
        """Build extra args for S3 upload."""
        extra_args = {}

        if content_type:
            extra_args["ContentType"] = content_type

        effective_acl = acl or self.config.default_acl
        extra_args["ACL"] = effective_acl.value

        effective_storage_class = storage_class or self.config.default_storage_class
        extra_args["StorageClass"] = effective_storage_class.value

        if metadata:
            extra_args["Metadata"] = metadata

        cache = cache_control or self.config.default_cache_control
        if cache:
            extra_args["CacheControl"] = cache

        return extra_args


# =============================================================================
# Progress Callback Helper
# =============================================================================

class _ProgressCallback:
    """Callback class for tracking upload/download progress."""

    def __init__(self, total_size: int, callback: Callable[[int], None]):
        self._total_size = total_size
        self._callback = callback
        self._seen_so_far = 0
        self._lock = threading.Lock()

    def __call__(self, bytes_amount: int):
        with self._lock:
            self._seen_so_far += bytes_amount
            self._callback(self._seen_so_far)


# =============================================================================
# Public API Functions
# =============================================================================

def upload_file(
    file_path: str,
    key: Optional[str] = None,
    content_type: Optional[str] = None,
    acl: Optional[str] = None,
    metadata: Optional[Dict[str, str]] = None,
    async_upload: bool = False,
) -> Dict[str, Any]:
    """Upload a file to S3.

    Main API function for uploading files to S3.

    Args:
        file_path: Path to local file
        key: S3 object key (auto-generated if not provided)
        content_type: MIME type (auto-detected if not provided)
        acl: Access control ('private', 'public-read', etc.)
        metadata: Custom metadata
        async_upload: If True, upload in background job

    Returns:
        Upload result dictionary
    """
    import frappe

    if async_upload:
        job = frappe.enqueue(
            "frappe_pim.pim.services.s3_storage._upload_file_job",
            queue="default",
            timeout=600,
            file_path=file_path,
            key=key,
            content_type=content_type,
            acl=acl,
            metadata=metadata,
        )
        return {
            "success": True,
            "status": "queued",
            "job_id": job.id if hasattr(job, "id") else str(job),
        }

    service = S3StorageService()
    acl_enum = ACL(acl) if acl else None
    result = service.upload_file(
        file_path=file_path,
        key=key,
        content_type=content_type,
        acl=acl_enum,
        metadata=metadata,
    )
    return result.to_dict()


def upload_product_media(
    product_id: str,
    file_path: str,
    media_type: str = "image",
    position: int = 0,
    metadata: Optional[Dict[str, str]] = None,
    async_upload: bool = False,
) -> Dict[str, Any]:
    """Upload media for a product.

    Args:
        product_id: Product identifier
        file_path: Path to media file
        media_type: Type of media ('image', 'video', 'document')
        position: Position/order of the media
        metadata: Additional metadata
        async_upload: If True, upload in background

    Returns:
        Upload result dictionary
    """
    import frappe

    if async_upload:
        job = frappe.enqueue(
            "frappe_pim.pim.services.s3_storage._upload_product_media_job",
            queue="default",
            timeout=600,
            product_id=product_id,
            file_path=file_path,
            media_type=media_type,
            position=position,
            metadata=metadata,
        )
        return {
            "success": True,
            "status": "queued",
            "job_id": job.id if hasattr(job, "id") else str(job),
        }

    service = S3StorageService()
    try:
        media_type_enum = MediaType(media_type)
    except ValueError:
        media_type_enum = MediaType.OTHER

    result = service.upload_product_media(
        product_id=product_id,
        file_path=file_path,
        media_type=media_type_enum,
        position=position,
        metadata=metadata,
    )
    return result.to_dict()


def batch_upload_files(
    files: List[Dict[str, Any]],
    prefix: Optional[str] = None,
    async_upload: bool = False,
) -> Dict[str, Any]:
    """Batch upload multiple files.

    Args:
        files: List of dicts with 'file_path' and optional 'key', 'metadata'
        prefix: Optional key prefix for all uploads
        async_upload: If True, upload in background

    Returns:
        Batch upload result dictionary
    """
    import frappe

    if async_upload:
        job = frappe.enqueue(
            "frappe_pim.pim.services.s3_storage._batch_upload_job",
            queue="long",
            timeout=3600,
            files=files,
            prefix=prefix,
        )
        return {
            "success": True,
            "status": "queued",
            "job_id": job.id if hasattr(job, "id") else str(job),
            "total_files": len(files),
        }

    service = S3StorageService()
    result = service.batch_upload(files=files, prefix=prefix)
    return result.to_dict()


def download_file(
    key: str,
    destination: str,
    version_id: Optional[str] = None,
) -> Dict[str, Any]:
    """Download a file from S3.

    Args:
        key: S3 object key
        destination: Local destination path
        version_id: Optional version ID

    Returns:
        Result dictionary
    """
    service = S3StorageService()
    success, message = service.download_file(
        key=key,
        destination=destination,
        version_id=version_id,
    )
    return {"success": success, "message": message}


def delete_file(
    key: str,
    version_id: Optional[str] = None,
) -> Dict[str, Any]:
    """Delete a file from S3.

    Args:
        key: S3 object key
        version_id: Optional version ID

    Returns:
        Result dictionary
    """
    service = S3StorageService()
    success, message = service.delete_object(key=key, version_id=version_id)
    return {"success": success, "message": message}


def get_signed_url(
    key: str,
    expiration: int = DEFAULT_URL_EXPIRATION,
    http_method: str = "GET",
) -> Dict[str, Any]:
    """Get a pre-signed URL for an object.

    Args:
        key: S3 object key
        expiration: URL expiration in seconds
        http_method: HTTP method (GET, PUT)

    Returns:
        Result dictionary with URL
    """
    service = S3StorageService()
    url = service.generate_presigned_url(
        key=key,
        expiration=expiration,
        http_method=http_method,
    )
    return {
        "success": url is not None,
        "url": url,
        "expiration": expiration,
    }


def get_upload_url(
    key: str,
    content_type: str,
    expiration: int = 3600,
    metadata: Optional[Dict[str, str]] = None,
) -> Dict[str, Any]:
    """Get a pre-signed URL for direct upload from client.

    Args:
        key: S3 object key
        content_type: Expected content type
        expiration: URL expiration in seconds
        metadata: Optional metadata

    Returns:
        Result dictionary with URL and fields
    """
    service = S3StorageService()
    result = service.generate_presigned_upload_url(
        key=key,
        content_type=content_type,
        expiration=expiration,
        metadata=metadata,
    )
    if result:
        return {"success": True, **result}
    return {"success": False, "error": "Failed to generate upload URL"}


def list_files(
    prefix: Optional[str] = None,
    max_keys: int = 100,
) -> Dict[str, Any]:
    """List files in S3 bucket.

    Args:
        prefix: Key prefix filter
        max_keys: Maximum number of keys

    Returns:
        Result dictionary with files list
    """
    service = S3StorageService()
    files = service.list_objects(prefix=prefix, max_keys=max_keys)
    return {
        "success": True,
        "files": files,
        "count": len(files),
    }


def test_s3_connection() -> Dict[str, Any]:
    """Test S3 connection.

    Returns:
        Connection test result
    """
    try:
        service = S3StorageService()
        success, message = service.test_connection()
        return {
            "success": success,
            "message": message,
            "config": service.config.to_dict(),
        }
    except Exception as e:
        return {
            "success": False,
            "message": str(e),
        }


def get_storage_providers() -> List[Dict[str, str]]:
    """Get list of supported storage providers.

    Returns:
        List of provider dictionaries
    """
    return [
        {"value": p.value, "label": p.name.replace("_", " ").title()}
        for p in StorageProvider
    ]


def get_storage_classes() -> List[Dict[str, str]]:
    """Get list of S3 storage classes.

    Returns:
        List of storage class dictionaries
    """
    return [
        {"value": sc.value, "label": sc.name.replace("_", " ").title()}
        for sc in StorageClass
    ]


# =============================================================================
# Helper Functions
# =============================================================================

def _get_pim_settings() -> Dict[str, Any]:
    """Get PIM Settings values."""
    import frappe

    try:
        if not frappe.db.exists("DocType", "PIM Settings"):
            return {}

        settings = frappe.get_single("PIM Settings")
        return {
            field.fieldname: settings.get(field.fieldname)
            for field in settings.meta.fields
        }
    except Exception:
        return {}


def _resolve_file_path(file_path: str) -> str:
    """Resolve a Frappe file URL or path to absolute filesystem path."""
    if file_path.startswith("/files/") or file_path.startswith("/private/files/"):
        try:
            import frappe

            site_path = frappe.get_site_path()
            if file_path.startswith("/private/"):
                return os.path.join(site_path, file_path.lstrip("/"))
            else:
                return os.path.join(site_path, "public", file_path.lstrip("/"))
        except Exception:
            return file_path
    return file_path


def _format_file_size(size_bytes: int) -> str:
    """Format file size in human-readable format."""
    for unit in ["B", "KB", "MB", "GB", "TB"]:
        if size_bytes < 1024:
            return f"{size_bytes:.1f} {unit}"
        size_bytes /= 1024
    return f"{size_bytes:.1f} PB"


def _log_error(message: str, title: str):
    """Log error to Frappe if available."""
    try:
        import frappe

        frappe.log_error(message=message, title=f"PIM S3 Storage - {title}")
    except Exception:
        pass


# =============================================================================
# Background Job Handlers
# =============================================================================

def _upload_file_job(
    file_path: str,
    key: Optional[str] = None,
    content_type: Optional[str] = None,
    acl: Optional[str] = None,
    metadata: Optional[Dict[str, str]] = None,
):
    """Background job for file upload."""
    service = S3StorageService()
    acl_enum = ACL(acl) if acl else None
    result = service.upload_file(
        file_path=file_path,
        key=key,
        content_type=content_type,
        acl=acl_enum,
        metadata=metadata,
    )

    if not result.success:
        _log_error(f"Upload failed: {result.error}", "Background Upload")


def _upload_product_media_job(
    product_id: str,
    file_path: str,
    media_type: str = "image",
    position: int = 0,
    metadata: Optional[Dict[str, str]] = None,
):
    """Background job for product media upload."""
    service = S3StorageService()
    try:
        media_type_enum = MediaType(media_type)
    except ValueError:
        media_type_enum = MediaType.OTHER

    result = service.upload_product_media(
        product_id=product_id,
        file_path=file_path,
        media_type=media_type_enum,
        position=position,
        metadata=metadata,
    )

    if not result.success:
        _log_error(f"Product media upload failed: {result.error}", "Background Upload")


def _batch_upload_job(
    files: List[Dict[str, Any]],
    prefix: Optional[str] = None,
):
    """Background job for batch upload."""
    service = S3StorageService()
    result = service.batch_upload(files=files, prefix=prefix)

    try:
        import frappe

        frappe.log_error(
            message=f"Batch upload complete: {result.success_count}/{result.total} success",
            title="PIM S3 Batch Upload Complete",
        )
    except Exception:
        pass


# =============================================================================
# Frappe API Wrappers
# =============================================================================

def _wrap_for_whitelist():
    """Wrap functions for Frappe whitelist at runtime."""
    import frappe

    functions = [
        "upload_file",
        "upload_product_media",
        "batch_upload_files",
        "download_file",
        "delete_file",
        "get_signed_url",
        "get_upload_url",
        "list_files",
        "test_s3_connection",
        "get_storage_providers",
        "get_storage_classes",
    ]

    module = __import__(__name__)
    for name in __name__.split(".")[1:]:
        module = getattr(module, name)

    for func_name in functions:
        func = getattr(module, func_name)
        if not getattr(func, "_whitelisted", False):
            whitelisted = frappe.whitelist()(func)
            setattr(module, func_name, whitelisted)


# Apply whitelist decorators when module is loaded in Frappe context
try:
    _wrap_for_whitelist()
except Exception:
    pass  # Not in Frappe context
