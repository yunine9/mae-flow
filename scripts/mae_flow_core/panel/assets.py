"""面板页面的样式与脚本(自包含,零外部依赖)。

设计原则(2026-08-09 重设计后):**层级靠留白和字重,不靠边框**。
全页只有一个真正的卡片——「待你裁决」;文档/变更/证据全是细分隔线的行,
低频内容(日志、出口自述)折进 details。框越少,需要人看的东西越突出。

版面优先级仍是契约的一部分,不是审美:
待你裁决 → 文档 → 变更 → 证据 → 建议 → **进度排最后且不给百分比**。
一排绿灯看久了,"绿了"会自动等于"我看过了",驳回权就被显示悄悄拿走了。
"""

CSS = r"""
:root{
  --bg:#fafafa;--card:#fff;--line:#e8e8ec;--ink:#1c1e21;--dim:#5f6672;
  --faint:#9298a3;--ok:#177a48;--ok-bg:#e9f6ef;--warn:#8a5a00;
  --warn-bg:#fdf3dc;--bad:#a52222;--bad-bg:#fdeceb;--run:#1f5fa8;
  --run-bg:#e9f1fb;--accent:#6d55e8;--code-bg:#f1f1f4;
  --mono:ui-monospace,SFMono-Regular,Menlo,Consolas,monospace;
}
@media (prefers-color-scheme:dark){
  :root{
    --bg:#141619;--card:#1d2024;--line:#2b2f34;--ink:#e7eaee;--dim:#9aa3ad;
    --faint:#6d7681;--ok:#4cc98a;--ok-bg:#132f20;--warn:#e0b155;
    --warn-bg:#332708;--bad:#f08585;--bad-bg:#3a1616;--run:#7fb3f0;
    --run-bg:#122436;--accent:#a08bff;--code-bg:#23272c;
  }
}
*{box-sizing:border-box}
body{margin:0;background:var(--bg);color:var(--ink);
  font:14px/1.65 -apple-system,BlinkMacSystemFont,"PingFang SC","Microsoft YaHei",sans-serif}
.wrap{max-width:860px;margin:0 auto;padding:30px 20px 64px}

/* ── 页眉 ── */
header{margin-bottom:30px}
h1{font-size:20px;margin:0 0 5px;font-weight:650;letter-spacing:.2px}
h1 .tick{font-family:var(--mono);color:var(--accent)}
.hd-meta{color:var(--dim);font-size:12px;font-family:var(--mono);
  display:flex;flex-wrap:wrap;gap:4px 14px}
.hd-meta .stamp{margin-left:auto;color:var(--faint)}

/* ── 区块:标题小而轻,内容拍平成行 ── */
section{margin:30px 0}
h2{font-size:11.5px;font-weight:650;letter-spacing:.14em;
  color:var(--faint);margin:0 0 6px}
h2 .n{font-weight:400;letter-spacing:0;font-family:var(--mono);font-size:11px}
.list{border-top:1px solid var(--line)}
.list>*{border-bottom:1px solid var(--line)}

/* ── 待你裁决:全页唯一的卡片 ── */
.decide .card{background:var(--card);border:1px solid var(--line);
  border-radius:10px;padding:15px 18px;
  box-shadow:0 1px 2px rgba(0,0,0,.04)}
.decide.has .card{border-left:3px solid var(--accent)}
.quiet{color:var(--dim);display:flex;align-items:center;gap:9px;font-size:13.5px}
.quiet .dot{width:7px;height:7px;border-radius:50%;background:var(--ok);flex:none}
.ask-title{font-weight:600;margin-bottom:2px}
.ask-sub{color:var(--dim);font-size:12.5px;margin-bottom:11px}
.kv{display:grid;grid-template-columns:max-content 1fr;gap:5px 16px;
  font-size:13px;margin:0 0 12px;padding:11px 14px;background:var(--bg);
  border-radius:7px}
.kv dt{color:var(--dim)}
.kv dd{margin:0;font-family:var(--mono);font-size:12.5px;word-break:break-all}
.hint{font-family:var(--mono);font-size:11.5px;color:var(--dim);
  background:var(--bg);border:1px dashed var(--line);border-radius:7px;
  padding:8px 11px;overflow-x:auto;white-space:pre;user-select:all}
.hint em{font-style:normal;color:var(--faint)}

/* ── 文档行 ── */
.doc{display:grid;grid-template-columns:84px minmax(0,1fr) auto auto;
  gap:12px;align-items:baseline;padding:8px 2px}
.doc .k{color:var(--dim);font-size:12.5px}
.doc .open{background:none;border:0;padding:0;cursor:pointer;text-align:left;
  color:var(--ink);font-family:var(--mono);font-size:12.5px;word-break:break-all}
.doc .open:hover{color:var(--accent)}
.doc .s{color:var(--faint);font-size:11.5px;font-family:var(--mono);
  white-space:nowrap}
.doc .raw{color:var(--faint);font-size:12px;text-decoration:none;white-space:nowrap}
.doc .raw:hover{color:var(--accent)}

/* ── 提交与变更 ── */
.commit{display:flex;gap:10px;align-items:baseline;padding:7px 2px;font-size:13px}
.commit code{font-family:var(--mono);font-size:12px;color:var(--accent)}
.commit .t{margin-left:auto;color:var(--faint);font-size:11.5px;
  font-family:var(--mono);white-space:nowrap}
.gtitle{display:flex;gap:10px;align-items:baseline;margin:16px 0 4px}
.gtitle b{font-size:13px;font-weight:600}
.gtitle span{color:var(--faint);font-size:11.5px;font-family:var(--mono)}
.chg .f{display:grid;grid-template-columns:minmax(0,1fr) auto auto auto;
  gap:12px;align-items:center;padding:7px 2px;border:0;background:none;
  text-align:left;font:inherit;color:var(--ink);width:100%;cursor:pointer}
.chg .f:hover .p,.chg .f:hover .go{color:var(--accent)}
.chg .f .p{font-family:var(--mono);font-size:12.5px;word-break:break-all}
.chg .f .p i{font-style:normal;color:var(--faint)}
.chg .f .n{font-family:var(--mono);font-size:11.5px;white-space:nowrap}
.chg .f .n .a{color:var(--ok)}
.chg .f .n .d{color:var(--bad)}
.chg .f .go{color:var(--faint);font-size:11px;white-space:nowrap}
.bar{display:inline-flex;height:8px;width:40px;border-radius:2px;
  overflow:hidden;background:var(--line)}
.bar i{display:block;height:100%}
.bar .g{background:var(--ok)}
.bar .r{background:var(--bad)}

/* ── 证据 ── */
.row{display:grid;grid-template-columns:104px 100px minmax(0,1fr);
  gap:12px;align-items:baseline;padding:8px 2px}
.row .name{font-weight:600;font-size:13px}
.row .why{color:var(--dim);font-size:12.5px}
.tag{display:inline-block;font-size:10.5px;font-weight:700;padding:2px 8px;
  border-radius:20px;font-family:var(--mono);white-space:nowrap;
  font-style:normal}
.t-ok{color:var(--ok);background:var(--ok-bg)}
.t-deg{color:var(--warn);background:var(--warn-bg)}
.t-bad{color:var(--bad);background:var(--bad-bg)}
.t-run{color:var(--run);background:var(--run-bg)}
.deg-note{margin-top:12px;padding:9px 13px;border-radius:7px;
  background:var(--warn-bg);color:var(--warn);font-size:12.5px;
  border-left:3px solid var(--warn)}

/* ── 建议 ── */
.adv{list-style:none;margin:0;padding:0;border-top:1px solid var(--line)}
.adv li{font-size:13px;padding:7px 2px;border-bottom:1px solid var(--line)}
.adv code{font-family:var(--mono);font-size:11.5px;color:var(--warn)}

/* ── 进度:一行字,不是一面墙 ── */
.prog .line{color:var(--dim);font-size:13px;display:flex;flex-wrap:wrap;
  gap:4px 18px}
.prog b{font-family:var(--mono);font-weight:600;color:var(--ink)}
.prog .cur{font-family:var(--mono);color:var(--accent)}

/* ── 低频内容折叠 ── */
details.note{margin:20px 0;font-size:12.5px;color:var(--dim)}
details.note summary{cursor:pointer;color:var(--faint);font-size:12px;
  user-select:none}
details.note summary:hover{color:var(--accent)}
details.note ul{margin:8px 0 0;padding-left:20px}
details.note li{margin:3px 0}
.paths{list-style:none;margin:8px 0 0;padding:0}
.paths li{font-family:var(--mono);font-size:12px;padding:2px 0}
.paths a{color:var(--dim);text-decoration:none}
.paths a:hover{color:var(--accent)}
footer{margin-top:36px;color:var(--faint);font-size:11.5px;line-height:1.9}
footer code{font-family:var(--mono)}

/* ── 阅读层(文档/diff 弹层) ── */
#viewer{position:fixed;inset:0;background:rgba(0,0,0,.45);z-index:50;
  display:none;padding:24px 16px;overflow:auto}
#viewer.on{display:block}
.vbox{max-width:920px;margin:0 auto;background:var(--card);
  border:1px solid var(--line);border-radius:12px;
  box-shadow:0 16px 48px rgba(0,0,0,.25)}
.vbar{position:sticky;top:0;background:var(--card);
  border-bottom:1px solid var(--line);border-radius:12px 12px 0 0;
  padding:11px 18px;display:flex;flex-wrap:wrap;align-items:center;
  gap:8px 12px;z-index:2}
.vbar .vt{font-weight:600;font-size:14px}
.vbar .vp{font-family:var(--mono);font-size:11px;color:var(--faint);
  word-break:break-all}
.vbar .sp{margin-left:auto;display:flex;gap:8px;align-items:center}
.vbar a,.vbar button{font-size:12px;font-family:inherit;color:var(--dim);
  background:var(--bg);border:1px solid var(--line);border-radius:7px;
  padding:4px 11px;text-decoration:none;cursor:pointer;white-space:nowrap}
.vbar a:hover,.vbar button:hover{color:var(--accent);border-color:var(--accent)}
.vtabs{display:flex;flex-wrap:wrap;gap:5px;padding:10px 18px 0}
.vtabs button{font:inherit;font-size:11.5px;background:var(--bg);
  color:var(--dim);border:1px solid var(--line);border-radius:20px;
  padding:2px 11px;cursor:pointer}
.vtabs button.on{color:var(--accent);border-color:var(--accent);font-weight:600}
.pane{display:none}
.pane.on{display:block}

/* ── 文档正文 ── */
.md{padding:8px 28px 32px;font-size:14.5px;line-height:1.74}
.md h1{font-size:21px;margin:22px 0 10px;padding-bottom:6px;
  border-bottom:1px solid var(--line)}
.md h2{font-size:17.5px;color:var(--ink);margin:26px 0 9px;letter-spacing:0;
  font-weight:650;padding-bottom:5px;border-bottom:1px solid var(--line)}
.md h3{font-size:15px;margin:20px 0 7px}
.md h4,.md h5,.md h6{font-size:13.5px;margin:16px 0 6px;color:var(--dim)}
.md p{margin:9px 0}
.md ul,.md ol{margin:8px 0;padding-left:24px}
.md li{margin:3px 0}
.md code{font-family:var(--mono);font-size:12.5px;background:var(--code-bg);
  padding:1px 5px;border-radius:4px}
.md hr{border:0;border-top:1px solid var(--line);margin:20px 0}
.md a{color:var(--accent)}
.md table{border-collapse:collapse;font-size:13px;min-width:100%}
.md th,.md td{border:1px solid var(--line);padding:6px 10px;text-align:left;
  vertical-align:top}
.md th{background:var(--bg);font-weight:600;white-space:nowrap}
.tbl{overflow-x:auto;margin:12px 0}
.fence{margin:12px 0;border:1px solid var(--line);border-radius:8px;
  overflow:hidden;background:var(--code-bg);position:relative}
.fence .fl{position:absolute;top:0;right:0;font-family:var(--mono);
  font-size:10.5px;color:var(--faint);background:var(--card);padding:1px 8px;
  border-radius:0 8px 0 7px;border-left:1px solid var(--line);
  border-bottom:1px solid var(--line)}
.fence pre{margin:0;padding:12px 14px;overflow-x:auto}
.fence code{font-family:var(--mono);font-size:12.5px;background:none;
  padding:0;white-space:pre;line-height:1.55}
.pfig{margin:16px 0;padding:12px 12px 8px;border:1px solid var(--line);
  border-radius:9px;background:var(--card);overflow-x:auto}
.pfig figcaption{margin-top:8px;font-size:11px;color:var(--faint);
  font-family:var(--mono)}
.pfig.bad{background:var(--warn-bg);border-color:var(--warn)}
.pfig .fn{display:block;font-size:11.5px;color:var(--warn);margin-bottom:6px}
.pfig .praw{margin:0;padding:10px 12px;background:var(--card);
  border-radius:7px;overflow-x:auto}
.pfig .praw code{font-family:var(--mono);font-size:12px;white-space:pre;
  background:none;padding:0}
.pumls{margin-top:6px}
.pumls summary{font-size:11px;color:var(--faint);cursor:pointer;
  font-family:var(--mono)}
.pumls summary:hover{color:var(--accent)}
.pumls pre{margin:6px 0 0;padding:10px 12px;background:var(--code-bg);
  border-radius:7px;overflow-x:auto}
.pumls code{font-family:var(--mono);font-size:12px;white-space:pre;
  background:none;padding:0}

/* ── 双排 diff ── */
.dwrap{padding:14px 18px 28px}
.diff{font-family:var(--mono);font-size:12px;line-height:1.62;
  border:1px solid var(--line);border-radius:8px;overflow:hidden}
.dhead{display:grid;
  grid-template-columns:38px minmax(0,1fr) 38px minmax(0,1fr);
  background:var(--bg);border-bottom:1px solid var(--line);font-size:10.5px;
  color:var(--faint)}
.dhead span{padding:4px 10px}
.dhead span:first-child{grid-column:1/3}
.dhead span:last-child{grid-column:3/5;border-left:1px solid var(--line)}
.dr{display:grid;grid-template-columns:38px minmax(0,1fr) 38px minmax(0,1fr);
  background:var(--card);border-top:1px solid var(--line)}
.dr .ln{color:var(--faint);font-size:10.5px;text-align:right;padding:0 6px;
  background:var(--bg);user-select:none}
.dr .c{padding:0 10px;white-space:pre-wrap;word-break:break-all;
  background:none;min-width:0}
.dr .c:nth-of-type(2){border-left:1px solid var(--line)}
.dr .c.add{background:var(--ok-bg);color:var(--ok)}
.dr .c.del{background:var(--bad-bg);color:var(--bad)}
.dr .c.nil{background:var(--bg)}
.dr .c.span{grid-column:1/-1;padding:2px 10px}
.dr.hk{background:var(--run-bg)}
.dr.hk .c{color:var(--run)}
.dr.cut{background:var(--warn-bg)}
.dr.cut .c{color:var(--warn)}
@media (max-width:760px){
  .dhead{display:none}
  .dr{grid-template-columns:38px minmax(0,1fr)}
  .dr .c:nth-of-type(2){border-left:0}
  .dr .c.nil{display:none}
  .doc{grid-template-columns:72px minmax(0,1fr) auto}
  .doc .raw{display:none}
}
"""

JS = r"""
var V = document.getElementById('viewer');
function show(key){
  var panes = document.querySelectorAll('.pane');
  for (var i = 0; i < panes.length; i++){
    panes[i].classList.toggle('on', panes[i].dataset.key === key);
  }
  var pane = document.querySelector('.pane[data-key="' + key + '"]');
  if (!pane) { return; }
  var group = pane.dataset.group;
  var tabs = document.querySelectorAll('.vtabs button');
  for (var j = 0; j < tabs.length; j++){
    tabs[j].style.display = (tabs[j].dataset.group === group) ? '' : 'none';
    tabs[j].classList.toggle('on', tabs[j].dataset.key === key);
  }
  document.getElementById('vtitle').textContent = pane.dataset.title;
  document.getElementById('vraw').href = pane.dataset.raw;
  document.getElementById('vpath').textContent = pane.dataset.rel;
  V.classList.add('on');
  V.scrollTop = 0;
}
function hide(){ V.classList.remove('on'); }
V.addEventListener('click', function(e){ if (e.target === V) hide(); });
document.addEventListener('keydown', function(e){
  if (e.key === 'Escape') hide();
});
"""
