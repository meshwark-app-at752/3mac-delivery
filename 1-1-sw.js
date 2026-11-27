/* 3mak offline view: cache pages + last loaded data (read only). Writes are blocked by common.js when offline. */
var P='3mak-pages-v1',A='3mak-api-v1';
var R=(new URL(location.href).searchParams.get('r')||'customer').replace(/[^a-z]/g,'');
self.addEventListener('install',function(e){self.skipWaiting();e.waitUntil(caches.open(P).then(function(c){return Promise.all(['/'+R,'/common.js','/logo-'+R+'.png','/icon-'+R+'.png','/logo.png'].map(function(u){return fetch(u).then(function(r){if(r.status===200)return c.put(u,r)}).catch(function(){})}))}))});
self.addEventListener('activate',function(e){e.waitUntil(clients.claim())});
function tmo(p,ms){return new Promise(function(res,rej){var t=setTimeout(function(){rej(new Error('t'))},ms);p.then(function(r){clearTimeout(t);res(r)},function(x){clearTimeout(t);rej(x)})})}
function mark(r){var h=new Headers(r.headers);h.set('X-3mak-Cached','1');return new Response(r.body,{status:r.status,statusText:r.statusText,headers:h})}
self.addEventListener('fetch',function(e){var q=e.request;if(q.method!=='GET')return;var u=new URL(q.url);if(u.origin!==location.origin)return;
 if(u.pathname==='/api/ver'){e.respondWith(fetch(q).catch(function(){return new Response('{"v":"offline"}',{headers:{'Content-Type':'application/json','X-3mak-Cached':'1'}})}));return}
 if(u.pathname==='/api/events'||u.pathname==='/sw.js')return;
 var api=u.pathname.indexOf('/api/')===0,store=api?A:P,key=q;
 if(api){var t=(q.headers.get('X-Token')||'').slice(0,8);key=new Request(u.pathname+u.search+(u.search?'&':'?')+'__u='+t)}
 e.respondWith(caches.open(store).then(function(c){return c.match(key).then(function(hit){
  var net=fetch(q).then(function(r){if(r&&r.status===200){try{c.put(key,r.clone())}catch(x){}}return r});
  return (hit?tmo(net,8000):net).catch(function(){return hit?(api?mark(hit):hit):Response.error()})})}))});
