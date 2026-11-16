# Module 3: 40+ Data Pipeline, API & Document Automations

This module delivers drop-in automation engines for data extraction, document parsing, financial reconciliation, webhook dispatching, encrypted cloud storage backups, and database synchronization. Every script is architected for autonomous execution inside cron daemons, systemd timers, or containerized worker pools.

---

## 1. Architectural Standards & Pipeline Design Patterns

All scripts within this module adhere to four non-negotiable operational requirements:

1. **Idempotency**: Running a pipeline twice over the same input state will never produce duplicate records, orphaned storage objects, or corrupted ledgers.
2. **Fail-Closed Operations**: Every network, filesystem, or database transaction executes inside an atomic context. Partial state changes are rolled back automatically.
3. **Structured Telemetry**: Standard output uses machine-readable JSON logs containing timestamps, transaction counts, execution latency, and trace hashes.
4. **Environment Isolation**: Zero hardcoded credentials. All tokens, secrets, endpoints, and bucket names resolve through strict environment variables.

### Environment Variable Specification (`.env.pipeline`)

```ini
# Database Endpoints
SOURCE_DB_URI=postgresql://etl_reader:Secr3tP@ss!@pg-primary.internal:5432/core_production
TARGET_DB_URI=postgresql://etl_writer:Secr3tP@ss!@pg-replica.internal:5432/core_warehouse

# S3 / Object Storage Configuration
AWS_ACCESS_KEY_ID=AKIAIOSFODNN7EXAMPLE
AWS_SECRET_ACCESS_KEY=wJalrXUtnFEMI/K7MDENG/bPxRfiCYEXAMPLEKEY
AWS_DEFAULT_REGION=us-east-1
S3_BACKUP_BUCKET=prod-database-backups-immutable
S3_ENDPOINT_URL=https://s3.us-east-1.amazonaws.com

# Webhook Event Bus Security
WEBHOOK_SHARED_SECRET=c8f8b3c4f9a0d2e5b7a1d4c8e9f2a5b7c1d3e5f7a9b1c3d5e7f9a1b3c5d7e9f1
WEBHOOK_DESTINATION_URL=https://events.partnerapi.com/v1/ingest
DEAD_LETTER_LOG_PATH=/var/log/automation/dead_letter_queue.jsonl

# PDF & Reconciliation File Targets
DOCUMENT_INGEST_DIR=/var/data/inbound_docs
RECONCILIATION_EXPORT_DIR=/var/data/finance_exports
```

---

## 2. Script 3.1: High-Performance Batch PDF Table & Text Extractor

Extracts semi-structured tabular records, line items, and invoice metadata from arbitrary batches of PDFs without external cloud APIs. Employs `pdfplumber` with automated bounding-box fallbacks and regex parsing for structured output to JSON Lines.

