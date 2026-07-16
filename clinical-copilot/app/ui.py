"""Minimal embedded chat panel (served at /). Week 1 chat + Week 2 document upload."""

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
  header { padding:10px 14px; background:var(--panel); display:flex; gap:10px; align-items:center; border-bottom:1px solid #334155; flex-wrap:wrap; }
  header h1 { font-size:15px; margin:0; flex:0 0 auto; }
  header .badge { background:#0369a1; color:#fff; border-radius:999px; padding:2px 10px; font-size:11px; }
  header .badge.w2 { background:#7c3aed; }
  header input, header select { background:#0f172a; color:#e2e8f0; border:1px solid #334155; border-radius:6px; padding:5px 8px; }
  #toolbar { padding:8px 14px; background:#111827; border-bottom:1px solid #334155; display:flex; gap:8px; align-items:center; flex-wrap:wrap; font-size:12px; color:var(--muted); }
  #toolbar button { background:#334155; color:#e2e8f0; border:0; border-radius:6px; padding:6px 10px; cursor:pointer; }
  #toolbar button:hover { background:#475569; }
  #docs { font-size:11px; color:var(--accent); }
  #preview { display:none; padding:10px 14px; background:#0b1220; border-bottom:1px solid #334155; }
  #preview.open { display:block; }
  .bbox-demo { position:relative; width:100%; max-width:520px; height:160px; background:linear-gradient(180deg,#1e293b,#0f172a); border:1px solid #334155; border-radius:8px; overflow:hidden; }
  .bbox { position:absolute; border:2px solid var(--accent); background:rgba(56,189,248,.15); font-size:10px; color:var(--accent); padding:2px 4px; }
  #log { flex:1; overflow:auto; padding:14px; display:flex; flex-direction:column; gap:10px; }
  .msg { max-width:92%; padding:10px 12px; border-radius:10px; white-space:pre-wrap; }
  .user { align-self:flex-end; background:#0369a1; }
  .bot { align-self:flex-start; background:var(--panel); border:1px solid #334155; }
  .meta { font-size:11px; color:var(--muted); margin-top:6px; }
  .cite { display:inline-block; background:#0b3b52; color:var(--accent); border-radius:4px; padding:1px 6px; margin:2px 3px 0 0; font-size:11px; cursor:pointer; }
  .cite:hover { background:#0e4a66; }
  .route { color:#c4b5fd; }
  .flag-critical { color:var(--crit); font-weight:600; }
  .denied { border-color:var(--crit); }
  footer { padding:10px 14px; background:var(--panel); display:flex; gap:8px; border-top:1px solid #334155; }
  footer input { flex:1; background:#0f172a; color:#e2e8f0; border:1px solid #334155; border-radius:8px; padding:10px; }
  footer button { background:var(--accent); color:#04293b; border:0; border-radius:8px; padding:10px 16px; font-weight:600; cursor:pointer; }
</style>
</head>
<body>
<header>
  <h1>Clinical Co-Pilot</h1>
  <span class="badge">W1</span>
  <span class="badge w2">W2 multimodal</span>
  <label>pid <input id="pid" type="number" value="1" style="width:70px"/></label>
  <label>role
    <select id="role"><option>physician</option><option>nurse</option><option>admin</option></select>
  </label>
  <label>user <input id="user" value="admin" style="width:110px"/></label>
  <label>mode
    <select id="mode"><option value="w2">Week 2 (docs+RAG)</option><option value="w1">Week 1 only</option></select>
  </label>
</header>
<div id="toolbar">
  <label>doc type
    <select id="docType"><option value="lab_pdf">lab_pdf</option><option value="intake_form">intake_form</option></select>
  </label>
  <input id="file" type="file" accept=".pdf,image/*"/>
  <button id="upload">Upload & extract</button>
  <span id="docs">docs: none</span>
  <button id="togglePreview" type="button">Citation preview</button>
</div>
<div id="preview">
  <div class="meta">Click-to-source demo overlay (bbox from extraction citations)</div>
  <div class="bbox-demo" id="bboxDemo">
    <div class="bbox" id="bbox1" style="left:12%;top:45%;width:43%;height:8%;">Creatinine 1.9</div>
    <div class="bbox" id="bbox2" style="left:12%;top:55%;width:38%;height:8%;">HbA1c 8.4%</div>
  </div>
</div>
<div id="log">
  <div class="msg bot">Week 2: upload a lab PDF or intake form, then ask “What changed, what should I pay attention to, and what evidence supports that?”</div>
</div>
<footer>
  <input id="q" placeholder="Ask the Co-Pilot…" autofocus/>
  <button id="send">Send</button>
</footer>
<script>
const log = document.getElementById('log');
const history = [];
const documentIds = [];
function add(cls, html){ const d=document.createElement('div'); d.className='msg '+cls; d.innerHTML=html; log.appendChild(d); log.scrollTop=log.scrollHeight; return d; }
function esc(s){ return (s||'').replace(/[&<>]/g, c=>({'&':'&amp;','<':'&lt;','>':'&gt;'}[c])); }
function refreshDocs(){ document.getElementById('docs').textContent = 'docs: '+(documentIds.length?documentIds.join(', '):'none'); }
document.getElementById('togglePreview').onclick=()=>document.getElementById('preview').classList.toggle('open');
function showBbox(cite){
  document.getElementById('preview').classList.add('open');
  const box=document.getElementById('bbox1');
  if(cite && cite.bbox && cite.bbox.length===4){
    const [x0,y0,x1,y1]=cite.bbox;
    box.style.left=(x0*100)+'%'; box.style.top=(y0*100)+'%';
    box.style.width=((x1-x0)*100)+'%'; box.style.height=((y1-y0)*100)+'%';
    box.textContent=cite.quote_or_value||cite.field_or_chunk_id||'source';
  }
}
document.getElementById('upload').onclick=async()=>{
  const f=document.getElementById('file').files[0];
  if(!f){ add('bot','Choose a file first.'); return; }
  const fd=new FormData();
  fd.append('patient_id', document.getElementById('pid').value);
  fd.append('doc_type', document.getElementById('docType').value);
  fd.append('user_id', document.getElementById('user').value);
  fd.append('role', document.getElementById('role').value);
  fd.append('file', f);
  const el=add('bot','Uploading…');
  try{
    const r=await fetch('/w2/upload',{method:'POST',body:fd});
    const d=await r.json();
    if(d.source_document_id){ documentIds.push(d.source_document_id); refreshDocs(); }
    let html='schema_valid='+d.schema_valid+' · doc='+esc(d.source_document_id||'');
    if(d.extraction && d.extraction.results){
      html+='\\n'+d.extraction.results.map(row=>row.test_name+': '+row.value+' '+(row.unit||'')+' ['+(row.abnormal_flag||'')+']').join('\\n');
      const cites=d.extraction.results.map(r=>r.citation).filter(Boolean);
      if(cites[0]) showBbox(cites[0]);
      html+='<div class="meta">Sources: '+cites.map((c,i)=>'<span class="cite" data-i="'+i+'">'+esc(c.field_or_chunk_id)+'</span>').join('')+'</div>';
      el.innerHTML=html.replace(/\\n/g,'<br/>');
      el.querySelectorAll('.cite').forEach((node,i)=>node.onclick=()=>showBbox(cites[i]));
    } else if(d.extraction){
      html+='\\nchief: '+esc(d.extraction.chief_concern||'');
      el.innerHTML=html.replace(/\\n/g,'<br/>');
    } else {
      el.innerHTML=html+'<br/>'+esc(JSON.stringify(d.errors||[]));
    }
  }catch(e){ el.innerHTML='Upload error: '+esc(''+e); }
};
async function send(){
  const q=document.getElementById('q'); const text=q.value.trim(); if(!text) return;
  q.value=''; add('user', esc(text));
  const mode=document.getElementById('mode').value;
  const body={ patient_id:+document.getElementById('pid').value, message:text,
               user_id:document.getElementById('user').value, role:document.getElementById('role').value, history,
               document_ids: documentIds };
  const el=add('bot','…');
  try{
    const path = mode==='w2' ? '/w2/chat' : '/chat';
    const r=await fetch(path,{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify(body)});
    const d=await r.json();
    let html=esc(d.answer).replace(/\\n/g,'<br/>');
    if(d.citations && d.citations.length){ html+='<div class="meta">Sources: '+d.citations.map(c=>'<span class="cite">'+esc(c.label)+'</span>').join('')+'</div>'; }
    if(d.claims && d.claims.length){
      const cites=[];
      d.claims.forEach(cl=> (cl.citations||[]).forEach(c=>cites.push(c)));
      html+='<div class="meta">W2 citations: '+cites.map((c,i)=>'<span class="cite" data-i="'+i+'">'+esc(c.source_type+':'+c.field_or_chunk_id)+'</span>').join('')+'</div>';
      setTimeout(()=>el.querySelectorAll('.cite').forEach((node,i)=>node.onclick=()=>showBbox(cites[i])),0);
    }
    if(d.supervisor_route){ html+='<div class="meta route">route: '+esc((d.supervisor_route||[]).join(' → '))+'</div>'; }
    const verify = d.verification ? ('verify:'+(d.verification.passed?'pass':'fail')+' · grounded:'+d.verification.grounded_claims) : 'w2';
    html+='<div class="meta">'+(d.authorized?'✓ authorized':'✗ denied')+' · '+verify+' · '+(d.latency_ms||0)+'ms · '+esc(d.correlation_id||'')+(d.degraded?' · degraded':'')+(d.trace_url?' · <a href="'+d.trace_url+'" target="_blank" style="color:var(--accent)">trace ↗</a>':'')+'</div>';
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
