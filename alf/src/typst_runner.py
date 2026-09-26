"""Run Typst with per-process Landlock filesystem and network restrictions."""

import ctypes
import os
import platform
import resource
import secrets
import shutil
import stat
import subprocess
import tempfile
from pathlib import Path


MAX_OUTPUT_SIZE = 4_000_000
LANDLOCK_CREATE_RULESET_VERSION = 1
LANDLOCK_RULE_PATH_BENEATH = 1
PR_SET_NO_NEW_PRIVS = 38

FS_EXECUTE = 1 << 0
FS_WRITE_FILE = 1 << 1
FS_READ_FILE = 1 << 2
FS_READ_DIR = 1 << 3
FS_REMOVE_DIR = 1 << 4
FS_REMOVE_FILE = 1 << 5
FS_MAKE_DIR = 1 << 7
FS_MAKE_REG = 1 << 8
FS_REFER = 1 << 13
FS_TRUNCATE = 1 << 14
FS_IOCTL_DEV = 1 << 15
NET_BIND_TCP = 1 << 0
NET_CONNECT_TCP = 1 << 1


class TypstSandboxError(RuntimeError):
    pass


class _RulesetAttr(ctypes.Structure):
    _fields_ = [
        ("handled_access_fs", ctypes.c_uint64),
        ("handled_access_net", ctypes.c_uint64),
        ("scoped", ctypes.c_uint64),
    ]


class _PathBeneathAttr(ctypes.Structure):
    _fields_ = [("allowed_access", ctypes.c_uint64), ("parent_fd", ctypes.c_int32)]


def _landlock_syscalls() -> tuple[int, int, int]:
    machine = platform.machine().lower()
    if machine not in {"x86_64", "amd64", "aarch64", "arm64"}:
        raise TypstSandboxError(f"Landlock syscall numbers are unknown for {machine}")
    return 444, 445, 446


def _check_syscall(libc, result: int, operation: str) -> int:
    if result < 0:
        error = ctypes.get_errno()
        raise OSError(error, f"{operation}: {os.strerror(error)}")
    return result


def _landlock_abi(libc, create_nr: int) -> int:
    abi = _check_syscall(
        libc,
        libc.syscall(create_nr, ctypes.c_void_p(), 0, LANDLOCK_CREATE_RULESET_VERSION),
        "query Landlock ABI",
    )
    if abi < 2:
        raise TypstSandboxError("Landlock ABI 2 or newer is required")
    return abi


def _apply_landlock(sandbox: Path, font_path: Path, typst_bin: Path) -> None:
    create_nr, add_nr, restrict_nr = _landlock_syscalls()
    libc = ctypes.CDLL(None, use_errno=True)
    libc.syscall.restype = ctypes.c_long
    abi = _landlock_abi(libc, create_nr)

    handled_fs = (1 << 13) - 1
    if abi >= 2:
        handled_fs |= FS_REFER
    if abi >= 3:
        handled_fs |= FS_TRUNCATE
    if abi >= 5:
        handled_fs |= FS_IOCTL_DEV
    attr = _RulesetAttr(handled_fs, NET_BIND_TCP | NET_CONNECT_TCP, 0)
    attr_size = 24 if abi >= 6 else 16
    ruleset_fd = _check_syscall(
        libc,
        libc.syscall(create_nr, ctypes.byref(attr), attr_size, 0),
        "create Landlock ruleset",
    )

    read_only = FS_READ_FILE | FS_READ_DIR
    system_access = read_only | FS_EXECUTE
    project_access = (
        read_only | FS_WRITE_FILE | FS_REMOVE_DIR | FS_REMOVE_FILE |
        FS_MAKE_DIR | FS_MAKE_REG | FS_REFER | FS_TRUNCATE
    )
    allowed = {}
    allowed[Path(sandbox).resolve(strict=True)] = project_access
    allowed[Path(font_path).resolve(strict=True)] = read_only
    allowed[Path(typst_bin).resolve(strict=True)] = FS_READ_FILE | FS_EXECUTE
    for name in (
        "/bin", "/usr/bin", "/usr/local/bin", "/lib", "/lib64",
        "/usr/lib", "/usr/local/lib", "/usr/share/fonts",
        "/usr/local/share/fonts", "/etc/fonts", "/var/cache/fontconfig",
    ):
        path = Path(name)
        if path.exists():
            resolved = path.resolve(strict=True)
            allowed[resolved] = allowed.get(resolved, 0) | system_access
    loader_cache = Path("/etc/ld.so.cache")
    if loader_cache.is_file():
        allowed[loader_cache.resolve(strict=True)] = FS_READ_FILE

    try:
        for path, allowed_access in allowed.items():
            path_fd = os.open(path, os.O_PATH | os.O_CLOEXEC)
            try:
                rule = _PathBeneathAttr(allowed_access, path_fd)
                _check_syscall(
                    libc,
                    libc.syscall(add_nr, ruleset_fd, LANDLOCK_RULE_PATH_BENEATH, ctypes.byref(rule), 0),
                    f"allow {path}",
                )
            finally:
                os.close(path_fd)

        if libc.prctl(PR_SET_NO_NEW_PRIVS, 1, 0, 0, 0) != 0:
            error = ctypes.get_errno()
            raise OSError(error, f"set no_new_privs: {os.strerror(error)}")
        _check_syscall(libc, libc.syscall(restrict_nr, ruleset_fd, 0), "restrict Typst process")
    finally:
        os.close(ruleset_fd)


