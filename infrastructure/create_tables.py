# -*- coding: utf-8 -*-
"""
VayuDrishti — DynamoDB Table Provisioner
=========================================
Creates the 4 DynamoDB tables required for the VayuDrishti MVP:
  1. DustReports         — individual resident-submitted reports
  2. IncidentCases       — aggregated incident cases (linked reports)
  3. ReviewDecisions     — reviewer approve/reject/more-info decisions
  4. AuditEvents         — timestamped audit trail for all key actions

Usage:
    # Against real AWS (uses env vars: AWS_ACCESS_KEY_ID, AWS_SECRET_ACCESS_KEY, AWS_REGION)
    python infrastructure/create_tables.py

    # Against LocalStack (set USE_LOCALSTACK=true in your .env or shell)
    USE_LOCALSTACK=true python infrastructure/create_tables.py

    # Dry-run: just print what would be created
    python infrastructure/create_tables.py --dry-run

    # Delete and recreate all tables (WARNING: destroys data)
    python infrastructure/create_tables.py --recreate
"""

import argparse
import sys
import time
import os

import boto3
from botocore.exceptions import ClientError

# ---------------------------------------------------------------------------
# Configuration
# ---------------------------------------------------------------------------

AWS_REGION = os.getenv("AWS_REGION", "ap-south-1")
USE_LOCALSTACK = os.getenv("USE_LOCALSTACK", "false").lower() == "true"
LOCALSTACK_ENDPOINT = os.getenv("LOCALSTACK_ENDPOINT", "http://localhost:4566")

# Table names — kept in sync with backend/config.py
TABLE_DUST_REPORTS = os.getenv("DYNAMO_REPORTS_TABLE", "DustReports")
TABLE_INCIDENT_CASES = os.getenv("DYNAMO_CASES_TABLE", "IncidentCases")
TABLE_REVIEW_DECISIONS = os.getenv("DYNAMO_DECISIONS_TABLE", "ReviewDecisions")
TABLE_AUDIT_EVENTS = os.getenv("DYNAMO_AUDIT_TABLE", "AuditEvents")

# Billing mode — PAY_PER_REQUEST is ideal for a hackathon (no capacity planning)
BILLING_MODE = "PAY_PER_REQUEST"

# ---------------------------------------------------------------------------
# Table Definitions
# ---------------------------------------------------------------------------

