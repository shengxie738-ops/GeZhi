"""Pure public-HTTPS normalization and fail-closed address-set classification.

No DNS resolution or transport occurs here. Task 3 must bind this complete
validated set to the actual numeric dial and peer before TLS/HTTP dispatch.
"""
from dataclasses import dataclass
import hashlib
import ipaddress
import json
import re
import unicodedata
from urllib.parse import quote, unquote, urlsplit, urlunsplit
import idna
from app.services.byok.errors import ByokError
from app.services.byok.limits import CAPS
from app.services.byok.types import ADAPTER_ID


@dataclass(frozen=True)
class NormalizedEndpoint:
    base_url: str
    endpoint_url: str
    host: str
    port: int
    base_path: str
    destination_digest: str


# Base classification uses the interpreter's complete ipaddress tables plus
# conservative explicit special-purpose ranges, including globally flagged
# anycast/transition allocations. Never rely only on sample SSRF blacklists.
_SPECIAL_V4 = tuple(ipaddress.ip_network(net) for net in (
    '0.0.0.0/8', '10.0.0.0/8', '100.64.0.0/10', '127.0.0.0/8', '169.254.0.0/16',
    '172.16.0.0/12', '192.0.0.0/24', '192.0.2.0/24', '192.31.196.0/24',
    '192.52.193.0/24', '192.88.99.0/24', '192.168.0.0/16', '192.175.48.0/24',
    '198.18.0.0/15', '198.51.100.0/24', '203.0.113.0/24', '224.0.0.0/4', '240.0.0.0/4'))
_SPECIAL_V6 = tuple(ipaddress.ip_network(net) for net in (
    '::/96', '::ffff:0:0/96', '64:ff9b::/96', '64:ff9b:1::/48', '100::/64',
    '2001::/23', '2001:db8::/32', '2002::/16', '2620:4f:8000::/48', '3fff::/20',
    '5f00::/16', 'fc00::/7', 'fe80::/10', 'ff00::/8'))
_GLOBAL_V6 = ipaddress.ip_network('2000::/3')


def is_global_unicast(value) -> bool:
    if type(value) is not str or '%' in value:
        return False
    try:
        address = ipaddress.ip_address(value)
    except ValueError:
        return False
    if not address.is_global or address.is_private or address.is_loopback or address.is_link_local or address.is_multicast or address.is_unspecified or address.is_reserved:
        return False
    if isinstance(address, ipaddress.IPv4Address):
        return not any(address in network for network in _SPECIAL_V4)
    return address in _GLOBAL_V6 and address.ipv4_mapped is None and not any(address in network for network in _SPECIAL_V6)


def validate_resolved_addresses(values) -> tuple[str, ...]:
    if type(values) not in (list, tuple) or not values:
        raise ByokError('DNS_REJECTED')
    result = []
    for value in values:
        if not is_global_unicast(value):
            raise ByokError('DNS_REJECTED')
        canonical = str(ipaddress.ip_address(value))
        if canonical not in result:
            result.append(canonical)
            if len(result) > CAPS.dns_addresses:
                raise ByokError('DNS_REJECTED')
    return tuple(result)


def _bad_chars(value):
    return any(char.isspace() or unicodedata.category(char) in {'Cc', 'Cf', 'Cs'} for char in value)


def _path(raw):
    if raw and not raw.startswith('/'):
        raise ValueError('invalid path')
    if re.search(r'%(?![0-9A-Fa-f]{2})', raw):
        raise ValueError('invalid path escape')
    candidate = raw
    # Validate every escape layer without changing legitimate path casing.
    # Nested escaped separators/dot segments cannot bypass an upstream decoder.
    for _ in range(len(raw) + 1):
        if re.search(r'%(?:2f|5c)', candidate, re.I) or '\\' in candidate or any(unicodedata.category(char) in {'Cc', 'Cf', 'Cs'} for char in candidate):
            raise ValueError('invalid path characters')
        if any(segment in {'.', '..'} for segment in candidate.split('/')):
            raise ValueError('invalid path segments')
        decoded = unquote(candidate, encoding='utf-8', errors='strict')
        if decoded == candidate:
            break
        candidate = decoded
    # Keep the original legitimate escapes and canonicalize their hex digits.
    raw = re.sub(r'%[0-9a-fA-F]{2}', lambda match: match.group().upper(), raw)
    return quote(raw, safe="/%:@!$&'()*+,;=-._~")


def normalize_endpoint(raw: str) -> NormalizedEndpoint:
    try:
        if type(raw) is not str or not 1 <= len(raw) <= CAPS.url_chars or _bad_chars(raw) or '\\' in raw or '?' in raw or '#' in raw:
            raise ValueError('invalid URL')
        parsed = urlsplit(raw)
        if parsed.scheme.lower() != 'https' or not parsed.netloc or parsed.username is not None or parsed.password is not None or '%' in parsed.netloc or '@' in parsed.netloc:
            raise ValueError('invalid authority')
        authority = parsed.netloc
        host = parsed.hostname
        if host is None:
            raise ValueError('missing hostname')
        if authority.startswith('['):
            match = re.fullmatch(r'\[([^\]]+)\](?::(443))?', authority)
            if match is None:
                raise ValueError('invalid IPv6 authority')
            address = ipaddress.IPv6Address(match.group(1))
            host = str(address)
            if not is_global_unicast(host):
                raise ValueError('prohibited address')
            canonical_authority = '[' + host + ']'
        else:
            if re.fullmatch(r'[^:]+(?::443)?', authority) is None:
                raise ValueError('invalid authority')
            if ':' in authority:
                _, port = authority.rsplit(':', 1)
                if port != '443':
                    raise ValueError('invalid port')
            host = idna.encode(host, uts46=True, std3_rules=True).decode('ascii').lower().rstrip('.')
            if not host or len(host) > 253 or host == 'localhost' or host.endswith('.localhost') or host == 'local' or host.endswith('.local'):
                raise ValueError('prohibited hostname')
            try:
                address = ipaddress.IPv4Address(host)
            except ValueError:
                if '.' not in host or all(re.fullmatch(r'(?:[0-9]+|0x[0-9a-f]+)', label, re.I) for label in host.split('.')):
                    raise ValueError('ambiguous numeric or local hostname')
            else:
                if str(address) != host or not is_global_unicast(host):
                    raise ValueError('prohibited address')
            canonical_authority = host
        path = _path(parsed.path)
        suffix = '/chat/completions'
        if path.endswith(suffix):
            path = path[:-len(suffix)]
        base_path = path.rstrip('/')
        base_url = urlunsplit(('https', canonical_authority, base_path, '', ''))
        endpoint_url = urlunsplit(('https', canonical_authority, base_path + suffix, '', ''))
        destination = {'adapter_id': ADAPTER_ID, 'host': host, 'port': 443, 'base_path': base_path}
        digest = hashlib.sha256(json.dumps(destination, ensure_ascii=False, sort_keys=True, separators=(',', ':'), allow_nan=False).encode('utf-8')).hexdigest()
        return NormalizedEndpoint(base_url, endpoint_url, host, 443, base_path, digest)
    except (ValueError, UnicodeError, idna.IDNAError):
        raise ByokError('ENDPOINT_NOT_ALLOWED', fields=('base_url',)) from None