def _copy_tree(source: Path, destination: Path) -> None:
    source = Path(source)
    if source.is_symlink() or not source.is_dir():
        raise TypstSandboxError("sandbox input must be a regular directory")

    for root, dirnames, filenames in os.walk(source, followlinks=False):
        root_path = Path(root)
        target_root = destination / root_path.relative_to(source)
        target_root.mkdir(mode=0o700, parents=True, exist_ok=True)
        for dirname in list(dirnames):
            item = root_path / dirname
            if item.is_symlink() or not item.is_dir():
                raise TypstSandboxError("sandbox input contains a link or special directory")
            (target_root / dirname).mkdir(mode=0o700, exist_ok=True)
        for filename in filenames:
            item = root_path / filename
            if not stat.S_ISREG(item.lstat().st_mode):
                raise TypstSandboxError("sandbox input contains a link or special file")
            shutil.copyfile(item, target_root / filename, follow_symlinks=False)


def compile_typst(project_path: Path, typ_path: Path, pdf_path: Path, font_path: Path, timeout: int = 5):
    """Compile a private project copy with filesystem and TCP access restricted."""
    project_path = Path(project_path).resolve(strict=True)
    typ_path = Path(typ_path).resolve(strict=True)
    font_path = Path(font_path).resolve(strict=True)
    try:
        relative_typ = typ_path.relative_to(project_path)
    except ValueError as error:
        raise TypstSandboxError("Typst input is outside the project") from error
    if typ_path.is_symlink() or not typ_path.is_file():
        raise TypstSandboxError("Typst input must be a regular file")
    typst_bin = shutil.which("typst")
    if typst_bin is None:
        raise TypstSandboxError("Typst executable is unavailable")
    typst_bin = Path(typst_bin).resolve(strict=True)

    with tempfile.TemporaryDirectory(prefix="alf-typst-") as temporary:
        sandbox = Path(temporary)
        _copy_tree(project_path, sandbox / "project")
        _copy_tree(font_path, sandbox / "fonts")
        cache = sandbox / "cache"
        packages = sandbox / "packages"
        cache.mkdir(mode=0o700)
        packages.mkdir(mode=0o700)
        relative_input = Path("project") / relative_typ
        output = Path("project") / f".alf-output-{secrets.token_hex(12)}.pdf"
        env = {
            "HOME": str(sandbox),
            "TMPDIR": str(sandbox),
            "XDG_CACHE_HOME": str(cache),
            "TYPST_PACKAGE_PATH": str(packages),
            "PATH": os.path.dirname(typst_bin) + os.pathsep + os.defpath,
            "LANG": "C",
        }
        result = subprocess.run(
            [str(typst_bin), "compile", "--root", str(sandbox),
             "--font-path", str(sandbox / "fonts"), str(relative_input), str(output)],
            cwd=sandbox,
            env=env,
            stdin=subprocess.DEVNULL,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            timeout=timeout,
            preexec_fn=lambda: _apply_landlock(sandbox, sandbox / "fonts", typst_bin),
            close_fds=True,
        )
        sandbox_output = sandbox / output
        if result.returncode == 0:
            if sandbox_output.is_symlink() or not sandbox_output.is_file():
                raise TypstSandboxError("Typst did not produce a regular PDF")
            shutil.copyfile(sandbox_output, pdf_path)
        return result