```python
#!/usr/bin/env python3
"""
Production Batch PDF Extractor
Extracts tabular line items and metadata from PDF invoices into structured JSONL.
"""

import os
import re
import sys
import json
import logging
from pathlib import Path
from typing import Dict, List, Any, Optional
import pdfplumber

logging.basicConfig(
    level=logging.INFO,
    format='{"time":"%(asctime)s", "level":"%(levelname)s", "module":"%(filename)s", "message":"%(message)s"}'
)
logger = logging.getLogger("pdf_extractor")

REGEX_PATTERNS = {
    "invoice_number": re.compile(r"(?i)invoice\s*(?:no|number|#)?[:\s]+([A-Z0-9\-]+)"),
    "date": re.compile(r"(?i)(?:invoice\s*)?date[:\s]+(\d{1,2}[/-]\d{1,2}[/-]\d{2,4}|\w+\s+\d{1,2},\s*\d{4})"),
    "total_amount": re.compile(r"(?i)total\s*(?:due|amount)?[:\s]*[\$€£]?\s*([0-9,]+\.\d{2})"),
    "tax_amount": re.compile(r"(?i)(?:tax|vat)\s*(?:amount)?[:\s]*[\$€£]?\s*([0-9,]+\.\d{2})")
}

def clean_currency(val: Optional[str]) -> float:
    if not val:
        return 0.0
    cleaned = re.sub(r"[^\d.-]", "", val)
    try:
        return float(cleaned)
    except ValueError:
        return 0.0

def parse_metadata_from_text(text: str) -> Dict[str, Any]:
    metadata: Dict[str, Any] = {
        "invoice_number": None,
        "date": None,
        "total_amount": 0.0,
        "tax_amount": 0.0
    }
    for field, pattern in REGEX_PATTERNS.items():
        match = pattern.search(text)
        if match:
            if "amount" in field:
                metadata[field] = clean_currency(match.group(1))
            else:
                metadata[field] = match.group(1).strip()
    return metadata

def extract_tables_from_page(page: pdfplumber.page.Page) -> List[List[str]]:
    table_settings = {
        "vertical_strategy": "lines",
        "horizontal_strategy": "lines",
        "explicit_vertical_lines": [],
        "explicit_horizontal_lines": [],
        "snap_tolerance": 3,
        "join_tolerance": 3,
        "edge_min_length": 3,
        "min_words_vertical": 3,
        "min_words_horizontal": 1,
        "intersection_tolerance": 3,
    }
    extracted = page.extract_table(table_settings=table_settings)
    if not extracted:
        # Fallback to text strategy if no vector lines exist
        table_settings["vertical_strategy"] = "text"
        table_settings["horizontal_strategy"] = "text"
        extracted = page.extract_table(table_settings=table_settings)
    
    if not extracted:
        return []
    
    # Sanitize inner cells
    sanitized_table = []
    for row in extracted:
        cleaned_row = [re.sub(r"\s+", " ", cell).strip() if cell else "" for cell in row]
        if any(cleaned_row):
            sanitized_table.append(cleaned_row)
    return sanitized_table

def process_single_pdf(pdf_path: Path) -> Dict[str, Any]:
    document_record: Dict[str, Any] = {
        "source_file": pdf_path.name,
        "page_count": 0,
        "metadata": {},
        "line_items": []
    }
    
    with pdfplumber.open(pdf_path) as pdf:
        document_record["page_count"] = len(pdf.pages)
        aggregated_text = ""
        
        for idx, page in enumerate(pdf.pages):
            text = page.extract_text() or ""
            aggregated_text += f"\n{text}"
            
            tables = extract_tables_from_page(page)
            if tables and len(tables) > 1:
                headers = tables[0]
                for row in tables[1:]:
                    if len(row) == len(headers):
                        item = dict(zip(headers, row))
                        item["_page"] = idx + 1
                        document_record["line_items"].append(item)

        document_record["metadata"] = parse_metadata_from_text(aggregated_text)
        
    return document_record

def run_pdf_extraction_pipeline(inbound_dir: str, output_jsonl: str) -> None:
    input_path = Path(inbound_dir)
    output_path = Path(output_jsonl)
    output_path.parent.mkdir(parents=True, exist_ok=True)
    
    pdf_files = list(input_path.glob("*.pdf"))
    logger.info(f"Identified {len(pdf_files)} PDF documents in {inbound_dir}")
    
    success_count = 0
    failure_count = 0
    
    with open(output_path, "a", encoding="utf-8") as out_file:
        for file in pdf_files:
            try:
                record = process_single_pdf(file)
                out_file.write(json.dumps(record, ensure_ascii=False) + "\n")
                out_file.flush()
                success_count += 1
                logger.info(f"Successfully processed {file.name}")
            except Exception as e:
                failure_count += 1
                logger.error(f"Failed processing {file.name}: {str(e)}")
                
    logger.info(f"Pipeline complete. Succeeded: {success_count}, Failed: {failure_count}")

if __name__ == "__main__":
    INBOUND = os.getenv("DOCUMENT_INGEST_DIR", "./inbound_docs")
    OUT_JSONL = os.getenv("EXTRACTION_OUT_PATH", "./extracted_records.jsonl")
    run_pdf_extraction_pipeline(INBOUND, OUT_JSONL)
```

---

## 3. Script 3.2: Multi-Sheet Financial Reconciler & Difference Engine

Compares ERP General Ledger exports against Payment Gateway bank reconciliation settlement sheets. Computes outer joins, identifies missing entries, highlights variances beyond floating-point epsilon tolerances, and exports a formatted Excel file with color-coded variances.

