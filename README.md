# VayuDrishti (वायु दृष्टि)

> **AI-Powered Urban Dust Pollution Reporting, Spatial Clustering & Priority Inspection System**

VayuDrishti empowers residents to capture and report visible dust and air pollution sources with photos and GPS coordinates. The system leverages **Amazon Bedrock (Claude 3 Haiku)** to analyse imagery, assess severity and dust categories, cluster nearby incidents into investigation cases, and help environmental authorities prioritize inspection workflows.

---

## Architecture

```
                       ┌────────────────────────────────────────┐
                       │          React + Vite Frontend         │
                       │     (Tailored UI + Leaflet Maps)       │
                       └───────────────────┬────────────────────┘
                                           │ HTTPS
                                           ▼
                       ┌────────────────────────────────────────┐
                       │           FastAPI Backend              │
                       │     (Async Pipeline + REST API)        │
                       └────────┬──────────┬─────────────┬──────┘
                                │          │             │
                    Photo Upload│          │ Metadata    │ Vision AI
                                ▼          ▼             ▼
                       ┌─────────────┐┌──────────────┐┌──────────────┐
                       │  Amazon S3  ││Amazon DynamoDB││Amazon Bedrock│
                       │Presigned URL││ (4 Tables)   ││(Claude Haiku)│
                       └─────────────┘└──────────────┘└──────────────┘
```

---

## Key Features

- 📸 **Photo & GPS Reporting**: Residents snap photos, choose coordinates on an interactive map picker, and submit reports.
- 🤖 **Multimodal Vision AI**: Automatically evaluates pollution severity, confidence score, source classification (construction, road dust, industrial, vehicle emissions, open burning), and suggested actions.
- 📍 **Spatial Proximity & Clustering**: Links neighboring reports within a configurable radius and time window to spot recurring pollution hotspots.
- ⚡ **Full AWS Console Readiness**: 1-click CloudFormation template, App Runner deployment config, DynamoDB provisioning, and S3 CORS scripts.
- 🛡️ **Dual-Mode Operation**: Runs on real AWS services (`ap-south-1`, `us-east-1`, etc.) or in lightweight offline mock mode for instant local testing.

---

## AWS Management Console Deployment

For a detailed step-by-step console guide, see **[`docs/AWS_CONSOLE_DEPLOYMENT_GUIDE.md`](docs/AWS_CONSOLE_DEPLOYMENT_GUIDE.md)**.

### Quick CloudFormation Deploy
1. Open the [AWS CloudFormation Console](https://console.aws.amazon.com/cloudformation/).
2. Click **Create stack** → **Upload a template file** → Select [`infrastructure/cloudformation.yaml`](infrastructure/cloudformation.yaml).
3. Specify your unique `S3BucketName` (e.g. `vayudrishti-images-<your-id>`).
4. Click through to acknowledge IAM permissions and click **Submit**.

### Quick Pre-flight Check
Verify credentials, S3, DynamoDB tables, and Bedrock model access anytime:
```bash
python3 infrastructure/verify_aws.py --region ap-south-1
```

---

## Local Development

### 1. Prerequisites
- **Node.js** (v18+)
- **Python** (v3.10+)

### 2. Backend Setup
```bash
cd backend
python3 -m venv venv
source venv/bin/activate       # On Windows: .\venv\Scripts\activate
pip install -r requirements.txt
cp .env.example .env

# Run FastAPI server
uvicorn main:app --reload --port 8000
```
- Interactive Swagger docs: [http://127.0.0.1:8000/docs](http://127.0.0.1:8000/docs)
- Health probe: [http://127.0.0.1:8000/health](http://127.0.0.1:8000/health)

### 3. Frontend Setup
```bash
cd frontend
npm install
npm run dev
```
Open [http://localhost:5173](http://localhost:5173) in your browser.

---

## Docker Quickstart

Run both frontend and backend in isolated containers:
```bash
docker compose up --build
```
- Frontend: [http://localhost:3000](http://localhost:3000)
- Backend: [http://localhost:8000](http://localhost:8000)

---

## Core API Endpoints

| Method | Endpoint | Description |
|---|---|---|
| `POST` | `/api/v1/reports` | Submit photo report with GPS metadata |
| `GET` | `/api/v1/reports` | List reports (supports `status` and `limit`) |
| `GET` | `/api/v1/reports/{id}` | Retrieve individual report with AI visual analysis |
| `GET` | `/api/v1/reports/{id}/nearby` | Fetch nearby reports within geo-radius |
| `GET` | `/health` / `/api/v1/health` | Diagnostic liveness & AWS connectivity probe |

---

## License

This project is licensed under the MIT License.
