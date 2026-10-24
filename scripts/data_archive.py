"""Keep data/ on GitHub as a compressed archive: packed when committed, unpacked on checkout and pull.

    python3 scripts/data_archive.py setup    # once per clone: turn the hooks on, unpack data/
    python3 scripts/data_archive.py pack     # data/ -> data-archive/  (the commit hook does this)
    python3 scripts/data_archive.py unpack   # data-archive/ -> data/  (checkout and pull hooks do this)
    python3 scripts/data_archive.py status   # is data/ in step with the archive?

data/ itself stays git-ignored. Git stores data-archive/ instead: data.tar.gz split into parts
under GitHub's 100 MB file limit, SHA256SUMS for the parts, and MANIFEST (size and path of every
file packed), which lets the hooks notice a change without re-reading every byte. Git will not
switch hooks on by itself after a clone, so `setup` is the one step each teammate runs.
"""

import gzip
import hashlib
import os
import subprocess
import sys
import tarfile
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
DATA = ROOT / "data"
ARCHIVE = ROOT / "data-archive"
PART_SIZE = 95 * 1024 * 1024
PART_PREFIX = "data.tar.gz.part-"
STAMP = DATA / ".unpacked-from"          # which archive data/ was last unpacked from
SKIP = {".DS_Store", STAMP.name}


def data_files() -> list[Path]:
    out = []
    for dirpath, dirnames, filenames in os.walk(DATA):
        dirnames.sort()
        for name in sorted(filenames):
            path = Path(dirpath) / name
            if name not in SKIP and path.is_file() and not path.is_symlink():
                out.append(path)
    return out


def manifest() -> str:
    """One line per file, `<size> <path>`: cheap to rebuild, and changes whenever data/ gains,
    loses or resizes a file. A same-size edit slips past it; `pack` after such an edit."""
    return "".join(f"{p.stat().st_size} {p.relative_to(ROOT).as_posix()}\n" for p in data_files())


def parts() -> list[Path]:
    return sorted(ARCHIVE.glob(PART_PREFIX + "*"))


def sha256(path: Path) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for block in iter(lambda: f.read(1 << 20), b""):
            h.update(block)
    return h.hexdigest()


def archive_id() -> str:
    sums = ARCHIVE / "SHA256SUMS"
    return hashlib.sha256(sums.read_bytes()).hexdigest()[:16] if sums.exists() else ""


class PartWriter:
    """A write-only stream that rolls over to a new part file every PART_SIZE bytes."""

    def __init__(self) -> None:
        self.file, self.left, self.count = None, 0, 0

    def write(self, data) -> int:
        view = memoryview(data)
        while view:
            if self.file is None or self.left == 0:
                self._next()
            n = min(self.left, len(view))
            self.file.write(view[:n])
            self.left -= n
            view = view[n:]
        return len(data)

    def flush(self) -> None:
        if self.file:
            self.file.flush()

    def _next(self) -> None:
        if self.file:
            self.file.close()
        self.file = open(ARCHIVE / f"{PART_PREFIX}{self.count:03d}", "wb")
        self.left, self.count = PART_SIZE, self.count + 1

    def close(self) -> None:
        if self.file:
            self.file.close()


class PartReader:
    """Reads the parts back as one stream."""

    def __init__(self, paths: list[Path]) -> None:
        self.paths, self.file = list(paths), None

    def read(self, n: int = -1) -> bytes:
        out = bytearray()
        while n < 0 or len(out) < n:
            if self.file is None:
                if not self.paths:
                    break
                self.file = open(self.paths.pop(0), "rb")
            chunk = self.file.read(-1 if n < 0 else n - len(out))
            if not chunk:
                self.file.close()
                self.file = None
                continue
            out += chunk
        return bytes(out)


def pack() -> None:
    if not DATA.is_dir():
        sys.exit("no data/ folder to pack")
    ARCHIVE.mkdir(exist_ok=True)
    for old in parts():
        old.unlink()
    files = data_files()
    writer = PartWriter()
    # gzip with mtime=0 so the same data/ packs to the same bytes on any machine.
    with gzip.GzipFile(fileobj=writer, mode="wb", compresslevel=6, mtime=0) as gz:
        with tarfile.open(fileobj=gz, mode="w|", format=tarfile.PAX_FORMAT) as tar:
            for path in files:
                info = tar.gettarinfo(str(path), arcname=path.relative_to(ROOT).as_posix())
                info.uid = info.gid = 0
                info.uname = info.gname = ""
                info.mtime = 0
                with open(path, "rb") as f:
                    tar.addfile(info, f)
    writer.close()
    (ARCHIVE / "SHA256SUMS").write_text("".join(f"{sha256(p)}  {p.name}\n" for p in parts()))
    (ARCHIVE / "MANIFEST").write_text(manifest())
    STAMP.write_text(archive_id() + "\n")
    size = sum(p.stat().st_size for p in parts())
    print(f"packed {len(files):,} files from data/ into {len(parts())} parts, {size / 1e6:,.1f} MB")


def verify() -> None:
    lines = (ARCHIVE / "SHA256SUMS").read_text().split("\n")
    for line in filter(None, lines):
        digest, name = line.split("  ", 1)
        if sha256(ARCHIVE / name) != digest:
            sys.exit(f"{name} is corrupt or incomplete; pull again")


def unpack(force: bool = False) -> None:
    if not parts():
        return
    if not force and STAMP.exists() and STAMP.read_text().strip() == archive_id():
        return
    verify()
    print(f"unpacking data-archive/ into data/ ({len(parts())} parts) ...", flush=True)
    with gzip.GzipFile(fileobj=PartReader(parts()), mode="rb") as gz:
        with tarfile.open(fileobj=gz, mode="r|") as tar:
            kwargs = {"filter": "data"} if hasattr(tarfile, "data_filter") else {}
            tar.extractall(ROOT, **kwargs)
    STAMP.write_text(archive_id() + "\n")
    print(f"unpacked {sum(1 for _ in data_files()):,} files into data/")


def in_step() -> bool:
    packed = ARCHIVE / "MANIFEST"
    return packed.exists() and DATA.is_dir() and packed.read_text() == manifest()


def git(*args: str) -> None:
    subprocess.run(["git", *args], cwd=ROOT, check=True)


def main() -> None:
    cmd = sys.argv[1] if len(sys.argv) > 1 else "status"
    if cmd == "setup":
        git("config", "core.hooksPath", ".githooks")
        print("hooks on: commits pack data/, checkouts and pulls unpack it")
        unpack()
    elif cmd == "pack":
        pack()
    elif cmd == "unpack":
        unpack(force="--force" in sys.argv)
    elif cmd == "status":
        print("data/ matches the archive" if in_step() else "data/ differs from the archive: run pack")
    elif cmd == "pre-commit":
        # data/ changed since the last pack: re-pack it and put the new archive in this commit.
        if DATA.is_dir() and ARCHIVE.is_dir() and not in_step():
            pack()
            git("add", "--all", "data-archive")
    elif cmd == "pre-push":
        if DATA.is_dir() and ARCHIVE.is_dir() and not in_step():
            sys.exit("data/ changed since it was packed; commit first (the commit hook packs it), then push")
    else:
        sys.exit(__doc__)


if __name__ == "__main__":
    main()