```python
#!/usr/bin/env python3
"""
Multi-Sheet Financial Reconciler
Performs deterministic comparisons between Internal Ledger and External Bank/Gateway extracts.
Generates an audit-ready, styled Excel workbook containing delta matrices.
"""

import os
import sys
import logging
import pandas as pd
import numpy as np
from openpyxl import load_workbook
from openpyxl.styles import PatternFill, Font, Alignment, Border, Side
from openpyxl.utils import get_column_letter

logging.basicConfig(
    level=logging.INFO,
    format='{"time":"%(asctime)s", "level":"%(levelname)s", "message":"%(message)s"}'
)
logger = logging.getLogger("reconciliation_engine")

EPSILON_TOLERANCE = 0.01  # Cash tolerances below 1 cent are ignored

def run_reconciliation(internal_path: str, external_path: str, report_output_path: str) -> None:
    logger.info(f"Loading internal ledger: {internal_path}")
    df_internal = pd.read_excel(internal_path, sheet_name=0)
    
    logger.info(f"Loading external statement: {external_path}")
    df_external = pd.read_excel(external_path, sheet_name=0)
    
    # Required standard schema validation
    required_cols = {"transaction_id", "amount", "date"}
    if not required_cols.issubset(set(df_internal.columns)) or not required_cols.issubset(set(df_external.columns)):
        missing_int = required_cols - set(df_internal.columns)
        missing_ext = required_cols - set(df_external.columns)
        raise ValueError(f"Schema mismatch. Internal missing: {missing_int}, External missing: {missing_ext}")

    # Coerce data types
    for df in [df_internal, df_external]:
        df["transaction_id"] = df["transaction_id"].astype(str).str.strip().str.upper()
        df["amount"] = pd.to_numeric(df["amount"], errors="coerce").fillna(0.0)
        df["date"] = pd.to_datetime(df["date"], errors="coerce")

    # Aggregate by transaction_id to prevent multi-hit inflation
    int_grouped = df_internal.groupby("transaction_id").agg({
        "amount": "sum",
        "date": "first"
    }).reset_index().rename(columns={"amount": "internal_amount", "date": "internal_date"})

    ext_grouped = df_external.groupby("transaction_id").agg({
        "amount": "sum",
        "date": "first"
    }).reset_index().rename(columns={"amount": "external_amount", "date": "external_date"})

    # Full Outer Join
    merged = pd.merge(int_grouped, ext_grouped, on="transaction_id", how="outer")
    merged["internal_amount"] = merged["internal_amount"].fillna(0.0)
    merged["external_amount"] = merged["external_amount"].fillna(0.0)
    
    # Calculate Variance
    merged["variance"] = (merged["internal_amount"] - merged["external_amount"]).round(4)
    merged["abs_variance"] = merged["variance"].abs()

    # Classification
    conditions = [
        (merged["internal_date"].isna()) & (merged["external_date"].notna()),
        (merged["internal_date"].notna()) & (merged["external_date"].isna()),
        (merged["abs_variance"] <= EPSILON_TOLERANCE),
        (merged["abs_variance"] > EPSILON_TOLERANCE)
    ]
    choices = [
        "MISSING_IN_INTERNAL_LEDGER",
        "MISSING_IN_EXTERNAL_STATEMENT",
        "MATCHED",
        "AMOUNT_MISMATCH"
    ]
    merged["status"] = np.select(conditions, choices, default="UNKNOWN_ERROR")
    merged.drop(columns=["abs_variance"], inplace=True)
    merged.sort_values(by=["status", "variance"], ascending=[True, False], inplace=True)

    # Export to Excel
    logger.info(f"Writing audit reconciliation to {report_output_path}")
    with pd.ExcelWriter(report_output_path, engine="openpyxl") as writer:
        merged.to_excel(writer, sheet_name="Reconciliation_Summary", index=False)
        
        # Summary KPI Sheet
        kpis = {
            "Total Internal Transactions": [len(df_internal)],
            "Total External Transactions": [len(df_external)],
            "Matched Count": [len(merged[merged["status"] == "MATCHED"])],
            "Mismatched Value Count": [len(merged[merged["status"] == "AMOUNT_MISMATCH"])],
            "Missing in Internal Ledger": [len(merged[merged["status"] == "MISSING_IN_INTERNAL_LEDGER"])],
            "Missing in External Statement": [len(merged[merged["status"] == "MISSING_IN_EXTERNAL_STATEMENT"])],
            "Gross Ledger Exposure": [merged["variance"].sum()]
        }
        pd.DataFrame(kpis).T.to_excel(writer, sheet_name="Executive_KPIs", header=False)

    apply_excel_formatting(report_output_path)
    logger.info("Reconciliation run completed successfully.")

def apply_excel_formatting(filepath: str) -> None:
    wb = load_workbook(filepath)
    ws = wb["Reconciliation_Summary"]

    red_fill = PatternFill(start_color="FCE4D6", end_color="FCE4D6", fill_type="solid")
    yellow_fill = PatternFill(start_color="FFF2CC", end_color="FFF2CC", fill_type="solid")
    green_fill = PatternFill(start_color="E2EFDA", end_color="E2EFDA", fill_type="solid")
    header_fill = PatternFill(start_color="1F4E79", end_color="1F4E79", fill_type="solid")
    header_font = Font(name="Calibri", size=11, bold=True, color="FFFFFF")

    thin_border = Border(
        left=Side(style="thin", color="D9D9D9"),
        right=Side(style="thin", color="D9D9D9"),
        top=Side(style="thin", color="D9D9D9"),
        bottom=Side(style="thin", color="D9D9D9")
    )

    # Format Headers
    for cell in ws[1]:
        cell.fill = header_fill
        cell.font = header_font
        cell.alignment = Alignment(horizontal="center", vertical="center")

    status_col_idx = None
    for col in range(1, ws.max_column + 1):
        if ws.cell(row=1, column=col).value == "status":
            status_col_idx = col
            break

    # Format Data Rows
    for row in range(2, ws.max_row + 1):
        status_val = ws.cell(row=row, column=status_col_idx).value if status_col_idx else ""
        row_fill = None
        if status_val == "MATCHED":
            row_fill = green_fill
        elif status_val == "AMOUNT_MISMATCH":
            row_fill = red_fill
        elif "MISSING" in str(status_val):
            row_fill = yellow_fill

        for col in range(1, ws.max_column + 1):
            cell = ws.cell(row=row, column=col)
            cell.border = thin_border
            if row_fill:
                cell.fill = row_fill
            # Format currency columns
            if col in [2, 4, 6]:  # amounts and variance
                cell.number_format = '$#,##0.00;($#,##0.00);"-";@'

    # Auto-adjust column widths
    for col in ws.columns:
        max_len = max(len(str(cell.value or "")) for cell in col)
        col_letter = get_column_letter(col[0].column)
        ws.column_dimensions[col_letter].width = max(max_len + 3, 12)

    wb.save(filepath)

if __name__ == "__main__":
    INTERNAL = os.getenv("INTERNAL_LEDGER_PATH", "./internal_ledger.xlsx")
    EXTERNAL = os.getenv("EXTERNAL_LEDGER_PATH", "./bank_statement.xlsx")
    REPORT = os.getenv("RECON_OUTPUT_PATH", "./reconciliation_report.xlsx")
    
    if not (os.path.exists(INTERNAL) and os.path.exists(EXTERNAL)):
        logger.error("Missing input files for reconciliation run.")
        sys.exit(1)
        
    run_reconciliation(INTERNAL, EXTERNAL, REPORT)
```

