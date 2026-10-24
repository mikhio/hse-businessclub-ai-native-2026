'use strict';

const $ = (selector, root = document) => root.querySelector(selector);
const state = {user: null, csrf: '', view: 'feed', kind: '', query: '', items: [], offset: 0, total: 0, renderId: 0};
const escapeHTML = value => String(value ?? '').replace(/[&<>"']/g, c => ({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));
const initials = name => name.split(' ').slice(0,2).map(w=>w[0]).join('');
const statuses = {pending:'На рассмотрении', accepted:'Отклик принят', rejected:'Отклик отклонён'};
const kindLabel = kind => kind === 'startup' ? 'СТАРТАП' : 'ВАКАНСИЯ';
let toastTimer;
function toast(message) { $('#toast').textContent = message; $('#toast').hidden = false; clearTimeout(toastTimer); toastTimer = setTimeout(()=>$('#toast').hidden=true, 4500); }
function dateLabel(date) { return new Intl.DateTimeFormat('ru-RU',{day:'numeric',month:'short'}).format(new Date(date)); }
function avatar(user, size = '') { return `<span class="avatar ${size}">${escapeHTML(initials(user.name))}</span>`; }
function person(user) { return `<div class="person">${avatar(user)}<span><strong>${escapeHTML(user.name)}</strong><small>${escapeHTML(user.headline)}</small></span></div>`; }
function decisionBadge(status) { return `<span class="decision ${status}">${statuses[status]}</span>`; }

async function api(path, options = {}) {
  const {method = 'GET', body, key} = options;
  const headers = {'Accept':'application/json'};
  if (body !== undefined) headers['Content-Type'] = 'application/json';
  if (method !== 'GET') headers['X-CSRF-Token'] = state.csrf;
  if (key) headers['Idempotency-Key'] = key;
  const response = await fetch(`/api${path}`, {method, headers, credentials:'same-origin', body:body === undefined ? undefined : JSON.stringify(body)});
  let result;
  try { result = await response.json(); } catch { throw new Error('Сервис временно недоступен. Попробуй ещё раз.'); }
  if (!response.ok) {
    if (response.status === 401 && path !== '/auth/login') { state.user=null; showLogin(); }
    const message = Array.isArray(result.detail) ? 'Проверь поля формы: часть данных заполнена некорректно.' : result.detail;
    throw new Error(message || 'Не получилось выполнить действие. Попробуй ещё раз.');
  }
  return result;
}

function showLogin() { $('#app-screen').hidden=true; $('#login-screen').hidden=false; if ($('#modal').open) $('#modal').close(); }
function showApp() { $('#login-screen').hidden=true; $('#app-screen').hidden=false; $('#header-avatar').textContent=initials(state.user.name); navigate(); }
async function login(email,password) {
  const result=await api('/auth/login',{method:'POST',body:{email,password}});
  state.user=result.user; state.csrf=result.csrf_token; $('#login-error').textContent=''; showApp();
}
$('#login-form').addEventListener('submit',async event=>{
  event.preventDefault(); const button=$('button[type=submit]',event.target); button.disabled=true; $('#login-error').textContent='';
  try {await login($('#login-email').value,$('#login-password').value);} catch(error){$('#login-error').textContent=error.message;} finally{button.disabled=false;}
});
document.querySelectorAll('[data-demo]').forEach(button=>button.addEventListener('click',async()=>{
  document.querySelectorAll('[data-demo]').forEach(b=>b.disabled=true);
  try{await login(`${button.dataset.demo}@example.test`,'ClubDemo2026!');}catch(error){$('#login-error').textContent=error.message;}finally{document.querySelectorAll('[data-demo]').forEach(b=>b.disabled=false);}
}));
$('#logout').addEventListener('click',async()=>{try{await api('/auth/logout',{method:'POST'});state.user=null;state.csrf='';showLogin();}catch(error){toast(error.message);}});
$('#header-profile').addEventListener('click',()=>location.hash='profile');
$('#new-publication').addEventListener('click',showCreate);
$('#modal .modal-close').addEventListener('click',()=>$('#modal').close());
$('#modal').addEventListener('click',event=>{if(event.target===$('#modal')){const box=$('#modal').getBoundingClientRect();if(event.clientX<box.left||event.clientX>box.right||event.clientY<box.top||event.clientY>box.bottom)$('#modal').close();}});
window.addEventListener('hashchange',navigate);

function navigate() {
  if (!state.user) return;
  const value=location.hash.replace('#','') || 'feed';
  state.view=['feed','mine','sent','received','profile'].includes(value)?value:'feed';
  state.offset=0; state.items=[]; state.kind=''; state.query='';
  document.querySelectorAll('[data-view]').forEach(a=>a.classList.toggle('active',a.dataset.view===state.view));
  renderPage();
}

async function renderPage() {
  const id=++state.renderId;
  const main=$('#main-content');
  main.innerHTML='<div class="loading" role="status">Загружаем возможности…</div>';
  try{
    if(state.view==='profile'){renderProfile();return;}
    if(state.view==='sent'||state.view==='received'){await renderApplications(id);return;}
    const mine=state.view==='mine';
    main.innerHTML=mine?`<div class="page-title"><p class="eyebrow">Твои идеи и предложения</p><h1>Мои публикации</h1><p>Управляй набором и находи людей для своих проектов.</p></div>`:`<div class="page-kicker">СООБЩЕСТВО / ВОЗМОЖНОСТИ</div><section class="hero"><div><h1>Идеи ищут людей.<br>Люди находят своих.</h1><p>Стартапы и вакансии участников клуба.<br>Выбери, где твои навыки пригодятся больше всего.</p></div><div class="hero-art" aria-hidden="true"><span>✳</span></div></section>`;
    main.insertAdjacentHTML('beforeend',`<div class="filters"><div class="tabs" role="group" aria-label="Тип публикации"><button class="tab active" data-kind="">Все возможности</button><button class="tab" data-kind="startup">Стартапы</button><button class="tab" data-kind="vacancy">Вакансии</button></div><label class="search"><span class="sr-only" hidden>Поиск по публикациям</span><input id="search-input" aria-label="Поиск по публикациям" type="search" maxlength="100" placeholder="Проект, роль или навык"></label></div><div class="results-meta"><span id="result-count"></span><span>${mine?'Открытые и закрытые':'Сначала новые'}</span></div><div class="cards" id="cards" aria-live="polite"></div><div class="load-more" id="load-more"></div>`);
    main.querySelectorAll('[data-kind]').forEach(button=>button.addEventListener('click',()=>{
      state.kind=button.dataset.kind;state.offset=0; main.querySelectorAll('[data-kind]').forEach(b=>b.classList.toggle('active',b===button));loadCards(++state.renderId);
    }));
    let debounce;
    $('#search-input').addEventListener('input',event=>{clearTimeout(debounce);state.query=event.target.value;debounce=setTimeout(()=>{state.offset=0;loadCards(++state.renderId);},250);});
    await loadCards(id);
  }catch(error){if(id===state.renderId)renderError(error.message);}
}

function renderError(message){$('#main-content').innerHTML=`<section class="error-panel"><h3>Не получилось загрузить страницу</h3><p>${escapeHTML(message)}</p><button class="button" id="retry">Попробовать снова</button></section>`;$('#retry').addEventListener('click',renderPage);}
async function loadCards(id) {
  try{
    const params=new URLSearchParams({status:state.view==='mine'?'all':'open',mine:String(state.view==='mine'),q:state.query,offset:String(state.offset)});
    if(state.kind)params.set('kind',state.kind);
    const data=await api(`/publications?${params}`);
    if(id!==state.renderId||!$('#cards'))return;
    state.items=state.offset?[...state.items,...data.items]:data.items;state.total=data.total;
    $('#result-count').textContent=`Найдено: ${data.total}`;
    $('#cards').innerHTML=state.items.length?state.items.map(cardHTML).join(''):emptyHTML(state.view==='mine'?'Здесь начнётся твой проект':'Пока ничего не нашлось',state.view==='mine'?'Расскажи об идее или опубликуй вакансию. Первый отклик может стать началом команды.':'Попробуй другой запрос или тип публикации.',state.view==='mine');
    $('#cards').querySelectorAll('[data-publication]').forEach(button=>button.addEventListener('click',()=>showDetail(Number(button.dataset.publication))));
    $('#empty-create')?.addEventListener('click',showCreate);
    $('#load-more').innerHTML=state.items.length<state.total?'<button class="button" id="more">Показать ещё</button>':'';
    $('#more')?.addEventListener('click',()=>{state.offset=state.items.length;$('#more').disabled=true;loadCards(++state.renderId);});
  }catch(error){if(id===state.renderId){toast(error.message);$('#more')?.removeAttribute('disabled');}}
}

function emptyHTML(title,description,create=false){return `<div class="empty-state"><span class="empty-icon" aria-hidden="true">✳</span><h3>${escapeHTML(title)}</h3><p>${escapeHTML(description)}</p>${create?'<button class="button primary" id="empty-create">Создать публикацию</button>':''}</div>`;}
function cardHTML(p){return `<article class="card ${p.status==='closed'?'publication-closed':''}"><div class="card-top"><span class="tag ${p.kind}">${kindLabel(p.kind)}</span><span class="status ${p.status}">${p.status==='closed'?'Набор закрыт':escapeHTML(p.work_format)}</span></div><h3><button class="text-link" data-publication="${p.id}">${escapeHTML(p.title)}</button></h3><p class="card-description">${escapeHTML(p.description)}</p><p class="skills-line">${escapeHTML(p.looking_for)}</p>${p.my_application?`<p>${decisionBadge(p.my_application.status)}</p>`:''}<div class="card-bottom">${person(p.author)}<button class="card-link" data-publication="${p.id}" aria-label="Открыть: ${escapeHTML(p.title)}">↗</button></div></article>`;}

function openModal(html){$('#modal-content').innerHTML=html;if(!$('#modal').open)$('#modal').showModal();$('#modal').scrollTop=0;}
async function showDetail(id){
  openModal('<p class="loading">Загружаем публикацию…</p>');
  try{
    const p=await api(`/publications/${id}`);
    let action='';
    if(p.is_mine)action=`<p class="note">Это твоя публикация. Входящие отклики доступны в личном кабинете.</p><button class="button" id="toggle-status">${p.status==='open'?'Закрыть набор':'Открыть набор снова'}</button>`;
    else if(p.my_application)action=`${decisionBadge(p.my_application.status)}<p class="note detail-status">${p.my_application.status==='pending'?'Автор увидит твой отклик. Решение появится в разделе «Мои отклики».':p.my_application.status==='accepted'?'Автор принял твой отклик. Посмотри детали в разделе «Мои отклики».':'Автор уже рассмотрел этот отклик. Можно найти другой проект в ленте.'}</p>`;
    else if(p.status==='closed')action='<p class="inline-note">Набор закрыт. Новые отклики больше не принимаются.</p>';
    else action=`<form id="apply-form"><label>Почему тебе интересен этот проект?<textarea name="message" minlength="10" maxlength="2000" required placeholder="Расскажи о навыках и о том, чем можешь помочь"></textarea></label><p class="form-error" role="alert"></p><button class="button primary" type="submit">Отправить отклик ↗</button></form>`;
    openModal(`<span class="tag ${p.kind}">${kindLabel(p.kind)}</span><h2 class="modal-title">${escapeHTML(p.title)}</h2><div class="detail-meta"><span class="tag">${escapeHTML(p.work_format)}</span><span class="tag">${p.status==='open'?'Набор открыт':'Набор закрыт'}</span><span class="tag">${dateLabel(p.created_at)}</span></div><p class="detail-description">${escapeHTML(p.description)}</p><div class="detail-box"><strong>Кого ищем</strong>${escapeHTML(p.looking_for)}</div>${person(p.author)}<div class="detail-footer">${action}</div>`);
    $('#toggle-status')?.addEventListener('click',async event=>{
      event.target.disabled=true;
      try{await api(`/publications/${p.id}`,{method:'PATCH',body:{status:p.status==='open'?'closed':'open'}});toast(p.status==='open'?'Набор закрыт. Старые отклики сохранены.':'Набор снова открыт');await showDetail(p.id);refreshCurrent();}catch(error){toast(error.message);event.target.disabled=false;}
    });
    $('#apply-form')?.addEventListener('submit',async event=>{
      event.preventDefault();const button=$('button',event.target);button.disabled=true;
      try{await api(`/publications/${p.id}/applications`,{method:'POST',body:{message:new FormData(event.target).get('message')}});toast('Отклик отправлен автору');await showDetail(p.id);refreshCurrent();}catch(error){$('.form-error',event.target).textContent=error.message;button.disabled=false;}
    });
  }catch(error){openModal(`<h2 class="modal-title">Не удалось открыть публикацию</h2><p>${escapeHTML(error.message)}</p>`);}
}

function refreshCurrent(){if(state.view==='feed'||state.view==='mine'){state.offset=0;loadCards(++state.renderId);}else if(state.view==='sent'||state.view==='received')renderPage();}
function showCreate(){
  const creationKey=crypto.randomUUID();
  openModal(`<p class="eyebrow">Первый шаг к команде</p><h2 class="modal-title">Создать публикацию</h2><p class="muted">Расскажи, что делаешь и кто тебе нужен.</p><form id="create-form"><div class="form-grid"><label>Тип публикации<select name="kind"><option value="startup">Стартап / поиск команды</option><option value="vacancy">Вакансия в проект</option></select></label><label>Формат работы<input name="work_format" value="По договорённости" required minlength="2" maxlength="80"></label></div><label>Название<input name="title" required minlength="5" maxlength="120" placeholder="Например, backend-разработчик в StudyPal"></label><label>Описание<textarea name="description" required minlength="20" maxlength="5000" placeholder="Что за проект, на каком он этапе и что предстоит делать"></textarea></label><label>Кого ищешь<input name="looking_for" required minlength="3" maxlength="300" placeholder="Роль, навыки или опыт"></label><p class="form-hint">Публикация появится в ленте сразу. Ты сможешь закрыть набор в любой момент.</p><p class="form-error" role="alert"></p><button class="button primary" type="submit">Опубликовать ↗</button></form>`);
  $('#create-form').addEventListener('submit',async event=>{
    event.preventDefault();const button=$('button[type=submit]',event.target);button.disabled=true;
    try{const p=await api('/publications',{method:'POST',key:creationKey,body:Object.fromEntries(new FormData(event.target))});toast('Публикация появилась в ленте');await showDetail(p.id);refreshCurrent();}catch(error){$('.form-error',event.target).textContent=error.message;button.disabled=false;}
  });
}

async function renderApplications(id){
  const received=state.view==='received';const data=await api(`/applications?direction=${received?'received':'sent'}`);
  if(id!==state.renderId)return;
  $('#main-content').innerHTML=`<div class="page-title"><p class="eyebrow">Личный кабинет</p><h1>${received?'Входящие отклики':'Мои отклики'}</h1><p>${received?'Люди, которым интересны твои проекты. Познакомься и прими решение.':'Все отправленные отклики и решения авторов — в одном месте.'}</p></div><div class="application-list">${data.items.length?data.items.map(a=>`<article class="application-row"><div class="application-heading"><div><span class="tag ${a.publication.kind}">${kindLabel(a.publication.kind)}</span><h3><button class="text-link" data-publication="${a.publication.id}">${escapeHTML(a.publication.title)}</button></h3></div>${decisionBadge(a.status)}</div>${person(received?a.applicant:a.publication.author)}<p class="application-message">${escapeHTML(a.message)}</p><div class="application-actions"><span class="note">Отправлен ${dateLabel(a.created_at)}${a.decided_at?` · Решение ${dateLabel(a.decided_at)}`:''}</span>${received&&a.status==='pending'?`<div class="decision-buttons"><button class="button compact danger" data-decision="rejected" data-application="${a.id}">Отклонить</button><button class="button compact secondary" data-decision="accepted" data-application="${a.id}">Принять отклик</button></div>`:''}</div></article>`).join(''):emptyHTML(received?'Пока нет входящих откликов':'Ты ещё не откликался',received?'Как только кто-то заинтересуется твоей публикацией, отклик появится здесь.':'Открой ленту и найди проект, в котором пригодятся твои навыки.')}</div>`;
  $('#main-content').querySelectorAll('[data-publication]').forEach(button=>button.addEventListener('click',()=>showDetail(Number(button.dataset.publication))));
  $('#main-content').querySelectorAll('[data-decision]').forEach(button=>button.addEventListener('click',async()=>{
    if(!confirm(`${button.dataset.decision==='accepted'?'Принять':'Отклонить'} отклик? Изменить решение после подтверждения нельзя.`))return;
    button.disabled=true;
    try{await api(`/applications/${button.dataset.application}`,{method:'PATCH',body:{status:button.dataset.decision}});toast('Решение сохранено и видно участнику');renderPage();}catch(error){toast(error.message);button.disabled=false;}
  }));
}

function renderProfile(){
  const u=state.user;
  $('#main-content').innerHTML=`<div class="page-title"><p class="eyebrow">Личный кабинет</p><h1>Привет, ${escapeHTML(u.name.split(' ')[0])}.</h1><p>Помоги будущей команде узнать тебя чуть лучше.</p></div><div class="profile-layout"><form class="profile-form" id="profile-form"><p class="profile-email">Учебный аккаунт: ${escapeHTML(u.email)}</p><label>Имя и фамилия<input name="name" minlength="2" maxlength="80" value="${escapeHTML(u.name)}" required></label><label>Чем занимаешься<input name="headline" maxlength="140" value="${escapeHTML(u.headline)}" placeholder="Например, продуктовый дизайнер"></label><label>О себе<textarea name="bio" maxlength="2000">${escapeHTML(u.bio)}</textarea></label><label>Навыки<input name="skills" maxlength="300" value="${escapeHTML(u.skills)}" placeholder="Python, аналитика, дизайн"></label><p class="form-hint">Имя, описание и навыки видны участникам клуба. Email остаётся в твоём кабинете.</p><p class="form-error" role="alert"></p><button class="button primary" type="submit">Сохранить профиль</button></form><aside class="profile-preview">${avatar(u,'large')}<h3>${escapeHTML(u.name)}</h3><p>${escapeHTML(u.headline)}</p><p class="skill-tags">${escapeHTML(u.skills)}</p></aside></div>`;
  $('#profile-form').addEventListener('submit',async event=>{
    event.preventDefault();const button=$('button[type=submit]',event.target);button.disabled=true;
    try{const result=await api('/me',{method:'PATCH',body:Object.fromEntries(new FormData(event.target))});state.user=result.user;$('#header-avatar').textContent=initials(state.user.name);toast('Профиль сохранён');renderProfile();}catch(error){$('.form-error',event.target).textContent=error.message;button.disabled=false;}
  });
}

(async()=>{try{const result=await api('/me');state.user=result.user;state.csrf=result.csrf_token;showApp();}catch{showLogin();}})();
