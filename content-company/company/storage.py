"""ローカルファイルによる永続化層 (§26)。

初期は複雑な DB を作りすぎない方針 (§26)。実体は 2 種類だけ:

* **コレクション** — ``data/<name>/<id>.json``。1レコード1ファイル。
  products / articles / research / analytics / experiments / hypotheses /
  tasks / approvals などの「台帳」に使う。
* **ログ (append-only)** — ``data/<name>/log.jsonl``。時系列で積むだけの
  memory / decisions / metrics に使う。

必要になった段階で SQLite 等へ移行できるよう、上位コードはこの ``Storage``
API だけに依存し、ファイル形式を直接触らない。
"""

from __future__ import annotations

import json
import pathlib
import tempfile
from typing import Any, Iterable, Iterator


class Storage:
    def __init__(self, data_dir: pathlib.Path | str):
        self.data_dir = pathlib.Path(data_dir)
        self.data_dir.mkdir(parents=True, exist_ok=True)

    # ---- 内部ユーティリティ ----------------------------------------------

    def _dir(self, collection: str) -> pathlib.Path:
        d = self.data_dir / collection
        d.mkdir(parents=True, exist_ok=True)
        return d

    @staticmethod
    def _atomic_write(path: pathlib.Path, text: str) -> None:
        """書き込み途中でのファイル破損を避けるため一時ファイル経由で置換する。

        Company Memory / 実験データの喪失は事業の記憶喪失に等しい (付録A #6)。
        """
        path.parent.mkdir(parents=True, exist_ok=True)
        fd, tmp = tempfile.mkstemp(dir=str(path.parent), suffix=".tmp")
        try:
            with open(fd, "w", encoding="utf-8") as fh:
                fh.write(text)
            pathlib.Path(tmp).replace(path)
        except BaseException:
            pathlib.Path(tmp).unlink(missing_ok=True)
            raise

    # ---- コレクション (1レコード1ファイル) --------------------------------

    def put(self, collection: str, record: dict[str, Any]) -> dict[str, Any]:
        if "id" not in record:
            raise ValueError("record must have an 'id' field")
        path = self._dir(collection) / f"{record['id']}.json"
        self._atomic_write(path, json.dumps(record, ensure_ascii=False, indent=2))
        return record

    def get(self, collection: str, record_id: str) -> dict[str, Any] | None:
        path = self._dir(collection) / f"{record_id}.json"
        if not path.exists():
            return None
        return json.loads(path.read_text(encoding="utf-8"))

    def delete(self, collection: str, record_id: str) -> bool:
        path = self._dir(collection) / f"{record_id}.json"
        if path.exists():
            path.unlink()
            return True
        return False

    def all(self, collection: str) -> list[dict[str, Any]]:
        records = [
            json.loads(p.read_text(encoding="utf-8"))
            for p in sorted(self._dir(collection).glob("*.json"))
        ]
        return records

    def find(self, collection: str, **filters: Any) -> list[dict[str, Any]]:
        out = []
        for rec in self.all(collection):
            if all(rec.get(k) == v for k, v in filters.items()):
                out.append(rec)
        return out

    # ---- ログ (append-only JSONL) ----------------------------------------

    def append(self, log: str, record: dict[str, Any]) -> dict[str, Any]:
        path = self._dir(log) / "log.jsonl"
        line = json.dumps(record, ensure_ascii=False)
        with open(path, "a", encoding="utf-8") as fh:
            fh.write(line + "\n")
        return record

    def read_log(self, log: str) -> Iterator[dict[str, Any]]:
        path = self._dir(log) / "log.jsonl"
        if not path.exists():
            return iter(())

        def _gen() -> Iterator[dict[str, Any]]:
            with open(path, "r", encoding="utf-8") as fh:
                for line in fh:
                    line = line.strip()
                    if line:
                        yield json.loads(line)

        return _gen()

    # ---- バックアップ (付録A #6) -----------------------------------------

    def snapshot(self, dest: pathlib.Path | str) -> pathlib.Path:
        """data ディレクトリ全体を zip でバックアップする。"""
        import shutil

        dest = pathlib.Path(dest)
        dest.parent.mkdir(parents=True, exist_ok=True)
        base = dest.with_suffix("")  # make_archive appends .zip
        archive = shutil.make_archive(str(base), "zip", root_dir=str(self.data_dir))
        return pathlib.Path(archive)


def iter_ids(records: Iterable[dict[str, Any]]) -> list[str]:
    return [r["id"] for r in records if "id" in r]
