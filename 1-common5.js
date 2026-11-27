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
function timeAgo(ts){const m=Math.floor((Date.now()/1000-ts)/60);return m<1?'دلوقتي':m<60?'من '+m+' دقيقة':'من '+Math.floor(m/60)+' ساعة'}
/* theme */
function applyTheme(){document.documentElement.setAttribute('data-theme','light')}
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
const P='#F55905';
const ICONS={home:'<path d="M3 11l9-8 9 8M5 10v10h14V10"/>',ord:'<rect x="5" y="3" width="14" height="18" rx="2"/><path d="M9 8h6M9 12h6M9 16h4"/>',pin:'<path d="M12 21s7-6 7-11a7 7 0 00-14 0c0 5 7 11 7 11z"/><circle cx="12" cy="10" r="2.5"/>',phone:'<path d="M5 4h4l2 5-2.5 1.5a11 11 0 005 5L15 13l5 2v4a2 2 0 01-2 2A16 16 0 013 6a2 2 0 012-2z"/>',map:'<path d="M9 4l-6 2v14l6-2 6 2 6-2V4l-6 2z"/><path d="M9 4v14M15 6v14"/>',back:'<path d="M9 5l7 7-7 7"/>',note:'<path d="M5 4h14v12l-4 4H5z"/><path d="M9 9h6M9 13h4"/>',wifi:'<path d="M2 9a15 15 0 0120 0M5 13a10 10 0 0114 0M8.5 16.5a5 5 0 017 0"/><path d="M3 3l18 18"/>',search:'<circle cx="11" cy="11" r="7"/><path d="M20 20l-4-4"/>',check:'<path d="M5 12l5 5 9-10"/>'};
function I(n,s,c){s=s||20;return `<svg class=ic width="${s}" height="${s}" viewBox="0 0 24 24" fill="none" stroke="${c||'currentColor'}" stroke-width="1.8" stroke-linecap="round" stroke-linejoin="round">${ICONS[n]||''}</svg>`}
function skel(n){let h='';for(let k=0;k<(n||3);k++)h+='<div class=card style="padding:0"><div class=sk style="aspect-ratio:16/9;border-radius:12px 12px 0 0"></div><div style="padding:12px"><div class=sk style="height:14px;width:55%;margin-bottom:8px"></div><div class=sk style="height:12px;width:35%"></div></div></div>';return h}
const CSS=`@import url('https://fonts.googleapis.com/css2?family=Noto+Sans+Arabic:wght@400;500;600;700&display=swap');
:root{--p:#F55905;--pl:#FEE9DD;--tx:#262626;--mut:#969696;--bd:#E5E5E5;--inb:#CED4DA;--bg2:#F4F4F4;--ok:#1E9E55;--er:#D92D20;--wn:#F55905}
*{-webkit-tap-highlight-color:transparent}
body{font-family:'Noto Sans Arabic','Noto Naskh Arabic',sans-serif;font-size:14px;font-weight:400;margin:0;background:#fff;color:var(--tx);direction:rtl;line-height:1.6}
header{background:#fff;color:var(--tx);border-bottom:1px solid var(--bd);padding:8px 16px;min-height:56px;display:flex;justify-content:space-between;align-items:center;position:sticky;top:0;z-index:5;box-sizing:border-box}
header b{font-size:20px;font-weight:700;color:var(--p)}#app{padding:12px 16px 88px;max-width:640px;margin:auto}
.card{background:#fff;color:var(--tx);border:1px solid var(--bd);border-radius:12px;padding:12px;margin:8px 0 12px;box-shadow:0 1px 3px rgba(0,0,0,.05);overflow:hidden}
.card.empty{text-align:center;color:var(--mut);padding:28px 16px}
input,select,textarea{width:100%;box-sizing:border-box;height:48px;padding:0 12px;margin:4px 0;font-size:14px;font-weight:400;border:1px solid var(--inb);background:#fff;color:var(--tx);border-radius:10px;font-family:inherit;outline:0;transition:border-color .2s}
textarea{height:auto;padding:10px 12px}input::placeholder,textarea::placeholder{color:var(--mut)}input:focus,select:focus,textarea:focus{border-color:var(--p)}
input[type=checkbox],input[type=radio]{width:auto;height:auto}
button{background:var(--p);color:#fff;font-weight:600;border:0;min-height:48px;padding:0 16px;border-radius:10px;font-size:16px;margin:3px;font-family:inherit;transition:background .2s,transform .15s;cursor:pointer}
button:active{background:#D94E04;transform:scale(.98)}button:disabled{background:var(--bd);color:var(--mut);transform:none}
button.alt{background:#fff;color:var(--tx);border:1px solid var(--inb)}button.alt:active{background:var(--bg2)}
button.red{background:var(--er);color:#fff}button.red:active{background:#B42318}
button.sm{min-height:36px;padding:0 12px;font-size:14px;border-radius:8px}
header button{margin:0 2px;min-height:36px;padding:0 12px;font-size:14px;border-radius:18px}
.st{font-weight:700;font-size:12px;color:var(--p);background:var(--pl);border-radius:12px;padding:2px 10px}
#toast{display:none;position:fixed;bottom:84px;left:16px;right:16px;max-width:608px;margin:auto;background:var(--tx);color:#fff;padding:12px;border-radius:10px;text-align:center;z-index:50;font-size:14px}
small,.mut{color:var(--mut);font-size:12px}h2{font-size:20px;font-weight:700;margin:8px 0 12px}h3{font-size:18px;font-weight:600;margin:16px 0 8px}a{color:var(--p)}.row{display:flex;justify-content:space-between;align-items:center;gap:8px}
.tabs{display:flex;gap:8px;overflow-x:auto;padding:4px 0 8px;scrollbar-width:none}.tabs::-webkit-scrollbar{display:none}
.tabs button{flex:0 0 auto;min-height:36px;padding:0 16px;border-radius:18px;font-size:14px;font-weight:500;margin:0;border:0}.tabs button.on{background:var(--pl);color:var(--p)}.tabs button:not(.on){background:var(--bg2);color:var(--tx)}
img.food{width:64px;height:64px;object-fit:cover;border-radius:10px;margin-inline-end:12px}
.chip{display:inline-block;background:var(--pl);color:var(--p);border-radius:12px;padding:2px 10px;margin:2px;font-size:12px;font-weight:700}.chip.off{background:var(--bg2);color:var(--mut)}
.banner{background:var(--pl);color:var(--p);font-weight:600;text-align:center;border-radius:12px;padding:12px;margin:8px 0}
.ov{position:fixed;inset:0;background:rgba(0,0,0,.4);z-index:40;display:flex;align-items:flex-end;justify-content:center;animation:fi .2s}
.ov>.card{width:100%;max-width:640px;margin:0;border:0;border-radius:20px 20px 0 0;padding:20px;box-shadow:none;animation:su .25s}
@keyframes fi{from{opacity:0}to{opacity:1}}@keyframes su{from{transform:translateY(40px)}to{transform:none}}
footer{text-align:center;padding:14px;color:var(--mut);font-size:12px}
.big .card{font-size:18px}.big button{font-size:18px}.new{border:1px solid var(--p)}
.price{font-size:16px;font-weight:700;color:var(--p)}.ic{vertical-align:middle;margin-inline-end:4px}
.hero{aspect-ratio:16/9;position:relative;border-radius:12px;overflow:hidden;margin:-12px -12px 0}.hero svg{display:block;width:100%;height:100%}.hero .g{position:absolute;inset:0;background:linear-gradient(to top,rgba(0,0,0,.65),transparent 60%)}
.hero b{position:absolute;bottom:8px;right:12px;color:#fff;font-size:18px;font-weight:700}.hero .chip{position:absolute;top:8px;right:8px;margin:0}
.sk{background:linear-gradient(90deg,#F0F0F0,#E5E5E5,#F0F0F0);background-size:200% 100%;border-radius:8px;animation:sh 1.2s infinite}@keyframes sh{to{background-position:-200% 0}}
.bnav{position:fixed;bottom:0;left:0;right:0;height:64px;background:#fff;border-top:1px solid var(--bd);display:flex;justify-content:space-around;align-items:stretch;z-index:6;padding-bottom:env(safe-area-inset-bottom);box-sizing:content-box}
.bnav button{flex:1;background:#fff;color:var(--mut);border-radius:0;margin:0;font-size:12px;font-weight:500;min-height:64px;display:flex;flex-direction:column;align-items:center;justify-content:center;gap:2px;border:0}.bnav button.on{color:var(--p)}.bnav .ic{margin:0}
.offl{background:var(--er);color:#fff;text-align:center;padding:6px;font-size:12px;display:none}
@media print{header,button,footer,.noprint,.bnav{display:none!important}body{background:#fff;color:#000}.card{box-shadow:none;border:1px solid #000}}`;
function shell(title,extraHdr){
 document.title=title;document.head.insertAdjacentHTML('beforeend','<meta name=viewport content="width=device-width,initial-scale=1"><style>'+CSS+'</style>');
 document.body.dir='rtl';
 document.body.innerHTML=`<div class=offl id=offl>مفيش اتصال بالإنترنت</div><header><b>${esc(title)}</b><span>${extraHdr||''}${TOKEN?'<button class=alt id=lo>خروج</button>':''}</span></header><div id=app></div><footer id=ft></footer><div id=toast></div>`;
 window.addEventListener('offline',()=>$('#offl').style.display='block');window.addEventListener('online',()=>$('#offl').style.display='none');if(!navigator.onLine)$('#offl').style.display='block';if($('#lo'))$('#lo').onclick=logout;
 fetch('/api/settings').then(r=>r.json()).then(s=>{window.SET=s;const p=s.contact_phone;if(p)$('#ft').innerHTML='تواصل معنا: <a href="tel:'+esc(p)+'">'+esc(p)+'</a>';if(window.onSettings)window.onSettings(s)}).catch(()=>{})}
function loginView(){
 $('#app').innerHTML=`<div class=card><h2 style="text-align:center;color:var(--p)">${esc(TITLE)}</h2><p class=mut style="text-align:center">اكتب الكود اللي واخده للدخول</p><input id=pw placeholder="اكتب الكود" inputmode=numeric autocomplete=off><button id=go>دخول</button></div>`;
 $('#go').onclick=async()=>{const k=$('#pw').value.trim();if(!k)return toast('اكتب الكود');const r=await api('login',{phone:k,password:k,role:ROLE});if(r&&r.token){localStorage.setItem('tk_'+ROLE,r.token);TOKEN=r.token;location.reload()}}}
function start(main){shell(TITLE);if(!TOKEN)return loginView();main()}
