"""TLS identity of this PC for API v1: a self-signed certificate created on first use.

Phones cannot verify a self-signed certificate through a CA, so they pin its SHA-256
fingerprint at pairing time (see docs/PULSE_MOBILE_API_V1.md). The private key is stored
encrypted; its password is kept in the DPAPI secret store.
"""
import datetime
import hashlib
import secrets as random
import socket
import ssl
from pathlib import Path

from pulse_pc.core.secrets import SecretStore

CERT_NAME, KEY_NAME = "cert.pem", "key.pem"
PASSWORD_SECRET = "TLS_KEY_PASSWORD"
VALID_DAYS = 3650


def _paths(config_dir):
    folder = Path(config_dir) / "tls"
    return folder, folder / CERT_NAME, folder / KEY_NAME


def ensure_certificate(config_dir):
    """Create the certificate once; returns (cert path, key path, password)."""
    from cryptography import x509
    from cryptography.hazmat.primitives import hashes, serialization
    from cryptography.hazmat.primitives.asymmetric import ec
    from cryptography.x509.oid import NameOID

    folder, cert_path, key_path = _paths(config_dir)
    store = SecretStore(config_dir)
    password = store.get(PASSWORD_SECRET)
    if cert_path.exists() and key_path.exists() and password:
        return cert_path, key_path, password

    folder.mkdir(parents=True, exist_ok=True)
    password = random.token_urlsafe(32)
    key = ec.generate_private_key(ec.SECP256R1())
    name = x509.Name([x509.NameAttribute(NameOID.COMMON_NAME, f"PulseDeck {socket.gethostname()}"[:64]),
                      x509.NameAttribute(NameOID.ORGANIZATION_NAME, "PulseDeck")])
    now = datetime.datetime.now(datetime.timezone.utc)
    cert = (x509.CertificateBuilder().subject_name(name).issuer_name(name).public_key(key.public_key())
            .serial_number(x509.random_serial_number())
            .not_valid_before(now - datetime.timedelta(minutes=5))
            .not_valid_after(now + datetime.timedelta(days=VALID_DAYS))
            .add_extension(x509.BasicConstraints(ca=False, path_length=None), critical=True)
            .sign(key, hashes.SHA256()))
    key_path.write_bytes(key.private_bytes(serialization.Encoding.PEM, serialization.PrivateFormat.PKCS8,
                                           serialization.BestAvailableEncryption(password.encode())))
    cert_path.write_bytes(cert.public_bytes(serialization.Encoding.PEM))
    store.set(PASSWORD_SECRET, password)
    return cert_path, key_path, password


def server_context(config_dir):
    cert_path, key_path, password = ensure_certificate(config_dir)
    context = ssl.create_default_context(ssl.Purpose.CLIENT_AUTH)
    context.minimum_version = ssl.TLSVersion.TLSv1_2
    context.load_cert_chain(cert_path, key_path, password=password)
    return context


def fingerprint(config_dir):
    """SHA-256 of the certificate (DER), as AA:BB:…; '' if there is no certificate yet."""
    _, cert_path, _ = _paths(config_dir)
    if not cert_path.exists():
        return ""
    der = ssl.PEM_cert_to_DER_cert(cert_path.read_text(encoding="ascii"))
    digest = hashlib.sha256(der).hexdigest().upper()
    return ":".join(digest[i:i + 2] for i in range(0, len(digest), 2))


def short_fingerprint(value):
    """First 8 bytes in groups, for reading aloud: 'AB12 CD34 EF56 7890'."""
    hexes = value.replace(":", "")[:16]
    return " ".join(hexes[i:i + 4] for i in range(0, len(hexes), 4))
