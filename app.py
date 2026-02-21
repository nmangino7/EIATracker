import os
import sys
import io
import threading
import webbrowser
from datetime import datetime, timedelta
from html import escape as html_escape
from flask import Flask, render_template, request, jsonify, send_file
import yfinance as yf
from reportlab.lib.pagesizes import letter
from reportlab.lib import colors
from reportlab.lib.units import inch
from reportlab.platypus import (
    SimpleDocTemplate, Table, TableStyle, Paragraph, Spacer, Image,
    HRFlowable, KeepTogether, Flowable
)
from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle
from reportlab.lib.enums import TA_CENTER, TA_LEFT, TA_RIGHT

# Handle PyInstaller bundled paths
if getattr(sys, "frozen", False):
    # Running as bundled app — resources are in sys._MEIPASS
    base_dir = sys._MEIPASS
    app = Flask(__name__,
                template_folder=os.path.join(base_dir, "templates"),
                static_folder=os.path.join(base_dir, "static"))
else:
    base_dir = os.path.dirname(__file__)
    app = Flask(__name__)

# ── Annuity products ─────────────────────────────────────────────────────────

ANNUITY_PRODUCTS = {
    "accelerator_plus_10": {
        "name": "Accelerator Plus 10",
        "carrier": "Fidelity & Guaranty Life",
        "indexes": [
            {"id": "sp500", "name": "S&P 500", "ticker": "^GSPC"},
            {"id": "ba10", "name": "Balanced Asset 10 Index", "ticker": None},
            {"id": "ba5", "name": "Balanced Asset 5 Index", "ticker": None},
            {"id": "bts5", "name": "Barclays Trailblazer Sectors 5", "ticker": None},
            {"id": "brk_ma", "name": "BlackRock Market Advantage Index", "ticker": None},
            {"id": "gs_global", "name": "GS Global Factor Index", "ticker": None},
            {"id": "ms_eq", "name": "Morgan Stanley US Equity Allocator", "ticker": None},
        ],
    },
    "silac_denali_14": {
        "name": "SILAC Denali 14 Elevation Plus",
        "carrier": "SILAC",
        "indexes": [
            {"id": "sp500", "name": "S&P 500", "ticker": "^GSPC"},
            {"id": "bloom_versa10", "name": "Bloomberg Versa 10", "ticker": None},
            {"id": "barc_atlas5", "name": "Barclays Atlas 5", "ticker": None},
            {"id": "sp500_raven", "name": "S&P 500 RavenPack AI", "ticker": None},
            {"id": "ndx_gen5", "name": "NDX Generations 5", "ticker": None},
        ],
    },
    "silac_teton_10": {
        "name": "SILAC Teton 10 Elevation Plus",
        "carrier": "SILAC",
        "indexes": [
            {"id": "sp500", "name": "S&P 500", "ticker": "^GSPC"},
            {"id": "bloom_versa10", "name": "Bloomberg Versa 10", "ticker": None},
            {"id": "barc_atlas5", "name": "Barclays Atlas 5", "ticker": None},
            {"id": "sp500_raven", "name": "S&P 500 RavenPack AI", "ticker": None},
            {"id": "ndx_gen5", "name": "NDX Generations 5", "ticker": None},
        ],
    },
    "silac_vega_14": {
        "name": "SILAC Vega Bonus 14",
        "carrier": "SILAC",
        "indexes": [
            {"id": "sp500", "name": "S&P 500", "ticker": "^GSPC"},
            {"id": "bloom_versa10", "name": "Bloomberg Versa 10", "ticker": None},
            {"id": "barc_atlas5", "name": "Barclays Atlas 5", "ticker": None},
            {"id": "sp500_raven", "name": "S&P 500 RavenPack AI", "ticker": None},
            {"id": "ndx_gen5", "name": "NDX Generations 5", "ticker": None},
        ],
    },
}

# ── Index data ───────────────────────────────────────────────────────────────

