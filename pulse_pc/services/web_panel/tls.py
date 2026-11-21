"""HTTPS for the web panel: a home certificate authority of this PC and a server certificate.

Phone browsers trust a certificate only through an authority they know. The owner
installs this PC's authority once (iPhone: a profile, Android: «Сертификат ЦС»), then
https://<pc>:8781 opens without warnings and the browser may control music.

Safety of the authority:
  * Name Constraints: it can vouch only for home addresses (10/8, 172.16/12, 192.168/16,
    169.254/16, 127/8) and, for site names and e-mail, only for the reserved «.invalid»
    (RFC 6761, never a real site). Even with its key stolen nobody could fake another website
    with it. An authority made before this (IP addresses only) is replaced once; the phone
    then installs the new one;
  * its private key is stored encrypted, the password in the DPAPI secret store, like the
    API v1 certificate (services/local_api/tls.py).

The server certificate follows Apple's rules for user-trusted authorities: P-256, SHA-256,
the IP addresses in SAN, serverAuth, at most 825 days (we use 397). It is renewed
automatically when an address changes or it is a month from expiry.
"""
import datetime
import hashlib
import ipaddress
import plistlib
import secrets as random
import socket
import ssl
import uuid
from pathlib import Path

from pulse_pc.core.secrets import SecretStore

FOLDER = "web_tls"
CA_CERT, CA_KEY, CERT, KEY = "ca.pem", "ca-key.pem", "server.pem", "server-key.pem"
PASSWORD_SECRET = "WEB_TLS_KEY_PASSWORD"
CA_DAYS = 3650
SERVER_DAYS = 397
RENEW_DAYS = 30
HOME_NETWORKS = ("10.0.0.0/8", "172.16.0.0/12", "192.168.0.0/16", "169.254.0.0/16", "127.0.0.0/8")
NO_SITES = "invalid"        # the only site name (and e-mail domain) the authority may vouch for


def _constrains_names(cert):
    """Does this authority also limit site names (not only IP addresses)?"""
    from cryptography import x509
    try:
        constraints = cert.extensions.get_extension_for_class(x509.NameConstraints).value
    except x509.ExtensionNotFound:
        return False
    return any(isinstance(n, x509.DNSName) for n in constraints.permitted_subtrees or ())


def _folder(config_dir):
    return Path(config_dir) / FOLDER


def _password(config_dir):
    store = SecretStore(config_dir)
    password = store.get(PASSWORD_SECRET)
    if not password:
        password = random.token_urlsafe(32)
        store.set(PASSWORD_SECRET, password)
    return password


def _write_key(path, key, password):
    from cryptography.hazmat.primitives import serialization
    path.write_bytes(key.private_bytes(serialization.Encoding.PEM, serialization.PrivateFormat.PKCS8,
                                       serialization.BestAvailableEncryption(password.encode())))


def _read_key(path, password):
    from cryptography.hazmat.primitives import serialization
    return serialization.load_pem_private_key(path.read_bytes(), password.encode())


def _now():
    return datetime.datetime.now(datetime.timezone.utc)


def ensure_authority(config_dir):
    """The home authority of this PC (created once); returns (certificate, key)."""
    from cryptography import x509
    from cryptography.hazmat.primitives import hashes
    from cryptography.hazmat.primitives.asymmetric import ec
    from cryptography.x509.oid import NameOID

    folder = _folder(config_dir)
    cert_path, key_path = folder / CA_CERT, folder / CA_KEY
    password = _password(config_dir)
    if cert_path.exists() and key_path.exists():
        try:
            cert = x509.load_pem_x509_certificate(cert_path.read_bytes())
            if _constrains_names(cert):
                return cert, _read_key(key_path, password)
            # made before site names were constrained: replaced by a new one (below)
        except (ValueError, TypeError):
            pass        # unreadable (password lost with the Windows profile): make a new one
    folder.mkdir(parents=True, exist_ok=True)
    key = ec.generate_private_key(ec.SECP256R1())
    name = x509.Name([x509.NameAttribute(NameOID.COMMON_NAME, f"PulseDeck {socket.gethostname()}"[:64]),
                      x509.NameAttribute(NameOID.ORGANIZATION_NAME, "PulseDeck (домашний сертификат)")])
    now = _now()
    permitted = [x509.IPAddress(ipaddress.ip_network(net)) for net in HOME_NETWORKS] + \
        [x509.DNSName(NO_SITES), x509.RFC822Name(NO_SITES)]
    cert = (x509.CertificateBuilder().subject_name(name).issuer_name(name).public_key(key.public_key())
            .serial_number(x509.random_serial_number())
            .not_valid_before(now - datetime.timedelta(minutes=5))
            .not_valid_after(now + datetime.timedelta(days=CA_DAYS))
            .add_extension(x509.BasicConstraints(ca=True, path_length=0), critical=True)
            .add_extension(x509.KeyUsage(digital_signature=True, key_cert_sign=True, crl_sign=True,
                                         content_commitment=False, key_encipherment=False, data_encipherment=False,
                                         key_agreement=False, encipher_only=False, decipher_only=False), critical=True)
            .add_extension(x509.NameConstraints(permitted_subtrees=permitted, excluded_subtrees=None), critical=True)
            .add_extension(x509.SubjectKeyIdentifier.from_public_key(key.public_key()), critical=False)
            .sign(key, hashes.SHA256()))
    _write_key(key_path, key, password)
    from cryptography.hazmat.primitives import serialization
    cert_path.write_bytes(cert.public_bytes(serialization.Encoding.PEM))
    for stale in (folder / CERT, folder / KEY):     # signed by the old authority
        stale.unlink(missing_ok=True)
    return cert, key


