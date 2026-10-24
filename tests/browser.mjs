/** Optional end-to-end acceptance check. Uses its own browser and fake demo data. */
import assert from 'node:assert/strict';
import {mkdir} from 'node:fs/promises';
const {chromium} = await import(process.env.PLAYWRIGHT_MODULE || 'playwright');
const baseURL=process.env.APP_URL||'http://127.0.0.1:8173';
const browser=await chromium.launch({headless:true,...(process.env.CHROMIUM_PATH?{executablePath:process.env.CHROMIUM_PATH}:{})});
const ownerContext=await browser.newContext({viewport:{width:1440,height:1000}});
const applicantContext=await browser.newContext({viewport:{width:390,height:844}});
const owner=await ownerContext.newPage();
const applicant=await applicantContext.newPage();
const errors=[];
for(const page of [owner,applicant]){
  page.on('pageerror',error=>errors.push(error.message));
  page.on('response',response=>{if(response.status()>=500)errors.push(`${response.status()} ${response.url()}`);});
}
const title=`Демо-команда ${Date.now()}`;
try{
  await mkdir('artifacts',{recursive:true});
  const docs=await ownerContext.newPage();
  await docs.addInitScript(()=>{window.cspViolations=[];document.addEventListener('securitypolicyviolation',event=>window.cspViolations.push({directive:event.effectiveDirective,blocked:event.blockedURI}));});
  const docsResponse=await docs.goto(`${baseURL}/docs`);
  await docs.locator('#swagger-ui .opblock').first().waitFor();
  assert.equal(await docs.evaluate(()=>typeof SwaggerUIBundle),'function');
  assert.deepEqual(await docs.evaluate(()=>window.cspViolations),[]);
  assert.ok(docsResponse.headers()['content-security-policy'].includes("'nonce-"));
  await docs.screenshot({path:'artifacts/docs.png',fullPage:true});
  const operationCount=await docs.locator('#swagger-ui .opblock').count();
  await docs.close();
  const mainResponse=await owner.goto(baseURL);
  const mainCsp=mainResponse.headers()['content-security-policy'];
  assert.ok(!mainCsp.includes('cdn.jsdelivr.net')&&!mainCsp.includes("'unsafe-inline'")&&!mainCsp.includes('nonce-'));
  await owner.locator('[data-demo="anna"]').click();
  await owner.locator('#cards .card').first().waitFor();
  await owner.screenshot({path:'artifacts/desktop-feed.png',fullPage:true});
  await owner.getByRole('button',{name:'Создать публикацию',exact:true}).click();
  await owner.locator('#create-form [name=title]').fill(title);
  await owner.locator('#create-form [name=description]').fill('Вымышленный проект для проверки полного сценария публикации и отклика.');
  await owner.locator('#create-form [name=looking_for]').fill('Python backend');
  await owner.locator('#create-form button[type=submit]').click();
  await owner.locator('.modal-title').filter({hasText:title}).waitFor();
  await owner.getByRole('button',{name:'Закрыть диалог'}).click();

  await applicant.goto(baseURL);
  await applicant.locator('[data-demo="max"]').click();
  await applicant.locator('#cards .card').first().waitFor();
  await applicant.locator('#search-input').fill(title);
  await applicant.locator('#cards .text-link').filter({hasText:title}).click();
  await applicant.locator('#apply-form [name=message]').fill('Хочу помочь с Python backend. Готов обсудить первый прототип.');
  await applicant.locator('#apply-form button[type=submit]').click();
  await applicant.locator('#modal .decision.pending').waitFor();
  await applicant.getByRole('button',{name:'Закрыть диалог'}).click();

  await owner.locator('a[data-view=received]').click();
  const incoming=owner.locator('.application-row').filter({hasText:title});
  await incoming.locator('.decision.pending').waitFor();
  owner.once('dialog',dialog=>dialog.accept());
  await incoming.getByRole('button',{name:'Принять отклик'}).click();
  await incoming.locator('.decision.accepted').waitFor();
  await owner.screenshot({path:'artifacts/desktop-incoming.png',fullPage:true});

  await applicant.locator('a[data-view=sent]').click();
  await applicant.locator('.application-row').filter({hasText:title}).locator('.decision.accepted').waitFor();
  await applicant.screenshot({path:'artifacts/mobile-result.png',fullPage:true});
  for(const width of [320,390,768,1440]){
    await applicant.setViewportSize({width,height:900});
    await applicant.locator('a[data-view=feed]').click();
    await applicant.locator('#cards').waitFor();
    const dimensions=await applicant.evaluate(()=>({viewport:innerWidth,content:document.documentElement.scrollWidth}));
    assert.ok(dimensions.content<=dimensions.viewport,`horizontal overflow at ${width}: ${JSON.stringify(dimensions)}`);
    if(width===390)await applicant.screenshot({path:'artifacts/mobile-feed.png',fullPage:true});
  }
  assert.deepEqual(errors,[]);
  console.log(JSON.stringify({status:'passed',scenario:title,docs:{operations:operationCount,cspViolations:0},mainCspUnchanged:true,viewports:[320,390,768,1440],errors,screenshots:['desktop-feed.png','desktop-incoming.png','mobile-result.png','mobile-feed.png','docs.png']}));
}finally{await ownerContext.close();await applicantContext.close();await browser.close();}
