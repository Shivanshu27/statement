"""RenderPlan -> PDF bytes with reportlab.

``invariant=1`` removes the timestamp and random document id reportlab
would otherwise embed, so the same plan always produces the same bytes —
and therefore the same ``doc_id`` (INV-08).
"""

from __future__ import annotations

import io

from reportlab.pdfgen import canvas

from statement.forge.plan import Align, RenderPlan


def render_pdf(plan: RenderPlan) -> bytes:
    buf = io.BytesIO()
    c = canvas.Canvas(buf, pagesize=(plan.width, plan.height), invariant=1)
    c.setTitle(plan.title)
    c.setAuthor("statement forge (synthetic data)")
    for page in plan.pages:
        for item in page.items:
            c.setFont("Helvetica-Bold" if item.bold else "Helvetica", item.size)
            y = plan.height - item.top
            if item.align is Align.RIGHT:
                c.drawRightString(item.x, y, item.text)
            else:
                c.drawString(item.x, y, item.text)
        c.showPage()
    c.save()
    return buf.getvalue()
