"""
storage.py - Everything to do with storing videos in AWS S3.

Remember the plan: video files are large, so they NEVER pass through our
backend. Instead:
  1. The backend creates a PRESIGNED URL: a temporary link that allows exactly
     one upload, of one specific file type and size, to one specific place.
  2. The browser uploads the video straight to S3 using that link.
  3. The browser tells the backend "done", and the backend checks S3 to make
     sure the file really arrived and matches what was approved.

Playback works the same way in reverse: a presigned GET URL lets the browser
stream one private video for a limited time.

Keeping all of this in one file means the rest of the app never touches
boto3 directly, and the tests can swap in a fake S3 (moto) easily.
"""

from dataclasses import dataclass

import boto3
from botocore.config import Config
from botocore.exceptions import ClientError
from fastapi import Request

from app.config import Settings


@dataclass
class UploadedFileInfo:
    size_bytes: int
    content_type: str


class VideoStorage:
    def __init__(self, settings: Settings):
        self.settings = settings
        self.bucket = settings.s3_videos_bucket
        # boto3 finds the access keys by itself (environment variables in dev,
        # an IAM role on AWS). We only tell it the region and two details:
        #   - signature_version="s3v4": the modern, required signing method.
        #   - addressing_style="virtual": produce links like
        #     https://BUCKET.s3.eu-north-1.amazonaws.com/... (the bucket's own
        #     regional address). Older-style links can be temporarily redirected
        #     for new buckets outside the US, and browsers refuse to follow
        #     redirects during an upload.
        self.client = boto3.client(
            "s3",
            region_name=settings.aws_region,
            config=Config(signature_version="s3v4", s3={"addressing_style": "virtual"}),
        )

    @property
    def is_configured(self) -> bool:
        return bool(self.bucket)

    def presign_upload(self, key: str, content_type: str, size_bytes: int) -> str:
        """
        A link that allows uploading ONE file to `key`. Because ContentType and
        ContentLength are included, they become part of the signature: S3 will
        reject the upload if the browser sends a different type or size. That
        stops anyone from using the link to upload a huge or unexpected file.
        """
        return self.client.generate_presigned_url(
            "put_object",
            Params={
                "Bucket": self.bucket,
                "Key": key,
                "ContentType": content_type,
                "ContentLength": size_bytes,
            },
            ExpiresIn=self.settings.upload_url_expiry_seconds,
        )

    def presign_download(self, key: str) -> str:
        """A temporary link for watching one private video."""
        return self.client.generate_presigned_url(
            "get_object",
            Params={"Bucket": self.bucket, "Key": key},
            ExpiresIn=self.settings.video_url_expiry_seconds,
        )

    def get_uploaded_file_info(self, key: str) -> UploadedFileInfo | None:
        """
        Ask S3 about a file without downloading it (a "HEAD" request).
        Returns None if it isn't there.

        Note: without "list" permission on the bucket, S3 answers 403 Forbidden
        (not 404 Not Found) for missing files, so it can't reveal which files
        exist. We treat both the same way: "not uploaded".
        """
        try:
            response = self.client.head_object(Bucket=self.bucket, Key=key)
        except ClientError as error:
            if error.response["Error"]["Code"] in ("404", "403", "NoSuchKey", "NotFound"):
                return None
            raise
        return UploadedFileInfo(
            size_bytes=response["ContentLength"],
            content_type=response.get("ContentType", ""),
        )

    def delete(self, key: str) -> None:
        self.client.delete_object(Bucket=self.bucket, Key=key)


def get_storage(request: Request) -> VideoStorage:
    """FastAPI dependency: the VideoStorage created at startup (see main.py)."""
    return request.app.state.storage
