"""Generate PINV PDFs for accounting-agent cases (prepaid, subscription, escalate)."""
from __future__ import annotations

from pathlib import Path

from reportlab.lib import colors
from reportlab.lib.pagesizes import A4
from reportlab.lib.styles import ParagraphStyle, getSampleStyleSheet
from reportlab.lib.units import mm
from reportlab.platypus import Paragraph, SimpleDocTemplate, Spacer, Table, TableStyle

OUT_DIR = Path(__file__).resolve().parent / "agent-cases"
VAT_RATE = 0.21
CURRENCY = "EUR"

BUYER = {
    "name": "Nova B.V.",
    "address": "Keizersgracht 1",
    "postcode": "1015 AA",
    "city": "Amsterdam",
    "country": "Netherlands",
}

NAVY = colors.HexColor("#1B365D")
TEAL = colors.HexColor("#2A6F7F")
LIGHT = colors.HexColor("#F4F7FA")
LINE = colors.HexColor("#D5DEE7")
MUTED = colors.HexColor("#5B6B7A")
AMBER = colors.HexColor("#FFF4D6")


def nl_vat(first_eight: str, establishment: str = "01") -> str:
    digits = [int(c) for c in first_eight]
    checksum = sum((9 - i) * digits[i] for i in range(8)) % 11
    if checksum == 10:
        raise ValueError(f"invalid RSIN prefix {first_eight}")
    return f"NL{first_eight}{checksum}B{establishment}"


SUPPLIERS = {
    "lumen": {
        "name": "Lumen Advisory B.V.",
        "email": "billing@lumen-advisory.example",
        "phone": "+31 20 555 0101",
        "website": "www.lumen-advisory.example",
        "address": "Herengracht 120",
        "postcode": "1015 BT",
        "city": "Amsterdam",
        "country": "Netherlands",
        "vat": nl_vat("12345678"),
        "iban": "NL13RABO0123456701",
        "bic": "RABONL2U",
        "kvk": "81234567",
    },
    "nimbus": {
        "name": "Nimbus Hosting B.V.",
        "email": "accounts@nimbus-hosting.example",
        "phone": "+31 20 555 0202",
        "website": "www.nimbus-hosting.example",
        "address": "Wibautstraat 80",
        "postcode": "1091 GP",
        "city": "Amsterdam",
        "country": "Netherlands",
        "vat": nl_vat("23456781"),
        "iban": "NL13RABO0123456702",
        "bic": "RABONL2U",
        "kvk": "82345678",
    },
    "orbit": {
        "name": "Orbit Cloud B.V.",
        "email": "invoices@orbit-cloud.example",
        "phone": "+31 20 555 0303",
        "website": "www.orbit-cloud.example",
        "address": "Overhoeksplein 2",
        "postcode": "1031 KS",
        "city": "Amsterdam",
        "country": "Netherlands",
        "vat": nl_vat("34567812"),
        "iban": "NL13RABO0123456703",
        "bic": "RABONL2U",
        "kvk": "83456789",
    },
    "northline": {
        "name": "Northline Support B.V.",
        "email": "finance@northline-support.example",
        "phone": "+31 20 555 0404",
        "website": "www.northline-support.example",
        "address": "Weesperstraat 61",
        "postcode": "1018 VN",
        "city": "Amsterdam",
        "country": "Netherlands",
        "vat": nl_vat("45678123"),
        "iban": "NL13RABO0123456704",
        "bic": "RABONL2U",
        "kvk": "84567890",
    },
    "kite": {
        "name": "Kite Software B.V.",
        "email": "billing@kite-software.example",
        "phone": "+31 20 555 0505",
        "website": "www.kite-software.example",
        "address": "Jodenbreestraat 4",
        "postcode": "1011 NK",
        "city": "Amsterdam",
        "country": "Netherlands",
        "vat": nl_vat("56781234"),
        "iban": "NL13RABO0123456705",
        "bic": "RABONL2U",
        "kvk": "85678901",
    },
}