def fetch_index_return(ticker, start_date_str):
    stock = yf.Ticker(ticker)
    start_dt = datetime.strptime(start_date_str, "%Y-%m-%d")
    search_start = start_dt - timedelta(days=10)
    hist_start = stock.history(
        start=search_start.strftime("%Y-%m-%d"),
        end=(start_dt + timedelta(days=1)).strftime("%Y-%m-%d"),
    )
    if hist_start.empty:
        return None, "No market data available for the start date"
    start_price = float(hist_start.iloc[-1]["Close"])
    start_actual = hist_start.index[-1].strftime("%Y-%m-%d")
    hist_end = stock.history(period="5d")
    if hist_end.empty:
        return None, "No recent market data available"
    end_price = float(hist_end.iloc[-1]["Close"])
    end_date = hist_end.index[-1].strftime("%Y-%m-%d")
    index_return = ((end_price - start_price) / start_price) * 100
    return {
        "ticker": ticker,
        "start_date": start_actual,
        "start_price": round(start_price, 2),
        "end_date": end_date,
        "end_price": round(end_price, 2),
        "index_return": round(index_return, 4),
    }, None


# ── Crediting math ───────────────────────────────────────────────────────────

def calculate_credited_return(index_return, cap_rate=None, par_rate=None, spread_rate=None):
    """1) Spread  2) Par Rate  3) Cap  4) Floor at 0%"""
    if index_return is None or index_return <= 0:
        return 0.0
    credited = index_return
    if spread_rate is not None and spread_rate > 0:
        credited -= spread_rate
        if credited <= 0:
            return 0.0
    if par_rate is not None and par_rate > 0:
        credited *= (par_rate / 100.0)
    if cap_rate is not None and cap_rate > 0:
        credited = min(credited, cap_rate)
    return max(round(credited, 4), 0.0)


def calculate_account_value(current_value, allocations):
    total_new = 0.0
    results = []
    for alloc in allocations:
        pct = alloc.get("allocation_pct", 0)
        alloc_amount = current_value * (pct / 100.0)
        if alloc.get("is_fixed"):
            credited = alloc.get("fixed_rate", 0.0) or 0.0
        else:
            credited = calculate_credited_return(
                alloc.get("index_return", 0.0),
                alloc.get("cap_rate"),
                alloc.get("par_rate"),
                alloc.get("spread_rate"),
            )
        new_amount = alloc_amount * (1 + credited / 100.0)
        total_new += new_amount
        results.append({
            "name": alloc.get("name", ""),
            "allocation_pct": pct,
            "alloc_amount": round(alloc_amount, 2),
            "index_return": alloc.get("index_return") if not alloc.get("is_fixed") else None,
            "credited_return": round(credited, 4),
            "new_amount": round(new_amount, 2),
            "cap_rate": alloc.get("cap_rate"),
            "par_rate": alloc.get("par_rate"),
            "spread_rate": alloc.get("spread_rate"),
            "fixed_rate": alloc.get("fixed_rate"),
            "is_fixed": alloc.get("is_fixed", False),
        })
    return round(total_new, 2), results


# ── PDF: Custom flowable for solid color bars ────────────────────────────────

class ColorBar(Flowable):
    """A solid colored rectangle spanning the full width."""
    def __init__(self, width, height, fill_color):
        Flowable.__init__(self)
        self.width = width
        self.height = height
        self._fill = fill_color

    def draw(self):
        self.canv.setFillColor(self._fill)
        self.canv.rect(0, 0, self.width, self.height, fill=1, stroke=0)


class GoldRule(Flowable):
    """A thin gold line."""
    def __init__(self, width, thickness=1.5):
        Flowable.__init__(self)
        self.width = width
        self.height = thickness

    def draw(self):
        self.canv.setStrokeColor(colors.HexColor("#b8963e"))
        self.canv.setLineWidth(self.height)
        self.canv.line(0, 0, self.width, 0)


# ── PDF Report ───────────────────────────────────────────────────────────────

C_NAVY = colors.HexColor("#0a1628")
C_NAVY2 = colors.HexColor("#0f2240")
C_GOLD = colors.HexColor("#b8963e")
C_GOLD_LIGHT = colors.HexColor("#cdb06a")
C_BG = colors.HexColor("#f9f8f6")
C_BG2 = colors.HexColor("#f3f1ed")
C_BORDER = colors.HexColor("#e0dcd5")
C_TEXT = colors.HexColor("#1c1c1c")
C_TEXT2 = colors.HexColor("#555555")
C_TEXT3 = colors.HexColor("#999999")
C_GREEN = colors.HexColor("#0d6938")
C_RED = colors.HexColor("#a31515")
C_WHITE = colors.white


