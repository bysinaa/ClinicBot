# -*- coding: utf-8 -*-
from __future__ import annotations

import os
from datetime import datetime
from pathlib import Path
from typing import Sequence

import arabic_reshaper
from bidi.algorithm import get_display
from reportlab.lib import colors
from reportlab.lib.enums import TA_CENTER, TA_RIGHT
from reportlab.lib.pagesizes import A4
from reportlab.lib.styles import ParagraphStyle
from reportlab.lib.units import mm
from reportlab.pdfbase import pdfmetrics
from reportlab.pdfbase.ttfonts import TTFont
from reportlab.platypus import Image, Paragraph, SimpleDocTemplate, Spacer, Table, TableStyle

from src.config import settings

FONT_NAME = "ClinicBotFont"
_FONT_REGISTERED = False
_STAMP_WARNING_EMITTED = False
_PERSIAN_DIGITS = str.maketrans("0123456789", "۰۱۲۳۴۵۶۷۸۹")

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


def _fa_digits(value: str | int | float | None) -> str:
    if value is None:
        return ""
    return str(value).translate(_PERSIAN_DIGITS)


def _rtl_fa(text: str | int | float | None) -> str:
    return _rtl(_fa_digits(text))


def _ensure_font_registered() -> str:
    global _FONT_REGISTERED
    if _FONT_REGISTERED:
        return FONT_NAME
    font_paths: list[Path] = []
    if settings.pdf_font_path:
        font_paths.append(Path(settings.pdf_font_path).expanduser())
    font_paths.extend(
        [
            Path("C:/Windows/Fonts/tahoma.ttf"),
            Path("C:/Windows/Fonts/arial.ttf"),
        ]
    )
    for candidate in font_paths:
        if candidate and candidate.exists():
            pdfmetrics.registerFont(TTFont(FONT_NAME, str(candidate)))
            _FONT_REGISTERED = True
            return FONT_NAME
    # Fallback to default if no font found
    return "Helvetica"


def _status_label(value: str) -> str:
    return _STATUS_LABELS.get(value, value)


def _stamp_flowable(max_width_mm: float = 45.0):
    global _STAMP_WARNING_EMITTED
    stamp_path = settings.pdf_stamp_path
    if not stamp_path:
        return None
    try:
        candidate = Path(stamp_path).expanduser()
    except Exception as exc:
        if not _STAMP_WARNING_EMITTED:
            print(f"[WARN] Unable to read PDF_STAMP_PATH ({stamp_path}): {exc}")
            _STAMP_WARNING_EMITTED = True
        return None
    if not candidate.is_file():
        if not _STAMP_WARNING_EMITTED:
            print(f"[WARN] Stamp image not found at {candidate}")
            _STAMP_WARNING_EMITTED = True
        return None
    img = Image(str(candidate))
    max_width = max_width_mm * mm
    if img.drawWidth > max_width:
        scale = max_width / img.drawWidth
        img.drawWidth *= scale
        img.drawHeight *= scale
    img.hAlign = "RIGHT"
    img.vAlign = "BOTTOM"
    return img


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
        fontSize=18,
        leading=24,
        alignment=TA_CENTER,
        spaceAfter=10,
    )
    body_style = ParagraphStyle(
        name="Body",
        fontName=font_name,
        fontSize=13,
        leading=18,
        alignment=TA_CENTER,
        spaceAfter=6,
    )
    section_style = ParagraphStyle(
        name="Section",
        parent=body_style,
        fontSize=14,
        leading=20,
        spaceBefore=10,
        spaceAfter=8,
    )
    footer_style = ParagraphStyle(
        name="Footer",
        fontName=font_name,
        fontSize=9,
        leading=12,
        alignment=TA_CENTER,
        textColor=colors.grey,
    )

    card_rows: list[list] = []

    def add_text_line(text: str, style: ParagraphStyle = body_style) -> None:
        card_rows.append([Paragraph(_rtl_fa(text), style)])

    add_text_line("رسید نوبت", header_style)
    add_text_line(f"نام بیمار: {patient_name}")
    add_text_line(f"شماره نوبت: {_fa_digits(appt_id)}")
    add_text_line(f"تاریخ: {_fa_digits(jdate)}")
    add_text_line(f"ساعت: {_fa_digits(time_slot or '-')}")
    add_text_line(f"وضعیت: {_status_label(status)}")
    add_text_line(f"زمان صدور: {_fa_digits(datetime.now().strftime('%Y-%m-%d %H:%M'))}")

    if appointments:
        card_rows.append([Spacer(1, 10)])
        add_text_line("لیست نوبت‌های کاربر", section_style)
        table_data = [[_rtl_fa("وضعیت"), _rtl_fa("ساعت"), _rtl_fa("تاریخ")]]
        for item in appointments:
            table_data.append(
                [
                    _rtl_fa(_status_label(item.get("status", ""))),
                    _rtl_fa(item.get("time_slot", "-")),
                    _rtl_fa(item.get("jdate", "-")),
                ]
            )
        table = Table(table_data, colWidths=[40 * mm, 35 * mm, 40 * mm])
        table.setStyle(
            TableStyle(
                [
                    ("BACKGROUND", (0, 0), (-1, 0), colors.whitesmoke),
                    ("ALIGN", (0, 0), (-1, -1), "CENTER"),
                    ("FONTNAME", (0, 0), (-1, -1), font_name),
                    ("FONTSIZE", (0, 0), (-1, -1), 11),
                    ("GRID", (0, 0), (-1, -1), 0.25, colors.lightgrey),
                    ("BOTTOMPADDING", (0, 0), (-1, 0), 6),
                    ("TOPPADDING", (0, 0), (-1, 0), 6),
                ]
            )
        )
        card_rows.append([table])

    stamp = _stamp_flowable()
    if stamp:
        card_rows.append([Spacer(1, 10)])
        card_rows.append([stamp])

    card_rows.append([Spacer(1, 8)])
    add_text_line("تهیه و توسعه توسط ClinicBot", footer_style)

    card_table = Table(card_rows, colWidths=[doc.width])
    card_table.setStyle(
        TableStyle(
            [
                ("BOX", (0, 0), (-1, -1), 2.5, colors.black),
                ("LEFTPADDING", (0, 0), (-1, -1), 18),
                ("RIGHTPADDING", (0, 0), (-1, -1), 18),
                ("TOPPADDING", (0, 0), (-1, -1), 16),
                ("BOTTOMPADDING", (0, 0), (-1, -1), 16),
                ("BACKGROUND", (0, 0), (-1, -1), colors.whitesmoke),
                ("ALIGN", (0, 0), (-1, -1), "CENTER"),
            ]
        )
    )

    doc.build([card_table])
    return path



