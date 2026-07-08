#!/usr/bin/env python3
"""All-Japan-Grid — MATPOWER 配布ケースで潮流計算 (Python / pandapower 版).

配布物 ``dist/matpower_national/<island>.mat`` を読み込み、pandapower で
AC 潮流 (Newton-Raphson) を解きます。収束しない場合は DC 潮流に自動で
フォールバックします。**MATLAB は不要**です。

対象は非同期 4 島 (北海道 50Hz / 東日本 50Hz / 西日本 60Hz / 沖縄 60Hz)。
各島は独立した .mat で、これらは ``runpf`` 用 (発電コスト gencost を含まない
= 最適潮流 OPF ではなく通常潮流)。

使い方::

    python solve_pf.py                 # okinawa (最小・数秒)
    python solve_pf.py hokkaido
    python solve_pf.py east --dc       # DC 潮流を直接
    python solve_pf.py west --csv out  # 結果バス表を out/ に CSV 出力

依存: pandapower (>=2.11), scipy, numpy
  pip install pandapower scipy numpy
"""
from __future__ import annotations

import argparse
import sys
import warnings
from pathlib import Path

warnings.filterwarnings("ignore")

ISLANDS = ("okinawa", "hokkaido", "east", "west")


def _find_mat(island: str, mat_dir: Path | None) -> Path:
    """配布ケース .mat の場所を解決する。

    既定はリポジトリ (または配布バンドル) ルート直下の
    ``dist/matpower_national/``。``--mat-dir`` で上書き可能。
    """
    if mat_dir is not None:
        cand = mat_dir / f"{island}.mat"
    else:
        # dataset/01_matpower_powerflow/solve_pf.py -> ルートは 2 つ上
        root = Path(__file__).resolve().parents[2]
        cand = root / "dist" / "matpower_national" / f"{island}.mat"
    if not cand.exists():
        sys.exit(
            f"[ERROR] ケースが見つかりません: {cand}\n"
            f"        --mat-dir で dist/matpower_national の場所を指定してください。"
        )
    return cand


def solve(island: str, force_dc: bool, csv_dir: str | None, mat_dir: Path | None) -> int:
    import pandapower as pp
    from pandapower.converter.matpower import from_mpc

    mat = _find_mat(island, mat_dir)
    print(f"=== {island} ===")
    print(f"case: {mat}")

    net = from_mpc(str(mat))
    n_bus = len(net.bus)
    n_branch = len(net.line) + len(net.trafo)
    n_gen = len(net.gen) + len(net.ext_grid)
    print(f"loaded: {n_bus} bus, {n_branch} branch, {n_gen} gen "
          f"(slack bus(es): {list(net.ext_grid.bus.values)})")

    mode = "DC"
    if not force_dc:
        try:
            pp.runpp(net, max_iteration=100)
            mode = "AC"
        except Exception as exc:  # noqa: BLE001 — NR 非収束は DC へ退避
            print(f"AC (Newton-Raphson) failed -> DC fallback ({type(exc).__name__})")
            pp.rundcpp(net)
    else:
        pp.rundcpp(net)

    if not net.converged:
        print("RESULT: NOT CONVERGED")
        return 1

    total_gen = float(net.res_gen.p_mw.sum() + net.res_ext_grid.p_mw.sum())
    total_load = float(net.res_load.p_mw.sum()) if len(net.load) else 0.0
    print(f"RESULT: {mode} CONVERGED")
    print(f"  total generation: {total_gen:>10.0f} MW")
    print(f"  total load:       {total_load:>10.0f} MW")
    if mode == "AC":
        loss = total_gen - total_load
        vm = net.res_bus.vm_pu
        print(f"  transmission loss:{loss:>10.0f} MW  ({loss / max(total_load, 1) * 100:.2f} % of load)")
        print(f"  voltage Vm:        {vm.min():.3f} - {vm.max():.3f} pu")
        # --- 健全性チェック (pandapower の from_mpc 変換の制約) ------------------
        # 多成分の島 (例: hokkaido は 9 成分・各成分 1 slack) では、pandapower の
        # from_mpc が複数 slack を正しく扱えず、損失が負になる等の需給不整合が
        # 出ます。配布 .mat 自体は健全で、MATLAB 版 (solve_pf.m, MATPOWER runpf)
        # では同じケースを正しく解けます (実機確認: hokkaido AC 収束・損失 +3.5%)。
        # 単一成分の okinawa は Python でも綺麗に閉じます。
        loss_frac = loss / max(total_load, 1)
        if loss_frac < 0 or loss_frac > 0.20:
            n_slack = len(net.ext_grid)
            print(
                "  ⚠ pandapower 変換で需給内訳が不整合です (損失が負 or 過大)。原因は\n"
                f"    from_mpc が多成分島の複数 slack ({n_slack} 個) を正しく扱えないためで、\n"
                "    配布 .mat 自体は健全です。MATLAB 版 (solve_pf.m, MATPOWER runpf) なら\n"
                "    同じケースを正しく解けます (例: hokkaido は損失 +3.5%)。Python で\n"
                "    大規模島を解くなら UC→潮流 連成 (dataset/02_uc_from_excel) を使ってください。"
            )

    if csv_dir:
        out = Path(csv_dir)
        out.mkdir(parents=True, exist_ok=True)
        bus_csv = out / f"{island}_res_bus.csv"
        net.res_bus.to_csv(bus_csv)
        print(f"  wrote {bus_csv}")
    return 0


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("island", nargs="?", default="okinawa", choices=ISLANDS,
                    help="対象の非同期島 (既定: okinawa)")
    ap.add_argument("--dc", action="store_true", help="DC 潮流を直接解く")
    ap.add_argument("--csv", metavar="DIR", default=None, help="結果バス表を CSV 出力するディレクトリ")
    ap.add_argument("--mat-dir", metavar="DIR", default=None,
                    help="dist/matpower_national の場所 (既定: 自動検出)")
    args = ap.parse_args()
    mat_dir = Path(args.mat_dir) if args.mat_dir else None
    return solve(args.island, args.dc, args.csv, mat_dir)


if __name__ == "__main__":
    raise SystemExit(main())