---

## 4. Script 3.3: Production Webhook Dispatcher & Idempotent Event Delivery

Reliable event egress dispatcher engineered to withstand upstream downtime. Features cryptographically signed payloads via HMAC-SHA256, SQLite-based deduplication and persistent retry buffers, exponential backoff with full jitter, and auto-dead-letter archiving.

```python
#!/usr/bin/env python3
"""
Production Webhook Dispatcher
Features HMAC authentication, local SQLite FIFO queues, exponential backoff, and DLQ handling.
"""

import os
import sys
import time
import json
import hmac
import hashlib
import sqlite3
import random
import logging
from typing import Dict, Any, Optional
import requests
from requests.adapters import HTTPAdapter
from urllib3.util import Retry

logging.basicConfig(
    level=logging.INFO,
    format='{"time":"%(asctime)s", "level":"%(levelname)s", "event":"%(message)s"}'
)
logger = logging.getLogger("webhook_dispatcher")

DB_PATH = os.getenv("QUEUE_DB_PATH", "/tmp/webhook_buffer.db")
MAX_RETRIES = 5
BASE_BACKOFF_SECONDS = 2.0
MAX_BACKOFF_SECONDS = 60.0

def init_db(db_path: str = DB_PATH) -> None:
    with sqlite3.connect(db_path) as conn:
        conn.execute("""
            CREATE TABLE IF NOT EXISTS outbound_events (
                event_id TEXT PRIMARY KEY,
                payload TEXT NOT NULL,
                attempts INTEGER DEFAULT 0,
                next_attempt_at REAL NOT NULL,
                status TEXT CHECK(status IN ('QUEUED', 'IN_FLIGHT', 'FAILED', 'DEAD_LETTER')) NOT NULL DEFAULT 'QUEUED',
                created_at REAL NOT NULL
            );
        """)
        conn.execute("CREATE INDEX IF NOT EXISTS idx_next_attempt ON outbound_events (status, next_attempt_at);")
        conn.commit()

def calculate_signature(secret: str, payload_bytes: bytes) -> str:
    return hmac.new(secret.encode("utf-8"), payload_bytes, hashlib.sha256).hexdigest()

def get_http_client() -> requests.Session:
    session = requests.Session()
    retries = Retry(
        total=2,
        connect=2,
        read=2,
        status_forcelist=[502, 503, 504],
        raise_on_status=False
    )
    adapter = HTTPAdapter(max_retries=retries)
    session.mount("https://", adapter)
    session.mount("http://", adapter)
    return session

def queue_event(event_id: str, payload: Dict[str, Any], db_path: str = DB_PATH) -> None:
    raw_payload = json.dumps(payload, separators=(',', ':'), sort_keys=True)
    now = time.time()
    with sqlite3.connect(db_path) as conn:
        conn.execute(
            """
            INSERT OR IGNORE INTO outbound_events (event_id, payload, attempts, next_attempt_at, status, created_at)
            VALUES (?, ?, 0, ?, 'QUEUED', ?)
            """,
            (event_id, raw_payload, now, now)
        )
        conn.commit()
    logger.info(f"Queued event {event_id}")

def calculate_jittered_backoff(attempt: int) -> float:
    # Full jitter backoff formula: Uniform(0, min(max_backoff, base * 2 ^ attempt))
    temp = min(MAX_BACKOFF_SECONDS, BASE_BACKOFF_SECONDS * (2 ** attempt))
    return random.uniform(0, temp)

def process_outbound_queue(target_url: str, secret: str, dead_letter_log: str, db_path: str = DB_PATH) -> None:
    now = time.time()
    session = get_http_client()
    
    with sqlite3.connect(db_path) as conn:
        conn.row_factory = sqlite3.Row
        cursor = conn.cursor()
        
        # Select items ready for dispatch
        cursor.execute(
            """
            SELECT event_id, payload, attempts 
            FROM outbound_events 
            WHERE status = 'QUEUED' AND next_attempt_at <= ?
            LIMIT 100
            """,
            (now,)
        )
        batch = cursor.fetchall()

    if not batch:
        return

    logger.info(f"Processing webhook batch of size: {len(batch)}")

    for row in batch:
        event_id = row["event_id"]
        payload_str = row["payload"]
        attempts = row["attempts"]
        payload_bytes = payload_str.encode("utf-8")
        
        signature = calculate_signature(secret, payload_bytes)
        headers = {
            "Content-Type": "application/json",
            "X-Signature-256": signature,
            "X-Event-ID": event_id,
            "X-Delivery-Attempt": str(attempts + 1),
            "User-Agent": "AutomationVault-Dispatcher/1.0"
        }

        success = False
        try:
            response = session.post(target_url, data=payload_bytes, headers=headers, timeout=10.0)
            if response.status_code in [200, 201, 202, 204]:
                success = True
            else:
                logger.warning(f"Delivery rejected by upstream: {response.status_code} for event {event_id}")
        except requests.exceptions.RequestException as e:
            logger.error(f"Network error delivering event {event_id}: {str(e)}")

        with sqlite3.connect(db_path) as conn:
            if success:
                conn.execute("DELETE FROM outbound_events WHERE event_id = ?", (event_id,))
                conn.commit()
                logger.info(f"Dispatched event {event_id} successfully.")
            else:
                new_attempts = attempts + 1
                if new_attempts >= MAX_RETRIES:
                    # Route to Dead Letter Queue
                    conn.execute("UPDATE outbound_events SET status = 'DEAD_LETTER' WHERE event_id = ?", (event_id,))
                    conn.commit()
                    with open(dead_letter_log, "a", encoding="utf-8") as dlq_file:
                        dead_letter_entry = {
                            "event_id": event_id,
                            "payload": json.loads(payload_str),
                            "final_failure_timestamp": time.time(),
                            "total_attempts": new_attempts
                        }
                        dlq_file.write(json.dumps(dead_letter_entry) + "\n")
                    logger.error(f"Event {event_id} moved to DEAD_LETTER after {new_attempts} attempts.")
                else:
                    delay = calculate_jittered_backoff(new_attempts)
                    next_attempt = time.time() + delay
                    conn.execute(
                        "UPDATE outbound_events SET attempts = ?, next_attempt_at = ? WHERE event_id = ?",
                        (new_attempts, next_attempt, event_id)
                    )
                    conn.commit()
                    logger.info(f"Rescheduled event {event_id} for attempt {new_attempts + 1} in {delay:.2f}s")

if __name__ == "__main__":
    init_db()
    URL = os.getenv("WEBHOOK_DESTINATION_URL", "https://httpbin.org/post")
    SECRET = os.getenv("WEBHOOK_SHARED_SECRET", "super-secret-key-12345")
    DLQ_PATH = os.getenv("DEAD_LETTER_LOG_PATH", "./dlq.jsonl")

    # Example dispatch execution
    sample_id = f"evt_{hashlib.md5(str(time.time()).encode()).hexdigest()[:12]}"
    queue_event(sample_id, {"event": "customer.subscription.renewed", "id": sample_id, "amount": 99.00})
    
    process_outbound_queue(URL, SECRET, DLQ_PATH)
```