def _home(address):
    try:
        ip = ipaddress.ip_address(address)
    except ValueError:
        return False
    return any(ip in ipaddress.ip_network(net) for net in HOME_NETWORKS)


def ensure_server_certificate(config_dir, addresses):
    """Server certificate for these LAN addresses (+127.0.0.1); returns (cert path, key path, password)."""
    from cryptography import x509
    from cryptography.hazmat.primitives import hashes, serialization
    from cryptography.hazmat.primitives.asymmetric import ec
    from cryptography.x509.oid import ExtendedKeyUsageOID, NameOID

    ca_cert, ca_key = ensure_authority(config_dir)
    folder = _folder(config_dir)
    cert_path, key_path = folder / CERT, folder / KEY
    password = _password(config_dir)
    wanted = sorted({a for a in addresses if _home(a)} | {"127.0.0.1"})
    if cert_path.exists() and key_path.exists():
        try:
            current = x509.load_pem_x509_certificate(cert_path.read_bytes())
            names = sorted(str(ip) for ip in current.extensions.get_extension_for_class(
                x509.SubjectAlternativeName).value.get_values_for_type(x509.IPAddress))
            fresh = current.not_valid_after_utc - _now() > datetime.timedelta(days=RENEW_DAYS)
            signed_by_ca = current.issuer == ca_cert.subject
            if names == wanted and fresh and signed_by_ca:
                _read_key(key_path, password)       # still readable
                return cert_path, key_path, password
        except (ValueError, TypeError, x509.ExtensionNotFound):
            pass
    key = ec.generate_private_key(ec.SECP256R1())
    now = _now()
    cert = (x509.CertificateBuilder()
            .subject_name(x509.Name([x509.NameAttribute(NameOID.COMMON_NAME, "PulseDeck")]))
            .issuer_name(ca_cert.subject).public_key(key.public_key())
            .serial_number(x509.random_serial_number())
            .not_valid_before(now - datetime.timedelta(minutes=5))
            .not_valid_after(now + datetime.timedelta(days=SERVER_DAYS))
            .add_extension(x509.BasicConstraints(ca=False, path_length=None), critical=True)
            .add_extension(x509.KeyUsage(digital_signature=True, key_encipherment=False, key_cert_sign=False,
                                         crl_sign=False, content_commitment=False, data_encipherment=False,
                                         key_agreement=False, encipher_only=False, decipher_only=False), critical=True)
            .add_extension(x509.ExtendedKeyUsage([ExtendedKeyUsageOID.SERVER_AUTH]), critical=False)
            .add_extension(x509.SubjectAlternativeName([x509.IPAddress(ipaddress.ip_address(a)) for a in wanted]),
                           critical=False)
            .add_extension(x509.AuthorityKeyIdentifier.from_issuer_public_key(ca_key.public_key()), critical=False)
            .sign(ca_key, hashes.SHA256()))
    _write_key(key_path, key, password)
    cert_path.write_bytes(cert.public_bytes(serialization.Encoding.PEM))
    return cert_path, key_path, password


def server_context(config_dir, addresses):
    cert_path, key_path, password = ensure_server_certificate(config_dir, addresses)
    context = ssl.create_default_context(ssl.Purpose.CLIENT_AUTH)
    context.minimum_version = ssl.TLSVersion.TLSv1_2
    context.load_cert_chain(cert_path, key_path, password=password)
    return context


def authority_der(config_dir):
    from cryptography.hazmat.primitives import serialization
    cert, _ = ensure_authority(config_dir)
    return cert.public_bytes(serialization.Encoding.DER)


def authority_fingerprint(config_dir):
    digest = hashlib.sha256(authority_der(config_dir)).hexdigest().upper()
    return " ".join(digest[i:i + 4] for i in range(0, 16, 4))


def mobileconfig(config_dir):
    """iPhone/iPad profile with the authority (Settings shows «Профиль загружен»)."""
    der = authority_der(config_dir)
    host = socket.gethostname()
    payload_id = uuid.uuid5(uuid.NAMESPACE_OID, hashlib.sha256(der).hexdigest())
    profile = {
        "PayloadType": "Configuration", "PayloadVersion": 1,
        "PayloadIdentifier": f"pulsedeck.webpanel.{payload_id}",
        "PayloadUUID": str(uuid.uuid5(payload_id, "profile")).upper(),
        "PayloadDisplayName": f"PulseDeck — {host}",
        "PayloadDescription": ("Домашний сертификат вашего ПК: веб-панель PulseDeck открывается по HTTPS без "
                               "предупреждений. Действует только для адресов домашней сети."),
        "PayloadOrganization": "PulseDeck",
        "PayloadRemovalDisallowed": False,
        "PayloadContent": [{
            "PayloadType": "com.apple.security.root", "PayloadVersion": 1,
            "PayloadIdentifier": f"pulsedeck.webpanel.{payload_id}.ca",
            "PayloadUUID": str(uuid.uuid5(payload_id, "ca")).upper(),
            "PayloadDisplayName": f"PulseDeck {host}",
            "PayloadContent": der,
        }],
    }
    return plistlib.dumps(profile, fmt=plistlib.FMT_XML)
