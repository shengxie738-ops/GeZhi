"""Bounded versioned bytes-only framing. This module provides no sandbox/time limit."""
from dataclasses import dataclass
import struct
from typing import BinaryIO

REQUEST_MAGIC = b"GZCWREQ1"
RESPONSE_MAGIC = b"GZCWRES1"
EXT_PDF, EXT_PPTX = 1, 2
KIND_READY, KIND_ERROR = 1, 2
MAX_ERROR_BYTES = 32
LIMIT_NAMES = (
    'max_file_bytes', 'max_pages', 'max_page_chars', 'max_total_chars',
    'max_output_bytes', 'max_zip_entries', 'max_zip_member_bytes',
    'max_zip_total_bytes', 'max_zip_ratio', 'max_xml_depth', 'max_xml_elements',
    'max_wall_seconds', 'max_cpu_seconds', 'max_memory_bytes',
)
LIMIT_CAPS = (10*1024*1024, 200, 20000, 200000, 1024*1024, 2048,
              16*1024*1024, 48*1024*1024, 100, 64, 100000, 5, 3, 256*1024*1024)
ERROR_CODES = frozenset({
    'INVALID_INPUT', 'INVALID_LIMITS', 'UNSUPPORTED_FORMAT', 'EMPTY_INPUT',
    'FILE_LIMIT', 'FORMAT_MISMATCH', 'CORRUPT_SOURCE', 'ENCRYPTED_SOURCE',
    'NO_EXTRACTABLE_TEXT', 'PAGE_LIMIT', 'PAGE_TEXT_LIMIT', 'TOTAL_TEXT_LIMIT',
    'OUTPUT_LIMIT', 'ZIP_ENTRY_LIMIT', 'ZIP_MEMBER_LIMIT', 'ZIP_TOTAL_LIMIT',
    'ZIP_RATIO_LIMIT', 'UNSAFE_ARCHIVE', 'UNSAFE_XML', 'XML_DEPTH_LIMIT',
    'XML_ELEMENT_LIMIT', 'DEPENDENCY_UNAVAILABLE', 'ISOLATION_UNAVAILABLE',
    'HARD_LIMITS_UNAVAILABLE', 'INVALID_OUTPUT', 'RUNNER_FAILED',
    'DEADLINE_EXCEEDED', 'RESOURCE_LIMIT', 'EXTRACTION_FAILED',
})
_HEADER = struct.Struct('>8sBI14I')

class WireProtocolError(Exception):
    def __init__(self, code: str):
        self.code = code if type(code) is str and code in ERROR_CODES else 'EXTRACTION_FAILED'
        super().__init__(self.code)

@dataclass(frozen=True)
class RequestHeader:
    extension: str
    limits: tuple[int, ...]
    data_length: int

@dataclass(frozen=True)
class WireRequest:
    extension: str
    limits: tuple[int, ...]
    data: bytes

@dataclass(frozen=True)
class WirePage:
    page: int
    text: str

@dataclass(frozen=True)
class WireResponse:
    pages: tuple[WirePage, ...] = ()
    error_code: str | None = None

def validate_limits(limits: tuple[int, ...]) -> None:
    if type(limits) is not tuple or len(limits) != len(LIMIT_CAPS):
        raise WireProtocolError('INVALID_LIMITS')
    if any(type(value) is not int or not 1 <= value <= cap for value, cap in zip(limits, LIMIT_CAPS)):
        raise WireProtocolError('INVALID_LIMITS')

def _validate_header(header: RequestHeader) -> None:
    if type(header) is not RequestHeader:
        raise WireProtocolError('INVALID_INPUT')
    validate_limits(header.limits)
    if type(header.extension) is not str or header.extension not in ('.pdf', '.pptx'):
        raise WireProtocolError('UNSUPPORTED_FORMAT')
    if type(header.data_length) is not int or header.data_length < 1:
        raise WireProtocolError('EMPTY_INPUT')
    if header.data_length > header.limits[0]:
        raise WireProtocolError('FILE_LIMIT')

def _read_exact(source: BinaryIO, count: int, code: str) -> bytes:
    pieces = bytearray()
    while len(pieces) < count:
        wanted = min(65536, count-len(pieces))
        piece = source.read(wanted)
        if type(piece) is not bytes or not piece or len(piece) > wanted:
            raise WireProtocolError(code)
        pieces.extend(piece)
    return bytes(pieces)

def _eof(source: BinaryIO, code: str) -> None:
    value = source.read(1)
    if type(value) is not bytes or value != b'':
        raise WireProtocolError(code)

def read_request_header(source: BinaryIO) -> RequestHeader:
    """Read exactly 69 bytes, allowing hard limits before the document body."""
    magic, extension, length, *limits = _HEADER.unpack(_read_exact(source, _HEADER.size, 'INVALID_INPUT'))
    if magic != REQUEST_MAGIC or extension not in (EXT_PDF, EXT_PPTX):
        raise WireProtocolError('INVALID_INPUT')
    header = RequestHeader('.pdf' if extension == EXT_PDF else '.pptx', tuple(limits), length)
    _validate_header(header)
    return header

def read_request_body(source: BinaryIO, header: RequestHeader) -> WireRequest:
    _validate_header(header)
    data = _read_exact(source, header.data_length, 'INVALID_INPUT')
    _eof(source, 'INVALID_INPUT')
    return WireRequest(header.extension, header.limits, data)

