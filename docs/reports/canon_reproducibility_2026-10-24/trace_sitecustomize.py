# 再生成の入力を洗い出すための記録(AGJ_TRACE_LOG があるときだけ)。開いたファイル・一覧を読んだフォルダ・DB を JSONL に書く
import os
import sys

_LOG = os.environ.get("AGJ_TRACE_LOG")
_HERE = os.path.dirname(os.path.abspath(__file__))
if _LOG:
    import json as _json
    _fh = open(_LOG, "a", buffering=1, encoding="utf-8")
    _seen = set()
    _SKIP_EXT = (".py", ".pyc", ".so", ".dylib", ".pyi", ".pth")
    _W = os.O_WRONLY | os.O_RDWR | os.O_CREAT | os.O_TRUNC | os.O_APPEND

    def _emit(kind, p, w=False):
        try:
            p = os.fsdecode(os.fspath(p))
        except TypeError:
            return
        if not p or p.endswith(_SKIP_EXT) or "/site-packages/" in p or "/lib/python3" in p:
            return
        key = (kind, p, w)
        if key in _seen:
            return
        _seen.add(key)
        script = sys.argv[0] if getattr(sys, "argv", None) else ""
        _fh.write(_json.dumps({"k": kind, "p": os.path.abspath(p), "w": w, "s": script,
                               "pid": os.getpid()}, ensure_ascii=False) + "\n")

    def _hook(ev, args):
        try:
            if ev == "open":
                path, mode, flags = args
                if isinstance(path, int) or path is None:
                    return
                w = any(c in mode for c in "wax+") if isinstance(mode, str) else bool((flags or 0) & _W)
                _emit("f", path, w)
            elif ev in ("os.listdir", "os.scandir"):
                if args and args[0] is not None and not isinstance(args[0], int):
                    _emit("d", args[0])
            elif ev == "glob.glob":
                _emit("g", args[0])
            elif ev == "sqlite3.connect":
                _emit("db", args[0])
            elif ev == "os.rename" or ev == "os.replace":
                _emit("f", args[1], True)
            elif ev == "shutil.copyfile":
                _emit("f", args[0]); _emit("f", args[1], True)
        except Exception:
            pass

    sys.addaudithook(_hook)

# 隠してしまう元の sitecustomize(Homebrew の)を呼ぶ
import importlib.util as _ilu
for _d in sys.path:
    _c = os.path.join(_d, "sitecustomize.py")
    if os.path.abspath(_d or ".") != _HERE and os.path.exists(_c):
        _spec = _ilu.spec_from_file_location("_orig_sitecustomize", _c)
        _m = _ilu.module_from_spec(_spec)
        _spec.loader.exec_module(_m)
        break
