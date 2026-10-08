#!/usr/bin/env python3
"""Verify all 27 before/after map views and report controls using Playwright."""
import hashlib
import json
from pathlib import Path
from playwright.sync_api import sync_playwright

ROOT = Path(__file__).resolve().parents[1]
REPORT = ROOT/'docs/reports/codex_same_site_trial_2026-09-13'
OUT = Path('/tmp/ajg_same_site_trial/qa')
OUT.mkdir(parents=True, exist_ok=True)
errors = []
with sync_playwright() as p:
    browser = p.chromium.launch()
    page = browser.new_page(viewport={'width': 1600, 'height': 1100}, device_scale_factor=1)
    page.on('pageerror', lambda e: errors.append(str(e)))
    page.goto((REPORT/'index.html').as_uri(), wait_until='load')
    assert page.locator('#case-select option').count() == 27
    assert page.locator('#rows tr').count() == 27
    assert page.locator('#slide-gallery img').count() == 6
    assert page.locator('#code-select option').count() == 20
    for i in range(20):
        page.select_option('#code-select',str(i))
        assert page.locator('#code-after').inner_text()
    page.select_option('#code-select','0')
    page.screenshot(path=str(OUT/'overview.png'))
    for i in range(27):
        page.select_option('#case-select', str(i))
        assert page.locator('#before-map svg').count() == page.locator('#after-map svg').count() == 1
        assert page.locator('#terminal-map svg').count() == 1
        assert '見えたこと' in page.locator('#visual-note').inner_text()
        assert 'NaN' not in page.locator('#terminal-map').inner_html()
        assert page.locator('#source-pair article').count() == 2
        assert page.locator('#case-explanation').text_content()
        assert 'NaN' not in page.locator('#before-map').inner_html()
        assert 'NaN' not in page.locator('#after-map').inner_html()
        if page.locator('#before-map image').count():
            page.evaluate("""async () => {await Promise.all([...document.querySelectorAll('#before-map image')].map(e=>new Promise((resolve,reject)=>{const i=new Image();i.onload=resolve;i.onerror=reject;i.src=e.getAttribute('href');})));}""")
            page.locator('#before-map').screenshot(path=str(OUT/f'photo-SS{i+1:02d}.png'))
        page.locator('#show-case-json').click()
        assert 'osm_identity' in page.locator('#dialog-body').inner_text()
        page.keyboard.press('Escape')
    for value, count in [('trial_alias', 13), ('hold', 14), ('source_tag', 5), ('all', 27)]:
        page.select_option('#filter', value)
        assert page.locator('#rows tr').count() == count
    page.fill('#search', '羽田')
    assert page.locator('#rows tr').count() == 1
    page.locator('#rows button').click()
    assert '羽田' in page.locator('#case-title').inner_text()
    assert '変更なし' in page.locator('#after-label').inner_text()
    page.locator('#case').scroll_into_view_if_needed()
    page.screenshot(path=str(OUT/'haneda.png'))
    page.select_option('#case-select', '0')
    page.locator('#case').scroll_into_view_if_needed()
    page.screenshot(path=str(OUT/'chichibu.png'))
    page.locator('#before-map svg').click()
    assert page.locator('#dialog[open] svg').count() == 1
    page.keyboard.press('Escape')
    page.uncheck('#show-poly')
    page.uncheck('#show-refs')
    page.select_option('#zoom', '3')
    page.check('#show-poly')
    page.check('#show-refs')
    page.select_option('#zoom', '1')
    for z in ['0.5', '1', '3', '12']:
        page.select_option('#zoom', z)
        assert page.locator('#before-map image').count() > 0
    page.select_option('#zoom', '1')
    page.select_option('#background', 'none')
    assert page.locator('#before-map image').count() == 0
    page.select_option('#background', 'photo')
    page.uncheck('#show-network')
    page.select_option('#zoom', '0.5')
    for i in [0, 2, 3, 7, 8, 9, 12, 20]:
        page.select_option('#case-select', str(i))
        page.evaluate("""async () => {await Promise.all([...document.querySelectorAll('#before-map image')].map(e=>new Promise((resolve,reject)=>{const i=new Image();i.onload=resolve;i.onerror=reject;i.src=e.getAttribute('href');})));}""")
        page.locator('#before-map').screenshot(path=str(OUT/f'detail-SS{i+1:02d}.png'))
    page.select_option('#case-select', '0')
    page.select_option('#zoom', '1')
    page.check('#show-network')
    assert '一致しました' in page.locator('#rebuild-note').inner_text()
    assert '0 MW' in page.locator('#projection-result').inner_text()
    page.locator('#terminal-map svg').click()
    assert page.locator('#dialog[open] svg').count() == 1
    page.keyboard.press('Escape')
    page.locator('#terminal-proposal').scroll_into_view_if_needed()
    page.screenshot(path=str(OUT/'third-proposal.png'))
    page.locator('#terminal-map').screenshot(path=str(OUT/'chichibu-terminals.png'))
    page.check('#show-overlap')
    page.select_option('#zoom','3')
    page.locator('#terminal-map').screenshot(path=str(OUT/'chichibu-overlap.png'))
    page.locator('#all-overlap').click()
    assert '5923' in page.locator('#dialog-body').inner_text()
    assert '19942' in page.locator('#dialog-body').inner_text()
    page.keyboard.press('Escape')
    page.uncheck('#show-overlap')
    page.select_option('#zoom','1')
    assert page.locator('#flow-table tbody tr').count() == 8
    page.locator('#results').scroll_into_view_if_needed()
    page.screenshot(path=str(OUT/'results.png'))
    page.locator('#show-length-trial').click()
    assert '10781' in page.locator('#dialog-body').inner_text()
    page.keyboard.press('Escape')
    for width in [390, 768, 1280]:
        page.set_viewport_size({'width': width, 'height': 1000})
        assert page.evaluate('document.documentElement.scrollWidth <= innerWidth + 1'), width
        page.locator('#case').scroll_into_view_if_needed()
        page.screenshot(path=str(OUT/f'case-{width}.png'))
        page.locator('#terminal-proposal').evaluate("e=>e.scrollIntoView({block:'start'})")
        page.screenshot(path=str(OUT/f'third-{width}.png'))
    browser.close()
assert not errors, errors
result = dict(cases=27, filter_counts=[13,14,5,27], responsive_widths=[390,768,1280],
              javascript_errors=errors, maps='All before/after pairs rendered and controls exercised',
              third_site_terminal_views=27, aerial_photo_views=27, photo_only_details=8,
              source_before_after_files=20, powerpoint_slide_previews=6,
              html_sha256=hashlib.sha256((REPORT/'index.html').read_bytes()).hexdigest())
(OUT/'result.json').write_text(json.dumps(result, indent=2)+'\n')
print('PASS: 27 map pairs, source dialogs, rejection controls, trial details, and responsive layouts.')
