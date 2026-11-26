const $=s=>document.querySelector(s);
let TOKEN=localStorage.getItem('tk_'+ROLE)||'';
async function api(p,d){const o={headers:{'X-Token':TOKEN,'Content-Type':'application/json'}};if(d!==undefined){o.method='POST';o.body=JSON.stringify(d)}
 try{const r=await fetch('/api/'+p,o);const j=await r.json();if(r.status==401&&TOKEN){logout();return null}if(!r.ok){alert(j.error||'خطأ');return null}return j}catch(e){toast('مفيش اتصال بالإنترنت');return null}}
function toast(t){let e=$('#toast');e.textContent=t;e.style.display='block';setTimeout(()=>e.style.display='none',2500)}
function logout(){localStorage.removeItem('tk_'+ROLE);TOKEN='';location.reload()}
function esc(s){return String(s).replace(/[&<>"]/g,c=>({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;'}[c]))}
function loginView(canReg){
 $('#app').innerHTML=`<div class=card><h2>${TITLE}</h2><input id=pw placeholder="الكود" inputmode=numeric><button id=go>دخول</button></div>`;
 $('#go').onclick=async()=>{const k=$('#pw').value.trim();const r=await api('login',{phone:k,password:k,role:ROLE});if(r&&r.token){localStorage.setItem('tk_'+ROLE,r.token);TOKEN=r.token;location.reload()}}
}
function start(canReg,main){if(!TOKEN)return loginView(canReg);main()}
const CSS=`<style>body{font-family:sans-serif;margin:0;background:#111;color:#eee;direction:rtl}header{background:#000;color:#d4af37;border-bottom:2px solid #d4af37;padding:12px;display:flex;justify-content:space-between;align-items:center}#app{padding:10px;max-width:600px;margin:auto}.card{background:#1d1d1d;color:#eee;border-radius:10px;padding:12px;margin:8px 0;box-shadow:0 1px 3px #0002}input,select{width:100%;box-sizing:border-box;padding:10px;margin:5px 0;font-size:16px;border:1px solid #d4af37;background:#000;color:#fff;border-radius:6px}button{background:#d4af37;color:#000;font-weight:bold;border:0;padding:10px 14px;border-radius:6px;font-size:16px;margin:3px}button.alt{background:#444;color:#d4af37}button.red{background:#c62828;color:#fff}.st{font-weight:bold;color:#d4af37}#toast{display:none;position:fixed;bottom:20px;left:10%;right:10%;background:#333;color:#fff;padding:10px;border-radius:8px;text-align:center}small{color:#aaa}h2,h3{color:#d4af37}a{color:#d4af37}.row{display:flex;justify-content:space-between;align-items:center}</style>`;
