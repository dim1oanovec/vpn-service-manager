from __future__ import annotations

import asyncio
from io import BytesIO

import qrcode
from qrcode.image.pil import PilImage


def _render(payload: str) -> bytes:
    qr = qrcode.QRCode(
        version=None,
        error_correction=qrcode.constants.ERROR_CORRECT_M,
        box_size=8,
        border=2,
    )
    qr.add_data(payload)
    qr.make(fit=True)
    image: PilImage = qr.make_image(fill_color="black", back_color="white")
    buffer = BytesIO()
    image.save(buffer, format="PNG")
    return buffer.getvalue()


async def make_qr_png(payload: str) -> bytes:
    """QR генерируется в тредпуле, чтобы не блокировать event loop."""
    return await asyncio.to_thread(_render, payload)
