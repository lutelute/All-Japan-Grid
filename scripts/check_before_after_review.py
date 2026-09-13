#!/usr/bin/env python3
"""Check the offline review UI with Playwright, including every slide and record.

Requires playwright and its Chromium browser. Writes QA results to /tmp by default.
"""
from pathlib import Path
import argparse
import json,hashlib
from playwright.sync_api import sync_playwright

ap=argparse.ArgumentParser(description=__doc__)
ap.add_argument('--report',type=Path,default=Path(__file__).resolve().parents[1]/'docs/reports/codex_before_after_2026-09-12')
ap.add_argument('--output',type=Path,default=Path('/tmp/ajg_html_review/qa'))
args=ap.parse_args();root=args.report.resolve();out=args.output
out.mkdir(parents=True,exist_ok=True)
manifest=json.loads((root/'manifest.json').read_text())
for rel,item in manifest['assets'].items():
    assert hashlib.sha256((root/rel).read_bytes()).hexdigest()==item['sha256'],rel
errors=[]
with sync_playwright() as p:
    browser=p.chromium.launch()
    page=browser.new_page(viewport={'width':1600,'height':1100},device_scale_factor=1)
    page.on('pageerror',lambda e:errors.append(str(e)))
    page.goto((root/'index.html').as_uri(),wait_until='load')
    assert page.locator('#view-methods').is_visible()
    assert page.locator('#method-index button').count()==8
    page.screenshot(path=str(out/'00-methods.png'))
    for i in range(8):
        page.locator('[data-method="'+str(i)+'"]').click()
        assert page.locator('#method-detail .trial-list li').count()>=2
        assert page.locator('#method-detail .mechanism p').text_content()
        for j in range(page.locator('#method-detail [data-method-source]').count()):
            page.locator('#method-detail [data-method-source]').nth(j).click()
            assert len(page.locator('#dialog-body pre').text_content())>100
            page.keyboard.press('Escape')
    page.locator('[data-method="2"]').click()
    page.locator('[data-replay]').click()
    assert 'mixed_voltage' in page.locator('#dialog-body').inner_text()
    page.keyboard.press('Escape')
    page.screenshot(path=str(out/'00-route-experiment.png'))
    page.locator('[data-view="slides"]').click()
    page.screenshot(path=str(out/'01-slides.png'))
    for n in range(1,31):
        page.select_option('#after-select',str(n))
        for k in ['question','how','why']:
            assert len(page.locator('#guide-'+k).text_content())>=8
    page.select_option('#after-select','1')
    assert page.locator('#after-select option').count()==30
    assert page.locator('#before-select option').count()==42
    assert page.locator('#gallery .thumb').count()==30
    page.select_option('#after-select','15')
    assert '783' in page.locator('#after-notes').text_content()
    page.screenshot(path=str(out/'02-uc-comparison.png'))
    page.select_option('#after-select','22')
    assert page.locator('#before-frame .slideempty').count()==1
    page.locator('#after-caption button').click()
    assert page.locator('dialog[open] img').count()==1
    page.keyboard.press('Escape')
    page.locator('[data-gallery="before"]').click()
    assert page.locator('#gallery .thumb').count()==41
    page.locator('[data-gallery="mapping"]').click()
    assert not page.locator('#gallery').is_visible()
    assert page.locator('#mapping tbody tr').count()==41
    page.locator('[data-view="model"]').click()
    page.screenshot(path=str(out/'03-model.png'))
    assert page.locator('#record-rows tr').count()==457
    for key,count in manifest['records'].items():
        page.select_option('#record-kind',key)
        assert page.locator('#record-rows [data-record]').count()==count,(key,count)
    page.select_option('#record-kind','terminal_voltage_conflicts')
    page.fill('#record-search','西札幌')
    assert page.locator('#record-rows [data-record]').count()==3
    page.locator('#record-rows [data-record]').first.click()
    assert '66' in page.locator('#dialog-body').inner_text()
    page.keyboard.press('Escape')
    page.locator('#demo-source').scroll_into_view_if_needed()
    assert page.locator('#demo-old').inner_text()=='充電として表示'
    assert page.locator('#demo-new').inner_text()=='電源へ到達できない'
    page.check('#demo-source')
    assert page.locator('#demo-new').inner_text()=='電源へ到達できる'
    page.uncheck('#demo-closed')
    assert page.locator('#demo-new').inner_text()=='電源へ到達できない'
    page.screenshot(path=str(out/'04-gui-concept.png'))
    page.locator('[data-view="files"]').click()
    assert page.locator('#file-list .filebtn').count()==43
    assert 'route_voltage_compatible' in page.locator('#file-content').inner_text()
    page.screenshot(path=str(out/'05-files.png'))
    for i in range(43):
        page.locator('[data-file-index="'+str(i)+'"]').click()
        assert page.locator('#file-title').inner_text()
        page.locator('[data-filemode="before"]').click()
        page.locator('[data-filemode="after"]').click()
        page.locator('[data-filemode="diff"]').click()
    page.locator('[data-view="provenance"]').click()
    assert manifest['source_sha256'] in page.locator('#before-sha').inner_text()
    # Every packaged image decodes, including lazy-loaded / hidden images.
    image_result=page.evaluate('''async (paths) => {let failed=[];for(const path of paths){const im=new Image();im.src=path;try{await im.decode();if(!im.naturalWidth)failed.push(path);}catch{failed.push(path);}}return failed;}''',list(manifest['assets']))
    assert not image_result,image_result
    for width in [390,768,1280]:
        page.set_viewport_size({'width':width,'height':1000})
        for view in ['methods','slides','model','files','provenance']:
            page.locator('[data-view="'+view+'"]').click()
            assert page.evaluate('document.documentElement.scrollWidth<=innerWidth+1'),(width,view)
        page.locator('[data-view="methods"]').click()
        page.locator('[data-method="0"]').click()
        page.screenshot(path=str(out/f'07-methods-{width}.png'))
        page.locator('[data-view="slides"]').click()
        page.screenshot(path=str(out/f'06-responsive-{width}.png'))
    browser.close()
assert not errors,errors
(out/'result.json').write_text(json.dumps({'assets':len(manifest['assets']),'before_pages':41,'after_pages':30,'files':43,'method_cases':8,'slide_guides':30,'record_counts':manifest['records'],'console_errors':errors,'responsive_widths':[390,768,1280]},indent=2)+'\n')
print('PASS: all slides, correspondence, GIF dialogs, 43 files, all record groups, concept controls, asset decoding and responsive widths.')
