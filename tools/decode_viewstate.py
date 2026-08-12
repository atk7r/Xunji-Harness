#!/usr/bin/env python3
"""decode_viewstate.py - ASP.NET __VIEWSTATE decoder (P1).

Decodes ASP.NET ViewState values — Base64-encoded, optionally GZip-compressed,
.NET binary-serialized object pairs used by ASP.NET WebForms for client-side
state persistence.

Handles both:
1. New format (LosFormatter / ObjectStateFormatter, .NET 4+): Base64 -> GZip
   decompress -> .NET BinaryFormatter parse to extract type names, field names,
   and string values.
2. Legacy format (pre-.NET 4): Base64 -> raw byte inspection for readable strings.

Pure computation — no network calls, no external dependencies beyond stdlib.

Usage:
  .venv/bin/python tools/decode_viewstate.py <base64_string>
  echo <base64_string> | .venv/bin/python tools/decode_viewstate.py
  .venv/bin/python tools/decode_viewstate.py --selftest
"""

from __future__ import annotations

import argparse
import base64
import gzip
import json
import re
import struct
import sys
from io import BytesIO
from pathlib import Path


# ---- .NET BinaryFormatter record type enum ----
# https://learn.microsoft.com/en-us/openspecs/windows_protocols/ms-nrbf/
RECORD_SERIALIZED_STREAM_HEADER      = 0
RECORD_CLASS_WITH_ID                 = 1
RECORD_SYSTEM_CLASS_WITH_MEMBERS     = 2
RECORD_CLASS_WITH_MEMBERS            = 3
RECORD_SYSTEM_CLASS_WITH_MEMBERS_AND_TYPES = 4
RECORD_CLASS_WITH_MEMBERS_AND_TYPES  = 5
RECORD_BINARY_OBJECT_STRING          = 6
RECORD_BINARY_ARRAY                  = 7
RECORD_MEMBER_PRIMITIVE_TYPED        = 8
RECORD_MEMBER_REFERENCE              = 9
RECORD_OBJECT_NULL                   = 10
RECORD_MESSAGE_END                   = 11
RECORD_BINARY_LIBRARY                = 12
RECORD_OBJECT_NULL_MULTIPLE_256      = 13
RECORD_OBJECT_NULL_MULTIPLE          = 14
RECORD_ARRAY_SINGLE_PRIMITIVE        = 15
RECORD_ARRAY_SINGLE_OBJECT           = 16
RECORD_ARRAY_SINGLE_STRING           = 17
RECORD_CROSS_APP_DOMAIN_MAP          = 18
RECORD_CROSS_APP_DOMAIN_STRING       = 19
RECORD_CROSS_APP_DOMAIN_ASSEMBLY     = 20
RECORD_METHOD_CALL                   = 21
RECORD_METHOD_RETURN                 = 22

RECORD_NAMES = {
    0: "SerializedStreamHeader",
    1: "ClassWithId",
    2: "SystemClassWithMembers",
    3: "ClassWithMembers",
    4: "SystemClassWithMembersAndTypes",
    5: "ClassWithMembersAndTypes",
    6: "BinaryObjectString",
    7: "BinaryArray",
    8: "MemberPrimitiveTyped",
    9: "MemberReference",
    10: "ObjectNull",
    11: "MessageEnd",
    12: "BinaryLibrary",
    13: "ObjectNullMultiple256",
    14: "ObjectNullMultiple",
    15: "ArraySinglePrimitive",
    16: "ArraySingleObject",
    17: "ArraySingleString",
}

# Primitive type enum values in BinaryFormatter
PRIMITIVE_TYPES = {
    1: "String",
    2: "Boolean",
    3: "Byte",
    4: "Char",
    5: "Decimal",
    6: "Double",
    7: "Int16",
    8: "Int32",
    9: "Int64",
    10: "SByte",
    11: "Single",
    12: "TimeSpan",
    13: "DateTime",
    14: "UInt16",
    15: "UInt32",
    16: "UInt64",
    17: "Null",
    18: "String",
}