CASES = [
    {
        "file": "C-INV-LM-2026-0731-lumen-prepaid-aug-oct.pdf",
        "case": "C",
        "expect": "create_prepaid_asset ~6000 (July close) — service is Aug–Oct",
        "supplier": "lumen",
        "invoice_number": "INV-LM-2026-0731",
        "invoice_date": "31/07/2026",
        "due_date": "30/08/2026",
        "your_ref": "prepaid Aug-Oct",
        "service_start": "2026-08-01",
        "service_end": "2026-10-31",
        "description": (
            "Consulting retainer 2026-08-01 to 2026-10-31 – Agent Test Prepaid C. "
            "This invoice covers three future months (invoice_months_covered = 3). "
            "Do not expense in July; create prepaid asset for the full net amount."
        ),
        "lines": [
            {
                "sku": "LM-RET-Q3",
                "description": "Consulting retainer Aug–Oct 2026 (service 2026-08-01 to 2026-10-31)",
                "qty": 3,
                "unit": 2000.00,
            }
        ],
    },
    {
        "file": "D-INV-NB-2026-0502-nimbus-prepaid-may-jul.pdf",
        "case": "D",
        "expect": "create_prepaid_asset 3600 and/or release_prepaid_asset ~1200 for July",
        "supplier": "nimbus",
        "invoice_number": "INV-NB-2026-0502",
        "invoice_date": "02/05/2026",
        "due_date": "01/06/2026",
        "your_ref": "prepaid May-Jul",
        "service_start": "2026-05-01",
        "service_end": "2026-07-31",
        "description": (
            "Quarterly hosting prepaid 2026-05-01 to 2026-07-31 – Agent Test Prepaid D. "
            "Invoice months covered = 3. Create prepaid once, then release the current-month slice."
        ),
        "lines": [
            {
                "sku": "NB-HOST-Q2",
                "description": "Managed hosting prepaid 2026-05-01 to 2026-07-31",
                "qty": 3,
                "unit": 1200.00,
            }
        ],
    },
    {
        "file": "E1-INV-OR-2026-0501-orbit-saas-may.pdf",
        "case": "E",
        "expect": "Pair with E2. July close: create_cost_accrual ~499 (no July invoice)",
        "supplier": "orbit",
        "invoice_number": "INV-OR-2026-0501",
        "invoice_date": "01/05/2026",
        "due_date": "31/05/2026",
        "your_ref": "Agent Test E",
        "service_start": "2026-05-01",
        "service_end": "2026-05-31",
        "description": "Monthly SaaS subscription – Agent Test E. Service 2026-05-01 to 2026-05-31.",
        "lines": [
            {
                "sku": "OR-SAAS-M",
                "description": "Monthly SaaS subscription – Agent Test E",
                "qty": 1,
                "unit": 499.00,
            }
        ],
    },
    {
        "file": "E2-INV-OR-2026-0601-orbit-saas-jun.pdf",
        "case": "E",
        "expect": "Pair with E1. Do not upload a July invoice for Orbit.",
        "supplier": "orbit",
        "invoice_number": "INV-OR-2026-0601",
        "invoice_date": "01/06/2026",
        "due_date": "30/06/2026",
        "your_ref": "Agent Test E",
        "service_start": "2026-06-01",
        "service_end": "2026-06-30",
        "description": "Monthly SaaS subscription – Agent Test E. Service 2026-06-01 to 2026-06-30.",
        "lines": [
            {
                "sku": "OR-SAAS-M",
                "description": "Monthly SaaS subscription – Agent Test E",
                "qty": 1,
                "unit": 499.00,
            }
        ],
    },
    {
        "file": "F1-INV-NL-2026-0615-northline-support.pdf",
        "case": "F1",
        "expect": "escalate_to_finance_controller — only one prior invoice, pattern unclear",
        "supplier": "northline",
        "invoice_number": "INV-NL-2026-0615",
        "invoice_date": "15/06/2026",
        "due_date": "15/07/2026",
        "your_ref": "Agent Test F1",
        "service_start": "2026-06-01",
        "service_end": "2026-06-30",
        "description": "Support retainer – Agent Test F1. One-off or continuing is not stated.",
        "lines": [
            {
                "sku": "NL-SUP-JUN",
                "description": "Support retainer – Agent Test F1",
                "qty": 1,
                "unit": 800.00,
            }
        ],
    },
    {
        "file": "F2a-INV-KT-2026-0501-kite-saas-cancelled.pdf",
        "case": "F2",
        "expect": "Pair with F2b. escalate — subscription ended, do not accrue July",
        "supplier": "kite",
        "invoice_number": "INV-KT-2026-0501",
        "invoice_date": "01/05/2026",
        "due_date": "31/05/2026",
        "your_ref": "Agent Test F2",
        "service_start": "2026-05-01",
        "service_end": "2026-05-31",
        "description": "Monthly SaaS – FINAL invoice cancelled – Agent Test F2. Contract ending.",
        "lines": [
            {
                "sku": "KT-SAAS-M",
                "description": "Monthly SaaS – FINAL invoice cancelled – Agent Test F2",
                "qty": 1,
                "unit": 499.00,
            }
        ],
    },
    {
        "file": "F2b-INV-KT-2026-0601-kite-saas-ended.pdf",
        "case": "F2",
        "expect": "Pair with F2a. escalate — contract ended",
        "supplier": "kite",
        "invoice_number": "INV-KT-2026-0601",
        "invoice_date": "01/06/2026",
        "due_date": "30/06/2026",
        "your_ref": "Agent Test F2",
        "service_start": "2026-06-01",
        "service_end": "2026-06-30",
        "description": "Monthly SaaS – contract ended – Agent Test F2. No further invoices.",
        "lines": [
            {
                "sku": "KT-SAAS-M",
                "description": "Monthly SaaS – contract ended – Agent Test F2",
                "qty": 1,
                "unit": 499.00,
            }
        ],
    },
]


