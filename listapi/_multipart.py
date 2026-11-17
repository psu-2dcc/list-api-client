"""Streaming ``multipart/form-data`` bodies, so multi-GB files are never held in memory."""

from __future__ import annotations

import hashlib
import io
import os
import secrets
import tempfile
from dataclasses import dataclass
from pathlib import Path
from typing import BinaryIO, Callable

CHUNK = 1024 * 1024


@dataclass
class Source:
    """Where the bytes of one file come from: a path, in-memory bytes, or a seekable stream."""

    name: str
    path: Path | None = None
    data: bytes | None = None
    stream: BinaryIO | None = None
    _start: int = 0

    @classmethod
    def of(cls, name: str, content: str | Path | bytes | BinaryIO) -> "Source":
        if isinstance(content, (bytes, bytearray)):
            return cls(name, data=bytes(content))
        if isinstance(content, (str, Path)):
            return cls(name, path=Path(content))
        if hasattr(content, "read"):
            stream: BinaryIO = content  # type: ignore[assignment]
            if not _seekable(stream):
                # Retries and the pre-hash need to read it twice: spool it to disk.
                spool = tempfile.SpooledTemporaryFile(max_size=64 * CHUNK)
                while True:
                    block = stream.read(CHUNK)
                    if not block:
                        break
                    spool.write(block.encode("utf-8") if isinstance(block, str) else block)
                spool.seek(0)
                stream = spool  # type: ignore[assignment]
            src = cls(name, stream=stream)
            src._start = stream.tell()
            return src
        raise TypeError(f"Unsupported file content type: {type(content)!r}")

    def size(self) -> int:
        if self.data is not None:
            return len(self.data)
        if self.path is not None:
            return self.path.stat().st_size
        assert self.stream is not None
        here = self.stream.tell()
        end = self.stream.seek(0, os.SEEK_END)
        self.stream.seek(here)
        return end - self._start

    def open(self) -> BinaryIO:
        """A fresh reader positioned at the start of this file."""
        if self.data is not None:
            return io.BytesIO(self.data)
        if self.path is not None:
            return open(self.path, "rb")
        assert self.stream is not None
        self.stream.seek(self._start)
        return _Borrowed(self.stream, self.size())

    def sha256(self) -> str:
        """SHA-256 hex digest, computed in chunks (never the whole file in memory)."""
        digest = hashlib.sha256()
        with self.open() as fh:
            for block in iter(lambda: fh.read(CHUNK), b""):
                digest.update(block)
        return digest.hexdigest()


class _Borrowed(io.RawIOBase):
    """Reads at most ``limit`` bytes of a caller-owned stream and never closes it."""

    def __init__(self, stream: BinaryIO, limit: int) -> None:
        self._stream = stream
        self._left = limit

    def readable(self) -> bool:
        return True

    def readinto(self, buffer) -> int:  # type: ignore[no-untyped-def]
        want = min(len(buffer), self._left)
        if want <= 0:
            return 0
        block = self._stream.read(want)
        buffer[: len(block)] = block
        self._left -= len(block)
        return len(block)

    def close(self) -> None:  # leave the caller's stream open
        super().close()


def _seekable(stream: BinaryIO) -> bool:
    try:
        return bool(stream.seekable())
    except (AttributeError, ValueError):
        return False


def _quote(value: str) -> str:
    return value.replace("\\", "\\\\").replace('"', "%22").replace("\r", "").replace("\n", "")


class MultipartBody:
    """File-like, length-known multipart body. ``requests`` streams it block by block."""

    def __init__(self) -> None:
        self.boundary = "listapi-" + secrets.token_hex(16)
        # (kind, payload, length): kind "b" = bytes, "s" = Source
        self._segments: list[tuple[str, object, int]] = []
        self._finished = False
        self._seg = 0
        self._cur: BinaryIO | None = None
        self._cur_bytes = b""
        self._cur_pos = 0
        self._length = 0

    @property
    def content_type(self) -> str:
        return f"multipart/form-data; boundary={self.boundary}"

    def add_field(self, name: str, value: str, content_type: str | None = None) -> None:
        head = f'--{self.boundary}\r\nContent-Disposition: form-data; name="{_quote(name)}"\r\n'
        if content_type:
            head += f"Content-Type: {content_type}\r\n"
        raw = value.encode("utf-8")
        self._add_bytes(head.encode("utf-8") + b"\r\n" + raw + b"\r\n")

    def add_file(self, name: str, source: Source, content_type: str) -> None:
        head = (
            f'--{self.boundary}\r\nContent-Disposition: form-data; name="{_quote(name)}"; '
            f'filename="{_quote(source.name)}"\r\nContent-Type: {content_type}\r\n\r\n'
        )
        self._add_bytes(head.encode("utf-8"))
        size = source.size()
        self._segments.append(("s", source, size))
        self._length += size
        self._add_bytes(b"\r\n")

    def finish(self) -> "MultipartBody":
        if not self._finished:
            self._add_bytes(f"--{self.boundary}--\r\n".encode("ascii"))
            self._finished = True
        return self

    def _add_bytes(self, raw: bytes) -> None:
        self._segments.append(("b", raw, len(raw)))
        self._length += len(raw)

    # -- file-like interface used by requests / http.client ---------------------

    def __len__(self) -> int:
        return self._length

    def read(self, size: int = -1) -> bytes:
        if size is None or size < 0:
            size = self._length
        out: list[bytes] = []
        want = size
        while want > 0:
            if self._cur is None and not self._cur_bytes:
                if self._seg >= len(self._segments):
                    break
                kind, payload, _ = self._segments[self._seg]
                self._seg += 1
                if kind == "b":
                    self._cur_bytes = payload  # type: ignore[assignment]
                    self._cur_pos = 0
                else:
                    self._cur = payload.open()  # type: ignore[union-attr]
            if self._cur_bytes:
                chunk = self._cur_bytes[self._cur_pos : self._cur_pos + want]
                self._cur_pos += len(chunk)
                if self._cur_pos >= len(self._cur_bytes):
                    self._cur_bytes = b""
                out.append(chunk)
                want -= len(chunk)
            elif self._cur is not None:
                chunk = self._cur.read(min(want, CHUNK))
                if not chunk:
                    self._cur.close()
                    self._cur = None
                    continue
                out.append(chunk)
                want -= len(chunk)
        return b"".join(out)

    def close(self) -> None:
        if self._cur is not None:
            self._cur.close()
            self._cur = None


def build(
    metadata_json: str | None,
    files: list[tuple[Source, str]],
) -> Callable[[], MultipartBody]:
    """Return a factory that builds a fresh body (one per attempt; retries re-read from the start)."""

    def factory() -> MultipartBody:
        body = MultipartBody()
        if metadata_json is not None:
            body.add_field("metadata", metadata_json, "application/json")
        for source, mime in files:
            body.add_file("file", source, mime)
        return body.finish()

    return factory