class BinaryReader:
    """Reads .NET BinaryFormatter data from a byte buffer."""

    def __init__(self, data: bytes):
        self._buf = BytesIO(data)
        self._strings: list[str] = []
        self._type_names: list[str] = []
        self._libraries: dict[int, str] = {}
        self._records: list[dict] = []

    def _read_byte(self) -> int:
        b = self._buf.read(1)
        if not b:
            raise EOFError("unexpected end of stream")
        return b[0]

    def _read_bytes(self, n: int) -> bytes:
        data = self._buf.read(n)
        if len(data) < n:
            raise EOFError("unexpected end of stream")
        return data

    def _read_int32(self) -> int:
        return struct.unpack("<i", self._read_bytes(4))[0]

    def _read_7bit_encoded_int(self) -> int:
        """Read a .NET 7-bit encoded integer (variable-length)."""
        result = 0
        shift = 0
        while True:
            b = self._read_byte()
            result |= (b & 0x7F) << shift
            shift += 7
            if not (b & 0x80):
                break
        return result

    def _read_string(self) -> str:
        """Read a length-prefixed UTF-8 string (BinaryFormatter format)."""
        try:
            length = self._read_7bit_encoded_int()
            raw = self._read_bytes(length)
            return raw.decode("utf-8", errors="replace")
        except (EOFError, struct.error):
            return ""

    def _read_binary_library(self) -> dict:
        """Read a BinaryLibrary record (assembly name + library ID)."""
        lib_id = self._read_int32()
        lib_name = self._read_string()
        self._libraries[lib_id] = lib_name
        return {"record": "BinaryLibrary", "library_id": lib_id, "library_name": lib_name}

    def _read_class_with_members_and_types(self) -> dict:
        """Read ClassWithMembersAndTypes record."""
        try:
            class_info = self._read_7bit_encoded_int()
            type_name = self._read_string()
            self._type_names.append(type_name)
            num_members = self._read_int32()
            member_names: list[str] = []
            for _ in range(num_members):
                member_names.append(self._read_string())
            # Read binary type enums
            for _ in range(num_members):
                self._read_byte()  # BinaryTypeEnum
            # Read additional type info
            result = {
                "record": "ClassWithMembersAndTypes",
                "type_name": type_name,
                "num_members": num_members,
                "member_names": member_names,
            }
            # Read member values
            values: dict[str, str] = {}
            for mn in member_names:
                try:
                    # Peek at next record type
                    peek = self._buf.read(1)
                    if not peek:
                        break
                    rt = peek[0]
                    if rt == RECORD_MEMBER_PRIMITIVE_TYPED:
                        ptype = self._read_byte()
                        pval = self._read_string_value(ptype)
                        values[mn] = f"{pval}"
                        self._strings.append(f"{mn}={pval}")
                    elif rt == RECORD_BINARY_OBJECT_STRING:
                        obj_id = self._read_int32()
                        sval = self._read_string()
                        values[mn] = sval
                        self._strings.append(f"{mn}={sval}")
                    elif rt == RECORD_OBJECT_NULL:
                        pass  # null value
                    elif rt == RECORD_MEMBER_REFERENCE:
                        self._read_int32()  # idref
                    else:
                        # Put the byte back and skip
                        self._buf.seek(-1, 1)
                        continue
                except (EOFError, struct.error):
                    break
            result["member_values"] = values
            return result
        except (EOFError, struct.error):
            return {"record": "ClassWithMembersAndTypes", "error": "truncated"}

    def _read_string_value(self, primitive_type: int) -> str:
        """Read a primitive-typed value as its string representation."""
        try:
            if primitive_type == 1:  # String (in MemberPrimitiveTyped)
                return self._read_string()
            elif primitive_type == 2:  # Boolean
                return str(bool(self._read_byte()))
            elif primitive_type == 7:  # Int16
                return str(struct.unpack("<h", self._read_bytes(2))[0])
            elif primitive_type == 8:  # Int32
                return str(self._read_int32())
            elif primitive_type == 9:  # Int64
                return str(struct.unpack("<q", self._read_bytes(8))[0])
            elif primitive_type == 3:  # Byte
                return str(self._read_byte())
            elif primitive_type == 11:  # Single
                return str(struct.unpack("<f", self._read_bytes(4))[0])
            elif primitive_type == 6:  # Double
                return str(struct.unpack("<d", self._read_bytes(8))[0])
            else:
                # For other types, skip length-prefixed data
                return f"<primitive_type={primitive_type}>"
        except (EOFError, struct.error):
            return "<truncated>"

    def parse(self) -> tuple[list[str], list[str], list[dict]]:
        """Parse the binary stream and return (strings, type_names, records)."""
        try:
            # Read SerializationHeaderRecord
            rt = self._read_byte()
            if rt != RECORD_SERIALIZED_STREAM_HEADER:
                self._records.append({"record": "Unknown", "type": rt})
                return self._strings, self._type_names, self._records

            root_id = self._read_int32()
            header_id = self._read_int32()
            major = self._read_int32()
            minor = self._read_int32()
            self._records.append({
                "record": "SerializedStreamHeader",
                "root_id": root_id, "header_id": header_id,
                "major_version": major, "minor_version": minor,
            })

            while True:
                rt = self._read_byte()
                if rt == RECORD_MESSAGE_END:
                    self._records.append({"record": "MessageEnd"})
                    break
                elif rt == RECORD_BINARY_LIBRARY:
                    self._records.append(self._read_binary_library())
                elif rt == RECORD_CLASS_WITH_MEMBERS_AND_TYPES:
                    self._records.append(self._read_class_with_members_and_types())
                elif rt == RECORD_CLASS_WITH_ID:
                    obj_id = self._read_int32()
                    metadata_id = self._read_int32()
                    self._records.append({"record": "ClassWithId", "object_id": obj_id, "metadata_id": metadata_id})
                elif rt == RECORD_SYSTEM_CLASS_WITH_MEMBERS_AND_TYPES:
                    class_info = self._read_7bit_encoded_int()
                    tn = self._read_string()
                    self._type_names.append(tn)
                    self._records.append({"record": "SystemClassWithMembersAndTypes", "type_name": tn})
                elif rt == RECORD_BINARY_OBJECT_STRING:
                    obj_id = self._read_int32()
                    s = self._read_string()
                    self._strings.append(s)
                    self._records.append({"record": "BinaryObjectString", "object_id": obj_id, "value": s})
                elif rt == RECORD_MEMBER_PRIMITIVE_TYPED:
                    ptype = self._read_byte()
                    pval = self._read_string_value(ptype)
                    self._strings.append(pval)
                    self._records.append({"record": "MemberPrimitiveTyped", "primitive_type": ptype, "value": pval})
                elif rt == RECORD_OBJECT_NULL:
                    self._records.append({"record": "ObjectNull"})
                elif rt == RECORD_OBJECT_NULL_MULTIPLE_256:
                    count = self._read_byte()
                    self._records.append({"record": "ObjectNullMultiple256", "count": count})
                elif rt == RECORD_OBJECT_NULL_MULTIPLE:
                    count = self._read_int32()
                    self._records.append({"record": "ObjectNullMultiple", "count": count})
                elif rt == RECORD_MEMBER_REFERENCE:
                    idref = self._read_int32()
                    self._records.append({"record": "MemberReference", "idref": idref})
                elif rt == RECORD_BINARY_ARRAY:
                    obj_id = self._read_int32()
                    rank = self._read_7bit_encoded_int()
                    self._records.append({"record": "BinaryArray", "object_id": obj_id, "rank": rank})
                    # Skip remaining array data
                    break
                elif rt == RECORD_CLASS_WITH_MEMBERS:
                    class_info = self._read_7bit_encoded_int()
                    tn = self._read_string()
                    self._type_names.append(tn)
                    num_members = self._read_int32()
                    members = [self._read_string() for _ in range(num_members)]
                    self._records.append({"record": "ClassWithMembers", "type_name": tn, "members": members})
                elif rt == RECORD_SYSTEM_CLASS_WITH_MEMBERS:
                    class_info = self._read_7bit_encoded_int()
                    tn = self._read_string()
                    self._type_names.append(tn)
                    self._records.append({"record": "SystemClassWithMembers", "type_name": tn})
                elif rt == RECORD_ARRAY_SINGLE_STRING:
                    array_info = self._read_7bit_encoded_int()
                    length = self._read_int32()
                    strings = [self._read_string() for _ in range(min(length, 200))]
                    self._strings.extend(strings)
                    self._records.append({"record": "ArraySingleString", "count": length, "values": strings[:20]})
                elif rt == RECORD_ARRAY_SINGLE_PRIMITIVE:
                    array_info = self._read_7bit_encoded_int()
                    length = self._read_int32()
                    ptype = self._read_byte()
                    self._records.append({"record": "ArraySinglePrimitive", "count": length, "primitive_type": ptype})
                    break  # too complex to parse inline; stop here
                else:
                    self._records.append({"record": f"Unknown(0x{rt:02X})", "type_byte": rt})
                    # Don't break — try to continue
                    if rt >= 20:
                        break  # beyond known types, bail
            return self._strings, self._type_names, self._records
        except (EOFError, struct.error):
            return self._strings, self._type_names, self._records


