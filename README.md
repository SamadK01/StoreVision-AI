# StoreVision AI

StoreVision AI is an agentic shelf-audit prototype for the OpenCV AI Competition 2026, powered by AWS. A store associate captures a shelf image; the system identifies product facings and potential stock-out gaps, explains its decision, and can emit an AWS-backed restock event.

## Problem statement

Manual shelf checks are slow, inconsistent, and often happen after a shopper encounters an empty slot. StoreVision AI converts a shelf photo into an auditable inventory signal, keeping a human in the review loop for replenishment decisions.

## Agentic vision architecture

```text
[React Native camera/gallery]
             |
             v  multipart image
[FastAPI /api/audit-shelf]
             |
             v
[Perception: OpenCV]
 grayscale → bilateral filter → Canny edges → contour hierarchy
             |
             v
[Decision: Shelf Health]
 product/gap metrics → score → restock threshold
             |
       +-----+-----+
       |           |
       v           v
[Annotated UI]  [Action tools]
                 S3 audit JSON + SNS restock event
```

## OpenCV & AWS integration

The perception pipeline detects product-like contour rectangles and computes uncovered horizontal intervals within shelf bands as candidate gaps. Green boxes mark inventory candidates; red boxes mark gaps. This is a classical, explainable OpenCV pipeline designed for a competition prototype—not SKU recognition.

AWS actions are opt-in and only occur when restocking is required. Configure standard boto3 credentials plus these variables before launching the backend:

```bash
export AWS_REGION=us-east-1
export STOREVISION_S3_BUCKET=your-audit-bucket
export STOREVISION_SNS_TOPIC_ARN=arn:aws:sns:us-east-1:123456789012:storevision-restock
```

Without them, the service safely simulates the action and records that in the agent trace.

## Run locally

### Backend

```bash
cd backend
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
./run.sh
```

The backend listens on `http://0.0.0.0:8000`; verify it with `curl http://localhost:8000/health`. It can also be started directly with `uvicorn app:app --reload` from `backend`.

### Android app

```bash
cd StoreVisionAI
npm install
npm run android
```

The app targets Android Emulator networking by default: `http://10.0.2.2:8000/api/audit-shelf`. For a physical Android device, set `USE_LAN_SERVER` to `true` and replace `LAN_SERVER_IP` in `App.tsx` with your computer's reachable LAN IPv4 address; make sure both devices share the network. Android cleartext HTTP is explicitly enabled for this local-development flow.

## Edge cases & responsible AI

- Blurry, dark, angled, crowded, or reflective shelves reduce contour reliability. The app reports a visual audit—not a guaranteed inventory count.
- If a visually detailed image produces no validated product clusters, StoreVision reports **Detection uncertain** instead of a misleading 100% healthy result; retake the photo with a front-facing, well-lit shelf.
- The system rejects empty/non-image uploads and continues to return an audit if an optional AWS operation fails.
- Red gap boxes are candidate stock-outs and must be reviewed by a store associate before placing orders. Product, pricing, customer, or biometric recognition is intentionally out of scope.
- This prototype does not train on or store shopper imagery. Apply least-privilege IAM, encryption, retention limits, and access logging before production use.
