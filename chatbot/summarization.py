"""OpenAI summarization for extracted attachment text."""
import json
import logging
from typing import Optional

from chatbot.config import OPENAI_API_KEY, OPENAI_MODEL_SMALL

logger = logging.getLogger(__name__)


def summarize_attachment_text(
    document_text: str,
    document_category: str,
) -> Optional[dict]:
    if not document_text.strip():
        return None
    if not OPENAI_API_KEY:
        logger.error("OPENAI_API_KEY is not configured")
        return None

    from openai import OpenAI

    client = OpenAI(api_key=OPENAI_API_KEY)
    completion = client.chat.completions.create(
        model=OPENAI_MODEL_SMALL,
        response_format={"type": "json_object"},
        messages=[
            {
                "role": "system",
                "content": (
                    'Summarize the document attachment text. Extract key information: parties, dates, '
                    'amounts, line items, reference numbers, VAT/tax, totals, and main terms. '
                    'Return strict JSON: {"combined_summary": string, "key_points": string[]}. '
                    "Keep combined_summary concise but complete."
                ),
            },
            {
                "role": "user",
                "content": (
                    f"Document category: {document_category}\n\n"
                    f"Attachment text:\n{document_text[:15000]}"
                ),
            },
        ],
    )
    raw = completion.choices[0].message.content
    if not raw:
        return None

    parsed = json.loads(raw)
    combined = (parsed.get("combined_summary") or parsed.get("summary") or "").strip()
    if not combined:
        return None
    key_points = [
        item.strip()
        for item in (parsed.get("key_points") or [])
        if isinstance(item, str) and item.strip()
    ]
    return {"combined_summary": combined, "key_points": key_points}
