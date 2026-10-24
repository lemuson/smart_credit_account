"""PDF-представление сохранённого учебного договора, без изменения его версии."""

from io import BytesIO
from pathlib import Path
from xml.sax.saxutils import escape

from reportlab.lib import colors
from reportlab.lib.enums import TA_CENTER
from reportlab.lib.pagesizes import A4
from reportlab.lib.styles import ParagraphStyle
from reportlab.lib.units import mm
from reportlab.pdfbase import pdfmetrics
from reportlab.pdfbase.ttfonts import TTFont
from reportlab.platypus import (
    LongTable,
    Paragraph,
    SimpleDocTemplate,
    Spacer,
    TableStyle,
)

FONT = "ContractSans"
pdfmetrics.registerFont(TTFont(FONT, str(Path(__file__).with_name("fonts") / "DejaVuSans.ttf")))


def contract_pdf(contract):
    stream = BytesIO()
    body = ParagraphStyle("Body", fontName=FONT, fontSize=10, leading=15, spaceAfter=8)
    heading = ParagraphStyle("Heading", parent=body, fontSize=15, leading=20, spaceAfter=14)
    small = ParagraphStyle("Small", parent=body, fontSize=8, leading=12)
    cell = ParagraphStyle("Cell", parent=small, spaceAfter=0)
    title = ParagraphStyle("Title", parent=heading, alignment=TA_CENTER, fontSize=19, leading=24)
    story = []

    def paragraph(text, style=body):
        return Paragraph(escape(str(text)), style)

    def add(text, style=body):
        story.append(paragraph(text, style))

    def rub(value):
        from decimal import Decimal

        return f"{Decimal(value):,.2f}".replace(",", " ").replace(".", ",") + " руб."

    offer, company = contract["offer"], contract["company"]
    add("УЧЕБНЫЙ КРЕДИТНЫЙ ДОГОВОР", title)
    add(f"Заявка № {contract['application_id']}", small)
    add(f"Дата формирования: {contract['created_at'][:10]}", small)
    add(contract["text"])
    add("1. Сведения о заёмщике", heading)
    for label, key in [
        ("Наименование", "name"),
        ("ИНН", "inn"),
        ("Дата регистрации", "registration_date"),
        ("Юридический адрес", "address"),
        ("ОКВЭД", "industry"),
    ]:
        add(f"{label}: {company[key]}")
    add("2. Условия финансирования", heading)
    for label, value in [
        ("Сумма кредита", rub(offer["amount"])),
        ("Срок", f"{offer['term_months']} мес."),
        ("Годовая процентная ставка", f"{offer['annual_rate']}%"),
        ("Ежемесячный платёж", rub(offer["monthly_payment"])),
        ("Общая сумма выплат", rub(offer["total_payment"])),
    ]:
        add(f"{label}: {value}")
    add("3. Порядок подтверждения", heading)
    add(
        "Подтверждение выполняется в кредитном кабинете вводом демонстрационного кода. "
        "Это учебная операция, не являющаяся реальной электронной подписью или выдачей средств."
    )
    add(
        "Версия условий зафиксирована при принятии предложения. "
        "Приведённый ниже идентификатор соответствует сохранённым данным договора.",
        small,
    )
    add(f"SHA-256 данных договора: {contract['sha256']}", small)
    story.append(Spacer(1, 6 * mm))
    add("4. График платежей", heading)
    data = [
        [
            paragraph(label, cell)
            for label in ["№", "Дата", "Платёж", "Основной долг", "Проценты", "Остаток"]
        ]
    ]
    for row in offer["schedule"]:
        data.append(
            [
                paragraph(value, cell)
                for value in [
                    row["number"],
                    row["due_date"],
                    rub(row["payment"]),
                    rub(row["principal"]),
                    rub(row["interest"]),
                    rub(row["balance"]),
                ]
            ]
        )
    table = LongTable(
        data,
        colWidths=[9 * mm, 24 * mm, 34 * mm, 34 * mm, 28 * mm, 41 * mm],
        repeatRows=1,
        hAlign="LEFT",
    )
    table.setStyle(
        TableStyle(
            [
                ("BACKGROUND", (0, 0), (-1, 0), colors.HexColor("#eef0f4")),
                ("GRID", (0, 0), (-1, -1), 0.3, colors.HexColor("#c6cbd3")),
                ("VALIGN", (0, 0), (-1, -1), "TOP"),
                ("TOPPADDING", (0, 0), (-1, -1), 7),
                ("BOTTOMPADDING", (0, 0), (-1, -1), 7),
            ]
        )
    )
    story.append(table)

    def footer(canvas, doc):
        canvas.setFont(FONT, 8)
        canvas.setFillColor(colors.HexColor("#687080"))
        canvas.drawString(20 * mm, 12 * mm, "Учебный документ. Без реальной выдачи средств.")
        canvas.drawRightString(190 * mm, 12 * mm, f"Страница {doc.page}")

    doc = SimpleDocTemplate(
        stream,
        pagesize=A4,
        leftMargin=20 * mm,
        rightMargin=20 * mm,
        topMargin=18 * mm,
        bottomMargin=22 * mm,
        title="Учебный кредитный договор",
        author="Кредитный кабинет",
        invariant=1,
    )
    doc.build(story, onFirstPage=footer, onLaterPages=footer)
    return stream.getvalue()