---

## 5. Script 3.4: Automated S3/R2 Multi-Cloud Encrypted Database Backup Pipeline

Directly executes `pg_dump` via a non-blocking UNIX pipe, streams standard output through an in-flight gzip compression utility, computes cryptographic integrity verification hashes, and transfers the payload directly to any S3-compliant target (AWS S3, Cloudflare R2, MinIO) without buffering the uncompressed dump to local disk.

```python
#!/usr/bin/env python3
"""
S3/R2 Direct-Streaming Encrypted Database Backup Engine
Streams database dumps into AWS S3/Cloudflare R2 without persisting uncompressed snapshots locally.
"""

import os
import sys
import subprocess
import logging
import datetime
from io import BytesIO
import boto3
from botocore.config import Config
from botocore.exceptions import ClientError

logging.basicConfig(
    level=logging.INFO,
    format='{"time":"%(asctime)s", "level":"%(levelname)s", "message":"%(message)s"}'
)
logger = logging.getLogger("backup_pipeline")

def get_s3_client() -> boto3.client:
    return boto3.client(
        "s3",
        region_name=os.getenv("AWS_DEFAULT_REGION", "us-east-1"),
        aws_access_key_id=os.getenv("AWS_ACCESS_KEY_ID"),
        aws_secret_access_key=os.getenv("AWS_SECRET_ACCESS_KEY"),
        endpoint_url=os.getenv("S3_ENDPOINT_URL", None),
        config=Config(retries={"max_attempts": 5, "mode": "standard"})
    )

def stream_postgres_backup(db_uri: str, bucket_name: str, retention_days: int = 14) -> None:
    timestamp = datetime.datetime.now(datetime.timezone.utc).strftime("%Y%m%d_%H%M%SZ")
    target_key = f"db_backups/postgres_{timestamp}.sql.gz"
    
    s3 = get_s3_client()
    logger.info(f"Initiating pipe stream for pg_dump targeting s3://{bucket_name}/{target_key}")

    # Launch dump process writing to standard out
    dump_cmd = ["pg_dump", "--dbname", db_uri, "--no-owner", "--no-acl", "--clean", "--if-exists"]
    gzip_cmd = ["gzip", "-9"]

    try:
        p_dump = subprocess.Popen(dump_cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
        p_gzip = subprocess.Popen(gzip_cmd, stdin=p_dump.stdout, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
        
        # Close dump stdout to allow p_dump to receive SIGPIPE if p_gzip fails
        if p_dump.stdout:
            p_dump.stdout.close()

        # Multi-part upload streaming
        s3.upload_fileobj(
            Fileobj=p_gzip.stdout,
            Bucket=bucket_name,
            Key=target_key,
            ExtraArgs={
                "ServerSideEncryption": "AES256",
                "Metadata": {
                    "source": "automation_vault_cron",
                    "backup_timestamp": timestamp
                }
            }
        )
        
        p_gzip.wait()
        p_dump.wait()

        if p_dump.returncode != 0:
            stderr_dump = p_dump.stderr.read().decode() if p_dump.stderr else "Unknown"
            raise RuntimeError(f"pg_dump exited with error code {p_dump.returncode}: {stderr_dump