def eur(amount: float) -> str:
    whole, frac = f"{amount:.2f}".split(".")
    grouped = f"{int(whole):,}".replace(",", ".")
    return f"EUR {grouped},{frac}"


def line_total(row: dict) -> float:
    return round(row["qty"] * row["unit"], 2)


def totals(lines: list[dict]) -> tuple[float, float, float]:
    net = round(sum(line_total(row) for row in lines), 2)
    vat = round(net * VAT_RATE, 2)
    return net, vat, round(net + vat, 2)


def styles():
    base = getSampleStyleSheet()
    return {
        "brand": ParagraphStyle("brand", parent=base["Normal"], fontName="Helvetica-Bold", fontSize=16, textColor=NAVY, leading=20),
        "meta": ParagraphStyle("meta", parent=base["Normal"], fontName="Helvetica", fontSize=8, textColor=MUTED, leading=11),
        "doc_type": ParagraphStyle("doc_type", parent=base["Normal"], fontName="Helvetica-Bold", fontSize=18, textColor=NAVY, alignment=2, leading=22),
        "label": ParagraphStyle("label", parent=base["Normal"], fontName="Helvetica-Bold", fontSize=8, textColor=TEAL, leading=11),
        "body": ParagraphStyle("body", parent=base["Normal"], fontName="Helvetica", fontSize=9, textColor=NAVY, leading=12),
        "small": ParagraphStyle("small", parent=base["Normal"], fontName="Helvetica", fontSize=8, textColor=NAVY, leading=11),
        "th": ParagraphStyle("th", parent=base["Normal"], fontName="Helvetica-Bold", fontSize=8, textColor=colors.white, leading=11),
        "td": ParagraphStyle("td", parent=base["Normal"], fontName="Helvetica", fontSize=8, textColor=NAVY, leading=11),
        "note": ParagraphStyle("note", parent=base["Normal"], fontName="Helvetica-Oblique", fontSize=8, textColor=MUTED, leading=11),
        "banner": ParagraphStyle("banner", parent=base["Normal"], fontName="Helvetica-Bold", fontSize=9, textColor=NAVY, leading=12),
    }


def party_block(s, label: str, lines: list[str]):
    return [Paragraph(label, s["label"]), Paragraph("<br/>".join(lines), s["body"])]


def meta_grid(s, rows: list[tuple[str, str]]):
    data = [[Paragraph(k, s["label"]), Paragraph(v, s["body"])] for k, v in rows]
    table = Table(data, colWidths=[42 * mm, 50 * mm])
    table.setStyle(
        TableStyle(
            [
                ("BACKGROUND", (0, 0), (-1, -1), LIGHT),
                ("BOX", (0, 0), (-1, -1), 0.4, LINE),
                ("INNERGRID", (0, 0), (-1, -1), 0.3, LINE),
                ("LEFTPADDING", (0, 0), (-1, -1), 6),
                ("RIGHTPADDING", (0, 0), (-1, -1), 6),
                ("TOPPADDING", (0, 0), (-1, -1), 4),
                ("BOTTOMPADDING", (0, 0), (-1, -1), 4),
                ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
            ]
        )
    )
    return table


