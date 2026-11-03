"""Read bounded regular files under a pinned directory, without following links."""

import os
import stat
from pathlib import Path

MAX_FILE_BYTES = 2 * 1024 * 1024


class MaterialError(ValueError):
    """Safe-to-display material error; never includes file contents or absolute paths."""


def check_parts(parts: tuple[str, ...], *, allow_hidden: bool = False) -> None:
    if ".." in parts or (not allow_hidden and any(p.startswith(".") and p != "." for p in parts)):
        raise MaterialError("不允许父目录引用或隐藏路径。")
    if any(a == "benchmark" and b == "gold" for a, b in zip(parts, parts[1:], strict=False)):
        raise MaterialError("禁止读取 benchmark/gold 参考答案。")


def open_directory(path: Path) -> int:
    """Open every component separately, rejecting symlinks including in the root."""
    if os.name != "posix" or os.open not in os.supports_dir_fd:
        raise MaterialError("当前安全文件读取需要支持 dir_fd 的 POSIX 系统。")
    flags = os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW
    fd = os.open(path.anchor, flags)
    try:
        for part in path.parts[1:]:
            child = os.open(part, flags, dir_fd=fd)
            os.close(fd)
            fd = child
        return fd
    except BaseException:
        os.close(fd)
        raise


class AuthorizedRoot:
    """Context-managed root handle; tools never receive filesystem paths."""

    def __init__(self, root: Path, *, allow_hidden_root: bool = False):
        root = root.absolute()
        # Only packaged resources opt in: installed packages may live under .venv.
        check_parts(root.parts, allow_hidden=allow_hidden_root)
        # Refuse this source checkout and its ancestors, even when cwd is elsewhere.
        checkout = Path(__file__).resolve().parents[3]
        if (checkout / "DeepDebug_planning.md").is_file() and (
            root == checkout or root in checkout.parents
        ):
            raise MaterialError("请指定独立材料目录，不能授权整个项目或其上级目录。")
        if root == Path(root.anchor) or (root / ".git").exists():
            raise MaterialError("不能授权文件系统根目录或整个仓库。")
        try:
            self._fd = open_directory(root)
            self._root_parts = root.parts
            self.display_path = str(root)
        except OSError as exc:
            raise MaterialError("材料根目录不可读取，或包含符号链接。") from exc

    def __enter__(self) -> "AuthorizedRoot":
        return self

    def __exit__(self, *args: object) -> None:
        os.close(self._fd)
        self._fd = -1

    def read(self, relative: str) -> bytes:
        path = Path(relative)
        if path.is_absolute() or not path.parts or "\\" in relative:
            raise MaterialError("材料必须使用根目录内的相对路径。")
        check_parts(path.parts)
        check_parts((*self._root_parts, *path.parts), allow_hidden=True)
        fd = os.dup(self._fd)
        try:
            for part in path.parts[:-1]:
                child = os.open(part, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW, dir_fd=fd)
                os.close(fd)
                fd = child
            file_fd = os.open(path.name, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK, dir_fd=fd)
            with os.fdopen(file_fd, "rb") as stream:
                info = os.fstat(stream.fileno())
                if not stat.S_ISREG(info.st_mode) or info.st_nlink != 1:
                    raise MaterialError("材料必须是普通文件，且不能使用硬链接。")
                if info.st_size > MAX_FILE_BYTES:
                    raise MaterialError("单份材料超过 2 MiB。")
                data = stream.read(MAX_FILE_BYTES + 1)
                if len(data) > MAX_FILE_BYTES:
                    raise MaterialError("单份材料超过 2 MiB。")
                return data
        except OSError as exc:
            raise MaterialError("材料不存在、不可读取或包含符号链接。") from exc
        finally:
            os.close(fd)

    def inspect(self, relative: str) -> dict:
        """Inspect one explicit reference without reading contents or listing siblings."""
        path = Path(relative)
        if path.is_absolute() or not path.parts or "\\" in relative or "\x00" in relative:
            raise MaterialError("路径引用必须是授权根目录内的相对路径。")
        check_parts(path.parts)
        check_parts((*self._root_parts, *path.parts), allow_hidden=True)
        fd = os.dup(self._fd)
        try:
            for part in path.parts[:-1]:
                child = os.open(part, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW, dir_fd=fd)
                os.close(fd)
                fd = child
            info = os.stat(path.name, dir_fd=fd, follow_symlinks=False)
            if stat.S_ISLNK(info.st_mode):
                raise MaterialError("路径引用不能包含符号链接。")
            if stat.S_ISREG(info.st_mode) and info.st_nlink == 1:
                kind = "file"
            elif stat.S_ISDIR(info.st_mode):
                kind = "directory"
            else:
                raise MaterialError("路径引用只接受普通文件和目录，拒绝硬链接。")
            return {"exists": True, "type": kind}
        except FileNotFoundError:
            return {"exists": False, "type": None}
        except OSError as exc:
            raise MaterialError("路径引用不可检查，或包含链接/非目录中间节点。") from exc
        finally:
            os.close(fd)
