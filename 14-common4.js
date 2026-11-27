const $=s=>document.querySelector(s);
let TOKEN=localStorage.getItem('tk_'+ROLE)||'';
const SOUND_ROLES=['restaurant','courier'];
const _inf={};
async function api(p,d){const _k=d!==undefined?p+JSON.stringify(d):'';if(_k){if(_inf[_k])return null;_inf[_k]=1}try{return await api0(p,d)}finally{if(_k)setTimeout(()=>{delete _inf[_k]},600)}}
async function api0(p,d){const o={headers:{'X-Token':TOKEN,'Content-Type':'application/json'}};if(d!==undefined){o.method='POST';o.body=JSON.stringify(d)}
 try{const r=await fetch('/api/'+p,o);let j=null;try{j=await r.json()}catch(e){}
  if(r.status==401&&TOKEN){logout();return null}
  if(!r.ok){toast((j&&j.error)||'حدث خطأ، برجاء المحاولة مرة أخرى');return null}return j}catch(e){toast('لا يوجد اتصال بالإنترنت');return null}}
function toast(t){const e=$('#toast');e.textContent=t;e.style.display='block';clearTimeout(window._tt);window._tt=setTimeout(()=>e.style.display='none',3000)}
function logout(){localStorage.removeItem('tk_'+ROLE);TOKEN='';location.reload()}
function esc(s){return String(s==null?'':s).replace(/[&<>"']/g,c=>({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]))}
function money(n){return (Math.round((n||0)*100)/100)+' ج'}
function timeAgo(ts){const m=Math.floor((Date.now()/1000-ts)/60);return m<1?'الآن':m<60?'من '+m+' دقيقة':'من '+Math.floor(m/60)+' ساعة'}
/* theme */
function applyTheme(){document.documentElement.setAttribute('data-theme',localStorage.getItem('theme')||'dark')}
function toggleTheme(){localStorage.setItem('theme',(localStorage.getItem('theme')||'dark')=='dark'?'light':'dark');applyTheme()}
applyTheme();
/* sound */
let AC=null;
function unlockAudio(){try{AC=AC||new (window.AudioContext||window.webkitAudioContext)();if(AC.state==='suspended')AC.resume()}catch(e){}}
document.addEventListener('click',unlockAudio);document.addEventListener('touchstart',unlockAudio);
function beep(n){try{unlockAudio();if(!AC)return;n=n||3;for(let i=0;i<n;i++){const o=AC.createOscillator(),g=AC.createGain();o.connect(g);g.connect(AC.destination);o.frequency.value=880;g.gain.value=0.4;const t=AC.currentTime+i*0.5;o.start(t);o.stop(t+0.3)}}catch(e){}
 try{navigator.vibrate&&navigator.vibrate([300,150,300])}catch(e){}}
/* polling on version counter */
function watch(fn,ms){let last=null,busy=false;const tick=async()=>{if(busy||document.hidden)return;busy=true;try{const r=await fetch('/api/ver');const j=await r.json();if(j.v!==last){last=j.v;await fn()}}catch(e){}busy=false};
 tick();setInterval(tick,ms||4000);document.addEventListener('visibilitychange',()=>{if(!document.hidden){last=null;tick()}})}
/* image resize to jpeg dataURL */
function resizeImage(file,max){return new Promise((res,rej)=>{const fr=new FileReader();fr.onerror=rej;fr.onload=()=>{const im=new Image();im.onerror=rej;im.onload=()=>{let w=im.width,h=im.height;const s=Math.min(1,(max||400)/Math.max(w,h));w=Math.round(w*s);h=Math.round(h*s);const c=document.createElement('canvas');c.width=w;c.height=h;const x=c.getContext('2d');x.fillStyle='#fff';x.fillRect(0,0,w,h);x.drawImage(im,0,0,w,h);res(c.toDataURL('image/jpeg',0.6))};im.src=fr.result};fr.readAsDataURL(file)})}
/* shell */
const CSS=`:root{--bg:#111;--card:#1d1d1d;--fg:#eee;--mut:#aaa;--gold:#d4af37;--inp:#000;--btn2:#444}
[data-theme=light]{--bg:#f4f1e8;--card:#fff;--fg:#222;--mut:#666;--gold:#8a6d00;--inp:#fff;--btn2:#e6e0cc}
body{font-family:sans-serif;margin:0;background:var(--bg);color:var(--fg);direction:rtl}
header{background:#000;color:#d4af37;border-bottom:2px solid #d4af37;padding:10px 12px;display:flex;justify-content:space-between;align-items:center;position:sticky;top:0;z-index:5}
header b{font-size:18px}#app{padding:10px;max-width:640px;margin:auto}
.card{background:var(--card);color:var(--fg);border-radius:10px;padding:12px;margin:8px 0;box-shadow:0 1px 3px #0003}
input,select,textarea{width:100%;box-sizing:border-box;padding:10px;margin:5px 0;font-size:16px;border:1px solid var(--gold);background:var(--inp);color:var(--fg);border-radius:6px;font-family:inherit}
button{background:#d4af37;color:#000;font-weight:bold;border:0;padding:10px 14px;border-radius:6px;font-size:16px;margin:3px;font-family:inherit}
button.alt{background:var(--btn2);color:var(--gold)}button.red{background:#c62828;color:#fff}button.sm{padding:5px 10px;font-size:14px}
header button{margin:0 2px;padding:6px 10px;font-size:15px}
.st{font-weight:bold;color:var(--gold)}#toast{display:none;position:fixed;bottom:20px;left:8%;right:8%;background:#333;color:#fff;padding:10px;border-radius:8px;text-align:center;z-index:50}
small,.mut{color:var(--mut)}h2,h3{color:var(--gold)}a{color:var(--gold)}.row{display:flex;justify-content:space-between;align-items:center;gap:6px}
.tabs{display:flex;gap:4px;flex-wrap:wrap}.tabs button{flex:1;min-width:70px}.tabs button.on{background:#d4af37;color:#000}.tabs button:not(.on){background:var(--btn2);color:var(--gold)}
img.food{width:64px;height:64px;object-fit:cover;border-radius:8px;margin-inline-end:8px}
.chip{display:inline-block;background:var(--btn2);color:var(--gold);border-radius:12px;padding:3px 10px;margin:2px;font-size:13px}
.banner{background:#d4af37;color:#000;font-weight:bold;text-align:center;border-radius:10px;padding:10px;margin:8px 0}
.ov{position:fixed;inset:0;background:#000c;z-index:40;display:flex;align-items:center;justify-content:center;padding:20px}
footer{text-align:center;padding:14px;color:var(--mut);font-size:14px}
.big .card{font-size:20px}.big button{font-size:20px;padding:14px 18px}.new{border:2px solid #d4af37}
@media print{header,button,footer,.noprint{display:none!important}body{background:#fff;color:#000}.card{box-shadow:none;border:1px solid #000}}`;
var BK3D='.bk{color:#FFF;text-shadow:0 -0.006em 0 #FFD9C2,0.006em 0.012em 0 #E04A00,0.012em 0.024em 0 #D24300,0.018em 0.036em 0 #C53D00,0.024em 0.048em 0 #B73800,0.030em 0.060em 0 #A93300,0.036em 0.072em 0 #9B2E00,0.042em 0.084em 0 #8C2900,0.048em 0.096em 0 #7E2400,0.05em 0.115em 0.03em #5A1A00,0.07em 0.15em 0.09em rgba(60,15,0,.45);font-weight:900;font-size:inherit;line-height:1;text-align:center;direction:ltr;white-space:nowrap;overflow:visible;padding-bottom:.17em;font-family:Arial Black,Helvetica Neue,Arial,Roboto,sans-serif}.bk span{display:inline-block}.bk i,.bk b{position:relative;display:inline-block;font-style:normal;font-weight:inherit}.bk i{will-change:transform;transform-origin:15% 65%;z-index:1;animation:k3s 6.5s infinite}.bk i::after,.bk b::after{content:attr(data-t);position:absolute;left:0;top:0;text-shadow:none;color:transparent;-webkit-text-fill-color:transparent;pointer-events:none;background-image:linear-gradient(105deg,transparent 28%,rgba(255,170,0,.9) 37%,#FFD23F 43%,#FFF4C2 47.5%,#FFFFFF 50%,#FFF4C2 52.5%,#FFD23F 57%,rgba(255,170,0,.9) 63%,transparent 72%);background-size:260% 100%;background-repeat:no-repeat;-webkit-background-clip:text;background-clip:text;background-position:120% 0;filter:drop-shadow(0 0 .045em rgba(255,185,30,.95));animation:k3sh 6.5s infinite}.bk b{will-change:transform;transform-origin:80% 65%;z-index:2;animation:k3m 6.5s infinite}.bk b::after{animation-delay:.22s}@keyframes k3s{0.00%{transform:perspective(520px) translateX(.27em) rotateY(0deg) translateX(-.27em) translateZ(0px);animation-timing-function:cubic-bezier(.5,0,.25,1)}15.38%{transform:perspective(520px) translateX(.27em) rotateY(360deg) translateX(-.27em) translateZ(0px)}56.92%{z-index:3;transform:perspective(520px) translateX(.27em) rotateY(360deg) translateX(-.27em) translateZ(0px);animation-timing-function:cubic-bezier(.15,.7,.2,1)}60.77%{transform:perspective(520px) translateX(.27em) rotateY(360deg) translateX(-.27em) translateZ(200px)}62.31%{transform:perspective(520px) translateX(.27em) rotateY(360deg) translateX(-.27em) translateZ(200px);animation-timing-function:cubic-bezier(.5,0,.3,1.4)}68.46%{z-index:3;transform:perspective(520px) translateX(.27em) rotateY(360deg) translateX(-.27em) translateZ(0px)}68.47%{z-index:1}75.38%{opacity:1}78.77%{opacity:.25}80.00%{opacity:.25}86.15%{opacity:1}100.00%{transform:perspective(520px) translateX(.27em) rotateY(360deg) translateX(-.27em) translateZ(0px)}}@keyframes k3m{0.00%{transform:perspective(520px) translateZ(0px)}75.38%{z-index:2;transform:perspective(520px) translateZ(0px);animation-timing-function:cubic-bezier(.15,.7,.2,1)}78.77%{transform:perspective(520px) translateZ(145px)}80.00%{transform:perspective(520px) translateZ(145px);animation-timing-function:cubic-bezier(.5,0,.3,1.4)}86.15%{z-index:5;transform:perspective(520px) translateZ(0px)}86.16%{z-index:2}100.00%{transform:perspective(520px) translateZ(0px)}}@keyframes k3sh{0%{background-position:120% 0}18.46%{background-position:120% 0;animation-timing-function:cubic-bezier(.4,0,.6,1)}32.31%{background-position:-20% 0}33.85%{background-position:120% 0}35.38%{background-position:120% 0;animation-timing-function:cubic-bezier(.4,0,.6,1)}49.23%{background-position:-20% 0}50.77%,100%{background-position:120% 0}}.bk b::before{content:"";position:absolute;right:-.02em;top:.02em;width:.3em;height:.3em;pointer-events:none;opacity:0;background:linear-gradient(90deg,transparent,#fff 50%,transparent) center/100% 7% no-repeat,linear-gradient(0deg,transparent,#fff 50%,transparent) center/7% 100% no-repeat,radial-gradient(circle,#fff 0,rgba(255,225,110,.85) 22%,transparent 62%);animation:k3sp 6.5s infinite;animation-delay:.22s}@keyframes k3sp{0%,26.92%{transform:scale(0) rotate(0);opacity:0}32.31%{transform:scale(1.15) rotate(45deg);opacity:1}36.92%{transform:scale(0) rotate(90deg);opacity:0}43.08%{transform:scale(0) rotate(0);opacity:0}49.23%{transform:scale(1.15) rotate(45deg);opacity:1}53.08%,100%{transform:scale(0) rotate(90deg);opacity:0}}@media(prefers-reduced-motion:reduce){.bk i,.bk b,.bk i::after,.bk b::after,.bk b::before{animation:none}}header .ht{display:block;line-height:1.1}header .bk b{font-size:inherit;font-weight:inherit}.bk .sf{animation:none;margin-inline-start:.22em;font-size:.55em}.bk{margin:6px 0}';function t3d(t,sz){var m=/^3mak(?: (.*))?$/.exec(t||'');if(!m)return esc(t);return '<div class=bk data-fit="'+sz+'" style="font-size:'+sz+'px"><span><i data-t=3>3</i><b data-t=mak>mak</b></span>'+(m[1]?'<span class=sf>'+esc(m[1])+'</span>':'')+'</div>'}
function fit3d(){document.querySelectorAll('.bk[data-fit]').forEach(function(e){var mx=+e.dataset.fit,h=e.closest('header'),w;if(h){var sib=h.children[1];w=h.clientWidth-(sib?sib.offsetWidth:0)-30}else{var cd=e.closest('.card');w=(cd?cd.clientWidth-36:e.parentElement.clientWidth)-4};var s=mx;e.style.fontSize=s+'px';e.style.display='inline-block';while(e.offsetWidth>w&&s>16){s-=1;e.style.fontSize=s+'px'}e.style.display='';e.dataset.fs=s})}window.addEventListener('resize',fit3d);
function shell(title,extraHdr){
 document.title=title;document.head.insertAdjacentHTML('beforeend','<meta name=viewport content="width=device-width,initial-scale=1"><style>'+CSS+BK3D+'</style>');
 document.body.dir='rtl';
 document.body.innerHTML=`<header><span class=ht>${/^3mak/.test(title)?t3d(title,46):'🍔 '+esc(title)}</span><span>${extraHdr||''}<button class=alt id=thm>🌓</button>${TOKEN?'<button class=alt id=lo>خروج</button>':''}</span></header><div id=app></div><footer id=ft></footer><div id=toast></div>`;
 $('#thm').onclick=toggleTheme;fit3d();setTimeout(fit3d,400);if($('#lo'))$('#lo').onclick=logout;
 fetch('/api/settings').then(r=>r.json()).then(s=>{window.SET=s;const p=s.contact_phone;if(p)$('#ft').innerHTML='تواصل معنا: <a href="tel:'+esc(p)+'">'+esc(p)+'</a>';if(window.onSettings)window.onSettings(s)}).catch(()=>{})}
function loginView(){
 $('#app').innerHTML=`<div class=card><img src=/logo.png style="width:120px;display:block;margin:auto"><h2 style="text-align:center">${t3d(TITLE,92)}</h2><input id=pw placeholder="اكتب الكود" inputmode=numeric autocomplete=off><button id=go>دخول</button></div>`;
 fit3d();setTimeout(fit3d,400);$('#go').onclick=async()=>{const k=$('#pw').value.trim();if(!k)return toast('اكتب الكود');const r=await api('login',{phone:k,password:k,role:ROLE});if(r&&r.token){localStorage.setItem('tk_'+ROLE,r.token);TOKEN=r.token;location.reload()}}}
function start(main){shell(TITLE);if(!TOKEN)return loginView();main()}

(function(){var pushed=false,ign=0;function deep(){try{return !!(window.isDeep&&window.isDeep())}catch(e){return false}}
function sync(){if(deep()&&!pushed){try{history.pushState({n:1},'');pushed=true}catch(e){}}else if(!deep()&&pushed){pushed=false;ign=1;try{history.back()}catch(e){ign=0}}}
setInterval(sync,250);
window.addEventListener('popstate',function(){if(ign){ign=0;return}if(!pushed)return;pushed=false;try{window.onBack&&window.onBack()}catch(e){}sync()})})();
