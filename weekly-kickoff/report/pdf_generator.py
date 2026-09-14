"""Generate the 6-page KataLYST Weekly Market Intelligence PDF report."""

from __future__ import annotations

import io
import os
from datetime import date

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
from reportlab.lib import colors
from reportlab.lib.enums import TA_CENTER, TA_LEFT
from reportlab.lib.pagesizes import letter
from reportlab.lib.styles import ParagraphStyle, getSampleStyleSheet
from reportlab.lib.units import inch
from reportlab.platypus import (
    Image,
    PageBreak,
    Paragraph,
    SimpleDocTemplate,
    Spacer,
    Table,
    TableStyle,
)

from analytics import (
    ListingMetrics,
    SalesMetrics,
    SubmarketRow,
    BrokerActivity,
    compute_broker_activity,
    compute_listing_metrics,
    compute_sales_metrics,
    compute_submarket_scorecard,
    deal_to_watch,
    intelligence_highlights,
    market_commentary,
)
from config import (
    BRAND,
    COLOR_DARK_TEXT,
    COLOR_GOLD,
    COLOR_GRAY,
    COLOR_GREEN,
    COLOR_LIGHT,
    COLOR_NAVY,
    COLOR_TEAL,
    COLOR_WHITE,
    CONTACT_LINE,
    FOOTER_DISCLAIMER,
    REPORT_TITLE,
    SUBTITLE,
)
from models import PropertyRecord

PAGE_W, PAGE_H = letter
MARGIN = 0.55 * inch


def _fmt_money(val, short=False) -> str:
    if val is None:
        return "—"
    if short and val >= 1_000_000:
        return f"${val / 1e6:.1f}M"
    return f"${val:,.0f}"


def _fmt_ppu(val) -> str:
    return f"${val:,.0f}" if val else "—"


def _fmt_ppsf(val) -> str:
    return f"${val:.2f}/SF" if val else "—"


def _make_chart_bar(data: dict, title: str, color: str = COLOR_TEAL) -> Image:
    """Render a horizontal bar chart to a ReportLab Image."""
    if not data:
        data = {"No data": 0}

    fig, ax = plt.subplots(figsize=(3.0, 1.8), dpi=100)
    labels = list(data.keys())
    values = list(data.values())
    y_pos = range(len(labels))
    ax.barh(y_pos, values, color=color, height=0.55)
    ax.set_yticks(y_pos)
    ax.set_yticklabels(labels, fontsize=8)
    ax.set_title(title, fontsize=9, fontweight="bold", color=COLOR_NAVY)
    ax.spines["top"].set_visible(False)
    ax.spines["right"].set_visible(False)
    ax.tick_params(axis="x", labelsize=7)
    fig.tight_layout()

    buf = io.BytesIO()
    fig.savefig(buf, format="png", bbox_inches="tight", facecolor="white")
    plt.close(fig)
    buf.seek(0)
    return Image(buf, width=3.4 * inch, height=1.75 * inch)


def _make_chart_dist(data: dict, title: str) -> Image:
    """Vertical bar chart for distributions."""
    if not data:
        data = {"—": 0}
    fig, ax = plt.subplots(figsize=(3.0, 1.8), dpi=100)
    labels = list(data.keys())
    values = list(data.values())
    ax.bar(labels, values, color=COLOR_NAVY, width=0.55)
    ax.set_title(title, fontsize=9, fontweight="bold", color=COLOR_NAVY)
    ax.spines["top"].set_visible(False)
    ax.spines["right"].set_visible(False)
    ax.tick_params(axis="both", labelsize=7)
    fig.tight_layout()
    buf = io.BytesIO()
    fig.savefig(buf, format="png", bbox_inches="tight", facecolor="white")
    plt.close(fig)
    buf.seek(0)
    return Image(buf, width=3.4 * inch, height=1.75 * inch)


