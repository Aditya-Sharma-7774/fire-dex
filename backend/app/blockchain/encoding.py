"""Address encodings shared by the Bitcoin and Solana adapters.

Three encodings, each implemented from its specification rather than a
library, so that every rejection can be explained:

    base58         Solana public keys. No checksum.
    base58check    Legacy Bitcoin addresses: base58 plus a 4-byte checksum
                   from a double SHA-256, so a typo is detected.
    bech32 / m     SegWit (BIP-173) and Taproot (BIP-350) addresses, with a
                   BCH checksum that detects any error in up to four
                   characters.
"""

import hashlib

BASE58_ALPHABET = "123456789ABCDEFGHJKLMNPQRSTUVWXYZabcdefghijkmnopqrstuvwxyz"
_BASE58_INDEX = {char: index for index, char in enumerate(BASE58_ALPHABET)}

BECH32_CHARSET = "qpzry9x8gf2tvdw0s3jn54khce6mua7l"
BECH32_CONST = 1
BECH32M_CONST = 0x2BC830A3
_BECH32_GENERATOR = [0x3B6A57B2, 0x26508E6D, 0x1EA119FA, 0x3D4233DD, 0x2A1462B3]


# ---------------------------------------------------------------------
# base58 and base58check
# ---------------------------------------------------------------------


def b58decode(text: str) -> bytes:
    """Decode base58 as Bitcoin and Solana define it.

    Leading '1' characters encode leading zero bytes, which is why Solana's
    System Program address, 32 ones, decodes to 32 zero bytes.
    """
    number = 0
    for char in text:
        digit = _BASE58_INDEX.get(char)
        if digit is None:
            raise ValueError(f"'{char}' is not a base58 character")
        number = number * 58 + digit
    body = number.to_bytes((number.bit_length() + 7) // 8, "big") if number else b""
    leading_zeros = len(text) - len(text.lstrip("1"))
    return b"\x00" * leading_zeros + body


def b58check_decode(text: str) -> tuple[int, bytes]:
    """Return (version byte, payload), or raise ValueError.

    The last four bytes must equal the first four of SHA-256(SHA-256(rest)).
    """
    raw = b58decode(text)
    if len(raw) < 5:
        raise ValueError("too short to carry a checksum")
    body, checksum = raw[:-4], raw[-4:]
    if hashlib.sha256(hashlib.sha256(body).digest()).digest()[:4] != checksum:
        raise ValueError("checksum does not match, so a character is wrong")
    return body[0], body[1:]


# ---------------------------------------------------------------------
# bech32 and bech32m (BIP-173, BIP-350)
# ---------------------------------------------------------------------


def _polymod(values: list[int]) -> int:
    checksum = 1
    for value in values:
        top = checksum >> 25
        checksum = (checksum & 0x1FFFFFF) << 5 ^ value
        for index in range(5):
            if (top >> index) & 1:
                checksum ^= _BECH32_GENERATOR[index]
    return checksum


def _hrp_expand(hrp: str) -> list[int]:
    return [ord(char) >> 5 for char in hrp] + [0] + [ord(char) & 31 for char in hrp]


def bech32_decode(text: str) -> tuple[str, list[int], int]:
    """Return (human-readable part, data, checksum constant), or raise ValueError."""
    if any(ord(char) < 33 or ord(char) > 126 for char in text):
        raise ValueError("contains characters outside printable ASCII")
    if text.lower() != text and text.upper() != text:
        raise ValueError("mixes upper and lower case, which bech32 forbids")
    text = text.lower()
    separator = text.rfind("1")
    if separator < 1 or separator + 7 > len(text) or len(text) > 90:
        raise ValueError("not a well-formed bech32 string")
    if any(char not in BECH32_CHARSET for char in text[separator + 1 :]):
        raise ValueError("contains a character bech32 does not use")

    hrp = text[:separator]
    data = [BECH32_CHARSET.find(char) for char in text[separator + 1 :]]
    constant = _polymod(_hrp_expand(hrp) + data)
    if constant not in (BECH32_CONST, BECH32M_CONST):
        raise ValueError("checksum does not match, so a character is wrong")
    return hrp, data[:-6], constant


def _convert_bits(data: list[int], from_bits: int, to_bits: int) -> list[int] | None:
    """Regroup 5-bit words into bytes, rejecting non-zero padding."""
    accumulator, bits, out = 0, 0, []
    max_value = (1 << to_bits) - 1
    max_accumulator = (1 << (from_bits + to_bits - 1)) - 1
    for value in data:
        if value < 0 or value >> from_bits:
            return None
        accumulator = ((accumulator << from_bits) | value) & max_accumulator
        bits += from_bits
        while bits >= to_bits:
            bits -= to_bits
            out.append((accumulator >> bits) & max_value)
    if bits >= from_bits or (accumulator << (to_bits - bits)) & max_value:
        return None
    return out


def decode_segwit(text: str) -> tuple[str, int, bytes]:
    """Return (human-readable part, witness version, program), or raise ValueError.

    Version 0 must use bech32 and a 20- or 32-byte program. Version 1 and
    above -- Taproot is version 1 -- must use bech32m. Accepting the wrong
    checksum variant was the flaw BIP-350 was written to close.
    """
    hrp, data, constant = bech32_decode(text)
    if not data:
        raise ValueError("carries no witness program")
    version = data[0]
    program = _convert_bits(data[1:], 5, 8)
    if program is None or not 2 <= len(program) <= 40:
        raise ValueError("witness program has an invalid length")
    if version > 16:
        raise ValueError("witness version is out of range")
    if version == 0 and len(program) not in (20, 32):
        raise ValueError("a version 0 program must be 20 or 32 bytes")
    expected = BECH32_CONST if version == 0 else BECH32M_CONST
    if constant != expected:
        raise ValueError("uses the wrong checksum variant for its witness version")
    return hrp, version, bytes(program)
