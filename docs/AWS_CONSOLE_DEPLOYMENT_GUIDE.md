# VayuDrishti — AWS Management Console Deployment Guide

This guide walks you through deploying **VayuDrishti** (Backend, Frontend, S3, DynamoDB, and Bedrock AI) directly using the **AWS Management Console**.

---

## Architecture Overview

```
                      ┌────────────────────────────────────────┐
                      │             React Frontend             │
                      │   (AWS Amplify / S3 + CloudFront)      │
                      └──────────────────┬─────────────────────┘
                                         │ HTTPS Requests
                                         ▼
                      ┌────────────────────────────────────────┐
                      │          FastAPI Backend API           │
                      │         (AWS App Runner / ECS)         │
                      └────────┬───────────┬──────────────┬────┘
                               │           │              │
           Presigned URL Upload│           │ Metadata     │ Vision AI
                               ▼           ▼              ▼
                      ┌─────────────┐ ┌──────────────┐ ┌──────────────┐
                      │  Amazon S3  │ │Amazon DynamoDB││Amazon Bedrock│
                      │(Photo Store)│ │ (4 Tables)   │ │(Claude Haiku)│
                      └─────────────┘ └──────────────┘ └──────────────┘
```

---

## Method 1: Automated 1-Click Setup via CloudFormation Console (Recommended)