def read_request(source: BinaryIO) -> WireRequest:
    return read_request_body(source, read_request_header(source))

def encode_request(request: WireRequest) -> bytes:
    if type(request) is not WireRequest or type(request.data) is not bytes:
        raise WireProtocolError('INVALID_INPUT')
    header = RequestHeader(request.extension, request.limits, len(request.data))
    _validate_header(header)
    return _HEADER.pack(REQUEST_MAGIC, EXT_PDF if request.extension == '.pdf' else EXT_PPTX,
                        len(request.data), *request.limits) + request.data

def response_transport_cap(limits: tuple[int, ...]) -> int:
    validate_limits(limits)
    return max(43, 11 + 6*limits[1] + limits[4])

def _validate_pages(pages: tuple[WirePage, ...], limits: tuple[int, ...]) -> tuple[bytes, ...]:
    validate_limits(limits)
    if type(pages) is not tuple or not pages:
        raise WireProtocolError('INVALID_OUTPUT')
    if len(pages) > limits[1]:
        raise WireProtocolError('PAGE_LIMIT')
    encoded, characters, byte_count, searchable = [], 0, 0, False
    for index, page in enumerate(pages, 1):
        if (type(page) is not WirePage or type(page.page) is not int or page.page != index
                or type(page.text) is not str):
            raise WireProtocolError('INVALID_OUTPUT')
        if len(page.text) > limits[2]:
            raise WireProtocolError('PAGE_TEXT_LIMIT')
        characters += len(page.text)
        if characters > limits[3]:
            raise WireProtocolError('TOTAL_TEXT_LIMIT')
        try:
            text = page.text.encode('utf-8', errors='strict')
        except UnicodeError:
            raise WireProtocolError('INVALID_OUTPUT') from None
        byte_count += len(text)
        if byte_count > limits[4]:
            raise WireProtocolError('OUTPUT_LIMIT')
        encoded.append(text)
        searchable = searchable or bool(page.text.strip())
    if not searchable:
        raise WireProtocolError('NO_EXTRACTABLE_TEXT')
    return tuple(encoded)

def error_response(code: str) -> bytes:
    safe = WireProtocolError(code).code.encode('ascii')
    return RESPONSE_MAGIC + bytes((KIND_ERROR,)) + struct.pack('>H', len(safe)) + safe

def encode_response(response: WireResponse, limits: tuple[int, ...]) -> bytes:
    validate_limits(limits)
    if type(response) is not WireResponse:
        raise WireProtocolError('INVALID_OUTPUT')
    if response.error_code is not None:
        if (type(response.pages) is not tuple or response.pages or type(response.error_code) is not str
                or response.error_code not in ERROR_CODES):
            raise WireProtocolError('INVALID_OUTPUT')
        return error_response(response.error_code)
    texts = _validate_pages(response.pages, limits)
    chunks = [RESPONSE_MAGIC, bytes((KIND_READY,)), struct.pack('>H', len(texts))]
    for index, text in enumerate(texts, 1):
        chunks.extend((struct.pack('>HI', index, len(text)), text))
    return b''.join(chunks)

def read_response(source: BinaryIO, limits: tuple[int, ...]) -> WireResponse:
    validate_limits(limits)
    prefix = _read_exact(source, 9, 'INVALID_OUTPUT')
    if prefix[:8] != RESPONSE_MAGIC:
        raise WireProtocolError('INVALID_OUTPUT')
    count = struct.unpack('>H', _read_exact(source, 2, 'INVALID_OUTPUT'))[0]
    if prefix[8] == KIND_ERROR:
        if not 1 <= count <= MAX_ERROR_BYTES:
            raise WireProtocolError('INVALID_OUTPUT')
        try:
            code = _read_exact(source, count, 'INVALID_OUTPUT').decode('ascii')
        except UnicodeError:
            raise WireProtocolError('INVALID_OUTPUT') from None
        if code not in ERROR_CODES:
            raise WireProtocolError('INVALID_OUTPUT')
        _eof(source, 'INVALID_OUTPUT')
        return WireResponse(error_code=code)
    if prefix[8] != KIND_READY or not 1 <= count <= limits[1]:
        raise WireProtocolError('INVALID_OUTPUT')
    pages, used = [], 0
    for expected in range(1, count+1):
        index, length = struct.unpack('>HI', _read_exact(source, 6, 'INVALID_OUTPUT'))
        if index != expected or length > limits[4]-used or length > 4*limits[2]:
            raise WireProtocolError('INVALID_OUTPUT')
        try:
            text = _read_exact(source, length, 'INVALID_OUTPUT').decode('utf-8', errors='strict')
        except UnicodeError:
            raise WireProtocolError('INVALID_OUTPUT') from None
        pages.append(WirePage(index, text)); used += length
    _eof(source, 'INVALID_OUTPUT')
    response = WireResponse(tuple(pages))
    _validate_pages(response.pages, limits)
    return response

def write_all(sink: BinaryIO, data: bytes) -> None:
    if type(data) is not bytes or len(data) > max(69+LIMIT_CAPS[0], response_transport_cap(LIMIT_CAPS)):
        raise WireProtocolError('INVALID_OUTPUT')
    view = memoryview(data)
    offset = 0
    while offset < len(view):
        chunk = view[offset:offset+65536]
        written = sink.write(chunk)
        if type(written) is not int or not 1 <= written <= len(chunk):
            raise WireProtocolError('INVALID_OUTPUT')
        offset += written
