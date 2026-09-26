"""Strict tar extraction for untrusted Typst projects."""

import os
import tarfile
from pathlib import Path, PurePosixPath


MAX_MEMBERS = 128
MAX_EXPANDED_SIZE = 4_000_000
COPY_CHUNK_SIZE = 64 * 1024


class UnsafeArchiveError(ValueError):
    pass


def _member_path(member: tarfile.TarInfo) -> PurePosixPath:
    name = member.name
    if member.isdir() and name in (".", "./"):
        return PurePosixPath(".")
    if not name or name.startswith("/") or "\\" in name or "\0" in name:
        raise UnsafeArchiveError("invalid archive path")
    if len(name.encode("utf-8")) > 1024:
        raise UnsafeArchiveError("archive path is too long")

    parts = name.split("/")
    while parts and parts[0] == ".":
        parts.pop(0)
    if member.isdir() and parts and parts[-1] == "":
        parts.pop()
    if not parts or any(part in ("", ".", "..") for part in parts):
        raise UnsafeArchiveError("invalid archive path")
    if len(parts) > 32 or any(len(part.encode("utf-8")) > 255 for part in parts):
        raise UnsafeArchiveError("archive path is too deep or has an oversized component")
    return PurePosixPath(*parts)


def extract_archive(fileobj, destination: Path) -> Path:
    """Extract only bounded regular files and directories into an empty tree."""
    destination = Path(destination)
    if destination.is_symlink() or any(destination.iterdir()):
        raise UnsafeArchiveError("destination must be an empty directory")

    with tarfile.open(fileobj=fileobj, mode="r:") as archive:
        members = []
        for member in archive:
            members.append(member)
            if len(members) > MAX_MEMBERS:
                raise UnsafeArchiveError("too many archive entries")
        planned = {}
        total_size = 0
        for member in members:
            path = _member_path(member)
            if path == PurePosixPath(".") and member.isdir():
                continue
            if path in planned:
                raise UnsafeArchiveError("duplicate archive path")
            if member.isdir():
                if member.size != 0:
                    raise UnsafeArchiveError("directory entry contains data")
                planned[path] = (member, True)
            elif member.isreg() and member.type in (tarfile.REGTYPE, tarfile.AREGTYPE):
                if getattr(member, "sparse", None):
                    raise UnsafeArchiveError("sparse files are not supported")
                if member.size < 0:
                    raise UnsafeArchiveError("invalid file size")
                total_size += member.size
                if total_size > MAX_EXPANDED_SIZE:
                    raise UnsafeArchiveError("expanded archive is too large")
                planned[path] = (member, False)
            else:
                raise UnsafeArchiveError("links and special files are not allowed")

        for path in planned:
            for parent in path.parents:
                if parent == PurePosixPath("."):
                    continue
                parent_entry = planned.get(parent)
                if parent_entry and not parent_entry[1]:
                    raise UnsafeArchiveError("file used as an archive directory")

        main_entry = planned.get(PurePosixPath("main.typ"))
        if main_entry is None or main_entry[1]:
            raise UnsafeArchiveError("archive must contain a regular main.typ")

        for path, (_, is_dir) in planned.items():
            if is_dir:
                (destination / Path(*path.parts)).mkdir(mode=0o700, parents=True, exist_ok=True)
        for path, (member, is_dir) in planned.items():
            if is_dir:
                continue
            output_path = destination.joinpath(*path.parts)
            output_path.parent.mkdir(mode=0o700, parents=True, exist_ok=True)
            source = archive.extractfile(member)
            if source is None:
                raise UnsafeArchiveError("missing archive file data")
            flags = os.O_WRONLY | os.O_CREAT | os.O_EXCL
            flags |= getattr(os, "O_NOFOLLOW", 0)
            fd = os.open(output_path, flags, 0o600)
            with os.fdopen(fd, "wb") as output, source:
                remaining = member.size
                while remaining:
                    chunk = source.read(min(COPY_CHUNK_SIZE, remaining))
                    if not chunk:
                        raise UnsafeArchiveError("truncated archive file")
                    output.write(chunk)
                    remaining -= len(chunk)

    return destination / "main.typ"
