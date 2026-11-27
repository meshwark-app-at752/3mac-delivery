const $=s=>document.querySelector(s);
let TOKEN=localStorage.getItem('tk_'+ROLE)||'';
const SOUND_ROLES=['restaurant','courier'];
async function api(p,d){const o={headers:{'X-Token':TOKEN,'Content-Type':'application/json'}};if(d!==undefined){o.method='POST';o.body=JSON.stringify(d)}
 try{const r=await fetch('/api/'+p,o);let j=null;try{j=await r.json()}catch(e){}
  if(r.status==401&&TOKEN){logout();return null}
  if(!r.ok){toast((j&&j.error)||'حصل خطأ، جرب تاني');return null}return j}catch(e){toast('مفيش اتصال بالإنترنت');return null}}
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
function shell(title,extraHdr){
 document.title=title;document.head.insertAdjacentHTML('beforeend','<meta name=viewport content="width=device-width,initial-scale=1"><style>'+CSS+'</style>');
 document.body.dir='rtl';
 document.body.innerHTML=`<header><b>🍔 ${esc(title)}</b><span>${extraHdr||''}<button class=alt id=thm>🌓</button>${TOKEN?'<button class=alt id=lo>خروج</button>':''}</span></header><div id=app></div><footer id=ft></footer><div id=toast></div>`;
 $('#thm').onclick=toggleTheme;if($('#lo'))$('#lo').onclick=logout;
 fetch('/api/settings').then(r=>r.json()).then(s=>{window.SET=s;const p=s.contact_phone;if(p)$('#ft').innerHTML='تواصل معنا: <a href="tel:'+esc(p)+'">'+esc(p)+'</a>';if(window.onSettings)window.onSettings(s)}).catch(()=>{})}
function loginView(){
 $('#app').innerHTML=`<div class=card><img src=/logo.png style="width:120px;display:block;margin:auto"><h2>${esc(TITLE)}</h2><input id=pw placeholder="اكتب الكود" inputmode=numeric autocomplete=off><button id=go>دخول</button></div>`;
 $('#go').onclick=async()=>{const k=$('#pw').value.trim();if(!k)return toast('اكتب الكود');const r=await api('login',{phone:k,password:k,role:ROLE});if(r&&r.token){localStorage.setItem('tk_'+ROLE,r.token);TOKEN=r.token;location.reload()}}}
function start(main){shell(TITLE);if(!TOKEN)return loginView();main()}
