"""QR code for pairing PulseDeck Panel / Pulse Mobile.

pulsedeck://pair?v=1&name=<PC>&hosts=<ip,ip>&port=<TLS port>&fp=<SHA-256 hex>&code=<6 digits>

The phone takes the full certificate fingerprint from the QR code and pins exactly that
certificate, so a man in the middle cannot pose as the PC (stronger than comparing the
short fingerprint by eye). The code is the same one-time code that is shown as digits.
"""
import io
from urllib.parse import urlencode

import segno


def payload(name, hosts, port, fingerprint, code):
    query = urlencode({"v": 1, "name": name, "hosts": ",".join(hosts), "port": port,
                       "fp": fingerprint.replace(":", "").upper(), "code": code})
    return f"pulsedeck://pair?{query}"


def png(text, scale=8):
    """Black on white with the standard quiet zone; low error correction keeps modules big for weak cameras."""
    out = io.BytesIO()
    segno.make(text, error="l").save(out, kind="png", scale=scale, border=4, dark="black", light="white")
    return out.getvalue()
