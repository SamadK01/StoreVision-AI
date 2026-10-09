"""StoreVision AI: agentic shelf audit API.

AWS calls are deliberately opt-in. Set STOREVISION_S3_BUCKET and/or
STOREVISION_SNS_TOPIC_ARN (plus normal boto3 credentials) to make the agent
publish a real audit artifact / restock event; otherwise the response records
that the action was simulated.
"""

from __future__ import annotations

import base64
import json
import os
import uuid
from datetime import datetime, timezone
from typing import Any

import boto3
import cv2
import numpy as np
from fastapi import FastAPI, File, HTTPException, UploadFile
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel, Field

app = FastAPI(title="StoreVision AI", version="1.0.0")
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

MIN_PRODUCT_AREA = 900
RESTOCK_GAP_RATIO = 0.18
MAX_IMAGE_EDGE = 1600


class AuditResponse(BaseModel):
    shelf_health_score: float = Field(ge=0, le=100)
    items_detected: int = Field(ge=0)
    empty_slots: int = Field(ge=0)
    restock_required: bool
    detection_uncertain: bool
    agent_log: list[str]
    annotated_image: str


def _resize_for_analysis(image: np.ndarray) -> np.ndarray:
    height, width = image.shape[:2]
    scale = min(1.0, MAX_IMAGE_EDGE / max(height, width))
    if scale == 1:
        return image
    return cv2.resize(image, (int(width * scale), int(height * scale)))


def analyse_shelf(image: np.ndarray) -> tuple[np.ndarray, dict[str, Any], list[str]]:
    """Detect product clusters and gaps using adaptive, tier-aware geometry."""
    image = _resize_for_analysis(image)
    annotated = image.copy()
    gray = cv2.cvtColor(image, cv2.COLOR_BGR2GRAY)
    height, width = image.shape[:2]
    frame_area = height * width

    # This combination handles dark packages, bright labels, and uneven shelf lighting.
    blurred = cv2.GaussianBlur(gray, (5, 5), 0)
    adaptive = cv2.adaptiveThreshold(blurred, 255, cv2.ADAPTIVE_THRESH_GAUSSIAN_C, cv2.THRESH_BINARY_INV, 35, 5)
    _, otsu = cv2.threshold(blurred, 0, 255, cv2.THRESH_BINARY_INV + cv2.THRESH_OTSU)
    edges = cv2.Canny(blurred, 45, 130)
    mask = cv2.bitwise_or(adaptive, edges)
    mask = cv2.morphologyEx(mask, cv2.MORPH_CLOSE, cv2.getStructuringElement(cv2.MORPH_RECT, (7, 9)), iterations=2)
    mask = cv2.morphologyEx(mask, cv2.MORPH_OPEN, cv2.getStructuringElement(cv2.MORPH_RECT, (3, 5)))
    mask = cv2.bitwise_or(mask, cv2.morphologyEx(otsu, cv2.MORPH_OPEN, np.ones((3, 3), np.uint8)))
    contours, hierarchy = cv2.findContours(mask, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)

    min_box_area, max_box_area = frame_area * 0.005, frame_area * 0.25
    candidates: list[tuple[int, int, int, int]] = []
    for contour in contours:
        x, y, w, h = cv2.boundingRect(contour)
        if not min_box_area <= w * h <= max_box_area:
            continue
        if w < width * 0.025 or h < height * 0.08 or w / max(h, 1) > 3.5:
            continue
        candidates.append((x, y, w, h))

    candidates.sort(key=lambda box: box[2] * box[3], reverse=True)
    products: list[tuple[int, int, int, int]] = []
    for box in candidates:
        x1, y1, w1, h1 = box
        def overlaps(existing: tuple[int, int, int, int]) -> bool:
            x2, y2, w2, h2 = existing
            overlap = max(0, min(x1 + w1, x2 + w2) - max(x1, x2)) * max(0, min(y1 + h1, y2 + h2) - max(y1, y2))
            return overlap / max(w1 * h1 + w2 * h2 - overlap, 1) > 0.55
        if not any(overlaps(existing) for existing in products):
            products.append(box)

    # Group product clusters into horizontal shelf tiers, then evaluate each row.
    bands: list[list[tuple[int, int, int, int]]] = []
    for product in sorted(products, key=lambda b: b[1] + b[3] / 2):
        cy = product[1] + product[3] / 2
        for band in bands:
            average_y = sum(b[1] + b[3] / 2 for b in band) / len(band)
            average_h = float(np.mean([b[3] for b in band]))
            if abs(cy - average_y) < max(height * 0.08, average_h * 0.65):
                band.append(product)
                break
        else:
            bands.append([product])

    gaps: list[tuple[int, int, int, int]] = []
    for band in bands:
        if len(band) < 2:
            continue
        band.sort(key=lambda b: b[0])
        average_width = float(np.mean([b[2] for b in band]))
        top, bottom = max(0, min(b[1] for b in band) - 4), min(height, max(b[1] + b[3] for b in band) + 4)
        for left, right in zip(band, band[1:]):
            start, end = left[0] + left[2], right[0]
            if end - start > average_width * 1.2:
                gaps.append((start, top, end - start, bottom - top))

    for x, y, w, h in products:
        cv2.rectangle(annotated, (x, y), (x + w, y + h), (45, 210, 90), 2)
    for x, y, w, h in gaps:
        cv2.rectangle(annotated, (x, y), (x + w, y + h), (50, 55, 240), 3)

    occupied_width, gap_width = sum(w for _, _, w, _ in products), sum(w for _, _, w, _ in gaps)
    visual_content = bool(gray.std() > 16 or float(np.count_nonzero(edges)) / frame_area > 0.012)
    metrics = {
        "total_items": len(products), "empty_slots": len(gaps),
        "gap_ratio": round(gap_width / max(occupied_width + gap_width, 1), 3),
        "contours_examined": len(contours), "hierarchy_detected": hierarchy is not None,
        "detection_uncertain": len(products) == 0 and visual_content,
    }
    log = [
        "Perception: applied grayscale → Gaussian blur → adaptive/Otsu thresholding → CLOSE/OPEN morphology.",
        f"Perception: evaluated {len(contours)} external contours with dynamic {min_box_area:.0f}–{max_box_area:.0f}px² product limits.",
        f"Perception: found {metrics['total_items']} product clusters and {metrics['empty_slots']} shelf gaps (gap ratio {metrics['gap_ratio']:.1%}).",
    ]
    if metrics["detection_uncertain"]:
        log.append("Perception warning: detection uncertain — visible shelf detail was found but no reliable product clusters passed validation. Adjust framing, distance, or lighting.")
    return annotated, metrics, log


