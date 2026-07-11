"""Minimal embedded chat panel (served at /). In production this iframe lives in the
OpenEMR patient chart; here it takes a patient id + role for the demo."""

PANEL_HTML = """<!doctype html>
<html lang="en">
<head>
<meta charset="utf-8"/>
<meta name="viewport" content="width=device-width, initial-scale=1"/>
<title>Clinical Co-Pilot</title>
<style>
  :root { --bg:#0f172a; --panel:#1e293b; --accent:#38bdf8; --ok:#22c55e; --warn:#f59e0b; --crit:#ef4444; --muted:#94a3b8; }
  * { box-sizing:border-box; }
  body { margin:0; font:14px/1.5 -apple-system,Segoe UI,Roboto,sans-serif; background:var(--bg); color:#e2e8f0; height:100vh; display:flex; flex-direction:column; }
  header { padding:10px 14px; background:var(--panel); display:flex; gap:10px; align-items:center; border-bottom:1px solid #334155; }
  header h1 { font-size:15px; margin:0; flex:0 0 auto; }
  header .badge { background:#0369a1; color:#fff; border-radius:999px; padding:2px 10px; font-size:11px; }
  header input, header select { background:#0f172a; color:#e2e8f0; border:1px solid #334155; border-radius:6px; padding:5px 8px; }
  #log { flex:1; overflow:auto; padding:14px; display:flex; flex-direction:column; gap:10px; }
  .msg { max-width:92%; padding:10px 12px; border-radius:10px; white-space:pre-wrap; }
  .user { align-self:flex-end; background:#0369a1; }
  .bot { align-self:flex-start; background:var(--panel); border:1px solid #334155; }
  .meta { font-size:11px; color:var(--muted); margin-top:6px; }
  .cite { display:inline-block; background:#0b3b52; color:var(--accent); border-radius:4px; padding:1px 6px; margin:2px 3px 0 0; font-size:11px; }
  .flag-critical { color:var(--crit); font-weight:600; }
  .flag-warning { color:var(--warn); }
  .denied { border-color:var(--crit); }
  footer { padding:10px 14px; background:var(--panel); display:flex; gap:8px; border-top:1px solid #334155; }
  footer input { flex:1; background:#0f172a; color:#e2e8f0; border:1px solid #334155; border-radius:8px; padding:10px; }
  footer button { background:var(--accent); color:#04293b; border:0; border-radius:8px; padding:10px 16px; font-weight:600; cursor:pointer; }
</style>
</head>
<body>
<header>
  <h1>🩺 Clinical Co-Pilot</h1>
  <span class="badge">demo</span>
  <label>pid <input id="pid" type="number" value="1" style="width:70px"/></label>
  <label>role
    <select id="role"><option>physician</option><option>nurse</option><option>admin</option></select>
  </label>
  <label>user <input id="user" value="admin" style="width:110px"/></label>
</header>
<div id="log">
  <div class="msg bot">Ask about this patient: “what changed since last visit?”, “any drug interactions?”, “trend the labs”, “what did we plan last time?”</div>
</div>
<footer>
  <input id="q" placeholder="Ask the Co-Pilot…" autofocus/>
  <button id="send">Send</button>
</footer>
<script>
const log = document.getElementById('log');
const history = [];
function add(cls, html){ const d=document.createElement('div'); d.className='msg '+cls; d.innerHTML=html; log.appendChild(d); log.scrollTop=log.scrollHeight; return d; }
function esc(s){ return (s||'').replace(/[&<>]/g, c=>({'&':'&amp;','<':'&lt;','>':'&gt;'}[c])); }
async function send(){
  const q=document.getElementById('q'); const text=q.value.trim(); if(!text) return;
  q.value=''; add('user', esc(text));
  const body={ patient_id:+document.getElementById('pid').value, message:text,
               user_id:document.getElementById('user').value, role:document.getElementById('role').value, history };
  const el=add('bot','…');
  try{
    const r=await fetch('/chat',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify(body)});
    const d=await r.json();
    let html=esc(d.answer).replace(/\\n/g,'<br/>');
    if(d.citations && d.citations.length){ html+='<div class="meta">Sources: '+d.citations.map(c=>'<span class="cite">'+esc(c.label)+'</span>').join('')+'</div>'; }
    html+='<div class="meta">'+(d.authorized?'✓ authorized':'✗ denied')+' · verify:'+(d.verification.passed?'pass':'fail')+' · grounded:'+d.verification.grounded_claims+' · '+d.latency_ms+'ms · '+d.correlation_id+(d.degraded?' · degraded':'')+(d.usage&&d.usage.model?' · '+esc(d.usage.model)+' ('+d.usage.prompt+'→'+d.usage.completion+' tok)':'')+(d.trace_url?' · <a href="'+d.trace_url+'" target="_blank" style="color:var(--accent)">trace ↗</a>':'')+'</div>';
    el.classList.toggle('denied', !d.authorized);
    el.innerHTML=html;
    history.push({role:'user',content:text}); history.push({role:'assistant',content:d.answer});
  }catch(e){ el.innerHTML='Error: '+esc(''+e); }
}
document.getElementById('send').onclick=send;
document.getElementById('q').addEventListener('keydown',e=>{ if(e.key==='Enter') send(); });
</script>
</body>
</html>"""