TABLE_DEFINITIONS = [
    # ------------------------------------------------------------------
    # 1. DustReports
    #    PK:  report_id  (String)
    #    GSI: case_id-index  →  lookup all reports belonging to a case
    # ------------------------------------------------------------------
    {
        "TableName": TABLE_DUST_REPORTS,
        "KeySchema": [
            {"AttributeName": "report_id", "KeyType": "HASH"},  # Partition key
        ],
        "AttributeDefinitions": [
            {"AttributeName": "report_id", "AttributeType": "S"},
            {"AttributeName": "case_id",   "AttributeType": "S"},
        ],
        "BillingMode": BILLING_MODE,
        "GlobalSecondaryIndexes": [
            {
                "IndexName": "case_id-index",
                "KeySchema": [
                    {"AttributeName": "case_id", "KeyType": "HASH"},
                ],
                "Projection": {"ProjectionType": "ALL"},
            }
        ],
        "Tags": [
            {"Key": "Project",     "Value": "VayuDrishti"},
            {"Key": "Environment", "Value": "hackathon"},
        ],
    },

    # ------------------------------------------------------------------
    # 2. IncidentCases
    #    PK:  case_id  (String)
    #    GSI: status-updated_at-index  →  reviewer queue sorted by recency
    # ------------------------------------------------------------------
    {
        "TableName": TABLE_INCIDENT_CASES,
        "KeySchema": [
            {"AttributeName": "case_id", "KeyType": "HASH"},
        ],
        "AttributeDefinitions": [
            {"AttributeName": "case_id",    "AttributeType": "S"},
            {"AttributeName": "status",     "AttributeType": "S"},
            {"AttributeName": "updated_at", "AttributeType": "S"},
        ],
        "BillingMode": BILLING_MODE,
        "GlobalSecondaryIndexes": [
            {
                # Lets reviewers query: "give me all cases with status X,
                # ordered by when they were last updated"
                "IndexName": "status-updated_at-index",
                "KeySchema": [
                    {"AttributeName": "status",     "KeyType": "HASH"},
                    {"AttributeName": "updated_at",  "KeyType": "RANGE"},
                ],
                "Projection": {
                    "ProjectionType": "INCLUDE",
                    "NonKeyAttributes": [
                        "case_id", "priority_score", "latitude", "longitude",
                        "first_reported_at", "last_reported_at",
                    ],
                },
            }
        ],
        "Tags": [
            {"Key": "Project",     "Value": "VayuDrishti"},
            {"Key": "Environment", "Value": "hackathon"},
        ],
    },

    # ------------------------------------------------------------------
    # 3. ReviewDecisions
    #    PK:  decision_id  (String)
    #    GSI: case_id-index  →  get all decisions for a given case
    # ------------------------------------------------------------------
    {
        "TableName": TABLE_REVIEW_DECISIONS,
        "KeySchema": [
            {"AttributeName": "decision_id", "KeyType": "HASH"},
        ],
        "AttributeDefinitions": [
            {"AttributeName": "decision_id", "AttributeType": "S"},
            {"AttributeName": "case_id",     "AttributeType": "S"},
        ],
        "BillingMode": BILLING_MODE,
        "GlobalSecondaryIndexes": [
            {
                "IndexName": "case_id-index",
                "KeySchema": [
                    {"AttributeName": "case_id", "KeyType": "HASH"},
                ],
                "Projection": {"ProjectionType": "ALL"},
            }
        ],
        "Tags": [
            {"Key": "Project",     "Value": "VayuDrishti"},
            {"Key": "Environment", "Value": "hackathon"},
        ],
    },

    # ------------------------------------------------------------------
    # 4. AuditEvents
    #    PK:  event_id    (String)
    #    SK:  timestamp   (String — ISO-8601, sorts lexicographically)
    #    GSI: case_id-timestamp-index  →  full timeline for a case
    # ------------------------------------------------------------------
    {
        "TableName": TABLE_AUDIT_EVENTS,
        "KeySchema": [
            {"AttributeName": "event_id",  "KeyType": "HASH"},
            {"AttributeName": "timestamp", "KeyType": "RANGE"},
        ],
        "AttributeDefinitions": [
            {"AttributeName": "event_id",  "AttributeType": "S"},
            {"AttributeName": "timestamp", "AttributeType": "S"},
            {"AttributeName": "case_id",   "AttributeType": "S"},
        ],
        "BillingMode": BILLING_MODE,
        "GlobalSecondaryIndexes": [
            {
                # Query: "give me all audit events for case X, in order"
                "IndexName": "case_id-timestamp-index",
                "KeySchema": [
                    {"AttributeName": "case_id",   "KeyType": "HASH"},
                    {"AttributeName": "timestamp",  "KeyType": "RANGE"},
                ],
                "Projection": {"ProjectionType": "ALL"},
            }
        ],
        "Tags": [
            {"Key": "Project",     "Value": "VayuDrishti"},
            {"Key": "Environment", "Value": "hackathon"},
        ],
    },
]

# ---------------------------------------------------------------------------
# DynamoDB client factory
# ---------------------------------------------------------------------------

def get_dynamodb_client():
    """Return a boto3 DynamoDB client, pointing at LocalStack if requested."""
    kwargs = {
        "region_name": AWS_REGION,
    }
    if USE_LOCALSTACK:
        kwargs["endpoint_url"] = LOCALSTACK_ENDPOINT
        # LocalStack doesn't care about real creds, but boto3 requires *something*
        kwargs["aws_access_key_id"] = os.getenv("AWS_ACCESS_KEY_ID", "test")
        kwargs["aws_secret_access_key"] = os.getenv("AWS_SECRET_ACCESS_KEY", "test")

    return boto3.client("dynamodb", **kwargs)


def get_dynamodb_resource():
    """Return a boto3 DynamoDB resource (higher-level API for waiter)."""
    kwargs = {"region_name": AWS_REGION}
    if USE_LOCALSTACK:
        kwargs["endpoint_url"] = LOCALSTACK_ENDPOINT
        kwargs["aws_access_key_id"] = os.getenv("AWS_ACCESS_KEY_ID", "test")
        kwargs["aws_secret_access_key"] = os.getenv("AWS_SECRET_ACCESS_KEY", "test")
    return boto3.resource("dynamodb", **kwargs)


# ---------------------------------------------------------------------------
# Table lifecycle helpers
# ---------------------------------------------------------------------------

def table_exists(client, table_name: str) -> bool:
    """Return True if the table already exists in DynamoDB."""
    try:
        client.describe_table(TableName=table_name)
        return True
    except ClientError as e:
        if e.response["Error"]["Code"] == "ResourceNotFoundException":
            return False
        raise