def header(s, supplier: dict, number: str, invoice_date: str):
    left = [
        Paragraph(supplier["name"], s["brand"]),
        Paragraph(
            f"{supplier['address']}<br/>{supplier['postcode']} {supplier['city']}<br/>"
            f"{supplier['country']}<br/>VAT {supplier['vat']} &nbsp;|&nbsp; KvK {supplier['kvk']}<br/>"
            f"{supplier['email']}<br/>{supplier['phone']}<br/>{supplier['website']}",
            s["meta"],
        ),
    ]
    right = [
        Paragraph("PURCHASE INVOICE", s["doc_type"]),
        Paragraph(
            f"<b>Document no.</b> {number}<br/><b>Invoice date</b> {invoice_date}<br/>"
            f"<b>Currency</b> {CURRENCY}",
            s["small"],
        ),
    ]
    table = Table([[left, right]], colWidths=[110 * mm, 75 * mm])
    table.setStyle(
        TableStyle(
            [
                ("VALIGN", (0, 0), (-1, -1), "TOP"),
                ("LEFTPADDING", (0, 0), (-1, -1), 0),
                ("RIGHTPADDING", (0, 0), (-1, -1), 0),
                ("BOTTOMPADDING", (0, 0), (-1, -1), 8),
                ("LINEBELOW", (0, 0), (-1, 0), 1.5, NAVY),
            ]
        )
    )
    return table


def items_table(s, lines: list[dict]):
    data = [[
        Paragraph("SKU / Item code", s["th"]),
        Paragraph("Description", s["th"]),
        Paragraph("Qty", s["th"]),
        Paragraph("Unit price", s["th"]),
        Paragraph("Line total (excl. VAT)", s["th"]),
    ]]
    for row in lines:
        data.append([
            Paragraph(row["sku"], s["td"]),
            Paragraph(row["description"], s["td"]),
            Paragraph(str(row["qty"]), s["td"]),
            Paragraph(eur(row["unit"]), s["td"]),
            Paragraph(eur(line_total(row)), s["td"]),
        ])
    table = Table(data, colWidths=[32 * mm, 78 * mm, 16 * mm, 28 * mm, 32 * mm], repeatRows=1)
    table.setStyle(
        TableStyle(
            [
                ("BACKGROUND", (0, 0), (-1, 0), NAVY),
                ("ROWBACKGROUNDS", (0, 1), (-1, -1), [colors.white, LIGHT]),
                ("BOX", (0, 0), (-1, -1), 0.4, NAVY),
                ("INNERGRID", (0, 0), (-1, -1), 0.3, LINE),
                ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
                ("ALIGN", (2, 1), (-1, -1), "RIGHT"),
                ("ALIGN", (2, 0), (-1, 0), "RIGHT"),
                ("LEFTPADDING", (0, 0), (-1, -1), 6),
                ("RIGHTPADDING", (0, 0), (-1, -1), 6),
                ("TOPPADDING", (0, 0), (-1, -1), 5),
                ("BOTTOMPADDING", (0, 0), (-1, -1), 5),
            ]
        )
    )
    return table


def totals_table(s, net: float, vat: float, gross: float):
    white = ParagraphStyle("white", parent=s["td"], textColor=colors.white)
    data = [
        [Paragraph("Amount excluding VAT / Net amount / Subtotal", s["td"]), Paragraph(f"<b>{eur(net)}</b>", s["td"])],
        [Paragraph("VAT 21%", s["td"]), Paragraph(f"<b>{eur(vat)}</b>", s["td"])],
        [Paragraph("Total amount including VAT / Grand total", white), Paragraph(f"<b>{eur(gross)}</b>", white)],
    ]
    table = Table(data, colWidths=[95 * mm, 45 * mm])
    table.setStyle(
        TableStyle(
            [
                ("BACKGROUND", (0, 0), (-1, 1), LIGHT),
                ("BACKGROUND", (0, 2), (-1, 2), NAVY),
                ("BOX", (0, 0), (-1, -1), 0.4, NAVY),
                ("INNERGRID", (0, 0), (-1, -1), 0.3, LINE),
                ("ALIGN", (1, 0), (1, -1), "RIGHT"),
                ("LEFTPADDING", (0, 0), (-1, -1), 8),
                ("RIGHTPADDING", (0, 0), (-1, -1), 8),
                ("TOPPADDING", (0, 0), (-1, -1), 5),
                ("BOTTOMPADDING", (0, 0), (-1, -1), 5),
            ]
        )
    )
    wrap = Table([[Spacer(1, 1), table]], colWidths=[46 * mm, 140 * mm])
    wrap.setStyle(TableStyle([("LEFTPADDING", (0, 0), (-1, -1), 0), ("RIGHTPADDING", (0, 0), (-1, -1), 0)]))
    return wrap