class ReportCanvas:
    """Builds the multi-page weekly kickoff PDF."""

    def __init__(self, week_ending: date):
        self.week_ending = week_ending
        self.week_label = week_ending.strftime("Week Ending %B %d").replace(" 0", " ") + _ordinal(week_ending.day) + f", {week_ending.year}"
        self.styles = getSampleStyleSheet()
        self._setup_styles()

    def _setup_styles(self):
        self.styles.add(ParagraphStyle(
            name="BrandHeader",
            fontSize=11,
            textColor=colors.HexColor(COLOR_NAVY),
            fontName="Helvetica-Bold",
            spaceAfter=2,
        ))
        self.styles.add(ParagraphStyle(
            name="ReportTitle",
            fontSize=16,
            textColor=colors.HexColor(COLOR_NAVY),
            fontName="Helvetica-Bold",
            spaceAfter=2,
        ))
        self.styles.add(ParagraphStyle(
            name="Subtitle",
            fontSize=9,
            textColor=colors.HexColor(COLOR_GOLD),
            fontName="Helvetica-Bold",
            spaceAfter=4,
        ))
        self.styles.add(ParagraphStyle(
            name="Contact",
            fontSize=6.5,
            textColor=colors.HexColor(COLOR_GRAY),
            spaceAfter=6,
        ))
        self.styles.add(ParagraphStyle(
            name="SectionHead",
            fontSize=10,
            textColor=colors.HexColor(COLOR_NAVY),
            fontName="Helvetica-Bold",
            spaceBefore=8,
            spaceAfter=4,
        ))
        self.styles.add(ParagraphStyle(
            name="BodyText2",
            fontSize=8,
            textColor=colors.HexColor(COLOR_DARK_TEXT),
            leading=11,
            spaceAfter=4,
        ))
        self.styles.add(ParagraphStyle(
            name="CardTitle",
            fontSize=7,
            textColor=colors.HexColor(COLOR_GOLD),
            fontName="Helvetica-Bold",
        ))
        self.styles.add(ParagraphStyle(
            name="CardAddress",
            fontSize=8,
            textColor=colors.HexColor(COLOR_NAVY),
            fontName="Helvetica-Bold",
            leading=10,
        ))
        self.styles.add(ParagraphStyle(
            name="CardMeta",
            fontSize=7,
            textColor=colors.HexColor(COLOR_GRAY),
            leading=9,
        ))
        self.styles.add(ParagraphStyle(
            name="KPIValue",
            fontSize=14,
            textColor=colors.HexColor(COLOR_NAVY),
            fontName="Helvetica-Bold",
            alignment=TA_CENTER,
        ))
        self.styles.add(ParagraphStyle(
            name="KPILabel",
            fontSize=6.5,
            textColor=colors.HexColor(COLOR_GRAY),
            alignment=TA_CENTER,
        ))
        self.styles.add(ParagraphStyle(
            name="Footer",
            fontSize=5.5,
            textColor=colors.HexColor(COLOR_GRAY),
            leading=7,
        ))

    def _header_block(self) -> list:
        return [
            Paragraph(BRAND, self.styles["BrandHeader"]),
            Paragraph(REPORT_TITLE, self.styles["ReportTitle"]),
            Paragraph(SUBTITLE, self.styles["Subtitle"]),
            Paragraph(self.week_label, self.styles["BodyText2"]),
            Paragraph(CONTACT_LINE, self.styles["Contact"]),
        ]

    def _kpi_row(self, kpis: list[tuple]) -> Table:
        """Render KPIs in two rows of four to fit letter page width."""
        col_w = 1.8 * inch

        def _cell(val, label):
            return [
                Paragraph(val, self.styles["KPIValue"]),
                Paragraph(label, self.styles["KPILabel"]),
            ]

        row1 = [_cell(v, l) for v, l in kpis[:4]]
        row2 = [_cell(v, l) for v, l in kpis[4:8]]
        while len(row1) < 4:
            row1.append(["", ""])
        while len(row2) < 4:
            row2.append(["", ""])

        t = Table([row1, row2], colWidths=[col_w] * 4)
        t.setStyle(TableStyle([
            ("BACKGROUND", (0, 0), (-1, -1), colors.HexColor(COLOR_LIGHT)),
            ("BOX", (0, 0), (-1, -1), 0.5, colors.HexColor("#DEE2E6")),
            ("INNERGRID", (0, 0), (-1, -1), 0.5, colors.HexColor("#DEE2E6")),
            ("TOPPADDING", (0, 0), (-1, -1), 6),
            ("BOTTOMPADDING", (0, 0), (-1, -1), 6),
            ("ALIGN", (0, 0), (-1, -1), "CENTER"),
            ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
        ]))
        return t

    def _property_card(self, record: PropertyRecord, status_label: str) -> Table:
        addr_line = f"{record.address}"
        loc_line = f"{record.city}, {record.state}"
        if record.property_name:
            loc_line += f" · {record.property_name}"
        if record.market:
            loc_line += f" · {record.market} Market"

        broker_line = ""
        if record.broker and record.broker_firm:
            broker_line = f"{record.broker} | {record.broker_firm}"
        elif record.broker_firm:
            broker_line = record.broker_firm

        data = [
            [Paragraph(status_label, self.styles["CardTitle"]), ""],
            [Paragraph(addr_line, self.styles["CardAddress"]), ""],
            [Paragraph(loc_line, self.styles["CardMeta"]), ""],
            ["PRICE", _fmt_money(record.price)],
            ["UNITS", str(record.units) if record.units else "—"],
            ["$/UNIT", _fmt_ppu(record.price_per_unit)],
            ["$/SF", _fmt_ppsf(record.price_per_sf)],
            ["CAP", "—" if not record.cap_rate else f"{record.cap_rate:.2f}%"],
            ["CLASS", record.property_class or "—"],
            ["YR BUILT", str(record.year_built) if record.year_built else "—"],
            [Paragraph(broker_line, self.styles["CardMeta"]), ""],
        ]
        t = Table(data, colWidths=[0.65 * inch, 1.55 * inch])
        t.setStyle(TableStyle([
            ("BACKGROUND", (0, 0), (-1, 0), colors.HexColor(COLOR_NAVY)),
            ("TEXTCOLOR", (0, 0), (-1, 0), colors.white),
            ("SPAN", (0, 0), (1, 0)),
            ("SPAN", (0, 1), (1, 1)),
            ("SPAN", (0, 2), (1, 2)),
            ("SPAN", (0, -1), (1, -1)),
            ("FONTNAME", (0, 3), (0, -2), "Helvetica-Bold"),
            ("FONTSIZE", (0, 3), (-1, -2), 7),
            ("FONTSIZE", (1, 3), (1, -2), 7),
            ("TEXTCOLOR", (0, 3), (0, -2), colors.HexColor(COLOR_GRAY)),
            ("BOX", (0, 0), (-1, -1), 0.5, colors.HexColor("#DEE2E6")),
            ("TOPPADDING", (0, 0), (-1, -1), 3),
            ("BOTTOMPADDING", (0, 0), (-1, -1), 3),
            ("LEFTPADDING", (0, 0), (-1, -1), 5),
        ]))
        return t

    def generate(
        self,
        listings: list[PropertyRecord],
        sales: list[PropertyRecord],
        output_path: str,
        *,
        active_inventory: list[PropertyRecord] | None = None,
        market_commentary_override: dict[str, str] | None = None,
        submarket_order: list[str] | None = None,
        report_options: dict | None = None,
        no_sales_message: str | None = None,
    ) -> str:
        os.makedirs(os.path.dirname(output_path) or ".", exist_ok=True)
        opts = report_options or {}
        inv_mode = opts.get("intelligence_mode", "sales")

        listing_metrics = compute_listing_metrics(listings)
        sales_metrics = compute_sales_metrics(sales, listings)
        scorecard = compute_submarket_scorecard(listings, sales)
        if submarket_order:
            by_market = {r.market: r for r in scorecard}
            scorecard = [by_market[m] for m in submarket_order if m in by_market]
            for m in submarket_order:
                if m not in by_market:
                    from analytics import SubmarketRow
                    scorecard.append(SubmarketRow(market=m))
        brokers = compute_broker_activity(listings, sales)
        highlights = intelligence_highlights(
            sales, listings, active_inventory=active_inventory, mode=inv_mode,
        )
        deal = deal_to_watch(listings, sales)
        self._commentary_override = market_commentary_override or {}
        self._no_sales_message = no_sales_message
        self._report_options = opts

        doc = SimpleDocTemplate(
            output_path,
            pagesize=letter,
            leftMargin=MARGIN,
            rightMargin=MARGIN,
            topMargin=0.45 * inch,
            bottomMargin=0.45 * inch,
        )

        story = []
        story.extend(self._page_listings_summary(listing_metrics, listings, sales_metrics))
        story.append(PageBreak())
        story.extend(self._page_sales_summary(sales_metrics))
        story.append(PageBreak())
        story.extend(self._page_scorecard(scorecard, listings, sales))
        story.append(PageBreak())
        story.extend(self._page_listing_cards(listings))
        story.append(PageBreak())
        story.extend(self._page_sales_cards(sales, sales_metrics))
        story.append(PageBreak())
        story.extend(self._page_intelligence(highlights, deal, brokers, active_inventory))

        doc.build(story, onFirstPage=self._page_footer, onLaterPages=self._page_footer)
        return output_path

    def _page_footer(self, canvas, doc):
        canvas.saveState()
        canvas.setFont("Helvetica", 6)
        canvas.setFillColor(colors.HexColor(COLOR_GRAY))
        page_num = canvas.getPageNumber()
        canvas.drawRightString(PAGE_W - MARGIN, 0.35 * inch, f"Page {page_num} of 6")
        if page_num == 6:
            canvas.setFont("Helvetica", 5)
            text = FOOTER_DISCLAIMER
            # Wrap footer text
            max_w = PAGE_W - 2 * MARGIN
            words = text.split()
            line, lines = [], []
            for w in words:
                test = " ".join(line + [w])
                if canvas.stringWidth(test, "Helvetica", 5) < max_w:
                    line.append(w)
                else:
                    lines.append(" ".join(line))
                    line = [w]
            if line:
                lines.append(" ".join(line))
            y = 0.55 * inch
            for ln in lines:
                canvas.drawString(MARGIN, y, ln)
                y -= 7
        canvas.restoreState()

    def _page_listings_summary(
        self, m: ListingMetrics, listings: list, sales_m: SalesMetrics
    ) -> list:
        flow = self._header_block()
        flow.append(Paragraph(
            f"NEW LISTING ACTIVITY · {m.count} listings · {m.total_units} units",
            self.styles["SectionHead"],
        ))

        summary = (
            f"{m.count} multifamily listings totaling {m.total_units} units entered the Central Iowa market this week. "
            f"New inventory averaged {int(m.avg_units)} units per property with a {m.avg_vintage} average vintage. "
            f"{sales_m.count} sales totaling {sales_m.total_units} units closed"
        )
        if sales_m.total_volume:
            largest_sale = max((s for s in [] if False), default=None)
            summary += f", led by significant transactions. "
        else:
            summary += ". "
        top = max(m.by_market, key=m.by_market.get) if m.by_market else "DSM"
        summary += (
            f"{top} remained the most active submarket with {m.by_market.get(top, 0)} listings"
        )
        if sales_m.by_market.get(top):
            summary += f" and {sales_m.by_market.get(top, 0)} sales. "
        if m.avg_price_per_unit and sales_m.avg_price_per_unit:
            summary += (
                f"Average sold pricing of {_fmt_ppu(sales_m.avg_price_per_unit)}/unit exceeded "
                f"average listing pricing of {_fmt_ppu(m.avg_price_per_unit)}/unit, indicating a "
                f"compression in available inventory quality relative to what is transacting."
            )
        flow.append(Paragraph(summary, self.styles["BodyText2"]))
        flow.append(Spacer(1, 6))

        flow.append(self._kpi_row([
            (str(m.count), "NEW LISTINGS<br/>this week"),
            (_fmt_money(m.total_volume, short=True), "LISTING VOLUME<br/>asking price total"),
            (str(m.total_units), "UNITS LISTED<br/>across all listings"),
            (str(int(m.avg_units)), "AVG UNITS<br/>per listing"),
            (str(int(m.median_units)), "MEDIAN UNITS<br/>per listing"),
            (str(m.avg_vintage), "AVG VINTAGE<br/>year built"),
            (_fmt_ppu(m.avg_price_per_unit), "AVG PRICE/UNIT<br/>listing avg"),
            (_fmt_ppsf(m.avg_price_per_sf) if m.avg_price_per_sf else "—", "AVG PRICE/SF<br/>listing avg"),
        ]))
        flow.append(Spacer(1, 4))

        market_counts = {k: v for k, v in sorted(m.by_market.items(), key=lambda x: -x[1])}
        market_ppu = {k: int(v) for k, v in m.avg_list_per_unit_by_market.items() if v}

        chart_row1 = Table(
            [[
                _make_chart_bar(market_counts, "LISTINGS BY MARKET"),
                _make_chart_bar(market_ppu, "AVG LIST $/UNIT BY MARKET", COLOR_GOLD),
            ]],
            colWidths=[3.5 * inch, 3.5 * inch],
        )
        chart_row2 = Table(
            [[
                _make_chart_dist(m.unit_size_distribution, "UNIT SIZE DISTRIBUTION"),
                _make_chart_dist(m.vintage_distribution, "VINTAGE DISTRIBUTION"),
            ]],
            colWidths=[3.5 * inch, 3.5 * inch],
        )
        flow.append(chart_row1)
        flow.append(Spacer(1, 4))
        flow.append(chart_row2)
        return flow

    def _page_sales_summary(self, m: SalesMetrics) -> list:
        flow = self._header_block()
        flow.append(Paragraph(
            f"RECENT SALES ACTIVITY · {m.count} closings · {m.total_units} units",
            self.styles["SectionHead"],
        ))
        flow.append(Spacer(1, 6))
        flow.append(self._kpi_row([
            (str(m.count), "NEW SALES<br/>this week"),
            (_fmt_money(m.total_volume, short=True), "SALES VOLUME<br/>total consideration"),
            (str(m.total_units), "UNITS SOLD<br/>closed this week"),
            (str(int(m.avg_units)), "AVG UNITS<br/>per transaction"),
            (str(int(m.median_units)), "MEDIAN UNITS<br/>per sale"),
            (str(m.avg_vintage), "AVG VINTAGE<br/>year built"),
            (_fmt_ppu(m.avg_price_per_unit), "AVG $/UNIT<br/>sold pricing"),
            (
                f"{m.sale_list_ratio}%" if m.sale_list_ratio else "—",
                f"SALE/LIST RATIO<br/>{m.sale_list_ratio_note or ''}",
            ),
        ]))
        flow.append(Spacer(1, 8))

        market_counts = {k: v for k, v in sorted(m.by_market.items(), key=lambda x: -x[1])}
        market_ppu = {k: int(v) for k, v in m.avg_sold_per_unit_by_market.items() if v}
        chart_row = Table(
            [[
                _make_chart_bar(market_counts, "SALES BY MARKET", COLOR_GREEN),
                _make_chart_bar(market_ppu, "AVG SOLD $/UNIT BY MARKET", COLOR_GREEN),
            ]],
            colWidths=[3.4 * inch, 3.4 * inch],
        )
        flow.append(chart_row)
        return flow

    def _page_scorecard(
        self,
        rows: list[SubmarketRow],
        listings: list[PropertyRecord],
        sales: list[PropertyRecord],
    ) -> list:
        flow = self._header_block()
        week_short = self.week_ending.strftime("Week of %B %d").replace(" 0", " ") + _ordinal(self.week_ending.day) + f", {self.week_ending.year}"
        flow.append(Paragraph(f"SUBMARKET SCORECARD · {week_short}", self.styles["SectionHead"]))
        flow.append(Paragraph(
            "Color guide: Sales count GREEN = closings recorded · Sold $/Unit GREEN = transaction confirmed · GRAY = no activity",
            self.styles["CardMeta"],
        ))
        flow.append(Spacer(1, 4))

        header = ["Market", "Lists", "Sales", "Units", "Avg List $/Unit", "Avg Sold $/Unit", "List Units", "Sold Units"]
        data = [header]
        for r in rows:
            data.append([
                r.market,
                str(r.listings),
                str(r.sales),
                str(r.list_units + r.sold_units),
                _fmt_ppu(r.avg_list_per_unit),
                _fmt_ppu(r.avg_sold_per_unit),
                str(r.list_units),
                str(r.sold_units),
            ])

        t = Table(data, colWidths=[0.75 * inch] * 2 + [0.55 * inch] + [0.95 * inch] * 2 + [0.75 * inch] * 2)
        style_cmds = [
            ("BACKGROUND", (0, 0), (-1, 0), colors.HexColor(COLOR_NAVY)),
            ("TEXTCOLOR", (0, 0), (-1, 0), colors.white),
            ("FONTNAME", (0, 0), (-1, 0), "Helvetica-Bold"),
            ("FONTSIZE", (0, 0), (-1, -1), 7),
            ("BOX", (0, 0), (-1, -1), 0.5, colors.HexColor("#DEE2E6")),
            ("INNERGRID", (0, 0), (-1, -1), 0.5, colors.HexColor("#DEE2E6")),
            ("TOPPADDING", (0, 0), (-1, -1), 4),
            ("BOTTOMPADDING", (0, 0), (-1, -1), 4),
            ("ALIGN", (1, 1), (-1, -1), "CENTER"),
        ]
        for i, r in enumerate(rows, start=1):
            if r.sales > 0:
                style_cmds.append(("TEXTCOLOR", (2, i), (2, i), colors.HexColor(COLOR_GREEN)))
                if r.avg_sold_per_unit:
                    style_cmds.append(("TEXTCOLOR", (5, i), (5, i), colors.HexColor(COLOR_GREEN)))
            elif r.listings == 0 and r.sales == 0:
                style_cmds.append(("TEXTCOLOR", (0, i), (-1, i), colors.HexColor(COLOR_GRAY)))
        t.setStyle(TableStyle(style_cmds))
        flow.append(t)
        flow.append(Spacer(1, 10))

        flow.append(Paragraph("MARKET COMMENTARY", self.styles["SectionHead"]))
        for r in rows:
            commentary = self._commentary_override.get(r.market) or market_commentary(r.market, listings, sales)
            flow.append(Paragraph(f"<b>{r.market}</b>", self.styles["BodyText2"]))
            flow.append(Paragraph(commentary, self.styles["BodyText2"]))
            flow.append(Spacer(1, 3))
        return flow

    def _page_listing_cards(self, listings: list[PropertyRecord]) -> list:
        flow = self._header_block()
        total_units = sum(l.units or 0 for l in listings)
        week_short = self.week_ending.strftime("week of %B %d").replace(" 0", " ") + _ordinal(self.week_ending.day) + f", {self.week_ending.year}"
        flow.append(Paragraph(
            f"NEW LISTINGS · {len(listings)} properties · {total_units} units · {week_short}",
            self.styles["SectionHead"],
        ))
        flow.append(Spacer(1, 6))

        if not listings:
            flow.append(Paragraph("No new listings recorded for this period.", self.styles["BodyText2"]))
            return flow

        cards = [self._property_card(l, "LISTED") for l in listings]
        rows = []
        for i in range(0, len(cards), 3):
            row = cards[i:i + 3]
            while len(row) < 3:
                row.append("")
            rows.append(row)

        t = Table(rows, colWidths=[2.35 * inch] * 3, rowHeights=[2.4 * inch] * len(rows))
        t.setStyle(TableStyle([
            ("VALIGN", (0, 0), (-1, -1), "TOP"),
            ("LEFTPADDING", (0, 0), (-1, -1), 3),
            ("RIGHTPADDING", (0, 0), (-1, -1), 3),
        ]))
        flow.append(t)
        return flow

    def _page_sales_cards(self, sales: list[PropertyRecord], m: SalesMetrics) -> list:
        flow = self._header_block()
        sales_head = f"RECENT SALES · {m.count} closings"
        if m.count:
            sales_head += f" · {m.total_units} units · {_fmt_money(m.total_volume, short=True)}"
        flow.append(Paragraph(sales_head, self.styles["SectionHead"]))
        if m.sale_list_ratio:
            gauge_text = (
                f"Sale-to-List Ratio Gauge {m.sale_list_ratio}% → BUYER ADVANTAGE "
                f"(based on {m.sale_list_ratio_note})"
            )
            flow.append(Paragraph(gauge_text, self.styles["BodyText2"]))
        flow.append(Spacer(1, 6))

        if not sales:
            msg = getattr(self, "_no_sales_message", None) or "No recent sales recorded for this period."
            flow.append(Paragraph(msg, self.styles["BodyText2"]))
            return flow

        cards = [self._property_card(s, "SOLD") for s in sales]
        rows = []
        for i in range(0, len(cards), 3):
            row = cards[i:i + 3]
            while len(row) < 3:
                row.append("")
            rows.append(row)

        t = Table(rows, colWidths=[2.35 * inch] * 3, rowHeights=[2.4 * inch] * len(rows))
        t.setStyle(TableStyle([
            ("VALIGN", (0, 0), (-1, -1), "TOP"),
            ("LEFTPADDING", (0, 0), (-1, -1), 3),
            ("RIGHTPADDING", (0, 0), (-1, -1), 3),
        ]))
        flow.append(t)
        return flow

    def _page_intelligence(
        self,
        highlights: dict,
        deal: dict,
        brokers: list[BrokerActivity],
        active_inventory: list[PropertyRecord] | None = None,
    ) -> list:
        flow = self._header_block()
        week_short = self.week_ending.strftime("Week of %B %d").replace(" 0", " ") + _ordinal(self.week_ending.day) + f", {self.week_ending.year}"
        flow.append(Paragraph(f"MARKET INTELLIGENCE · {week_short}", self.styles["SectionHead"]))
        flow.append(Spacer(1, 6))

        def highlight_card(title, line1, line2, line3):
            return Table([
                [Paragraph(title, self.styles["CardTitle"])],
                [Paragraph(line1, self.styles["CardAddress"])],
                [Paragraph(line2, self.styles["CardMeta"])],
                [Paragraph(line3, self.styles["KPIValue"])],
            ], colWidths=[2.2 * inch])

        cards = []
        opts = getattr(self, "_report_options", {})

        if highlights.get("mode") == "active_inventory":
            ln = highlights.get("largest_new_listing")
            if ln:
                cards.append(highlight_card(
                    "LARGEST NEW LISTING",
                    ln.address,
                    f"{ln.city} · {ln.units} units",
                    _fmt_money(ln.price),
                ))
            ha = highlights.get("highest_active_ppu")
            if ha:
                cards.append(highlight_card(
                    "HIGHEST ACTIVE $/UNIT",
                    ha.address,
                    f"{ha.city} · {ha.units} units",
                    f"{_fmt_ppu(ha.price_per_unit)}/unit",
                ))
            la = highlights.get("lowest_active_ppu")
            if la:
                cards.append(highlight_card(
                    "LOWEST ACTIVE $/UNIT",
                    la.address,
                    f"{la.city} · {la.units} units",
                    f"{_fmt_ppu(la.price_per_unit)}/unit",
                ))
            ll = highlights.get("largest_active_listing")
            if ll:
                price_note = "price TBD" if not ll.price else _fmt_money(ll.price)
                cards.append(highlight_card(
                    "LARGEST ACTIVE LISTING",
                    f"{ll.address}, {ll.city}",
                    f"{ll.units} units · {ll.broker_firm} · {price_note}",
                    f"{ll.units} Units",
                ))
        else:
            ls = highlights.get("largest_sale")
            if ls:
                cards.append(highlight_card(
                    "LARGEST SALE",
                    ls.address,
                    f"{ls.city} · {ls.units} units",
                    _fmt_money(ls.price),
                ))
            hp = highlights.get("highest_ppu")
            if hp:
                cards.append(highlight_card(
                    "HIGHEST $/UNIT SOLD",
                    f"{hp.address}, {hp.city}",
                    f"{hp.units} units · {hp.broker_firm}",
                    f"{_fmt_ppu(hp.price_per_unit)}/unit",
                ))
            lp = highlights.get("lowest_ppu")
            if lp:
                cards.append(highlight_card(
                    "LOWEST $/UNIT SOLD",
                    lp.address,
                    f"{lp.city} · {lp.units} units · {lp.broker_firm}",
                    f"{_fmt_ppu(lp.price_per_unit)}/unit",
                ))
            ll = highlights.get("largest_listing")
            if ll:
                cards.append(highlight_card(
                    "LARGEST LISTING",
                    f"{ll.address}, {ll.city}",
                    f"{ll.units} units · {ll.broker_firm} · price TBD",
                    f"{ll.units} Units",
                ))

        while len(cards) < 4:
            cards.append("")
        flow.append(Table([cards[:4]], colWidths=[2.2 * inch] * 4))
        flow.append(Spacer(1, 10))

        if opts.get("include_deal_to_watch", True):
            flow.append(Paragraph(f"DEAL TO WATCH — {deal['title']}", self.styles["SectionHead"]))
            flow.append(Paragraph(deal["body"], self.styles["BodyText2"]))
            if deal.get("broker_note"):
                flow.append(Paragraph(deal["broker_note"], self.styles["BodyText2"]))
            flow.append(Spacer(1, 8))

        if opts.get("include_brokers_table", True) and brokers:
            flow.append(Paragraph("BROKERS ACTIVE THIS WEEK", self.styles["SectionHead"]))
            broker_data = [["Firm", "Listings", "Sales", "Role"]]
            for b in brokers:
                broker_data.append([b.firm, str(b.listings), str(b.sales), b.role])
            bt = Table(broker_data, colWidths=[2.5 * inch, 0.9 * inch, 0.9 * inch, 1.5 * inch])
            bt.setStyle(TableStyle([
                ("BACKGROUND", (0, 0), (-1, 0), colors.HexColor(COLOR_NAVY)),
                ("TEXTCOLOR", (0, 0), (-1, 0), colors.white),
                ("FONTNAME", (0, 0), (-1, 0), "Helvetica-Bold"),
                ("FONTSIZE", (0, 0), (-1, -1), 7),
                ("BOX", (0, 0), (-1, -1), 0.5, colors.HexColor("#DEE2E6")),
                ("INNERGRID", (0, 0), (-1, -1), 0.5, colors.HexColor("#DEE2E6")),
                ("TOPPADDING", (0, 0), (-1, -1), 4),
                ("BOTTOMPADDING", (0, 0), (-1, -1), 4),
            ]))
            flow.append(bt)
        return flow


def _ordinal(n: int) -> str:
    if 11 <= n % 100 <= 13:
        return "th"
    return {1: "st", 2: "nd", 3: "rd"}.get(n % 10, "th")


def generate_report(
    listings: list[PropertyRecord],
    sales: list[PropertyRecord],
    week_ending: date,
    output_path: str,
    **kwargs,
) -> str:
    canvas = ReportCanvas(week_ending)
    return canvas.generate(listings, sales, output_path, **kwargs)
