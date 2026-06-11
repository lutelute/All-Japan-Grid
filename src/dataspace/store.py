"""データスペースのキャッシュ+出所記録（provenance）。

- キャッシュ: data/cache/dataspace/（gitignore）。キーは
  sha256(provider + 正規化クエリ)。消えても契約+クエリから再構築できる。
- provenance.jsonl: 何を・いつ・どこから・どのクエリで取得したかの追記ログ。
  「結果の再現は契約+クエリ+取得時刻で説明できる」を機械的に担保する。
"""

from __future__ import annotations

import hashlib
import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, Optional

from src.utils.logging_config import get_logger

logger = get_logger(__name__)


def _query_key(provider: str, query: Dict[str, Any]) -> str:
    blob = json.dumps({"provider": provider, "query": query},
                      sort_keys=True, ensure_ascii=False)
    return hashlib.sha256(blob.encode()).hexdigest()[:24]


class CacheStore:
    def __init__(self, cache_dir: str | Path) -> None:
        self.cache_dir = Path(cache_dir)
        self.cache_dir.mkdir(parents=True, exist_ok=True)
        self.provenance_path = self.cache_dir / "provenance.jsonl"

    def _path(self, provider: str, query: Dict[str, Any]) -> Path:
        return self.cache_dir / f"{provider}_{_query_key(provider, query)}.json"

    def get(self, provider: str, query: Dict[str, Any]) -> Optional[Any]:
        p = self._path(provider, query)
        if not p.exists():
            return None
        with open(p) as f:
            return json.load(f)["data"]

    def put(self, provider: str, query: Dict[str, Any], data: Any,
            contract) -> None:
        p = self._path(provider, query)
        payload = json.dumps({"data": data}, ensure_ascii=False)
        with open(p, "w") as f:
            f.write(payload)
        record = {
            "ts": datetime.now(timezone.utc).isoformat(),
            "provider": provider,
            "query": query,
            "sha256": hashlib.sha256(payload.encode()).hexdigest()[:16],
            "cache_file": p.name,
            "custodian": contract.custodian,
            "location": contract.location,
            "license": contract.license,
        }
        with open(self.provenance_path, "a") as f:
            f.write(json.dumps(record, ensure_ascii=False) + "\n")
        logger.info("dataspace cached %s (%s)", p.name, record["sha256"])
