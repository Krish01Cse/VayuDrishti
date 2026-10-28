#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
infrastructure/setup_s3_bucket.py — Provision and configure VayuDrishti S3 Bucket.

Responsibilities:
  1. Creates the S3 bucket if it doesn't already exist.
  2. Applies standard CORS configuration so browsers and the React frontend
     can fetch presigned images and perform uploads.
  3. Applies secure PublicAccessBlock (bucket remains private; access via presigned URLs).

Usage:
  python infrastructure/setup_s3_bucket.py
  python infrastructure/setup_s3_bucket.py --bucket custom-bucket-name --region ap-south-1
  python infrastructure/setup_s3_bucket.py --cors-only
"""

import argparse
import json
import logging
import os
import sys

import boto3
from botocore.exceptions import ClientError

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S",
logger = logging.getLogger("setup_s3")


def load_env_file():
    candidates = [
        os.path.join(os.path.dirname(__file__), "..", "backend", ".env"),
        os.path.join(os.path.dirname(__file__), "..", ".env"),
        ".env",
        "backend/.env",
    ]
    for path in candidates:
        if os.path.isfile(path):
            with open(path, "r", encoding="utf-8") as f:
                for line in f:
                    line = line.strip()
                    if line and not line.startswith("#") and "=" in line:
                        k, v = line.split("=", 1)
                        k, v = k.strip(), v.strip().strip("'\"")
                        if k and k not in os.environ:
                            os.environ[k] = v
            break


load_env_file()


def get_s3_client(region: str, use_localstack: bool = False, localstack_endpoint: str = "http://localhost:4566"):
    kwargs = {"region_name": region}
    if use_localstack:
        kwargs["endpoint_url"] = localstack_endpoint
        kwargs["aws_access_key_id"] = os.getenv("AWS_ACCESS_KEY_ID", "test")
        kwargs["aws_secret_access_key"] = os.getenv("AWS_SECRET_ACCESS_KEY", "test")
    return boto3.client("s3", **kwargs)


def ensure_bucket(client, bucket_name: str, region: str) -> bool:
    """Ensure S3 bucket exists, creating it if necessary."""
    try:
        client.head_bucket(Bucket=bucket_name)
        logger.info("Bucket '%s' already exists and is accessible.", bucket_name)
        return True
    except ClientError as exc:
        error_code = exc.response.get("Error", {}).get("Code", "")
        if error_code in {"404", "NoSuchBucket"}:
            logger.info("Bucket '%s' does not exist. Creating in %s...", bucket_name, region)
            create_kwargs = {"Bucket": bucket_name}
            if region != "us-east-1":
                create_kwargs["CreateBucketConfiguration"] = {"LocationConstraint": region}
            try:
                client.create_bucket(**create_kwargs)
                logger.info("Successfully created bucket '%s'.", bucket_name)
                return True
            except ClientError as create_exc:
                logger.error("Failed to create bucket '%s': %s", bucket_name, create_exc)
                return False
        elif error_code == "403":
            logger.error("Access denied to bucket '%s'. Check IAM permissions or bucket ownership.", bucket_name)
            return False
        else:
            logger.error("head_bucket failed for '%s': %s", bucket_name, exc)
            return False


def apply_cors_policy(client, bucket_name: str) -> bool:
    """Apply CORS configuration allowing GET, PUT, and HEAD from web clients."""
    cors_configuration = {
        "CORSRules": [
            {
                "AllowedHeaders": ["*"],
                "AllowedMethods": ["GET", "PUT", "HEAD"],
                "AllowedOrigins": ["*"],
                "ExposeHeaders": ["ETag", "x-amz-request-id"],
                "MaxAgeSeconds": 3600,
            }
        ]
    }
    try:
        client.put_bucket_cors(
            Bucket=bucket_name,
            CORSConfiguration=cors_configuration,
        )
        logger.info("Successfully applied CORS rules to bucket '%s'.", bucket_name)
        return True
    except ClientError as exc:
        logger.error("Failed to set CORS policy on bucket '%s': %s", bucket_name, exc)
        return False


def apply_public_access_block(client, bucket_name: str) -> bool:
    """Enforce block on public access (bucket private; access via presigned URLs)."""
    try:
        client.put_public_access_block(
            Bucket=bucket_name,
            PublicAccessBlockConfiguration={
                "BlockPublicAcls": True,
                "IgnorePublicAcls": True,
                "BlockPublicPolicy": True,
                "RestrictPublicBuckets": True,
            },
        )
        logger.info("Applied PublicAccessBlock to '%s' (private bucket).", bucket_name)
        return True
    except ClientError as exc:
        logger.warning("Could not set PublicAccessBlock on '%s': %s", bucket_name, exc)
        return False


def main():
    parser = argparse.ArgumentParser(description="VayuDrishti S3 Bucket Provisioner")
    parser.add_argument(
        "--bucket",
        default=os.getenv("S3_BUCKET_NAME", "vayudrishti-images"),
        help="S3 bucket name (default: from env or 'vayudrishti-images')",
    )
    parser.add_argument(
        "--region",
        default=os.getenv("AWS_REGION", "ap-south-1"),
        help="AWS region (default: from env or 'ap-south-1')",
    )
    parser.add_argument(
        "--cors-only",
        action="store_true",
        help="Only update CORS configuration on an existing bucket",
    )
    args = parser.parse_args()

    use_localstack = os.getenv("USE_LOCALSTACK", "false").lower() == "true"
    localstack_endpoint = os.getenv("LOCALSTACK_ENDPOINT", "http://localhost:4566")

    client = get_s3_client(args.region, use_localstack, localstack_endpoint)

    if not args.cors_only:
        ok = ensure_bucket(client, args.bucket, args.region)
        if not ok:
            sys.exit(1)
        apply_public_access_block(client, args.bucket)

    cors_ok = apply_cors_policy(client, args.bucket)
    if not cors_ok:
        sys.exit(1)

    logger.info("S3 provisioning for '%s' complete!", args.bucket)


if __name__ == "__main__":
    main()
