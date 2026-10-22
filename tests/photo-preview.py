"""Read-only photo lightbox regressions for both photo lists, mobile and desktop."""
from pathlib import Path
import json, os, subprocess
from playwright.sync_api import sync_playwright

ROOT = Path(__file__).resolve().parents[1]
js = Path(os.environ['JSZIP_PATH']).read_bytes() if os.environ.get('JSZIP_PATH') else subprocess.check_output(['curl', '--fail', '--silent', '--show-error', 'https://cdn.jsdelivr.net/npm/jszip@3.10.1/dist/jszip.min.js'])
with sync_playwright() as pw:
    browser = pw.chromium.launch(executable_path='/usr/bin/chromium', args=['--no-sandbox'])
    for mobile in [False, True]:
        ctx = browser.new_context(viewport={'width': 390 if mobile else 1280, 'height': 844 if mobile else 900}, has_touch=mobile, is_mobile=mobile, service_workers='block')
        page = ctx.new_page()
        errors, dialogs = [], []
        page.on('pageerror', lambda error: errors.append(str(error)))
        def dismiss(dialog):
            dialogs.append(dialog.message)
            dialog.dismiss()
        page.on('dialog', dismiss)
        page.route('http://test.local/**', lambda r: r.fulfill(body=(ROOT / 'index.html').read_bytes()))
        page.route('https://cdn.jsdelivr.net/**', lambda r: r.fulfill(content_type='application/javascript', body=js))
        page.goto('http://test.local/')
        page.wait_for_function('!!db')
        data = page.evaluate('''async()=>{
          await put('jobs',{id:'preview-job',name:'拡大検証',locations:[{id:'loc',building:'A棟',floor:'2階'}],tasks:[...DEFAULT]});
          const images=[];
          for(let i=0;i<3;i++){
            const c=document.createElement('canvas');c.width=i===1?900:1600;c.height=i===1?1600:900;
            const g=c.getContext('2d');g.fillStyle=['red','green','blue'][i];g.fillRect(0,0,c.width,c.height);
            const data=c.toDataURL('image/png');images.push(data);
            await put('photos',{id:i+1,jobId:'preview-job',locationId:'loc',building:'A棟',floor:'2階',task:DEFAULT[0],phase:'施工前',time:100+i,ledgerOrder:(i+1)*1000,data,comment:'写真'+(i+1),boardFields:{job:false}});
          }
          await openJob('preview-job');selectLocation('loc');await selectTask(DEFAULT[0]);await renderLedgerOrder();
          return images;
        }''')
        original = page.evaluate("async()=>JSON.stringify([await all('jobs'),await all('photos')])")
        page.evaluate("()=>document.addEventListener('click',event=>{if(event.target.closest('.photoPreviewTrigger'))window.previewClickScroll=window.scrollY},true)")
        state = page.evaluate("JSON.stringify([job.id,loc.id,task,[...document.querySelectorAll('#photoOrderList .orderTitle')].map(e=>e.textContent)])")
        for list_id in ['pg', 'photoOrderList']:
            for photo_id in [1, 2, 3]:
                trigger = page.locator(f'#{list_id} .photoPreviewTrigger[data-photo-id="{photo_id}"]')
                trigger.scroll_into_view_if_needed()
                # Wait for previous smooth scrolls initiated by capture selection to finish.
                page.evaluate("window.scrollTo({top:window.scrollY,behavior:'instant'})")
                trigger.click()
                # Record at the click itself, after any browser auto-scroll to uncover the target.
                scroll = page.evaluate('window.previewClickScroll')
                page.wait_for_function('photoPreview.open && photoPreviewImage.complete && photoPreviewImage.naturalWidth > 0')
                assert page.locator('#photoPreviewImage').get_attribute('src') == data[photo_id - 1]
                assert page.locator('#photoPreviewImage').evaluate('(e)=>getComputedStyle(e).objectFit') == 'contain'
                assert page.locator('#photoPreview').evaluate('(e)=>e.matches(":modal")')
                assert page.locator('#photoPreviewClose').is_visible()
                assert page.locator('#photoPreviewZoom').inner_text() == '100%'
                # Actual button, wheel, mouse or touch actions exercise the displayed image.
                page.locator('#photoPreviewZoomIn').click()
                assert page.locator('#photoPreviewZoom').inner_text() == '150%'
                page.locator('#photoPreviewZoomOut').click()
                assert page.locator('#photoPreviewZoom').inner_text() == '100%'
                box = page.locator('#photoPreviewStage').bounding_box()
                x, y = box['x'] + box['width']/2, box['y'] + box['height']/2
                if mobile:
                    cdp = ctx.new_cdp_session(page)
                    def touch(kind, points):
                        cdp.send('Input.dispatchTouchEvent', {'type':kind, 'touchPoints':[{'x':px,'y':py,'id':i} for i,(px,py) in enumerate(points)]})
                    touch('touchStart', [(x-30,y), (x+30,y)])
                    touch('touchMove', [(x-80,y), (x+80,y)])
                    touch('touchEnd', [])
                    page.wait_for_function('previewScale > 2')
                    before = page.locator('#photoPreviewImage').evaluate('(e)=>e.style.transform')
                    touch('touchStart', [(x,y)])
                    touch('touchMove', [(x+40,y+40)])
                    touch('touchEnd', [])
                    cdp.detach()
                else:
                    page.mouse.move(x,y);page.mouse.wheel(0,-100)
                    page.wait_for_function('previewScale > 1')
                    page.locator('#photoPreviewZoomIn').click()
                    before = page.locator('#photoPreviewImage').evaluate('(e)=>e.style.transform')
                    page.mouse.move(x,y);page.mouse.down();page.mouse.move(x+70,y+70,steps=5);page.mouse.up()
                assert page.locator('#photoPreviewImage').evaluate('(e)=>e.style.transform') != before
                page.get_by_role('button', name='全体表示', exact=True).click()
                assert page.locator('#photoPreviewZoom').inner_text() == '100%'
                if photo_id == 2:
                    page.keyboard.press('Escape')
                else:
                    page.locator('#photoPreviewClose').click()
                page.wait_for_function('!photoPreview.open && !photoPreviewState')
                assert abs(page.evaluate('window.scrollY') - scroll) <= 1, (mobile,list_id,photo_id,scroll,page.evaluate('window.scrollY'))
                assert trigger.evaluate('(e)=>e===document.activeElement')
                assert page.locator('#photoPreviewImage').get_attribute('src') is None
                assert page.evaluate("JSON.stringify([job.id,loc.id,task,[...document.querySelectorAll('#photoOrderList .orderTitle')].map(e=>e.textContent)])") == state
                assert page.evaluate("async()=>JSON.stringify([await all('jobs'),await all('photos')])") == original
                assert not dialogs, dialogs
        # Keyboard activation, focus containment, and the independent delete control.
        trigger = page.locator('#pg .photoPreviewTrigger').first
        trigger.focus();page.keyboard.press('Enter')
        page.wait_for_function('photoPreview.open')
        page.keyboard.press('Tab')
        assert page.evaluate('photoPreview.contains(document.activeElement)')
        page.keyboard.press('Escape');page.wait_for_function('!photoPreviewState')
        with page.expect_event('dialog'):
            page.locator('#pg .photoDelete').first.click()
        assert len(dialogs) == 1 and '写真を削除' in dialogs[-1], dialogs
        assert not page.locator('#photoPreview').is_visible()
        assert page.evaluate("async()=>JSON.stringify([await all('jobs'),await all('photos')])") == original
        # Reordering and editing still invoke their own actions and no lightbox.
        page.locator('#photoOrderList .orderBtns').first.get_by_role('button',name='↓',exact=True).click()
        page.wait_for_function('!photoMoveBusy')
        assert page.locator('#photoOrderList .photoPreviewTrigger').first.get_attribute('data-photo-id') == '2'
        page.locator('#photoOrderList .photoPreviewTrigger').first.click()
        page.wait_for_function('photoPreview.open')
        assert page.locator('#photoPreviewImage').get_attribute('src') == data[1]
        page.keyboard.press('Escape');page.wait_for_function('!photoPreviewState')
        page.locator('#photoOrderList .orderBtns').first.get_by_role('button',name='編集',exact=True).click()
        page.locator('#photoEdit').wait_for(state='visible')
        assert page.locator('#editPhotoId').input_value() == '2'
        assert not page.locator('#photoPreview').is_visible()
        assert not errors, errors
        print(('MOBILE' if mobile else 'DESKTOP') + ' PASS: both lists, 3 distinct originals including portrait, zoom/pan, Esc/close, scroll/focus/state, unchanged data, independent delete/reorder/edit, no JS errors')
        ctx.close()
    browser.close()
manifest = json.loads((ROOT / 'manifest.json').read_text())
assert '3.10.11' in manifest['name'] and '411' in manifest['start_url']
assert "iwasaki-photo-dx-v411" in (ROOT / 'sw.js').read_text()
print('ALL PASS; V3.10.11 manifest and cache updated')
