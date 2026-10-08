#!/usr/bin/env python3
"""Package the complete story/circuit review as an offline HTML report.

Reads the two PPTX files, rendered slides and the exact reviewed Git range.
No canonical network data is changed. The HTML template needs no CDN/server.
"""
from __future__ import annotations
import argparse
import hashlib
import json
import posixpath
import re
import subprocess
import zipfile
from pathlib import Path
import xml.etree.ElementTree as ET

ROOT = Path(__file__).resolve().parents[1]
BASE = '13b89c926f522fd623699c80a8f0b1bb85c3d4be'
HEAD = 'e0d8a2888153c07eff0b89d8662c52c5adb8f557'
BEFORE = ROOT/'docs/slides/ajg/AllJapanGrid_story.pptx'
AFTER = ROOT/'docs/slides/ajg/revised/output/AllJapanGrid_story_revised_2026-09-12_v4.pptx'
SOURCE_SHA = '1f31d77f6d2785ffd05943ba98666b7c0670d3e305ab6d75df264d06374bc96f'
AFTER_SHA = '760bed32bc12e906a93e2c49d09cb059ca04a39c4e5ccd0e67b6730162cc35ca'
NS = {'a':'http://schemas.openxmlformats.org/drawingml/2006/main',
      'p':'http://schemas.openxmlformats.org/presentationml/2006/main',
      'r':'http://schemas.openxmlformats.org/officeDocument/2006/relationships'}

# Editorial correspondence, not a claim that the old pages are identical.
MAPPING = [
 ([1,2], '再構成', '開発期間・コミット数の紹介から、地理・構内・計算をつなぐ研究の主題へ。'),
 ([3], '説明追加', '公開モデルの必要性を、再エネ・送電量・発電所停止という研究の問いへ置き換えた。'),
 ([4], '整理', '位置・属性・接続・計算条件を分け、観測だけでは決まらない情報を表にした。'),
 ([2,9], '版を整理', '全国のfeature数を投稿PDFの版にそろえ、現在のbuilt母線数と区別した。'),
 ([6,7,8], '統合', 'リリース履歴と組立GIFを、入力・出力・根拠を引き継ぐ5段階の説明へ。'),
 ([11,12], '説明追加', '個別バグの履歴から、二重登録・誤母線・孤立の隠蔽が計算を変える理由へ。'),
 ([16], '説明追加', '母線、ベイ・端子、変圧器の役割を、構内図と対応させて説明した。'),
 ([16,17], '再構成', '構内幾何と単線結線図を左右に並べ、位置と接続の対応を読める構成にした。'),
 ([14,16], '説明追加', '頂点共有・敷地内包・近傍引込を区別し、電圧・端子の照合が残ることを明記。'),
 ([4,16,40], '表現を訂正', '観測・推定・未確認を分離。「根拠へ戻れる」を実系統との一致と同一視しない。'),
 ([16,40], '数値を補足', '母線way被覆14.2%と流向棄権39.4%を、各母数・原稿評価版とともに示した。'),
 ([13], '焦点を整理', '二重登録の訂正で損失が増えた例に絞り、原因と結果を追いやすくした。'),
 ([12,36,38], '統合', '収束・給電対象・電気的妥当性を別々に検証する説明へ統合。'),
 ([10], '整理', '標準形式の出力→独立実装で読込→比較という検証の流れへ。現場照合とは区別。'),
 ([8,9,29], '数値の版を訂正', '原版757機と混ぜず、投稿PDF Table 6の783機・24時間を採用。目的関数が違う費用を改善率にしない。'),
 ([18], '説明追加', 'UCの出力が潮流・動揺の入力になる関係を表にし、蓄電池なども条件付きで扱う。'),
 ([32,33,34], '統合', '西日本の診断経緯を、発散の場所を観察する1つの例へ集約。過去断面と明記。'),
 ([35], '解説追加', '収束後の低電圧・slack・給電対象の確認点を図の横に明記。'),
 ([23], '条件を固定', '東N-3・10,618 MWの同一条件を採用。集約遮断量と消灯地点の表示用配置を区別。'),
 ([26], 'GIFを追加', '同じ保存時系列で急低下と15分回復を解説。最低48.49 Hz、終端49.84 Hz、完全復帰は未確認。'),
 ([2,13], '監査を追加', '履歴上の数値とは別に、入力SHAを固定して現在の断片525成分・313変電所座標を集計。'),
 ([], '新規', '秩父の12ノード断片を実データの地図・GIFで示し、近接を接続確定と扱わない。'),
 ([], '新規', '電圧不明の始点から異電圧wayを通過できたコード不具合と、修正の意味を説明。'),
 ([14], '監査を追加', '本四の端点定義を一次資料と比較。表示・連結性・PFの利用経路を区別。'),
 ([14,38], '再構成', '設備の同定、複製モデルでの試行、同じ運転条件での比較を一続きにした。'),
 ([40,41], '結論を整理', '成果、未確認点、次の改善を、線の根拠を計算まで追うという結論へ。'),
 ([8,9,29], '補足', 'feature・サイト・機数の版を一覧化。783／646／757を混ぜないための補足。'),
 ([5,11,36], '補足', '過去の相関・電圧照合・標準形式の結果を、それぞれの検証範囲とともに整理。'),
 ([4,16], '補足', '座標上の1点と電圧別母線を分ける概念図を追加。実設備の構成を示す図ではない。'),
 ([37,41], '補足', '原稿、接続監査、説明ノート、実行コマンドへ戻れる参照ページにした。'),
]
OMITTED = {
 15:'実況・日次更新の説明は本編から省略。接続モデルの理解を先に扱う構成にした。',
 **{n:'異なる事故・制御条件の実験は本編から省略。改善版19–20では東N-3の同一条件を追う。' for n in [19,20,21,22,24,25,27,28]},
 30:'線路負荷率の独立した図は本編から省略。改善版13・16で潮流の条件と検証を説明。',
 31:'短絡容量の独立した図は本編から省略。今回の物語は接続・潮流・周波数に絞った。',
 39:'総集編GIFは本編から省略。原版のGIFとしてこのHTML内で再生できる。',
}


