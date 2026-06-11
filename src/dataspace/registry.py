"""データスペースの契約カタログとプロバイダ解決。

config/dataspace.yaml を正本として、各プロバイダの契約（所在・ライセンス・
再配布可否）を型付きで提供し、コネクタを遅延ロードする。
取得は store 経由（キャッシュ+provenance記録）で行う。
"""

from __future__ import annotations

import os
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Dict, Optional

from src.dataspace.store import CacheStore
from src.utils.logging_config import get_logger

logger = get_logger(__name__)

_REPO_ROOT = Path(__file__).resolve().parents[2]
DEFAULT_CATALOG = _REPO_ROOT / "config" / "dataspace.yaml"
DEFAULT_CACHE_DIR = _REPO_ROOT / "data" / "cache" / "dataspace"

_REQUIRED_KEYS = (
    "title", "custodian", "location", "license",
    "redistribute_raw", "redistribute_derived", "connector",
)


@dataclass
class DataContract:
    """1プロバイダ分のデータ契約（カタログ1エントリの型付きビュー）。"""

    provider: str
    title: str
    custodian: str
    location: str
    license: str
    redistribute_raw: bool
    redistribute_derived: bool
    connector: Optional[str]
    granularity: str = ""
    notes: str = ""
    variables: list = field(default_factory=list)
    raw: dict = field(repr=False, default_factory=dict)

    def resolve_location(self) -> Optional[str]:
        """所在を解決する。``env:VAR`` 形式は環境変数を引く（未設定はNone）。

        暗黙のフォールバック先へ取りに行くことはしない — None の場合は
        呼び出し側（コネクタ）が設定方法を案内して失敗する。
        """
        if self.location.startswith("env:"):
            return os.environ.get(self.location[4:]) or None
        return self.location


class DataSpace:
    """カタログ解決+取得の窓口。

    Usage:
        ds = DataSpace()
        contract = ds.contract("msm")
        data = ds.fetch("occto_kohyo", {"kind": "area_demand", ...})
    """

    def __init__(
        self,
        catalog_path: str | Path = DEFAULT_CATALOG,
        cache_dir: str | Path = DEFAULT_CACHE_DIR,
    ) -> None:
        import yaml

        self.catalog_path = Path(catalog_path)
        with open(self.catalog_path) as f:
            raw = yaml.safe_load(f) or {}
        self._contracts: Dict[str, DataContract] = {}
        for name, spec in (raw.get("providers") or {}).items():
            missing = [k for k in _REQUIRED_KEYS if k not in spec]
            if missing:
                raise ValueError(
                    f"dataspace catalog '{name}': missing contract keys {missing}"
                )
            self._contracts[name] = DataContract(
                provider=name,
                title=spec["title"],
                custodian=spec["custodian"],
                location=str(spec["location"]),
                license=spec["license"],
                redistribute_raw=bool(spec["redistribute_raw"]),
                redistribute_derived=bool(spec["redistribute_derived"]),
                connector=spec["connector"],
                granularity=str(spec.get("granularity", "")),
                notes=str(spec.get("notes", "")),
                variables=list(spec.get("variables") or []),
                raw=dict(spec),
            )
        self.store = CacheStore(cache_dir)

    def providers(self) -> list[str]:
        return sorted(self._contracts)

    def contract(self, provider: str) -> DataContract:
        try:
            return self._contracts[provider]
        except KeyError:
            raise KeyError(
                f"unknown dataspace provider '{provider}' "
                f"(known: {self.providers()})"
            ) from None

    def _connector(self, contract: DataContract):
        if not contract.connector:
            raise ValueError(
                f"provider '{contract.provider}' has no connector — "
                f"access it via its documented pipeline instead "
                f"(notes: {contract.notes[:120]})"
            )
        if contract.connector == "occto":
            from src.dataspace.connectors.occto import OcctoConnector
            return OcctoConnector()
        if contract.connector == "msm":
            from src.dataspace.connectors.msm import MSMConnector
            return MSMConnector()
        raise ValueError(f"unknown connector '{contract.connector}'")

    def fetch(
        self,
        provider: str,
        query: Dict[str, Any],
        force: bool = False,
    ) -> Any:
        """契約に基づき集約データを取得する（キャッシュ+provenance記録）。"""
        contract = self.contract(provider)
        if not force:
            hit = self.store.get(provider, query)
            if hit is not None:
                logger.info("dataspace cache hit: %s %s", provider, query)
                return hit
        connector = self._connector(contract)
        data = connector.fetch(query, contract)
        self.store.put(provider, query, data, contract)
        return data
