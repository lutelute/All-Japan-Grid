"""pandapower のバージョン差を吸収する薄い互換層。

pandapower 3.5 でトップレベルの ``pp.drop_buses`` 再エクスポートが外れた
(実体は ``pandapower.toolbox.grid_modification.drop_buses`` に残っている)。
pyproject が ``pandapower>=3.4.0`` なので CI は最新を引き、手元の 3.4 系と
挙動が割れる。参照の解決順をここに一本化しておく。
"""

from __future__ import annotations

from typing import Any, Callable

_DROP_BUSES: Callable[..., Any] | None = None


def _resolve_drop_buses() -> Callable[..., Any]:
    """``drop_buses`` を新旧どちらの置き場所からでも引く。"""
    import pandapower as pp

    fn = getattr(pp, "drop_buses", None)          # <= 3.4
    if fn is None:
        try:
            from pandapower import toolbox        # 3.5 以降
            fn = getattr(toolbox, "drop_buses", None)
            if fn is None:
                from pandapower.toolbox import grid_modification
                fn = grid_modification.drop_buses
        except (ImportError, AttributeError) as exc:
            raise AttributeError(
                "drop_buses がこの pandapower から見つからない "
                f"(version={getattr(pp, '__version__', '?')})"
            ) from exc
    return fn


def drop_buses(net: Any, buses: Any, **kwargs: Any) -> Any:
    """``pandapower.drop_buses`` 相当。バージョン差は呼び出し側に出さない。"""
    global _DROP_BUSES
    if _DROP_BUSES is None:
        _DROP_BUSES = _resolve_drop_buses()
    return _DROP_BUSES(net, buses, **kwargs)