def generate_pdf_report(client_name, annuity_name, current_value, new_value,
                        allocations, report_date, index_date,
                        advisor_name="", advisor_title=""):
    buffer = io.BytesIO()

    page_w, page_h = letter
    margin_lr = 0.65 * inch
    usable = page_w - 2 * margin_lr

    doc = SimpleDocTemplate(
        buffer, pagesize=letter,
        leftMargin=margin_lr, rightMargin=margin_lr,
        topMargin=0.4 * inch, bottomMargin=0.5 * inch,
    )

    styles = getSampleStyleSheet()

    # ── Styles ──
    def ps(name, **kw):
        defaults = dict(parent=styles["Normal"], fontName="Helvetica",
                        fontSize=9, leading=12, textColor=C_TEXT)
        defaults.update(kw)
        return ParagraphStyle(name, **defaults)

    S = {
        "hero_label": ps("hl", fontSize=7.5, fontName="Helvetica-Bold",
                         textColor=C_TEXT3, leading=9),
        "hero_val": ps("hv", fontSize=20, fontName="Helvetica-Bold",
                       textColor=C_NAVY, leading=24),
        "hero_sub": ps("hs", fontSize=9, textColor=C_TEXT2, leading=11),
        "info_label": ps("il", fontSize=7, fontName="Helvetica-Bold",
                         textColor=C_TEXT3, leading=9),
        "info_val": ps("iv", fontSize=9.5, fontName="Helvetica-Bold",
                       textColor=C_TEXT, leading=12),
        "section": ps("sec", fontSize=8, fontName="Helvetica-Bold",
                      textColor=C_NAVY, leading=10, spaceBefore=14, spaceAfter=6),
        "cell": ps("c", fontSize=8, leading=10, textColor=C_TEXT),
        "cell_b": ps("cb", fontSize=8, fontName="Helvetica-Bold",
                     leading=10, textColor=C_TEXT),
        "cell_h": ps("ch", fontSize=6.5, fontName="Helvetica-Bold",
                     textColor=C_TEXT3, leading=8),
        "body": ps("b", fontSize=7.5, leading=10, textColor=C_TEXT2),
        "disc": ps("d", fontSize=6, leading=8, textColor=C_TEXT3),
        "footer": ps("f", fontSize=6.5, leading=8, textColor=C_TEXT3,
                     alignment=TA_CENTER),
    }

    elements = []

    # ═══════════════════════════════════════════════════════════════════════════
    # LOGO ON WHITE + NAVY ACCENT BAR
    # ═══════════════════════════════════════════════════════════════════════════

    logo_path = os.path.join(base_dir,
                             "Georgia-Financial-Advisors-About.jpg")

    # Logo rendered on white page background — clean, no dark bar clash
    if os.path.exists(logo_path):
        logo = Image(logo_path, width=2.1 * inch, height=0.71 * inch)
        elements.append(logo)
    else:
        elements.append(Paragraph(
            "<b>Georgia Financial Advisors</b>",
            ps("logo_txt", fontSize=14, fontName="Helvetica-Bold",
               textColor=C_NAVY, spaceAfter=4)))

    elements.append(Spacer(1, 8))

    # Slim navy accent bar: advisor info left, firm name right
    advisor_left = ""
    if advisor_name:
        advisor_left = f"<b>{html_escape(advisor_name)}</b>"
        if advisor_title:
            advisor_left += f"  <font color='#8899aa'>|</font>  {html_escape(advisor_title)}"
    else:
        advisor_left = "<b>Georgia Financial Advisors</b>"

    bar_cells = [[
        Paragraph(
            advisor_left,
            ps("bar_left", fontSize=7.5, fontName="Helvetica-Bold",
               textColor=C_WHITE, leading=10)),
        Paragraph(
            "Georgia Financial Advisors",
            ps("bar_right", fontSize=7, textColor=colors.HexColor("#8899aa"),
               alignment=TA_RIGHT, leading=10)),
    ]]
    bar_table = Table(bar_cells,
                      colWidths=[usable * 0.55, usable * 0.45])
    bar_table.setStyle(TableStyle([
        ("BACKGROUND", (0, 0), (-1, -1), C_NAVY),
        ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
        ("TOPPADDING", (0, 0), (-1, -1), 8),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 8),
        ("LEFTPADDING", (0, 0), (0, 0), 14),
        ("RIGHTPADDING", (-1, -1), (-1, -1), 14),
    ]))
    elements.append(bar_table)

    # Gold rule under accent bar
    elements.append(GoldRule(usable, 1.5))
    elements.append(Spacer(1, 18))

    # ═══════════════════════════════════════════════════════════════════════════
    # TITLE + CLIENT INFO
    # ═══════════════════════════════════════════════════════════════════════════

    elements.append(Paragraph(
        "Annuity Performance Report",
        ps("title", fontSize=22, fontName="Helvetica-Bold",
           textColor=C_NAVY, leading=26, spaceAfter=4)))

    elements.append(Paragraph(
        f"Prepared for {html_escape(client_name)}  |  {report_date}",
        ps("title_sub", fontSize=9, textColor=C_TEXT3, spaceAfter=14)))

    # Client detail grid — 2x2
    info_w = usable / 2
    info = Table(
        [
            [
                Paragraph("PRODUCT", S["info_label"]),
                Paragraph("MEASUREMENT PERIOD", S["info_label"]),
            ],
            [
                Paragraph(annuity_name, S["info_val"]),
                Paragraph(index_date, S["info_val"]),
            ],
        ],
        colWidths=[info_w, info_w],
    )
    info.setStyle(TableStyle([
        ("VALIGN", (0, 0), (-1, -1), "TOP"),
        ("TOPPADDING", (0, 0), (-1, 0), 0),
        ("BOTTOMPADDING", (0, 0), (-1, 0), 2),
        ("TOPPADDING", (0, 1), (-1, 1), 0),
        ("BOTTOMPADDING", (0, 1), (-1, 1), 8),
        ("LEFTPADDING", (0, 0), (-1, -1), 0),
    ]))
    elements.append(info)
    elements.append(GoldRule(usable, 0.75))
    elements.append(Spacer(1, 14))

    # ═══════════════════════════════════════════════════════════════════════════
    # ACCOUNT VALUE SUMMARY — 3 metric boxes
    # ═══════════════════════════════════════════════════════════════════════════

    total_return = ((new_value - current_value) / current_value * 100) if current_value > 0 else 0
    gain_loss = new_value - current_value
    ret_sign = "+" if total_return >= 0 else ""
    ret_color = C_GREEN if total_return >= 0 else C_RED

    card_w = usable / 3
    box_pad = 14

    # Build each card as a mini table with background
    def metric_card(label_text, value_text, sub_text, value_color=C_NAVY):
        return [
            Paragraph(label_text, S["hero_label"]),
            Paragraph(value_text, ps(f"mv_{label_text}", fontSize=20,
                      fontName="Helvetica-Bold", textColor=value_color, leading=24)),
            Paragraph(sub_text, S["hero_sub"]) if sub_text else Spacer(1, 1),
        ]

    cards_data = [
        metric_card("CURRENT ACCOUNT VALUE",
                    f"${current_value:,.2f}", " "),
        metric_card("ESTIMATED UPDATED VALUE",
                    f"${new_value:,.2f}",
                    f"{ret_sign}${abs(gain_loss):,.2f}",
                    C_NAVY),
        metric_card("ESTIMATED PERIOD RETURN",
                    f"{ret_sign}{total_return:.2f}%",
                    "Since last anniversary",
                    ret_color),
    ]

    # Transpose to rows
    cards_table_data = []
    for row_idx in range(3):
        cards_table_data.append([cards_data[c][row_idx] for c in range(3)])

    cards_table = Table(cards_table_data, colWidths=[card_w] * 3)
    cards_table.setStyle(TableStyle([
        ("BACKGROUND", (0, 0), (-1, -1), C_BG),
        ("BOX", (0, 0), (-1, -1), 0.5, C_BORDER),
        # Column dividers
        ("LINEAFTER", (0, 0), (0, -1), 0.5, C_BORDER),
        ("LINEAFTER", (1, 0), (1, -1), 0.5, C_BORDER),
        ("VALIGN", (0, 0), (-1, -1), "TOP"),
        ("TOPPADDING", (0, 0), (-1, 0), box_pad),
        ("BOTTOMPADDING", (0, -1), (-1, -1), box_pad),
        ("TOPPADDING", (0, 1), (-1, 1), 2),
        ("BOTTOMPADDING", (0, 1), (-1, 1), 2),
        ("TOPPADDING", (0, 2), (-1, 2), 2),
        ("LEFTPADDING", (0, 0), (-1, -1), box_pad),
        ("RIGHTPADDING", (0, 0), (-1, -1), box_pad),
    ]))
    elements.append(cards_table)
    elements.append(Spacer(1, 16))

    # ═══════════════════════════════════════════════════════════════════════════
    # ALLOCATION DETAIL TABLE
    # ═══════════════════════════════════════════════════════════════════════════

    elements.append(Paragraph("ALLOCATION DETAIL", S["section"]))

    col_widths = [2.55 * inch, 0.65 * inch, 0.9 * inch, 0.9 * inch, 1.15 * inch]

    def hdr_cell(text, align=TA_LEFT):
        return Paragraph(text, ps(f"th_{text}", fontSize=6.5,
                         fontName="Helvetica-Bold", textColor=C_TEXT3,
                         alignment=align, leading=8))

    header_row = [
        hdr_cell("INDEX / STRATEGY"),
        hdr_cell("WEIGHT", TA_RIGHT),
        hdr_cell("INDEX RETURN", TA_RIGHT),
        hdr_cell("CREDITED", TA_RIGHT),
        hdr_cell("EST. VALUE", TA_RIGHT),
    ]
    table_data = [header_row]

    for alloc in allocations:
        if alloc["is_fixed"]:
            idx_str = Paragraph("--", ps("fx_idx", fontSize=8,
                                alignment=TA_RIGHT, textColor=C_TEXT3))
            name_html = (f"<b>Fixed Interest</b><br/>"
                         f"<font size=6 color='#999999'>"
                         f"Rate: {alloc.get('fixed_rate', 0):.2f}%</font>")
        else:
            idx_ret = alloc.get("index_return", 0) or 0
            idx_c = "#0d6938" if idx_ret >= 0 else "#a31515"
            idx_str = Paragraph(
                f"<font color='{idx_c}'>{idx_ret:+.2f}%</font>",
                ps("idx_v", fontSize=8, alignment=TA_RIGHT))

            name_html = f"<b>{html_escape(alloc['name'])}</b>"
            rate_parts = []
            if alloc.get("spread_rate"):
                rate_parts.append(f"Spread {alloc['spread_rate']:.2f}%")
            if alloc.get("par_rate"):
                rate_parts.append(f"Par {alloc['par_rate']:.0f}%")
            if alloc.get("cap_rate"):
                rate_parts.append(f"Cap {alloc['cap_rate']:.2f}%")
            if rate_parts:
                name_html += (f"<br/><font size=6 color='#999999'>"
                              f"{'  |  '.join(rate_parts)}</font>")

        cr = alloc.get("credited_return", 0)
        cr_c = "#0d6938" if cr > 0 else ("#a31515" if cr < 0 else "#1c1c1c")

        row = [
            Paragraph(name_html, S["cell"]),
            Paragraph(f"{alloc['allocation_pct']:.0f}%",
                      ps("w", fontSize=8, alignment=TA_RIGHT)),
            idx_str,
            Paragraph(f"<font color='{cr_c}'>{cr:+.2f}%</font>",
                      ps("cr", fontSize=8, alignment=TA_RIGHT)),
            Paragraph(f"${alloc['new_amount']:,.2f}",
                      ps("ev", fontSize=8, fontName="Helvetica-Bold",
                         alignment=TA_RIGHT)),
        ]
        table_data.append(row)

    # Total row
    table_data.append([
        Paragraph("<b>TOTAL</b>", S["cell_b"]),
        Paragraph("<b>100%</b>",
                  ps("tw", fontSize=8, fontName="Helvetica-Bold",
                     alignment=TA_RIGHT)),
        Paragraph("", S["cell"]),
        Paragraph(
            f"<b><font color='{('#0d6938' if total_return >= 0 else '#a31515')}'>"
            f"{ret_sign}{total_return:.2f}%</font></b>",
            ps("tcr", fontSize=8, fontName="Helvetica-Bold",
               alignment=TA_RIGHT)),
        Paragraph(f"<b>${new_value:,.2f}</b>",
                  ps("tev", fontSize=8, fontName="Helvetica-Bold",
                     alignment=TA_RIGHT)),
    ])

    tbl = Table(table_data, colWidths=col_widths, repeatRows=1)
    tbl.setStyle(TableStyle([
        # Header row
        ("BACKGROUND", (0, 0), (-1, 0), C_BG2),
        ("LINEBELOW", (0, 0), (-1, 0), 1.5, C_GOLD),
        # Body rows
        ("LINEBELOW", (0, 1), (-1, -2), 0.5, colors.HexColor("#eae7e1")),
        # Total row
        ("LINEABOVE", (0, -1), (-1, -1), 1.5, C_NAVY),
        ("BACKGROUND", (0, -1), (-1, -1), C_BG),
        # Padding
        ("TOPPADDING", (0, 0), (-1, -1), 8),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 8),
        ("LEFTPADDING", (0, 0), (0, -1), 8),
        ("LEFTPADDING", (1, 0), (-1, -1), 4),
        ("RIGHTPADDING", (-1, 0), (-1, -1), 8),
        ("RIGHTPADDING", (0, 0), (-2, -1), 4),
        ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
        # Outer box
        ("BOX", (0, 0), (-1, -1), 0.5, C_BORDER),
    ]))
    elements.append(tbl)

    # ═══════════════════════════════════════════════════════════════════════════
    # METHODOLOGY BOX
    # ═══════════════════════════════════════════════════════════════════════════

    elements.append(Spacer(1, 16))

    meth_content = [
        [Paragraph(
            "<b>CREDITING METHODOLOGY</b>",
            ps("mh", fontSize=7, fontName="Helvetica-Bold",
               textColor=C_NAVY, leading=9))],
        [Paragraph(
            "Index interest is credited using the annual point-to-point method. "
            "For strategies with a spread, the spread is deducted from positive "
            "index gains first. The participation rate is then applied. The cap "
            "rate limits the maximum credited return. Negative index performance "
            "results in a 0% floor — the account value will never decrease due "
            "to index performance.",
            S["body"])],
    ]
    meth_table = Table(meth_content, colWidths=[usable - 24])
    meth_table.setStyle(TableStyle([
        ("BACKGROUND", (0, 0), (-1, -1), C_BG),
        ("BOX", (0, 0), (-1, -1), 0.5, C_BORDER),
        ("TOPPADDING", (0, 0), (-1, -1), 10),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 10),
        ("LEFTPADDING", (0, 0), (-1, -1), 12),
        ("RIGHTPADDING", (0, 0), (-1, -1), 12),
    ]))
    elements.append(meth_table)

    # ═══════════════════════════════════════════════════════════════════════════
    # DISCLOSURES + FOOTER
    # ═══════════════════════════════════════════════════════════════════════════

    elements.append(Spacer(1, 18))
    elements.append(GoldRule(usable, 0.5))
    elements.append(Spacer(1, 6))

    elements.append(Paragraph(
        "<b>Important Disclosures</b>",
        ps("dh", fontSize=6.5, fontName="Helvetica-Bold",
           textColor=C_TEXT3, spaceAfter=3)))

    elements.append(Paragraph(
        "This report is prepared for informational purposes only and does not "
        "constitute an offer to sell, a solicitation to buy, or a recommendation "
        "for any security or investment advisory service. Estimated values are "
        "based on publicly available index data and crediting parameters entered "
        "by the advisor. Actual credited returns are determined by the issuing "
        "insurance carrier per your annuity contract. Index returns are not "
        "directly investable. Past performance does not guarantee future results. "
        "Fixed indexed annuities are insurance products, not securities. Refer to "
        "your annuity contract for complete terms and conditions.",
        S["disc"]))

    elements.append(Spacer(1, 16))

    # Footer bar
    footer_left = "Georgia Financial Advisors"
    if advisor_name:
        footer_left = f"{html_escape(advisor_name)}"
        if advisor_title:
            footer_left += f"  |  {html_escape(advisor_title)}"

    footer_cells = [[
        Paragraph(
            f"<b>{footer_left}</b>",
            ps("fn", fontSize=7, fontName="Helvetica-Bold",
               textColor=C_WHITE, leading=9)),
        Paragraph(
            "6001 Chatham Center Dr, Suite 140, Savannah, GA 31405",
            ps("fa", fontSize=6, textColor=colors.HexColor("#8899aa"),
               alignment=TA_CENTER, leading=8)),
        Paragraph(
            f"Georgia Financial Advisors  |  {report_date}",
            ps("fd", fontSize=6, textColor=colors.HexColor("#8899aa"),
               alignment=TA_RIGHT, leading=8)),
    ]]
    footer_table = Table(footer_cells,
                         colWidths=[2.2 * inch, usable - 2.2 * inch - 2.2 * inch, 2.2 * inch])
    footer_table.setStyle(TableStyle([
        ("BACKGROUND", (0, 0), (-1, -1), C_NAVY),
        ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
        ("TOPPADDING", (0, 0), (-1, -1), 8),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 8),
        ("LEFTPADDING", (0, 0), (0, 0), 14),
        ("RIGHTPADDING", (-1, -1), (-1, -1), 14),
    ]))
    elements.append(footer_table)

    doc.build(elements)
    buffer.seek(0)
    return buffer


