from playwright.sync_api import sync_playwright
from pathlib import Path
import json,io,zipfile,base64,os,subprocess,xml.etree.ElementTree as ET
ROOT=Path(__file__).resolve().parents[1]
js_path=os.environ.get('JSZIP_PATH')
js=Path(js_path).read_bytes() if js_path else subprocess.check_output(['curl','--fail','--silent','--show-error','https://cdn.jsdelivr.net/npm/jszip@3.10.1/dist/jszip.min.js'])
with sync_playwright() as pw:
 b=pw.chromium.launch(executable_path='/usr/bin/chromium',args=['--no-sandbox'])
 ctx=b.new_context(service_workers='block');p=ctx.new_page();errors=[];p.on('pageerror',lambda e: errors.append(str(e)))
 p.route('http://test.local/**',lambda r:r.fulfill(body=(ROOT/('index.html' if r.request.url.endswith('/') else r.request.url.rsplit('/',1)[-1])).read_bytes()))
 p.route('https://cdn.jsdelivr.net/**',lambda r:r.fulfill(content_type='application/javascript',body=js))
 answers=[];dialogs=[]
 def dialog(d):
  dialogs.append(d.message)
  if d.type=='confirm' and answers and not answers.pop(0):d.dismiss()
  else:d.accept()
 p.on('dialog',dialog);p.goto('http://test.local/');p.wait_for_function('!!db && typeof JSZip === "function"')
 assert p.evaluate("async()=> (await all('jobs')).length")==0
 p.locator('#homeProjectImportBtn').click();print('PASS home import button available without jobs')
 image=p.evaluate("()=>{let c=document.createElement('canvas');c.width=640;c.height=480;return c.toDataURL('image/jpeg').split(',')[1]}")
 job={'id':'shared-job','name':'ZIP復元検証','no':'001','address':'検証住所','contact':'担当者','contractor':'施工会社','tasks':['01_受変電設備'],'locations':[{'id':'loc1','building':'A棟','floor':'1階','room':'101','place':'盤前'}]}
 records=[{'imagePath':f'images/{i:05}.jpg','mime':'image/jpeg','metadata':{'id':i,'locationId':'loc1','time':1720000000000+i,'task':'01_受変電設備','phase':'施工前','comment':str(i),'sortOrder':i,'boardPos':'right','boardSize':'small'}} for i in range(1,46)]
 def archive(missing=False):
  out=io.BytesIO()
  with zipfile.ZipFile(out,'w') as z:
   z.writestr('edit_project.json',json.dumps({'format':'iwasaki-edit-project','version':1,'job':job,'photos':records}))
   for r in records:
    if not missing or r!=records[-1]:z.writestr(r['imagePath'],base64.b64decode(image))
  return out.getvalue()
 def load(data):
  p.locator('#projectImportFile').set_input_files({'name':'project.zip','mimeType':'application/zip','buffer':data});p.wait_for_function('!projectTransferBusy')
 load(archive());assert p.locator('#job').is_visible();assert p.evaluate("async()=> (await all('photos')).length")==45
 assert p.evaluate("async()=> (await all('photos')).every(p=>p.locationId==='loc1'&&p.boardPos==='right')")
 p.evaluate("selectLocation('loc1')");assert p.locator('#locations .active').count()==1;assert p.locator('#editSelectedLocationBtn').is_enabled();print('PASS fresh import: job, location, 45 photos, metadata, blue selection and common edit button')
 before=p.evaluate("async()=>JSON.stringify([await all('jobs'),await all('photos')])")
 answers[:]=[True,False];load(archive());assert p.evaluate("async()=>JSON.stringify([await all('jobs'),await all('photos')])")==before;print('PASS replacement cancellation preserves all data')
 answers[:]=[True,True];load(archive(True));assert p.evaluate("async()=>JSON.stringify([await all('jobs'),await all('photos')])")==before;print('PASS missing photo rejects before writes')
 answers[:]=[True,True];load(archive());assert p.evaluate("async()=> (await all('photos')).length")==45;assert any('最終確認' in d for d in dialogs);print('PASS confirmed replacement')
 answers[:]=[False];load(archive());assert p.evaluate("async()=> (await all('jobs')).length")==2;assert p.evaluate("async()=> (await all('photos')).length")==90;print('PASS separate import preserves original')
 p.locator('#projectExportBtn').click();p.wait_for_function('!projectTransferBusy');raw=p.evaluate("async()=>Array.from(new Uint8Array(await (await fetch(projectDownloadLink.href)).arrayBuffer()))")
 z=zipfile.ZipFile(io.BytesIO(bytes(raw)));m=json.loads(z.read('edit_project.json'));assert len(m['photos'])==45;assert m['appVersion']=='3.10.9';print('PASS project ZIP export')
 p.locator('#excelExportBtn').click();p.wait_for_function("!ledgerExportBusy && downloadReadyLink.download.endsWith('.xlsx')",timeout=120000)
 raw=p.evaluate("async()=>Array.from(new Uint8Array(await (await fetch(downloadReadyLink.href)).arrayBuffer()))");z=zipfile.ZipFile(io.BytesIO(bytes(raw)));assert z.testzip() is None
 assert len([n for n in z.namelist() if n.startswith('xl/media/photo')])==45
 sheet=ET.fromstring(z.read('xl/worksheets/sheet2.xml'));assert 'No.45' in ''.join(sheet.itertext());ns={'s':'http://schemas.openxmlformats.org/spreadsheetml/2006/main'};assert len(sheet.findall('s:rowBreaks/s:brk',ns))==14
 cover=ET.fromstring(z.read('xl/worksheets/sheet1.xml'));assert '施工会社' in ''.join(cover.find(".//s:c[@r='E27']",ns).itertext());print('PASS Ver43 Excel 45 images / 15 pages / E27 contractor (blackboard enabled)')
 p.evaluate('home()');load(b'not a zip');assert '読み込み失敗' in p.locator('#homeProjectTransferStatus').inner_text();assert p.locator('#homeProjectTransferStatus').is_visible();print('PASS invalid ZIP error visible on home')
 assert not errors,errors;b.close();print('ALL PASS; no browser JavaScript errors')
