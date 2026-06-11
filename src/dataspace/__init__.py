"""データスペース — 外部データ源の疎結合連携層（docs/DATA_SPACE.md）。

原則: データは源泉に留め（zero-copy）、UCが必要とする集約断面のみを
契約（config/dataspace.yaml）に基づいて取得する。全取得はキャッシュされ、
provenance.jsonl に出所が機械記録される。
"""

from src.dataspace.registry import DataContract, DataSpace

__all__ = ["DataContract", "DataSpace"]