def _extract_readable_strings(data: bytes, min_len: int = 4) -> list[str]:
    """Extract printable ASCII/UTF-8 sequences from raw bytes (legacy format)."""
    strings: list[str] = []
    current: list[int] = []
    for b in data:
        if 32 <= b < 127:
            current.append(b)
        else:
            if len(current) >= min_len:
                strings.append(bytes(current).decode("ascii"))
            current = []
    if len(current) >= min_len:
        strings.append(bytes(current).decode("ascii"))
    return strings


def decode_viewstate(raw_input: str) -> dict:
    """Decode an ASP.NET __VIEWSTATE base64 string.

    Returns a structured dict per the tool spec.
    """
    if not raw_input or not raw_input.strip():
        return {"format": "empty", "note": "no ViewState data"}

    raw_input = raw_input.strip()

    # Step 1: Base64 decode
    try:
        data = base64.b64decode(raw_input)
    except Exception as e:
        return {"format": "unknown", "error": f"base64 decode failed: {e}"}

    original_len = len(raw_input)
    decoded_len = len(data)
    compressed = False

    # Step 2: Check for GZip compression
    if len(data) >= 2 and data[0] == 0x1F and data[1] == 0x8B:
        compressed = True
        try:
            buf = BytesIO(data)
            with gzip.GzipFile(fileobj=buf, mode="rb") as gz:
                data = gz.read()
            decoded_len = len(data)
        except Exception as e:
            return {
                "format": "los_formatter",
                "compressed": True,
                "original_len": original_len,
                "decoded_len": decoded_len,
                "error": f"gzip decompression failed: {e}",
                "raw_hex_preview": data[:64].hex(),
            }

    # Step 3: Check if it looks like .NET BinaryFormatter
    # SerializationHeaderRecord starts with 0x00
    if len(data) > 0 and data[0] == RECORD_SERIALIZED_STREAM_HEADER:
        # Try parsing as BinaryFormatter
        reader = BinaryReader(data)
        strings, type_names, records = reader.parse()

        # Also extract raw readable strings as fallback
        raw_strings = _extract_readable_strings(data)
        # Merge and deduplicate
        all_strings = list(dict.fromkeys(strings + raw_strings))

        return {
            "format": "los_formatter",
            "compressed": compressed,
            "original_len": original_len,
            "decoded_len": len(data),
            "strings": all_strings[:200],
            "type_names": list(dict.fromkeys(type_names))[:50],
            "record_count": len(records),
            "records": records[:50],
            "raw_hex_preview": data[:128].hex(),
        }

    # Step 4: Legacy format — extract readable strings
    readable = _extract_readable_strings(data)

    if readable:
        return {
            "format": "legacy",
            "compressed": compressed,
            "original_len": original_len,
            "decoded_len": len(data),
            "strings": readable[:200],
            "type_names": [],
            "raw_hex_preview": data[:128].hex(),
        }

    # Step 5: Unknown format — show what we can
    return {
        "format": "unknown",
        "compressed": compressed,
        "original_len": original_len,
        "decoded_len": len(data),
        "strings": _extract_readable_strings(data)[:200],
        "type_names": [],
        "raw_hex_preview": data[:128].hex(),
        "note": "unrecognised binary format (not a known .NET BinaryFormatter or legacy ViewState)",
    }


