from __future__ import annotations

import os
from datetime import datetime
from pathlib import Path
from typing import Sequence

import arabic_reshaper
from bidi.algorithm import get_display
from reportlab.lib import colors
from reportlab.lib.enums import TA_RIGHT
from reportlab.lib.pagesizes import A4
from reportlab.lib.styles import ParagraphStyle
from reportlab.lib.units import mm
from reportlab.pdfbase import pdfmetrics
from reportlab.pdfbase.ttfonts import TTFont
from reportlab.platypus import Paragraph, SimpleDocTemplate, Spacer, Table, TableStyle

FONT_NAME = "ClinicBotFont"
_FONT_REGISTERED = False

_STATUS_LABELS = {
    "pending": "در انتظار",
    "confirmed": "تایید شده",
    "canceled": "لغو شده",
}


def _rtl(text: str) -> str:
    if not text:
        return ""
    reshaped = arabic_reshaper.reshape(text)
    return get_display(reshaped)


def _ensure_font_registered() -> str:
    global _FONT_REGISTERED
    if _FONT_REGISTERED:
        return FONT_NAME
    font_paths = [
        Path("C:/Windows/Fonts/tahoma.ttf"),
        Path("C:/Windows/Fonts/arial.ttf"),
    ]
    for candidate in font_paths:
        if candidate.exists():
            pdfmetrics.registerFont(TTFont(FONT_NAME, str(candidate)))
            _FONT_REGISTERED = True
            return FONT_NAME
    # Fallback to default if no font found
    return "Helvetica"


def _status_label(value: str) -> str:
    return _STATUS_LABELS.get(value, value)


def generate_appointment_pdf(
    out_dir: str,
    appt_id: int,
    patient_name: str,
    jdate: str,
    time_slot: str,
    status: str,
    appointments: Sequence[dict[str, str]] | None = None,
) -> str:
    os.makedirs(out_dir, exist_ok=True)
    path = os.path.join(out_dir, f"appointment_{appt_id}.pdf")

    font_name = _ensure_font_registered()

    doc = SimpleDocTemplate(
        path,
        pagesize=A4,
        rightMargin=20 * mm,
        leftMargin=20 * mm,
        topMargin=20 * mm,
        bottomMargin=20 * mm,
    )

    header_style = ParagraphStyle(
        name="Header",
        fontName=font_name,
        fontSize=16,
        leading=20,
        alignment=TA_RIGHT,
        spaceAfter=10,
    )
    body_style = ParagraphStyle(
        name="Body",
        fontName=font_name,
        fontSize=12,
        leading=16,
        alignment=TA_RIGHT,
        spaceAfter=6,
    )
    section_style = ParagraphStyle(
        name="Section",
        parent=body_style,
        fontSize=13,
        leading=18,
        spaceBefore=10,
        spaceAfter=6,
    )
    footer_style = ParagraphStyle(
        name="Footer",
        fontName=font_name,
        fontSize=8,
        leading=12,
        alignment=TA_RIGHT,
        textColor=colors.grey,
    )

    story = []
    story.append(Paragraph(_rtl("رسید نوبت"), header_style))
    story.append(Paragraph(_rtl(f"نام بیمار: {patient_name}"), body_style))
    story.append(Paragraph(_rtl(f"شماره نوبت: {appt_id}"), body_style))
    story.append(Paragraph(_rtl(f"تاریخ: {jdate}"), body_style))
    story.append(Paragraph(_rtl(f"ساعت: {time_slot or '-'}"), body_style))
    story.append(Paragraph(_rtl(f"وضعیت: {_status_label(status)}"), body_style))
    story.append(Paragraph(_rtl(f"زمان صدور: {datetime.now().strftime('%Y-%m-%d %H:%M')}"), body_style))

    if appointments:
        story.append(Spacer(1, 12))
        story.append(Paragraph(_rtl("لیست نوبت‌های کاربر"), section_style))
        table_data = [[_rtl("وضعیت"), _rtl("ساعت"), _rtl("تاریخ")]]
        for item in appointments:
            table_data.append(
                [
                    _rtl(_status_label(item.get("status", ""))),
                    _rtl(item.get("time_slot", "-")),
                    _rtl(item.get("jdate", "-")),
                ]
            )
        table = Table(table_data, colWidths=[40 * mm, 35 * mm, 40 * mm])
        table.setStyle(
            TableStyle(
                [
                    ("BACKGROUND", (0, 0), (-1, 0), colors.whitesmoke),
                    ("ALIGN", (0, 0), (-1, -1), "RIGHT"),
                    ("FONTNAME", (0, 0), (-1, -1), font_name),
                    ("FONTSIZE", (0, 0), (-1, -1), 11),
                    ("GRID", (0, 0), (-1, -1), 0.25, colors.lightgrey),
                    ("BOTTOMPADDING", (0, 0), (-1, 0), 6),
                    ("TOPPADDING", (0, 0), (-1, 0), 6),
                ]
            )
        )
        story.append(table)

    story.append(Spacer(1, 20))
    story.append(Paragraph(_rtl("تهیه و توسعه توسط ClinicBot"), footer_style))

    doc.build(story)
    return path
