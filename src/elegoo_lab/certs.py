"""HTTPS for the home network, so the phone can install the workshop as an app (PWA).

Browsers only install apps (and run service workers) over HTTPS. We create a private certificate
authority once ("Atelier CC2 – autorité locale"); the phone trusts it after a one-time install of
``/lab/ca.crt``. It signs a short-lived certificate for this PC's addresses, renewed automatically.
The CA's private key never leaves ``.certs/`` (readable by you only).
"""

from __future__ import annotations

import datetime as dt
import ipaddress
import os
import socket
from pathlib import Path

from cryptography import x509
from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import ec
from cryptography.x509.oid import ExtendedKeyUsageOID, NameOID

from . import config

CA_DAYS, SERVER_DAYS, RENEW_DAYS = 3650, 397, 30   # 397: the most phones accept for a server certificate


def _dir() -> Path:
    d = config.ROOT / ".certs"
    d.mkdir(mode=0o700, exist_ok=True)
    return d


def _write_key(path: Path, key: ec.EllipticCurvePrivateKey) -> None:
    path.write_bytes(key.private_bytes(serialization.Encoding.PEM, serialization.PrivateFormat.PKCS8,
                                       serialization.NoEncryption()))
    os.chmod(path, 0o600)


def _now() -> dt.datetime:
    return dt.datetime.now(dt.timezone.utc)


def _ca() -> tuple[ec.EllipticCurvePrivateKey, x509.Certificate]:
    d = _dir()
    key_p, crt_p = d / "ca.key", d / "ca.crt"
    if key_p.exists() and crt_p.exists():
        return (serialization.load_pem_private_key(key_p.read_bytes(), None),
                x509.load_pem_x509_certificate(crt_p.read_bytes()))
    key = ec.generate_private_key(ec.SECP256R1())
    name = x509.Name([x509.NameAttribute(NameOID.COMMON_NAME, f"Atelier CC2 – autorité locale ({socket.gethostname()})"),
                      x509.NameAttribute(NameOID.ORGANIZATION_NAME, "Atelier CC2")])
    crt = (x509.CertificateBuilder().subject_name(name).issuer_name(name).public_key(key.public_key())
           .serial_number(x509.random_serial_number())
           .not_valid_before(_now() - dt.timedelta(days=1)).not_valid_after(_now() + dt.timedelta(days=CA_DAYS))
           .add_extension(x509.BasicConstraints(ca=True, path_length=0), critical=True)
           .add_extension(x509.KeyUsage(digital_signature=True, key_cert_sign=True, crl_sign=True, content_commitment=False,
                                        key_encipherment=False, data_encipherment=False, key_agreement=False,
                                        encipher_only=False, decipher_only=False), critical=True)
           .add_extension(x509.SubjectKeyIdentifier.from_public_key(key.public_key()), critical=False)
           .sign(key, hashes.SHA256()))
    _write_key(key_p, key)
    crt_p.write_bytes(crt.public_bytes(serialization.Encoding.PEM))
    return key, crt


def ca_pem() -> bytes:
    """The public CA certificate, for the phone to install (never the key)."""
    return _ca()[1].public_bytes(serialization.Encoding.PEM)


def ensure(ips: list[str], hostnames: list[str] | None = None) -> tuple[Path, Path]:
    """Server certificate + key for these addresses and names (plus localhost and <host>.local); renewed when needed."""
    ca_key, ca = _ca()
    d = _dir()
    crt_p, key_p = d / "server.crt", d / "server.key"
    names = sorted({"localhost", f"{socket.gethostname()}.local", *(hostnames or [])})
    addrs = sorted({"127.0.0.1", *ips})
    if crt_p.exists() and key_p.exists():
        old = x509.load_pem_x509_certificate(crt_p.read_bytes())
        san = old.extensions.get_extension_for_class(x509.SubjectAlternativeName).value
        have = {str(a) for a in san.get_values_for_type(x509.IPAddress)}
        have_names = set(san.get_values_for_type(x509.DNSName))
        if set(addrs) <= have and set(names) <= have_names and old.not_valid_after_utc - _now() > dt.timedelta(days=RENEW_DAYS) \
                and old.issuer == ca.subject:
            return crt_p, key_p
    key = ec.generate_private_key(ec.SECP256R1())
    crt = (x509.CertificateBuilder()
           .subject_name(x509.Name([x509.NameAttribute(NameOID.COMMON_NAME, "Atelier CC2")]))
           .issuer_name(ca.subject).public_key(key.public_key()).serial_number(x509.random_serial_number())
           .not_valid_before(_now() - dt.timedelta(days=1)).not_valid_after(_now() + dt.timedelta(days=SERVER_DAYS))
           .add_extension(x509.SubjectAlternativeName([*(x509.DNSName(n) for n in names),
                                                       *(x509.IPAddress(ipaddress.ip_address(a)) for a in addrs)]), critical=False)
           .add_extension(x509.BasicConstraints(ca=False, path_length=None), critical=True)
           .add_extension(x509.ExtendedKeyUsage([ExtendedKeyUsageOID.SERVER_AUTH]), critical=False)
           .add_extension(x509.AuthorityKeyIdentifier.from_issuer_public_key(ca_key.public_key()), critical=False)
           .sign(ca_key, hashes.SHA256()))
    _write_key(key_p, key)
    crt_p.write_bytes(crt.public_bytes(serialization.Encoding.PEM))
    return crt_p, key_p