# ── Routes ───────────────────────────────────────────────────────────────────

@app.route("/")
def index():
    return render_template("index.html", products=ANNUITY_PRODUCTS)

@app.route("/api/products")
def get_products():
    return jsonify(ANNUITY_PRODUCTS)

@app.route("/api/index-return", methods=["POST"])
def get_index_return():
    data = request.json
    ticker = data.get("ticker")
    start_date = data.get("start_date")
    if not ticker or not start_date:
        return jsonify({"error": "ticker and start_date required"}), 400
    try:
        result, error = fetch_index_return(ticker, start_date)
        if error:
            return jsonify({"error": error}), 404
        return jsonify(result)
    except Exception as e:
        return jsonify({"error": f"Failed to fetch: {str(e)}"}), 500

@app.route("/api/calculate", methods=["POST"])
def api_calculate():
    data = request.json
    current_value = float(data.get("current_value", 0))
    allocations = data.get("allocations", [])
    if current_value <= 0:
        return jsonify({"error": "Current value must be > 0"}), 400
    new_value, results = calculate_account_value(current_value, allocations)
    return jsonify({
        "current_value": current_value,
        "new_value": new_value,
        "total_return_pct": round(((new_value - current_value) / current_value) * 100, 4),
        "allocations": results,
    })

@app.route("/api/report", methods=["POST"])
def api_report():
    data = request.json
    client_name = data.get("client_name", "Client")
    annuity_name = data.get("annuity_name", "")
    current_value = float(data.get("current_value", 0))
    new_value = float(data.get("new_value", 0))
    allocations = data.get("allocations", [])
    index_date = data.get("index_date", "")
    advisor_name = data.get("advisor_name", "")
    advisor_title = data.get("advisor_title", "")
    report_date = datetime.now().strftime("%B %d, %Y")
    pdf_buffer = generate_pdf_report(
        client_name, annuity_name, current_value, new_value,
        allocations, report_date, index_date,
        advisor_name=advisor_name, advisor_title=advisor_title,
    )
    safe_name = client_name.replace(" ", "_").replace("/", "_")
    filename = f"GFA_Annuity_Report_{safe_name}_{datetime.now().strftime('%Y%m%d')}.pdf"
    return send_file(pdf_buffer, mimetype="application/pdf",
                     as_attachment=True, download_name=filename)


def open_browser():
    """Open the browser after a short delay to let Flask start."""
    import time
    time.sleep(1.5)
    webbrowser.open("http://127.0.0.1:5050")


if __name__ == "__main__":
    # Detect if running as a PyInstaller bundle
    is_bundled = getattr(sys, "frozen", False)

    if is_bundled:
        # Auto-open browser when running as packaged app
        threading.Thread(target=open_browser, daemon=True).start()
        # Run without debug mode in production
        print("=" * 50)
        print("  EIA Track — Georgia Financial Advisors")
        print("  Opening in your browser...")
        print("  Close this window to stop the app.")
        print("=" * 50)
        app.run(debug=False, port=5050)
    else:
        app.run(debug=True, port=5050)