def service_banner(s, spec: dict):
    months = spec.get("invoice_months_covered")
    if months is None and spec.get("service_start") and spec.get("service_end"):
        start_m = int(spec["service_start"][5:7])
        end_m = int(spec["service_end"][5:7])
        months = end_m - start_m + 1
    text = (
        f"SERVICE PERIOD: {spec['service_start']} to {spec['service_end']}<br/>"
        f"Invoice months covered: {months}. Currency {CURRENCY}."
    )
    inner = Table([[Paragraph(text, s["banner"])]], colWidths=[186 * mm])
    inner.setStyle(
        TableStyle(
            [
                ("BACKGROUND", (0, 0), (-1, -1), AMBER),
                ("BOX", (0, 0), (-1, -1), 0.8, TEAL),
                ("LEFTPADDING", (0, 0), (-1, -1), 8),
                ("RIGHTPADDING", (0, 0), (-1, -1), 8),
                ("TOPPADDING", (0, 0), (-1, -1), 6),
                ("BOTTOMPADDING", (0, 0), (-1, -1), 6),
            ]
        )
    )
    return inner


def build_invoice(spec: dict) -> list:
    s = styles()
    supplier = SUPPLIERS[spec["supplier"]]
    net, vat, gross = totals(spec["lines"])
    return [
        header(s, supplier, spec["invoice_number"], spec["invoice_date"]),
        Spacer(1, 6 * mm),
        Table(
            [[
                party_block(s, "BILL FROM / SUPPLIER / VENDOR", [
                    supplier["name"],
                    supplier["address"],
                    f"{supplier['postcode']} {supplier['city']}",
                    supplier["country"],
                    f"Email: {supplier['email']}",
                    f"Phone: {supplier['phone']}",
                    f"VAT / BTW: {supplier['vat']}",
                    f"Website: {supplier['website']}",
                ]),
                party_block(s, "BILL TO / CUSTOMER", [
                    BUYER["name"],
                    BUYER["address"],
                    f"{BUYER['postcode']} {BUYER['city']}",
                    BUYER["country"],
                ]),
                meta_grid(s, [
                    ("Invoice number", spec["invoice_number"]),
                    ("Invoice date", spec["invoice_date"]),
                    ("Due date", spec["due_date"]),
                    ("Your ref", spec["your_ref"]),
                    ("Service start", spec["service_start"]),
                    ("Service end", spec["service_end"]),
                    ("Case", f"Agent Test {spec['case']}"),
                ]),
            ]],
            colWidths=[68 * mm, 55 * mm, 63 * mm],
        ),
        Spacer(1, 5 * mm),
        service_banner(s, spec),
        Spacer(1, 4 * mm),
        Paragraph("Invoice description / notes", s["label"]),
        Paragraph(spec["description"], s["body"]),
        Spacer(1, 4 * mm),
        items_table(s, spec["lines"]),
        Spacer(1, 4 * mm),
        totals_table(s, net, vat, gross),
        Spacer(1, 5 * mm),
        Paragraph("Payment details", s["label"]),
        Paragraph(
            f"IBAN: {supplier['iban']}<br/>BIC: {supplier['bic']}<br/>"
            f"Bank: Rabobank<br/>Account name: {supplier['name']}<br/>"
            f"Subtotal / Amount excluding VAT / Amount without tax: {eur(net)}<br/>"
            f"VAT 21%: {eur(vat)}<br/>Total amount including VAT: {eur(gross)}",
            s["body"],
        ),
        Spacer(1, 3 * mm),
        Paragraph(
            "This is a tax invoice. Amounts shown in EUR. Use the net amount (excluding VAT) for accounting.",
            s["note"],
        ),
    ]


def main() -> None:
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    for spec in CASES:
        path = OUT_DIR / spec["file"]
        doc = SimpleDocTemplate(
            str(path),
            pagesize=A4,
            leftMargin=14 * mm,
            rightMargin=14 * mm,
            topMargin=12 * mm,
            bottomMargin=14 * mm,
            title=spec["invoice_number"],
            author=SUPPLIERS[spec["supplier"]]["name"],
        )
        doc.build(build_invoice(spec))
        net, vat, gross = totals(spec["lines"])
        print(f"Wrote {path.name}  net={net}  vat={vat}  gross={gross}  expect={spec['expect']}")


if __name__ == "__main__":
    main()
