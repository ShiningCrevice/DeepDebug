"""Host-authorized path references; model-facing calls only accept opaque IDs."""

from deepdebug.security.paths import AuthorizedRoot, MaterialError


class PathReferences:
    def __init__(self, root: AuthorizedRoot):
        self.root = root
        self._references: dict[str, str] = {}

    def register(self, relative: str) -> str:
        if not relative or len(relative) > 4096 or len(self._references) >= 10:
            raise MaterialError("最多登记 10 个路径引用，每个引用为 1～4096 字符。")
        reference_id = f"P{len(self._references) + 1:03}"
        self._references[reference_id] = relative
        return reference_id

    def inspect(self, reference_id: str) -> dict:
        if reference_id not in self._references:
            raise MaterialError("路径引用 ID 未登记。")
        relative = self._references[reference_id]
        return dict(
            reference_id=reference_id,
            path=relative,
            base_directory=self.root.display_path,
            **self.root.inspect(relative),
        )
