"""Generate matching PO, delivery note, and purchase invoice PDFs for agent testing."""
from __future__ import annotations

from pathlib import Path

from reportlab.lib import colors
from reportlab.lib.pagesizes import A4
from reportlab.lib.styles import ParagraphStyle, getSampleStyleSheet
from reportlab.lib.units import mm
from reportlab.platypus import (
    Paragraph,
    SimpleDocTemplate,
    Spacer,
    Table,
    TableStyle,
)

OUT_DIR = Path(__file__).resolve().parent / "helix-packaging"

SUPPLIER = {
    "name": "Helix Packaging B.V.",
    "email": "accounts@helix-packaging.example",
    "phone": "+31 20 123 4567",
    "website": "www.helix-packaging.example",
    "address": "Westhavenweg 88",
    "postcode": "1042 AG",
    "city": "Amsterdam",
    "country": "Netherlands",
    "vat": "NL860412349B01",  # 11-proef check digit; Exact rejects NL860412345B01
    "iban": "NL12RABO0123456789",
    "bic": "RABONL2U",
    "kvk": "87654321",
}

BUYER = {
    "name": "Nova B.V.",
    "address": "Keizersgracht 1",
    "postcode": "1015 AA",
    "city": "Amsterdam",
    "country": "Netherlands",
}

PO_NUMBER = "PO-HX-2026-0041"
# Nova-assigned PO number after upload — delivery matching uses this.
SYSTEM_PO_NUMBER = "PO-CE-2026-0035"
DN_NUMBER = "DN-HX-2026-0730"
INV_NUMBER = "INV-HX-2026-0802"
CURRENCY = "EUR"
GL_NOTE = "Charge to GL 5540"

LINES = [
    {
        "sku": "HX-CTN-643",
        "description": "Corrugated shipping cartons 600x400x300 mm",
        "qty": 80,
        "unit": 95.00,
    },
    {
        "sku": "HX-FILM-23",
        "description": "Stretch wrap film 23µm 500mm",
        "qty": 40,
        "unit": 95.00,
    },
]

NAVY = colors.HexColor("#1B365D")
TEAL = colors.HexColor("#2A6F7F")
LIGHT = colors.HexColor("#F4F7FA")
LINE = colors.HexColor("#D5DEE7")
MUTED = colors.HexColor("#5B6B7A")


def eur(amount: float) -> str:
    whole, frac = f"{amount:.2f}".split(".")
    grouped = f"{int(whole):,}".replace(",", ".")
    return f"EUR {grouped},{frac}"


def line_total(row: dict) -> float:
    return round(row["qty"] * row["unit"], 2)


def totals() -> tuple[float, float, float]:
    net = round(sum(line_total(row) for row in LINES), 2)
    vat = round(net * 0.21, 2)
    return net, vat, round(net + vat, 2)


def styles():
    base = getSampleStyleSheet()
    return {
        "brand": ParagraphStyle(
            "brand",
            parent=base["Normal"],
            fontName="Helvetica-Bold",
            fontSize=16,
            textColor=NAVY,
            leading=20,
        ),
        "meta": ParagraphStyle(
            "meta",
            parent=base["Normal"],
            fontName="Helvetica",
            fontSize=8,
            textColor=MUTED,
            leading=11,
        ),
        "doc_type": ParagraphStyle(
            "doc_type",
            parent=base["Normal"],
            fontName="Helvetica-Bold",
            fontSize=18,
            textColor=NAVY,
            alignment=2,
            leading=22,
        ),
        "label": ParagraphStyle(
            "label",
            parent=base["Normal"],
            fontName="Helvetica-Bold",
            fontSize=8,
            textColor=TEAL,
            leading=11,
        ),
        "body": ParagraphStyle(
            "body",
            parent=base["Normal"],
            fontName="Helvetica",
            fontSize=9,
            textColor=NAVY,
            leading=12,
        ),
        "small": ParagraphStyle(
            "small",
            parent=base["Normal"],
            fontName="Helvetica",
            fontSize=8,
            textColor=NAVY,
            leading=11,
        ),
        "th": ParagraphStyle(
            "th",
            parent=base["Normal"],
            fontName="Helvetica-Bold",
            fontSize=8,
            textColor=colors.white,
            leading=11,
        ),
        "td": ParagraphStyle(
            "td",
            parent=base["Normal"],
            fontName="Helvetica",
            fontSize=8,
            textColor=NAVY,
            leading=11,
        ),
        "note": ParagraphStyle(
            "note",
            parent=base["Normal"],
            fontName="Helvetica-Oblique",
            fontSize=8,
            textColor=MUTED,
            leading=11,
        ),
    }


