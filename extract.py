"""
Claude Haiku-based extraction of structured fields from a tax notice PDF.

The PDF is sent directly to the Messages API (as base64 document data) —
no local OCR or text-extraction step. Claude reads the PDF's embedded text
and rendered page images internally.
"""

import base64
import json

from anthropic import Anthropic
from dotenv import load_dotenv

load_dotenv()

client = Anthropic()  # reads ANTHROPIC_API_KEY from env

MODEL = "claude-haiku-4-5"

TAX_NOTICE_SCHEMA = {
    "type": "object",
    "properties": {
        "notice_date": {"type": ["string", "null"], "description": "Date printed on the notice, in YYYY-MM-DD format if determinable"},
        "tax_year": {"type": ["integer", "null"], "description": "The tax year referenced in the notice"},
        "jurisdiction": {"type": ["string", "null"], "description": "e.g. IRS, California Franchise Tax Board, etc."},
        "issue_summary": {"type": "string", "description": "1-2 sentence plain-language summary of the issue"},
        "amount_due": {"type": ["number", "null"], "description": "Total amount owed, if stated"},
    },
    "required": ["issue_summary"],
    "additionalProperties": False,
}


def extract_tax_fields(pdf_bytes: bytes, filename: str) -> dict:
    base64_pdf = base64.standard_b64encode(pdf_bytes).decode("utf-8")

    response = client.messages.create(
        model=MODEL,
        max_tokens=1024,
        messages=[
            {
                "role": "user",
                "content": [
                    {
                        "type": "document",
                        "title": filename,
                        "source": {
                            "type": "base64",
                            "media_type": "application/pdf",
                            "data": base64_pdf,
                        },
                    },
                    {
                        "type": "text",
                        "text": "Extract the requested fields from this tax notice PDF.",
                    },
                ],
            }
        ],
        output_config={
            "format": {
                "type": "json_schema",
                "schema": TAX_NOTICE_SCHEMA,
            }
        },
    )

    text = next((block.text for block in response.content if block.type == "text"), None)
    if text is None:
        raise ValueError("Claude returned no text content for this notice")

    return json.loads(text)