def delete_table(client, table_name: str) -> None:
    """Delete a table and wait for it to disappear (used by --recreate)."""
    print(f"  [DELETE] Deleting table '{table_name}' ...")
    client.delete_table(TableName=table_name)

    # Poll until the table no longer exists
    for _ in range(30):
        if not table_exists(client, table_name):
            print(f"         [OK] '{table_name}' deleted.")
            return
        time.sleep(2)

    raise TimeoutError(f"Table '{table_name}' was not deleted in time.")


def create_table(client, definition: dict) -> None:
    """Create a single DynamoDB table from a definition dict."""
    name = definition["TableName"]
    print(f"  [CREATE] Creating table '{name}' ...")

    # Tags are not accepted by all LocalStack versions — handle gracefully
    try:
        client.create_table(**definition)
    except ClientError as e:
        code = e.response["Error"]["Code"]
        if code == "ResourceInUseException":
            print(f"         [WARN] '{name}' already exists — skipping.")
            return
        raise

    # Wait until ACTIVE
    waiter = client.get_waiter("table_exists")
    waiter.wait(TableName=name, WaiterConfig={"Delay": 2, "MaxAttempts": 30})
    print(f"         [OK] '{name}' is ACTIVE.")


def describe_table_summary(client, table_name: str) -> None:
    """Print a short summary of an existing table."""
    resp = client.describe_table(TableName=table_name)
    tbl = resp["Table"]
    gsis = tbl.get("GlobalSecondaryIndexes", [])
    gsi_names = [g["IndexName"] for g in gsis]

    print(f"  [TABLE] {table_name}")
    print(f"          Status : {tbl['TableStatus']}")
    print(f"          Items  : {tbl.get('ItemCount', 'N/A')}")
    print(f"          GSIs   : {gsi_names or 'none'}")


# ---------------------------------------------------------------------------
# Main entry point
# ---------------------------------------------------------------------------

def run(dry_run: bool = False, recreate: bool = False) -> None:
    target = f"LocalStack ({LOCALSTACK_ENDPOINT})" if USE_LOCALSTACK else f"AWS ({AWS_REGION})"
    print(f"\n[VayuDrishti] DynamoDB Table Provisioner")
    print(f"   Target  : {target}")
    print(f"   Mode    : {'DRY RUN (no changes)' if dry_run else ('RECREATE' if recreate else 'CREATE (skip if exists)')}")
    print(f"   Tables  : {len(TABLE_DEFINITIONS)}")
    print()

    if dry_run:
        for defn in TABLE_DEFINITIONS:
            print(f"  [PLAN] Would create: {defn['TableName']}")
            for gsi in defn.get("GlobalSecondaryIndexes", []):
                print(f"         GSI: {gsi['IndexName']}")
        print("\n[OK] Dry-run complete. No tables were created or modified.")
        return

    client = get_dynamodb_client()

    for defn in TABLE_DEFINITIONS:
        name = defn["TableName"]
        exists = table_exists(client, name)

        if exists and recreate:
            delete_table(client, name)
            exists = False

        if exists:
            print(f"  [SKIP] '{name}' already exists — skipping creation.")
        else:
            create_table(client, defn)

    print()
    print("-" * 52)
    print("[STATUS] Final table status:")
    for defn in TABLE_DEFINITIONS:
        describe_table_summary(client, defn["TableName"])

    print()
    print("[DONE] All tables are ready. VayuDrishti backend can now start.")


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Provision VayuDrishti DynamoDB tables.",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=__doc__,
    )
    parser.add_argument(
        "--region",
        default=os.getenv("AWS_REGION", "ap-south-1"),
        help="AWS region (default: ap-south-1 or from env)",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Print what would be created without making any changes.",
    )
    parser.add_argument(
        "--recreate",
        action="store_true",
        help="DELETE existing tables before recreating them. WARNING: destroys all data.",
    )
    parser.add_argument(
        "-y",
        "--yes",
        action="store_true",
        help="Automatic yes to prompts (for automated deployment scripts).",
    )
    return parser.parse_args()


if __name__ == "__main__":
    args = parse_args()

    if args.region:
        AWS_REGION = args.region

    if args.recreate and not args.dry_run and not args.yes:
        confirm = input(
            "\n[WARNING] --recreate will DELETE all existing VayuDrishti tables and their data.\n"
            "   Type 'yes' to continue: "
        ).strip()
        if confirm != "yes":
            print("Aborted.")
            sys.exit(0)

    try:
        run(dry_run=args.dry_run, recreate=args.recreate)
    except Exception as exc:
        print(f"\n[ERROR] {exc}", file=sys.stderr)
        sys.exit(1)