1. Sign in to the **[AWS Management Console](https://console.aws.amazon.com/)**.
2. In the top search bar, type **CloudFormation** and navigate to the service.
3. Click **Create stack** → **With new resources (standard)**.
4. Under **Template source**, select **Upload a template file**.
5. Upload [`infrastructure/cloudformation.yaml`](../infrastructure/cloudformation.yaml).
6. Click **Next**, then enter stack details:
   - **Stack name**: `VayuDrishti-Production`
   - **S3BucketName**: `vayudrishti-images-<your-unique-id>` (S3 bucket names must be globally unique)
   - **Environment**: `production`
7. Click **Next** through stack options.
8. On the final Review page, check the box:
   > 🗹 *I acknowledge that AWS CloudFormation might create IAM resources.*
9. Click **Submit**. CloudFormation will automatically provision:
   - Secure S3 Bucket with web CORS policy
   - All 4 DynamoDB tables with GSIs (`DustReports`, `IncidentCases`, `ReviewDecisions`, `AuditEvents`)
   - IAM Execution Role with Bedrock, S3, and DynamoDB permissions

---

## Method 2: Manual Console Setup

### 1. Amazon Bedrock — Enable Claude 3 Haiku Model Access
1. In the AWS Console search bar, navigate to **Amazon Bedrock**.
2. In the left navigation menu, scroll down and click **Model access**.
3. Click **Modify model access** (or **Enable specific models**).
4. Under **Anthropic**, check **Claude 3 Haiku**.
5. Click **Next** and **Submit**. Access is usually granted immediately.

### 2. Amazon S3 — Resident Photo Storage Bucket
1. Open the **Amazon S3** Console and click **Create bucket**.
2. **Bucket name**: e.g., `vayudrishti-images` (or unique name).
3. **AWS Region**: e.g., `ap-south-1` (Asia Pacific - Mumbai) or `us-east-1`.
4. Keep **Block all public access** enabled (images are read safely via short-lived presigned URLs).
5. Click **Create bucket**.
6. Select your new bucket, go to the **Permissions** tab, scroll to **Cross-origin resource sharing (CORS)**, and paste:
```json
[
  {
    "AllowedHeaders": ["*"],
    "AllowedMethods": ["GET", "PUT", "HEAD"],
    "AllowedOrigins": ["*"],
    "ExposeHeaders": ["ETag", "x-amz-request-id"],
    "MaxAgeSeconds": 3600
  }
]
```
7. Click **Save changes**.

### 3. Amazon DynamoDB — Provision Tables
You can either run the table script in AWS CloudShell:
```bash
python3 infrastructure/create_tables.py --region ap-south-1
```
Or create them manually in the **DynamoDB Console**:
- **Table 1: `DustReports`**
  - Partition key: `report_id` (String)
  - Global Secondary Index: `case_id-index` (Partition key: `case_id` (String), Projected: All)
- **Table 2: `IncidentCases`**
  - Partition key: `case_id` (String)
  - Global Secondary Index: `status-updated_at-index` (Partition: `status` (S), Sort: `updated_at` (S))
- **Table 3: `ReviewDecisions`**
  - Partition key: `decision_id` (String)
  - Global Secondary Index: `case_id-index` (Partition: `case_id` (S))
- **Table 4: `AuditEvents`**
  - Partition key: `event_id` (String), Sort key: `timestamp` (String)
  - Global Secondary Index: `case_id-timestamp-index` (Partition: `case_id` (S), Sort: `timestamp` (S))

---

## Deploying the Backend via AWS App Runner Console

1. In the AWS Console, search for and open **AWS App Runner**.
2. Click **Create service**.
3. **Source**: Select **Source code repository**, click **Add new** to connect your GitHub account, and choose `Krish01Cse/VayuDrishti`.
4. **Branch**: `main`.
5. Under **Deployment settings**, choose **Automatic**.
6. Under **Configure build**:
   - Choose **Use a configuration file** (App Runner will automatically detect [`apprunner.yaml`](../apprunner.yaml)).
   - Alternatively, choose **Configure all settings here**:
     - Runtime: `Python 3`
     - Build command: `pip install -r backend/requirements.txt`
     - Start command: `python -m uvicorn backend.main:app --host 0.0.0.0 --port 8000`
     - Port: `8000`
7. Under **Security**:
   - Under **Instance role**, choose the IAM role created by CloudFormation (or attach a role with `AmazonDynamoDBFullAccess`, `AmazonS3FullAccess`, and `bedrock:InvokeModel`).
8. Click **Next** and **Create & deploy**.
9. Once active, copy the **Default domain** URL (e.g. `https://xyz123.ap-south-1.awsapprunner.com`).
10. Test your endpoint:
    - `https://xyz123.ap-south-1.awsapprunner.com/health` → returns `status: ok`
    - `https://xyz123.ap-south-1.awsapprunner.com/docs` → interactive Swagger API documentation

---

## Deploying the Frontend via AWS Amplify Console

1. In the AWS Console, search for and open **AWS Amplify**.
2. Click **Deploy an app** → **Host web app** → Select **GitHub**.
3. Choose repository `Krish01Cse/VayuDrishti` and branch `main`.
4. In the build settings:
   - App root: `frontend`
   - Build command: `npm run build`
   - Base directory: `frontend/dist`
5. Under **Advanced settings** → **Environment variables**:
   - Key: `VITE_API_BASE_URL`
   - Value: `https://<your-app-runner-domain>/api/v1`
6. Click **Save and deploy**.
7. In a few minutes, Amplify will provide your live SSL website URL!

---

## Pre-flight Verification in AWS CloudShell

To quickly verify that your AWS Console configuration is 100% operational, open **AWS CloudShell** from the console toolbar (terminal icon `>_`) and run:

```bash
git clone https://github.com/Krish01Cse/VayuDrishti.git
cd VayuDrishti
pip install boto3
python3 infrastructure/verify_aws.py --region ap-south-1
```

All 4 health checks will display:
```
  [✔ PASS] AWS Credentials & Identity
  [✔ PASS] S3 Bucket (vayudrishti-images)
  [✔ PASS] DynamoDB Table (DustReports)
  [✔ PASS] DynamoDB Table (IncidentCases)
  [✔ PASS] DynamoDB Table (ReviewDecisions)
  [✔ PASS] DynamoDB Table (AuditEvents)
  [✔ PASS] Bedrock Claude (anthropic.claude-3-haiku-20240307-v1:0)
```