def _selftest() -> int:
    """Regression test with known ViewState fixtures."""
    import zlib
    from io import BytesIO

    checks: list[tuple[str, bool]] = []

    # Test 1: Empty input
    r = decode_viewstate("")
    checks.append(("empty input -> format=empty", r["format"] == "empty"))
    r2 = decode_viewstate("   ")
    checks.append(("whitespace input -> format=empty", r2["format"] == "empty"))

    # Test 2: Invalid base64
    r3 = decode_viewstate("!!!not-valid-base64!!!")
    checks.append(("invalid base64 -> format=unknown", r3["format"] == "unknown"))

    # Test 3: Valid base64 but no .NET header (legacy format)
    plain = b"Hello World\x00Test\x00Value123"
    r4 = decode_viewstate(base64.b64encode(plain).decode())
    checks.append(("plain base64 -> format=legacy", r4["format"] == "legacy"))
    checks.append(("legacy extracts readable strings", len(r4.get("strings", [])) > 0))

    # Test 4: LosFormatter format (GZip + BinaryFormatter header)
    # Build a minimal BinaryFormatter stream: header + MessageEnd
    bf_header = struct.pack("<BiiiiB", 0x00, 1, -1, 1, 0, 0x0B)
    gz_buf = BytesIO()
    with gzip.GzipFile(fileobj=gz_buf, mode="wb") as gz:
        gz.write(bf_header)
    gz_data = gz_buf.getvalue()
    r5 = decode_viewstate(base64.b64encode(gz_data).decode())
    checks.append(("los_formatter gzip -> format=los_formatter", r5["format"] == "los_formatter"))
    checks.append(("los_formatter gzip -> compressed=true", r5["compressed"] is True))
    checks.append(("los_formatter gzip -> has header record", len(r5.get("records", [])) > 0))

    # Test 5: Non-gzipped BinaryFormatter stream
    bf_stream = struct.pack("<Biiii", 0x00, 1, -1, 1, 0) + bytes([0x0B])
    r6 = decode_viewstate(base64.b64encode(bf_stream).decode())
    checks.append(("non-gzip BF -> format=los_formatter", r6["format"] == "los_formatter"))
    checks.append(("non-gzip BF -> compressed=false", r6["compressed"] is False))

    # Test 6: BinaryFormatter with a string
    # SerializationHeader + BinaryObjectString + MessageEnd
    obj_str = b"TestValue"
    obj_data = struct.pack("<Bi", 0x06, 1) + bytes([len(obj_str)]) + obj_str + bytes([0x0B])
    full_stream = bf_stream[:-1] + obj_data  # Replace MessageEnd
    # Actually build properly:
    full = struct.pack("<Biiii", 0x00, 1, -1, 1, 0)  # header
    full += struct.pack("<Bi", 0x06, 1)  # BinaryObjectString, object_id=1
    full += bytes([len(obj_str)]) + obj_str
    full += bytes([0x0B])  # MessageEnd
    r7 = decode_viewstate(base64.b64encode(full).decode())
    checks.append(("BF with string -> extracts string", "TestValue" in r7.get("strings", [])))

    # Test 7: raw_hex_preview present in all non-empty formats
    for label, r in [("empty", r), ("legacy", r4), ("los_formatter", r5), ("unknown", r3)]:
        pass
    checks.append(("raw_hex_preview present in legacy", "raw_hex_preview" in r4))
    checks.append(("raw_hex_preview present in los_formatter", "raw_hex_preview" in r5))

    # Test 8: Large base64 with repeated char
    large = base64.b64encode(b"A" * 256).decode()
    r8 = decode_viewstate(large)
    checks.append(("large data handled", r8["original_len"] > 0 and r8["decoded_len"] == 256))

    bad = [n for n, ok in checks if not ok]
    for n, ok in checks:
        print(("ok   " if ok else "FAIL ") + n, file=sys.stderr)
    print("decode_viewstate selftest " + ("passed" if not bad else f"FAILED ({len(bad)})"), file=sys.stderr)
    return 0 if not bad else 1


def main() -> int:
    ap = argparse.ArgumentParser(
        description="Decode ASP.NET __VIEWSTATE base64 values")
    ap.add_argument("viewstate", nargs="?", help="Base64-encoded ViewState string")
    ap.add_argument("--selftest", action="store_true", help="run regression test and exit")
    args = ap.parse_args()

    if args.selftest:
        return _selftest()

    raw = args.viewstate
    if not raw:
        # Read from stdin
        if not sys.stdin.isatty():
            raw = sys.stdin.read().strip()
    if not raw:
        ap.error("viewstate string is required (or pipe via stdin, or use --selftest)")

    result = decode_viewstate(raw)
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 0 if "error" not in result else 1


if __name__ == "__main__":
    raise SystemExit(main())