def header(s, title: str, number: str, date_label: str, date_value: str):
    left = [
        Paragraph(SUPPLIER["name"], s["brand"]),
        Paragraph(
            f"{SUPPLIER['address']}<br/>{SUPPLIER['postcode']} {SUPPLIER['city']}<br/>"
            f"{SUPPLIER['country']}<br/>VAT {SUPPLIER['vat']} &nbsp;|&nbsp; KvK {SUPPLIER['kvk']}<br/>"
            f"{SUPPLIER['email']}<br/>{SUPPLIER['phone']}<br/>{SUPPLIER['website']}",
            s["meta"],
        ),
    ]
    right = [
        Paragraph(title, s["doc_type"]),
        Paragraph(
            f"<b>Document no.</b> {number}<br/><b>{date_label}</b> {date_value}<br/>"
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


def party_block(s, label: str, lines: list[str]):
    return [
        Paragraph(label, s["label"]),
        Paragraph("<br/>".join(lines), s["body"]),
    ]


def meta_grid(s, rows: list[tuple[str, str]]):
    data = [
        [Paragraph(k, s["label"]), Paragraph(v, s["body"])] for k, v in rows
    ]
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


def items_table(s, include_prices: bool):
    header_row = [
        Paragraph("SKU / Item code", s["th"]),
        Paragraph("Description", s["th"]),
        Paragraph("Qty", s["th"]),
    ]
    widths = [38 * mm, 95 * mm, 18 * mm]
    if include_prices:
        header_row += [
            Paragraph("Unit price", s["th"]),
            Paragraph("Line total (excl. VAT)", s["th"]),
        ]
        widths = [32 * mm, 78 * mm, 16 * mm, 28 * mm, 32 * mm]

    data = [header_row]
    for row in LINES:
        cells = [
            Paragraph(row["sku"], s["td"]),
            Paragraph(row["description"], s["td"]),
            Paragraph(str(row["qty"]), s["td"]),
        ]
        if include_prices:
            cells += [
                Paragraph(eur(row["unit"]), s["td"]),
                Paragraph(eur(line_total(row)), s["td"]),
            ]
        data.append(cells)

    table = Table(data, colWidths=widths, repeatRows=1)
    table.setStyle(
        TableStyle(
            [
                ("BACKGROUND", (0, 0), (-1, 0), NAVY),
                ("BACKGROUND", (0, 1), (-1, -1), colors.white),
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
    rows = [
        ["Amount excluding VAT / Net amount", eur(net)],
        ["VAT 21%", eur(vat)],
        ["Total amount including VAT / Grand total", eur(gross)],
    ]
    data = [
        [Paragraph(label, s["td"]), Paragraph(f"<b>{value}</b>", s["td"])]
        for label, value in rows
    ]
    table = Table(data, colWidths=[95 * mm, 45 * mm])
    table.setStyle(
        TableStyle(
            [
                ("BACKGROUND", (0, 0), (-1, 1), LIGHT),
                ("BACKGROUND", (0, 2), (-1, 2), NAVY),
                ("TEXTCOLOR", (0, 2), (-1, 2), colors.white),
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
    # White text on last row: rebuild last cells with white style
    white = ParagraphStyle("white", parent=s["td"], textColor=colors.white)
    data[2] = [
        Paragraph("Total amount including VAT / Grand total", white),
        Paragraph(f"<b>{eur(gross)}</b>", white),
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
    wrap.setStyle(
        TableStyle(
            [
                ("VALIGN", (0, 0), (-1, -1), "TOP"),
                ("LEFTPADDING", (0, 0), (-1, -1), 0),
                ("RIGHTPADDING", (0, 0), (-1, -1), 0),
            ]
        )
    )
    return wrap


def build_pdf(path: Path, story: list) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    doc = SimpleDocTemplate(
        str(path),
        pagesize=A4,
        leftMargin=14 * mm,
        rightMargin=14 * mm,
        topMargin=12 * mm,
        bottomMargin=14 * mm,
        title=path.stem,
        author=SUPPLIER["name"],
    )
    doc.build(story)


def purchase_order(s):
    net, vat, gross = totals()
    story = [
        header(s, "PURCHASE ORDER", PO_NUMBER, "Order date", "29/07/2026"),
        Spacer(1, 8 * mm),
        Table(
            [
                [
                    party_block(
                        s,
                        "SUPPLIER / VENDOR",
                        [
                            SUPPLIER["name"],
                            SUPPLIER["address"],
                            f"{SUPPLIER['postcode']} {SUPPLIER['city']}",
                            SUPPLIER["country"],
                            f"Email: {SUPPLIER['email']}",
                            f"VAT: {SUPPLIER['vat']}",
                            f"IBAN: {SUPPLIER['iban']}",
                        ],
                    ),
                    party_block(
                        s,
                        "BUYER / BILL TO",
                        [
                            BUYER["name"],
                            BUYER["address"],
                            f"{BUYER['postcode']} {BUYER['city']}",
                            BUYER["country"],
                        ],
                    ),
                    meta_grid(
                        s,
                        [
                            ("Purchase order number", PO_NUMBER),
                            ("Order date", "29/07/2026"),
                            ("Expected delivery date", "30/07/2026"),
                            ("Currency", CURRENCY),
                            ("Payment terms", "30 days from invoice"),
                        ],
                    ),
                ]
            ],
            colWidths=[68 * mm, 55 * mm, 63 * mm],
        ),
        Spacer(1, 6 * mm),
        Paragraph("Description / purpose", s["label"]),
        Paragraph(
            "Warehouse packaging materials – Agent Test Helix GRNI. "
            f"{GL_NOTE}.",
            s["body"],
        ),
        Spacer(1, 4 * mm),
        items_table(s, include_prices=True),
        Spacer(1, 4 * mm),
        totals_table(s, net, vat, gross),
        Spacer(1, 6 * mm),
        Paragraph(
            "POs are recorded net of VAT. Amount excluding VAT (net amount): "
            f"<b>{eur(net)}</b>. VAT is recoverable input tax and is not a period cost.",
            s["note"],
        ),
        Paragraph(
            "Please confirm this purchase order and deliver to the buyer warehouse on the expected delivery date.",
            s["note"],
        ),
    ]
    return story


def delivery_note(s):
    net, _, _ = totals()
    story = [
        header(s, "DELIVERY NOTE", DN_NUMBER, "Delivery date", "30/07/2026"),
        Spacer(1, 8 * mm),
        Table(
            [
                [
                    party_block(
                        s,
                        "SHIPPED FROM / SUPPLIER",
                        [
                            SUPPLIER["name"],
                            SUPPLIER["address"],
                            f"{SUPPLIER['postcode']} {SUPPLIER['city']}",
                            SUPPLIER["country"],
                            f"Email: {SUPPLIER['email']}",
                        ],
                    ),
                    party_block(
                        s,
                        "DELIVER TO",
                        [
                            BUYER["name"],
                            "Goods inwards – Warehouse A",
                            BUYER["address"],
                            f"{BUYER['postcode']} {BUYER['city']}",
                            BUYER["country"],
                        ],
                    ),
                    meta_grid(
                        s,
                        [
                            ("Delivery note #", DN_NUMBER),
                            ("Receipt number", DN_NUMBER),
                            ("Purchase order number", SYSTEM_PO_NUMBER),
                            ("PO #", SYSTEM_PO_NUMBER),
                            ("Delivery date", "30/07/2026"),
                            ("Shipped", "30/07/2026"),
                        ],
                    ),
                ]
            ],
            colWidths=[68 * mm, 55 * mm, 63 * mm],
        ),
        Spacer(1, 6 * mm),
        Paragraph("Goods receipt / packing slip", s["label"]),
        Paragraph(
            f"All items on purchase order {SYSTEM_PO_NUMBER} were delivered in full. "
            "Receipt status: Complete. Quantity received matches ordered quantity.",
            s["body"],
        ),
        Spacer(1, 4 * mm),
        items_table(s, include_prices=True),
        Spacer(1, 4 * mm),
        Paragraph(
            f"Delivery value excluding VAT (for matching): <b>{eur(net)}</b>. "
            f"Currency: {CURRENCY}. This delivery note is not a tax invoice.",
            s["note"],
        ),
        Paragraph(
            "Received in good condition. No shortages or damages reported.",
            s["note"],
        ),
    ]
    return story


def purchase_invoice(s):
    net, vat, gross = totals()
    story = [
        header(s, "PURCHASE INVOICE", INV_NUMBER, "Invoice date", "02/08/2026"),
        Spacer(1, 8 * mm),
        Table(
            [
                [
                    party_block(
                        s,
                        "BILL FROM / SUPPLIER / VENDOR",
                        [
                            SUPPLIER["name"],
                            SUPPLIER["address"],
                            f"{SUPPLIER['postcode']} {SUPPLIER['city']}",
                            SUPPLIER["country"],
                            f"Email: {SUPPLIER['email']}",
                            f"Phone: {SUPPLIER['phone']}",
                            f"VAT / BTW: {SUPPLIER['vat']}",
                            f"Website: {SUPPLIER['website']}",
                        ],
                    ),
                    party_block(
                        s,
                        "BILL TO / CUSTOMER",
                        [
                            BUYER["name"],
                            BUYER["address"],
                            f"{BUYER['postcode']} {BUYER['city']}",
                            BUYER["country"],
                        ],
                    ),
                    meta_grid(
                        s,
                        [
                            ("Invoice number", INV_NUMBER),
                            ("Invoice date", "02/08/2026"),
                            ("Due date", "01/09/2026"),
                            ("Purchase order number", PO_NUMBER),
                            ("PO Number", PO_NUMBER),
                            ("Your ref / Order Ref", PO_NUMBER),
                            ("Delivery note", DN_NUMBER),
                        ],
                    ),
                ]
            ],
            colWidths=[68 * mm, 55 * mm, 63 * mm],
        ),
        Spacer(1, 6 * mm),
        Paragraph("Invoice description / notes", s["label"]),
        Paragraph(
            "Invoice for warehouse packaging materials delivered 30/07/2026 against "
            f"{PO_NUMBER}. Payment terms: 30 days. Please pay by bank transfer.",
            s["body"],
        ),
        Spacer(1, 4 * mm),
        items_table(s, include_prices=True),
        Spacer(1, 4 * mm),
        totals_table(s, net, vat, gross),
        Spacer(1, 6 * mm),
        Paragraph("Payment details", s["label"]),
        Paragraph(
            f"IBAN: {SUPPLIER['iban']}<br/>BIC: {SUPPLIER['bic']}<br/>"
            f"Bank: Rabobank<br/>Account name: {SUPPLIER['name']}<br/>"
            f"Subtotal / Amount excluding VAT / Amount without tax: {eur(net)}<br/>"
            f"VAT 21%: {eur(vat)}<br/>Total amount including VAT: {eur(gross)}",
            s["body"],
        ),
        Spacer(1, 3 * mm),
        Paragraph(
            "This is a tax invoice. Amounts shown in EUR. Net amount is used for PO matching.",
            s["note"],
        ),
    ]
    return story


def main() -> None:
    s = styles()
    files = {
        "1-PO-HX-2026-0041-helix-packaging.pdf": purchase_order(s),
        "2-DN-HX-2026-0730-helix-packaging.pdf": delivery_note(s),
        "3-INV-HX-2026-0802-helix-packaging.pdf": purchase_invoice(s),
    }
    for name, story in files.items():
        path = OUT_DIR / name
        build_pdf(path, story)
        print(f"Wrote {path}")


if __name__ == "__main__":
    main()
