#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
infrastructure/verify_aws.py — Comprehensive AWS environment & service validator.

Run this script directly from your terminal or AWS CloudShell to verify:
  1. AWS Credentials & Caller Identity (Account, ARN, UserId)
  2. S3 Bucket availability and CORS configuration
  3. DynamoDB tables status (DustReports, IncidentCases, ReviewDecisions, AuditEvents)
  4. Bedrock Claude model accessibility

Usage:
  python infrastructure/verify_aws.py
  python infrastructure/verify_aws.py --region ap-south-1
"""

import argparse
import os
import sys

import boto3
from botocore.exceptions import ClientError


# Terminal colors
GREEN = "\033[92m"
RED = "\033[91m"
YELLOW = "\033[93m"
CYAN = "\033[96m"
BOLD = "\033[1m"
RESET = "\033[0m"


def print_status(item: str, status: bool, detail: str = ""):
    icon = f"{GREEN}✔ PASS{RESET}" if status else f"{RED}✗ FAIL{RESET}"
    detail_str = f" — {detail}" if detail else ""
    print(f"  [{icon}] {BOLD}{item}{RESET}{detail_str}")


def check_sts(session, region: str) -> tuple[bool, str]:
    try:
        sts = session.client("sts", region_name=region)
        ident = sts.get_caller_identity()
        arn = ident.get("Arn", "Unknown")
        account = ident.get("Account", "Unknown")
        return True, f"Account: {account} | ARN: {arn}"
    except Exception as exc:
        return False, str(exc)


def check_s3(session, bucket_name: str, region: str) -> tuple[bool, str]:
    try:
        s3 = session.client("s3", region_name=region)
        s3.head_bucket(Bucket=bucket_name)

        # Check CORS
        cors_info = "CORS not configured"
        try:
            cors = s3.get_bucket_cors(Bucket=bucket_name)
            rules_count = len(cors.get("CORSRules", []))
            cors_info = f"CORS configured ({rules_count} rules)"
        except ClientError:
            pass

        return True, f"Bucket '{bucket_name}' accessible ({cors_info})"
    except ClientError as exc:
        code = exc.response.get("Error", {}).get("Code", "")
        return False, f"Bucket '{bucket_name}' error: {code}"
    except Exception as exc:
        return False, str(exc)


def check_dynamodb_tables(session, region: str, tables: list[str]) -> list[tuple[str, bool, str]]:
    results = []
    dynamo = session.client("dynamodb", region_name=region)
    for tname in tables:
        try:
            desc = dynamo.describe_table(TableName=tname)
            status = desc.get("Table", {}).get("TableStatus", "UNKNOWN")
            item_count = desc.get("Table", {}).get("ItemCount", 0)
            ok = status == "ACTIVE"
            results.append((tname, ok, f"Status: {status} | Items: {item_count}"))
        except ClientError as exc:
            code = exc.response.get("Error", {}).get("Code", "")
            results.append((tname, False, f"Error: {code} (table may not exist yet)"))
        except Exception as exc:
            results.append((tname, False, str(exc)))
    return results


def check_bedrock(session, region: str, model_id: str) -> tuple[bool, str]:
    try:
        bedrock = session.client("bedrock", region_name=region)
        resp = bedrock.get_foundation_model(modelIdentifier=model_id)
        details = resp.get("modelDetails", {})
        name = details.get("modelName", model_id)
        return True, f"Model '{name}' is available in {region}"
    except ClientError as exc:
        code = exc.response.get("Error", {}).get("Code", "")
        if code == "AccessDeniedException":
            return False, f"Access denied for '{model_id}' — request model access in Bedrock Console"
        return False, f"Bedrock check: {code}"
    except Exception as exc:
        return False, str(exc)


def main():
    parser = argparse.ArgumentParser(description="VayuDrishti AWS Pre-flight Validator")
    parser.add_argument("--region", default=os.getenv("AWS_REGION", "ap-south-1"), help="AWS Region")
    parser.add_argument("--bucket", default=os.getenv("S3_BUCKET_NAME", "vayudrishti-images"), help="S3 Bucket")
    parser.add_argument(
        "--model",
        default=os.getenv("BEDROCK_MODEL_ID", "anthropic.claude-3-haiku-20240307-v1:0"),
        help="Bedrock Model ID",
    )
    args = parser.parse_args()

    print(f"\n{CYAN}{BOLD}======================================================{RESET}")
    print(f"{CYAN}{BOLD}    VayuDrishti AWS Verification (Region: {args.region})   {RESET}")
    print(f"{CYAN}{BOLD}======================================================{RESET}\n")

    session = boto3.Session()

    # 1. Check STS Identity
    sts_ok, sts_msg = check_sts(session, args.region)
    print_status("AWS Credentials & Identity", sts_ok, sts_msg)

    # 2. Check S3 Bucket
    s3_ok, s3_msg = check_s3(session, args.bucket, args.region)
    print_status(f"S3 Bucket ({args.bucket})", s3_ok, s3_msg)

    # 3. Check DynamoDB Tables
    table_names = [
        os.getenv("DYNAMODB_TABLE_DUST_REPORTS", "DustReports"),
        os.getenv("DYNAMODB_TABLE_INCIDENT_CASES", "IncidentCases"),
        os.getenv("DYNAMODB_TABLE_REVIEW_DECISIONS", "ReviewDecisions"),
        os.getenv("DYNAMODB_TABLE_AUDIT_EVENTS", "AuditEvents"),
    ]
    db_results = check_dynamodb_tables(session, args.region, table_names)
    for tname, tok, tmsg in db_results:
        print_status(f"DynamoDB Table ({tname})", tok, tmsg)

    # 4. Check Bedrock
    bedrock_ok, bedrock_msg = check_bedrock(session, args.region, args.model)
    print_status(f"Bedrock Claude ({args.model})", bedrock_ok, bedrock_msg)

    print(f"\n{BOLD}Verification complete.{RESET}\n")


if __name__ == "__main__":
    main()
