"""Browser regressions for Issue #2; no production data or external server required."""
from pathlib import Path
from playwright.sync_api import sync_playwright
import os, subprocess, base64
ROOT = Path(__file__).resolve().parents[1]
js = Path(os.environ['JSZIP_PATH']).read_bytes() if os.environ.get('JSZIP_PATH') else subprocess.check_output(['curl', '--fail', '--silent', '--show-error', 'https://cdn.jsdelivr.net/npm/jszip@3.10.1/dist/jszip.min.js'])
with sync_playwright() as pw:
    browser = pw.chromium.launch(executable_path='/usr/bin/chromium', args=['--no-sandbox'])
    page = browser.new_page(viewport={'width': 390, 'height': 844}, service_workers='block')
    errors, dialogs, answers = [], [], []
    page.on('pageerror', lambda error: errors.append(str(error)))
    def dialog(d):
        dialogs.append(d.message)
        if d.type == 'confirm' and answers and not answers.pop(0):
            d.dismiss()
        else:
            d.accept()
    page.on('dialog', dialog)
    page.route('http://test.local/**', lambda r: r.fulfill(body=(ROOT / 'index.html').read_bytes()))
    page.route('https://cdn.jsdelivr.net/**', lambda r: r.fulfill(content_type='application/javascript', body=js))
    page.goto('http://test.local/')
    page.wait_for_function('!!db')
    page.evaluate('''async()=>{
      const locations=[
        {id:'a10',building:'A棟',floor:'10階',room:'共通',place:'盤前'},
        {id:'a2',building:'A棟',floor:'2階',room:'共通',place:'盤前'},
        {id:'b2',building:'B棟',floor:'2階',room:'共通',place:'盤前'},
        {id:'skip',building:'A棟',place:'壁'},
        {id:'solo',place:'単独'}, {id:'parent',building:'A棟'},
        {id:'only',building:'消える棟',floor:'1階'},
        {id:'quote',place:'<img src=x onerror=alert(1)>'},
        {id:'same-label',room:'単独'}
      ];
      await put('jobs',{id:'tree',name:'階層検証',locations,tasks:[...DEFAULT]});
      await put('jobs',{id:'other',name:'他現場',locations:[{id:'solo',place:'単独'}],tasks:[...DEFAULT]});
      await openJob('tree');
    }''')
    original = page.evaluate("async()=>JSON.stringify((await all('jobs')).find(j=>j.id==='tree').locations)")
    assert page.locator('#deleteSelectedLocationBtn').is_disabled()
    assert page.locator('#editSelectedLocationBtn').is_disabled()
    assert page.locator('#locations details').count() == 9
    assert page.locator('#locations > details').first.locator(':scope > summary').inner_text() == 'A棟'
    a = page.locator('#locations > details').first
    assert a.locator(':scope > .locationChildren > details > summary').all_text_contents() == ['2階', '10階']
    assert page.locator('[data-location-id="skip"]').inner_text() == '📍 壁'
    assert page.locator('[data-location-id="solo"]').count() == 1
    assert page.locator('[data-location-id="same-label"]').count() == 1
    assert page.locator('#locations img').count() == 0
    a.locator(':scope > summary').click()
    assert not a.evaluate('(e)=>e.open')
    a.locator(':scope > summary').click()
    page.locator('[data-location-id="a2"]').click()
    assert page.locator('#locations .active').get_attribute('data-location-id') == 'a2'
    assert page.locator('#locations .active').evaluate('(e)=>getComputedStyle(e).backgroundColor') == 'rgb(22, 121, 186)'
    assert page.locator('#editSelectedLocationBtn').is_enabled()
    page.locator('#editSelectedLocationBtn').click()
    assert page.locator('#leFloor').input_value() == '2階'
    page.evaluate('cancelLocationEdit()')
    assert page.evaluate("async()=>JSON.stringify((await all('jobs')).find(j=>j.id==='tree').locations)") == original
    print('PASS hierarchy, skipped levels, independent parent, same names, natural order, collapse, blue selection, edit, unchanged IDs')
    page.evaluate('''async()=>{
      let canvas=document.createElement('canvas');canvas.width=10;canvas.height=10;
      await put('photos',{id:1,jobId:'tree',locationId:'a2',data:canvas.toDataURL(),time:1,comment:'保持',boardFields:{job:false}});
      await put('photos',{id:2,jobId:'other',locationId:'solo',data:canvas.toDataURL(),time:2});
    }''')
    before = page.evaluate("async()=>JSON.stringify(await all('photos'))")
    page.evaluate('deleteSelectedLocation()')
    assert '1枚' in dialogs[-1] and '削除できません' in dialogs[-1]
    assert page.evaluate("async()=>JSON.stringify(await all('photos'))") == before
    assert page.locator('[data-location-id="a2"]').count() == 1
    page.locator('[data-location-id="only"]').click()
    answers[:] = [False]
    page.evaluate('deleteSelectedLocation()')
    assert page.locator('[data-location-id="only"]').count() == 1
    page.locator('#deleteSelectedLocationBtn').click()
    page.wait_for_function('!loc')
    assert '消える棟' not in page.locator('#locations').inner_text()
    assert page.locator('#deleteSelectedLocationBtn').is_disabled()
    assert page.locator('#editSelectedLocationBtn').is_disabled()
    assert not page.locator('#taskCard').is_visible()
    assert not page.locator('#capture').is_visible()
    assert page.locator('[data-location-id="parent"]').count() == 1
    # Identical location IDs in another job must not block deletion in this job.
    page.evaluate("selectLocation('solo')")
    page.evaluate('deleteSelectedLocation()')
    assert page.locator('[data-location-id="solo"]').count() == 0
    assert page.evaluate("async()=>JSON.stringify(await all('photos'))") == before
    print('PASS cancel, empty deletion, parent pruning, state reset, job-scoped exact photo IDs, immutable photos')
    # Queue a real write during confirmation, before the atomic deletion transaction starts.
    page.evaluate('''()=>{
      window.realConfirm=window.confirm;
      window.confirm=()=>{add('photos',{id:3,jobId:'tree',locationId:'skip',data:'race',time:3});return true};
      selectLocation('skip');
    }''')
    page.evaluate('deleteSelectedLocation()')
    assert '1枚' in dialogs[-1] and '削除しません' in dialogs[-1]
    assert page.locator('[data-location-id="skip"]').count() == 1
    page.evaluate('window.confirm=window.realConfirm')
    # Concurrent job updates must survive: deletion reads the current persisted record.
    page.evaluate('''async()=>{
      let j=(await all('jobs')).find(j=>j.id==='tree');j.name='他タブの更新';
      j.locations.push({id:'new',building:'新棟'});await put('jobs',j);
      selectLocation('quote');await deleteSelectedLocation();
    }''')
    assert page.evaluate("job.name==='他タブの更新' && job.locations.some(l=>l.id==='new')")
    page.reload();page.wait_for_function('!!db');page.evaluate("openJob('tree')")
    assert page.locator('[data-location-id="only"]').count() == 0
    assert page.locator('[data-location-id="skip"]').count() == 1
    assert page.evaluate("async()=> (await all('photos')).length") == 3
    assert page.evaluate('document.documentElement.scrollWidth <= window.innerWidth')
    # Capture must serialize with deletion in both orders, including another stale tab.
    assert page.evaluate("""async()=>{
      try{await addLocationPhoto({jobId:'tree',locationId:'only',data:'stale'});return false}
      catch(e){return e.message.includes('削除')}
    }""")
    assert page.evaluate("async()=> (await all('photos')).length") == 3
    page.evaluate("addLocationPhoto({id:4,jobId:'tree',locationId:'new',data:'capture'})")
    assert page.evaluate("removeEmptyLocation('tree','new')")['count'] == 1
    assert page.evaluate("async()=> (await all('photos')).length") == 4
    print('PASS capture/deletion serialization in both orders; stale capture cannot orphan photos')
    page.evaluate("async()=>{selectLocation('a2');await selectTask(DEFAULT[0])}")
    png=page.evaluate("()=>{let c=document.createElement('canvas');c.width=10;c.height=10;return c.toDataURL().split(',')[1]}")
    page.locator('#cam').set_input_files({'name':'capture.png','mimeType':'image/png','buffer':base64.b64decode(png)})
    page.wait_for_function("saved.textContent.startsWith('保存しました：')")
    assert page.evaluate("async()=> (await all('photos')).filter(p=>p.jobId==='tree'&&p.locationId==='a2').length") == 2
    page.locator('#editSelectedLocationBtn').click();page.locator('#lePlace').fill('更新後の盤前')
    page.evaluate('saveLocationEdit()')
    assert page.evaluate("async()=> (await all('photos')).filter(p=>p.jobId==='tree'&&p.locationId==='a2').every(p=>p.place==='更新後の盤前')")
    assert page.locator('#locations .active').get_attribute('data-location-id') == 'a2'
    print('PASS image file capture, persisted location link, shared location edit propagates to existing photos')

    # Reproduce the review finding with real file decoding paused before persistence.
    page.evaluate("""async()=>{
      job.locations.push({id:'pending',building:'保存中の棟'},{id:'external',building:'他タブ削除'});
      await put('jobs',job);selectLocation('pending');await selectTask(DEFAULT[0]);
      window.realOriginalQuality=originalQuality;
      originalQuality=async f=>{await new Promise(resolve=>window.finishImage=resolve);return realOriginalQuality(f)};
    }""")
    payload={'name':'delayed.png','mimeType':'image/png','buffer':base64.b64decode(png)}
    page.locator('#cam').set_input_files(payload)
    page.wait_for_function('photoSaveBusy && typeof finishImage === "function"')
    assert page.locator('#deleteSelectedLocationBtn').is_disabled()
    page.evaluate('deleteSelectedLocation()')
    assert '写真を保存中' in dialogs[-1]
    assert page.evaluate("async()=> (await all('jobs')).find(j=>j.id==='tree').locations.some(l=>l.id==='pending')")
    # A tree rerender must not re-enable deletion during capture.
    page.evaluate('renderLocations()')
    assert page.locator('#deleteSelectedLocationBtn').is_disabled()
    page.evaluate('finishImage()');page.wait_for_function('!photoSaveBusy')
    assert page.evaluate("async()=> (await all('photos')).filter(p=>p.jobId==='tree'&&p.locationId==='pending').length") == 1
    assert page.locator('#deleteSelectedLocationBtn').is_enabled()
    assert page.locator('#cam').is_enabled()
    print('PASS delete during real image decoding is blocked; photo saved with original location')
    # Navigation while decoding must not retarget the pending photo or reopen the old job.
    page.evaluate('finishImage=undefined')
    page.locator('#cam').set_input_files(payload)
    page.wait_for_function('photoSaveBusy && typeof finishImage === "function"')
    page.evaluate("openJob('other')")
    page.evaluate("selectLocation('solo')")
    assert page.locator('#deleteSelectedLocationBtn').is_disabled()
    page.evaluate('finishImage()');page.wait_for_function('!photoSaveBusy')
    assert page.evaluate("job.id==='other' && loc.id==='solo'")
    assert page.evaluate("async()=> (await all('photos')).filter(p=>p.jobId==='tree'&&p.locationId==='pending').length") == 2
    assert page.evaluate("async()=> (await all('photos')).filter(p=>p.jobId==='other').length") == 1
    print('PASS navigation during decoding keeps photo tied to original job/location')
    # Another tab can delete before a photo is committed: report it without JS errors or orphans.
    page.evaluate("async()=>{await openJob('tree');selectLocation('external');await selectTask(DEFAULT[0]);finishImage=undefined}")
    page.locator('#cam').set_input_files(payload)
    page.wait_for_function('photoSaveBusy && typeof finishImage === "function"')
    assert page.evaluate("removeEmptyLocation('tree','external')").get('job')
    page.evaluate('finishImage()');page.wait_for_function('!photoSaveBusy')
    assert '写真を保存できませんでした' in dialogs[-1] and '場所は削除' in dialogs[-1]
    assert page.evaluate("async()=> (await all('photos')).filter(p=>p.locationId==='external').length") == 0
    assert page.locator('#cam').evaluate('(e)=>e.files.length') == 1
    # Decoder failures must also release the lock, so the next capture/deletion can proceed.
    page.evaluate("async()=>{selectLocation('pending');await selectTask(DEFAULT[0]);originalQuality=async()=>{throw new Error('画像読込テスト')}}")
    page.locator('#cam').set_input_files(payload);page.wait_for_function('!photoSaveBusy')
    assert '画像読込テスト' in dialogs[-1]
    assert page.locator('#deleteSelectedLocationBtn').is_enabled()
    assert page.locator('#cam').is_enabled()
    page.evaluate('()=>{originalQuality=realOriginalQuality}')
    page.locator('#cam').set_input_files(payload);page.wait_for_function('!photoSaveBusy && cam.value === ""')
    assert page.evaluate("async()=> (await all('photos')).filter(p=>p.jobId==='tree'&&p.locationId==='pending').length") == 3
    print('PASS external deletion and decoder failures are handled; file retained, lock released, retry succeeds')

    assert not errors, errors
    browser.close()
    print('ALL PASS; concurrent photo recheck, latest job preservation, reload, mobile width, no browser errors')