def generate_day_summary_pdf(out_dir: str, jdate: str, rows: Sequence[dict[str, str]]) -> str:
    os.makedirs(out_dir, exist_ok=True)
    path = os.path.join(out_dir, f"day_{jdate}.pdf")

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
        leading=18,
        alignment=TA_RIGHT,
        spaceAfter=8,
    )

    story = []
    story.append(Paragraph(_rtl_fa("گزارش نوبت‌های روز"), header_style))
    story.append(Paragraph(_rtl_fa(f"تاریخ: {jdate}"), body_style))
    story.append(Spacer(1, 12))

    table_data = [[
        _rtl_fa("وضعیت پرداخت"),
        _rtl_fa("شماره تماس"),
        _rtl_fa("سن"),
        _rtl_fa("نام و نام خانوادگی"),
        _rtl_fa("ردیف"),
    ]]

    for idx, row in enumerate(rows, start=1):
        table_data.append([
            _rtl_fa(row.get("payment", "-")),
            _rtl_fa(row.get("phone", "-")),
            _rtl_fa(row.get("age", "-")),
            _rtl_fa(row.get("full_name", "-")),
            _rtl_fa(idx),
        ])

    table = Table(table_data, colWidths=[35 * mm, 35 * mm, 20 * mm, 55 * mm, 20 * mm])
    table.setStyle(
        TableStyle(
            [
                ("BACKGROUND", (0, 0), (-1, 0), colors.whitesmoke),
                ("ALIGN", (0, 0), (-1, -1), "RIGHT"),
                ("FONTNAME", (0, 0), (-1, -1), font_name),
                ("FONTSIZE", (0, 0), (-1, -1), 11),
                ("GRID", (0, 0), (-1, -1), 0.3, colors.lightgrey),
                ("BOTTOMPADDING", (0, 0), (-1, 0), 8),
                ("TOPPADDING", (0, 0), (-1, 0), 8),
            ]
        )
    )
    story.append(table)

    stamp = _stamp_flowable()
    if stamp:
        story.append(Spacer(1, 15))
        story.append(stamp)

    doc.build(story)
    return path