def invoke_aws_tools(payload: dict[str, Any], audit_id: str, log: list[str]) -> None:
    """Use AWS only when explicitly configured; failures remain observable in trace."""
    bucket = os.getenv("STOREVISION_S3_BUCKET")
    topic_arn = os.getenv("STOREVISION_SNS_TOPIC_ARN")
    if not bucket and not topic_arn:
        log.append("Action: RESTOCK alert simulated (configure STOREVISION_S3_BUCKET / STOREVISION_SNS_TOPIC_ARN to invoke AWS).")
        return
    try:
        region = os.getenv("AWS_REGION", "us-east-1")
        session = boto3.session.Session(region_name=region)
        if bucket:
            key = f"storevision-audits/{audit_id}.json"
            session.client("s3").put_object(
                Bucket=bucket, Key=key, Body=json.dumps(payload).encode(), ContentType="application/json"
            )
            log.append(f"Action: AWS S3 audit artifact uploaded to s3://{bucket}/{key}.")
        if topic_arn:
            session.client("sns").publish(
                TopicArn=topic_arn, Subject="StoreVision AI — restock required", Message=json.dumps(payload)
            )
            log.append("Action: AWS SNS restock alert published.")
    except Exception as exc:  # Request should still yield useful visual audit when cloud action fails.
        log.append(f"Action: AWS tool call failed safely: {type(exc).__name__}. Audit remains available for review.")


@app.get("/health")
def health() -> dict[str, str]:
    return {"status": "ok", "service": "StoreVision AI"}


@app.post("/api/audit-shelf", response_model=AuditResponse)
async def audit_shelf(
    file: UploadFile | None = File(default=None),
    image: UploadFile | None = File(default=None),
) -> AuditResponse:
    # `file` is the mobile client contract. Keep `image` as a compatibility
    # alias so older clients and curl examples do not break.
    uploaded_image = file or image
    if uploaded_image is None:
        raise HTTPException(status_code=422, detail="Provide a shelf photo in the 'file' multipart field.")
    if not uploaded_image.content_type or not uploaded_image.content_type.startswith("image/"):
        raise HTTPException(status_code=415, detail="Upload a JPEG, PNG, or other image file.")
    raw = await uploaded_image.read()
    if not raw:
        raise HTTPException(status_code=400, detail="The uploaded image is empty.")
    decoded = cv2.imdecode(np.frombuffer(raw, dtype=np.uint8), cv2.IMREAD_COLOR)
    if decoded is None:
        raise HTTPException(status_code=400, detail="The image could not be decoded.")

    annotated, metrics, log = analyse_shelf(decoded)
    detection_uncertain = metrics["detection_uncertain"]
    score = 0.0 if detection_uncertain else round(max(0.0, 100 - metrics["gap_ratio"] * 100 - metrics["empty_slots"] * 4), 1)
    restock_required = not detection_uncertain and (metrics["gap_ratio"] >= RESTOCK_GAP_RATIO or metrics["empty_slots"] >= 2)
    if detection_uncertain:
        log.append("Decision: detection uncertain — no health or restock decision was made. Retake a front-facing, well-lit shelf image.")
    else:
        log.append(
            f"Decision: shelf health is {score:.1f}/100; restock threshold ({RESTOCK_GAP_RATIO:.0%} gaps or 2 slots) {'breached' if restock_required else 'not breached'}."
        )
    audit_id = str(uuid.uuid4())
    payload = {"audit_id": audit_id, "timestamp": datetime.now(timezone.utc).isoformat(), **metrics, "shelf_health_score": score}
    if restock_required:
        invoke_aws_tools(payload, audit_id, log)
    else:
        log.append("Action: no replenishment tool call needed; " + ("manual review is required." if detection_uncertain else "shelf is within configured tolerance."))

    ok, encoded = cv2.imencode(".jpg", annotated, [cv2.IMWRITE_JPEG_QUALITY, 88])
    if not ok:
        raise HTTPException(status_code=500, detail="Could not encode annotated audit image.")
    return AuditResponse(
        shelf_health_score=score,
        items_detected=metrics["total_items"],
        empty_slots=metrics["empty_slots"],
        restock_required=restock_required,
        detection_uncertain=detection_uncertain,
        agent_log=log,
        annotated_image="data:image/jpeg;base64," + base64.b64encode(encoded.tobytes()).decode("ascii"),
    )
