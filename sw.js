/* AI 讯息台（GitHub Pages 版）：网络优先，在线永远拿最新，离线用缓存 */
var C='ainews-gh-v1';
self.addEventListener('install',function(e){self.skipWaiting();});
self.addEventListener('activate',function(e){e.waitUntil(
  caches.keys().then(function(ks){return Promise.all(ks.filter(function(k){return k!==C;}).map(function(k){return caches.delete(k);}));})
  .then(function(){return self.clients.claim();})
);});
self.addEventListener('fetch',function(e){
  if(e.request.method!=='GET') return;
  e.respondWith(fetch(e.request).then(function(r){
    if(r && r.ok){var c=r.clone();caches.open(C).then(function(x){x.put(e.request,c);}).catch(function(){});}
    return r;
  }).catch(function(){return caches.match(e.request);}));
});
