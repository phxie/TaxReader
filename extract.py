"""
GPT-4o-based extraction of structured fields from a tax notice PDF.

The PDF is sent directly to the OpenAI Responses API (as base64 file
data) — no local OCR or text-extraction step. GPT-4o reads both the
extracted text and rendered page images internally.
"""

import base64
import json

from dotenv import load_dotenv
from openai import OpenAI

load_dotenv()

client = OpenAI()  # reads OPENAI_API_KEY from env

# All fields are nullable-and-required rather than optional: OpenAI's
# strict structured-output mode requires every property to be listed in
# "required", so "the model couldn't find this" is expressed as an
# explicit null rather than an absent field.
TAX_NOTICE_SCHEMA = {
    "type": "object",
    "properties": {
        "tax_year": {"type": ["integer", "null"], "description": "The tax year referenced in the notice"},
        "notice_type": {"type": ["string", "null"], "description": "e.g. CP2000, balance due, audit notice"},
        "amount_due": {"type": ["number", "null"], "description": "Total amount owed, if stated"},
        "issuing_agency": {"type": ["string", "null"], "description": "e.g. IRS, state department of revenue"},
        "summary": {"type": ["string", "null"], "description": "1-2 sentence plain-language summary"},
    },
    "required": ["tax_year", "notice_type", "amount_due", "issuing_agency", "summary"],
    "additionalProperties": False,
}


def extract_tax_fields(pdf_bytes: bytes, filename: str) -> dict:
    base64_pdf = base64.b64encode(pdf_bytes).decode("utf-8")

    response = client.responses.create(
        model="gpt-4o",
        input=[
            {
                "role": "user",
                "content": [
                    {
                        "type": "input_file",
                        "filename": filename,
                        "file_data": f"data:application/pdf;base64,{base64_pdf}",
                    },
                    {
                        "type": "input_text",
                        "text": "Extract the requested fields from this tax notice PDF.",
                    },
                ],
            }
        ],
        text={
            "format": {
                "type": "json_schema",
                "name": "tax_notice",
                "schema": TAX_NOTICE_SCHEMA,
                "strict": True,
            }
        },
    )

    if not response.output_text:
        raise ValueError("OpenAI returned no text content for this notice")

    return json.loads(response.output_text)
