from reportlab.lib.pagesizes import A4
from reportlab.pdfgen import canvas
import os

def generate_appointment_pdf(out_dir: str, appt_id: int, patient_name: str, jdate: str, time_slot: str, status: str) -> str:
    os.makedirs(out_dir, exist_ok=True)
    path = os.path.join(out_dir, f"appointment_{appt_id}.pdf")
    c = canvas.Canvas(path, pagesize=A4)
    w, h = A4
    c.setTitle("گزارش نوبت")
    c.setFont("Helvetica", 14)
    c.drawString(72, h-72, "گزارش نوبت کلینیک — TAZANACHI")
    c.setFont("Helvetica", 12)
    y = h-110
    lines = [
        f"شناسه نوبت: {appt_id}",
        f"نام بیمار: {patient_name}",
        f"تاریخ (جلالی): {jdate}",
        f"ساعت: {time_slot}",
        f"وضعیت: {status}",
    ]
    for line in lines:
        c.drawString(72, y, line)
        y -= 22
    c.showPage()
    c.save()
    return path