def git(*args):
    return subprocess.check_output(['git', '-C', str(ROOT), *args])


def digest(data):
    return hashlib.sha256(data).hexdigest()


def main():
    ap=argparse.ArgumentParser(description=__doc__)
    ap.add_argument('--before-render',type=Path,default=Path('/tmp/ajg_html_review/before'))
    ap.add_argument('--after-render',type=Path,default=Path('/tmp/ajg_story_review/final_v4_render'))
    ap.add_argument('--out',type=Path,default=ROOT/'docs/reports/codex_before_after_2026-09-12')
    args=ap.parse_args();out=args.out;out.mkdir(parents=True,exist_ok=True)
    assert digest(BEFORE.read_bytes())==SOURCE_SHA,'Original deck changed; rerender and explicitly update the comparison snapshot.'
    assert digest(AFTER.read_bytes())==AFTER_SHA,'Revised deck changed; update the comparison snapshot.'
    assets={}
    def asset(data,suffix):
        sha=digest(data);rel=f'assets/{sha[:20]}{suffix}'
        target=out/rel;target.parent.mkdir(exist_ok=True)
        if not target.exists():target.write_bytes(data)
        assets[rel]={'sha256':sha,'bytes':len(data)}
        return rel
    def deck(p,render,label):
        result=[]
        with zipfile.ZipFile(p) as z:
            names=sorted((n for n in z.namelist() if re.fullmatch(r'ppt/slides/slide\d+\.xml',n)),key=lambda s:int(re.search(r'slide(\d+)',s)[1]))
            for i,n in enumerate(names,1):
                root=ET.fromstring(z.read(n));shapes=[]
                for s in root.findall('.//p:sp',NS):
                    t=[''.join(t.itertext()) for t in s.findall('.//a:t',NS)]
                    if t: shapes.append(''.join(t))
                texts=[e.text for e in root.findall('.//a:t',NS) if e.text]
                title=shapes[1] if label=='after' else next((s for s in shapes if len(s)>=5
                    and not s.startswith(('出典','ALL-JAPAN','All-Japan-Grid'))
                    and not re.match(r'^(第\d+幕|終幕)',s)),'総集編GIF')
                rels=ET.fromstring(z.read(f'ppt/slides/_rels/slide{i}.xml.rels'))
                media=[];notes=''
                for rel in rels:
                    target=posixpath.normpath(posixpath.join('ppt/slides',rel.attrib.get('Target',''))).lstrip('/')
                    if target.endswith('.gif'):
                        src=asset(z.read(target),'.gif')
                        if src not in media:media.append(src)
                    if '/notesSlides/' in target and target.endswith('.xml'):
                        nt=ET.fromstring(z.read(target))
                        paras=[''.join(e.itertext()) for e in nt.findall('.//a:p',NS)]
                        notes='\n'.join(t for t in paras if t.strip() and not t.strip().isdigit())
                result.append(dict(n=i,title=title,text='\n'.join(texts),notes=notes,
                    image=asset((render/f'slide-{i}.png').read_bytes(),'.png'),gifs=media))
        return result
    before=deck(BEFORE,args.before_render,'before');after=deck(AFTER,args.after_render,'after')
    assert len(before)==41 and len(after)==30
    methods=json.loads((ROOT/'scripts/templates/before_after_methods.json').read_text())
    assert len(methods['slide_guides'])==len(after)
    for slide,guide in zip(after,methods.pop('slide_guides')):
        slide['guide']=dict(zip(['question','how','why'],guide))
    evidence={}
    for case in methods['cases']:
        for source in case['sources']:
            if 'path' not in source:continue
            path=source['path']
            if path not in evidence:
                content=git('show',f'{HEAD}:{path}')
                evidence[path]=dict(text=content.decode(),sha256=digest(content),commit=HEAD)
    methods['evidence']=evidence
    methods['replay']=json.loads((out/'methods_replay.json').read_text())
    mapped=set()
    for new,old in zip(after,MAPPING):
        new.update(before=old[0],change=old[1],reason=old[2]);mapped.update(old[0])
    assert mapped|set(OMITTED)==set(range(1,42))
    for old in before:
        old['after']=[s['n'] for s in after if old['n'] in s['before']]
        old['disposition']=OMITTED.get(old['n'],'改善版の対応ページへ統合・再構成。内容の対応であり、同じページの複製ではない。')
    files=[]
    paths=git('diff','--name-only',BASE,HEAD).decode().splitlines()
    for p in paths:
        b=git('show',f'{HEAD}:{p}');suffix=Path(p).suffix
        old_exists=subprocess.run(['git','-C',str(ROOT),'cat-file','-e',f'{BASE}:{p}'],capture_output=True).returncode==0
        a=git('show',f'{BASE}:{p}') if old_exists else None
        binary=suffix in ('.png','.gif','.pptx')
        category=('図・PowerPoint' if binary or suffix=='.svg' else
                  '監査JSON' if suffix in ('.json','.geojson') else
                  '説明・設定' if suffix=='.md' or Path(p).name.startswith('.') else 'コード')
        files.append(dict(path=p,category=category,status='変更' if old_exists else '新規',bytes=len(b),
            sha256=digest(b),before=a.decode() if a is not None and not binary else None,
            after=b.decode() if not binary else None,
            diff=git('diff','--no-ext-diff','--unified=4',BASE,HEAD,'--',p).decode() if not binary else '',
            image=asset(b,suffix) if suffix in ('.png','.gif','.svg') else None,
            url=f'https://github.com/lutelute/All-Japan-Grid/blob/{HEAD}/{p}',
            raw=f'https://raw.githubusercontent.com/lutelute/All-Japan-Grid/{HEAD}/{p}'))
    assert len(files)==43
    def committed_json(p):return json.loads(git('show',f'{HEAD}:{p}'))
    circuit=committed_json('docs/reports/codex_model_quality_2026-09-12/model_quality.json')
    connections=committed_json('docs/reports/codex_connection_audit_2026-09-12/connections.json')
    structures=committed_json('docs/reports/codex_model_quality_2026-09-12/structure_findings.json')
    recovery=committed_json('docs/reports/codex_connection_audit_2026-09-12/recovered_voltage_evidence.json')
    records={}
    def add(key,title,description,rows):records[key]=dict(title=title,description=description,rows=rows)
    for key,title,desc in [
        ('line_voltage_mismatches','線路両端の電圧不整合','通電中lineの両端バスが異電圧。457本とも記録線路電圧は0。修正は未適用。'),
        ('transformers_without_site_witness','変電所ノード証拠のない生成変圧器','計算モデルの確認候補。元データの変電所欠測もあり得るため、実在しない設備とは断定しない。'),
        ('unknown_line_components','不明電圧線路の連結部分','単一の観測階級は伝播候補。端点同定が正しいと確認する前に電圧を確定しない。')]:
        add(key,title,desc,[dict(island=isl,**r) for isl,v in circuit['islands'].items() for r in v[key]])
    for key,title in [('terminal_voltage_conflicts','構造DBの端子電圧衝突'),('bay_voltage_conflicts','構造DBのベイ・母線電圧衝突')]:
        add(key,title,'地域レコード単位。元wayの複数電圧タグを全クラス照合した結果。実設備の確定誤り件数ではない。',
            [dict(site=x['site'],**r) for x in structures['findings'] for r in x[key]])
    add('union_false_main','所属島をまたぐmain誤伝播','本番と同じstitch/tie規則で比較した3ノード。保存main差194ノードとは区別する。',circuit['membership']['union_false_main'])
    add('recovery','回収枝と異電圧wayの幾何共有','併架・重複wayも含み得る24候補。過去に選んだway列の完全復元ではない。',recovery['candidates'])
    for key,title,desc in [
        ('near_candidates','300 m以内の近接ペア','各断片端点の上位3点まで。132件の接続漏れを意味しない。'),
        ('geometry_gaps','接続点とpath端の500 m超の差','変電所代表点への接続も含む。256件の断線という意味ではない。'),
        ('main_disagreements','保存mainとの差','座標グラフの再集計。定義・鮮度差も含み、全件が誤伝播バグではない。'),
        ('disjoint_island_edges','端点の所属島が重ならない枝','HVDC/FC・地域帰属を分類する。34件のAC誤接続ではない。'),
        ('ambiguous_island_edges','端点の所属島が曖昧な枝','同じ座標にある別電圧・別島ノードを同一視しない。'),
        ('cross_island_coordinate_groups','複数島に属する座標','地域境界・変換設備・重複同定を確認する。'),
        ('self_loops','座標自己ループ','2,181件中2,172件は構内stubと明記。全件削除は不適切。'),
        ('missing_endpoints','端点ノードの欠落','今回の座標監査では0件。電圧・母線の正しさを保証する値ではない。')]:
        add(key,title,desc,connections[key])
    figures={Path(f['path']).name:f['image'] for f in files if f['image']}
    report=dict(before=before,after=after,files=files,records=records,figures=figures,methods=methods,
        circuit_summary={k:dict(counts=v['counts'],sensitivity=v['topology_sensitivity']) for k,v in circuit['islands'].items()},
        counts=connections['counts'],structure_counts=circuit['structure_counts'],
        meta=dict(base=BASE,head=HEAD,before_sha256=SOURCE_SHA,after_sha256=AFTER_SHA,
            built_sha256=circuit['source_sha256'],lines_sha256=connections['lines_sha256'],
            assembly_manifest=circuit['assembly_manifest'],scope=circuit['scope']))
    data=json.dumps(report,ensure_ascii=False,separators=(',',':')).replace('<','\\u003c').replace('\u2028','\\u2028').replace('\u2029','\\u2029')
    template=(ROOT/'scripts/templates/before_after_review.html').read_text()
    (out/'index.html').write_text(template.replace('/*__REVIEW_DATA__*/',data))
    manifest=dict(before_pages=41,after_pages=30,changed_files=43,records={k:len(v['rows']) for k,v in records.items()},
        assets=assets,source_sha256=SOURCE_SHA,after_sha256=AFTER_SHA,base=BASE,head=HEAD,
        method_cases=len(methods['cases']),slide_guides=len(after),explanation_updated=methods['updated'],
        replay_sha256=digest((out/'methods_replay.json').read_bytes()))
    (out/'manifest.json').write_text(json.dumps(manifest,ensure_ascii=False,indent=2)+'\n')
    (out/'README.md').write_text('# Before / After HTML\n\n`index.html` をブラウザで開く。サーバー・CDNは不要。`assets/` と一緒に保持する。\n\n原版41枚・改善版30枚、PPTX内のGIF、説明ノート、内容対応、全43変更ファイル、監査候補全件を収録。モデルの検出結果は、接続変更後の潮流結果ではない。\n\n2026-09-13追補：「発想・試行錯誤」に8事例。問い、発想、却下案・失敗・対照実験、成否の仕組み、残る仮説と原記録を収録。全30枚に説明の組立てを追加。既存の全国AC実験記録と今回の小入力再現を区別。PPTX v4自体は比較スナップショットとして固定し、今回の解説はHTML上の追補。\n\n比較元とSHAはmanifest.jsonおよび画面内「入力・検証」に記録。再生成: `python3 scripts/replay_review_experiments.py` → `python3 scripts/build_before_after_review.py`。先に固定版PPTXの全ページを指定ディレクトリへレンダリングする。小入力再現は正典を変更せず、Gitで固定した旧版・修正版を使う。全国ACは再実行していない。\n')
    print(json.dumps({k:v for k,v in manifest.items() if k!='assets'},ensure_ascii=False,indent=2))
    print(out/'index.html')


if __name__=='__main__':main()
