/* v1.5 UI: 侧栏导航滚动高亮(scrollspy) —— 纯增量逻辑, 不动旧功能 */
(function(){
  var links = Array.prototype.slice.call(document.querySelectorAll('.nav a[href^="#"]'));
  if(!links.length || !('IntersectionObserver' in window)){ return; }
  var byId = {};
  links.forEach(function(a){ byId[a.getAttribute('href').slice(1)] = a; });
  function activate(id){
    if(!byId[id]){ return; }
    links.forEach(function(a){ a.classList.remove('on'); });
    byId[id].classList.add('on');
  }
  var io = new IntersectionObserver(function(es){
    es.forEach(function(en){ if(en.isIntersecting){ activate(en.target.id); } });
  }, {rootMargin:'-12% 0px -66% 0px'});
  Object.keys(byId).forEach(function(id){
    var el = document.getElementById(id);
    if(el){ io.observe(el); } else { byId[id].style.display = 'none'; }
  });
})();
/* ===== v1.6 学习洞察面板: /api/analytics 异步渲染(不阻塞首屏) ===== */
(function(){
  var wrap = document.getElementById('inswrap');
  var TAGROWS = null;              // 最近一次稳固度行(模块A 高亮 / 模块D 钻取 共享)
  var toastEl = document.getElementById('lhtoast'), toastTimer = null;
  function toast(msg){             // 本 IIFE 私有 toast(与交互 IIFE 各持一份, 操作同一 DOM, 零全局污染)
    if(!toastEl){ return; }
    toastEl.textContent = msg;
    toastEl.classList.add('on');
    clearTimeout(toastTimer);
    toastTimer = setTimeout(function(){ toastEl.classList.remove('on'); }, 3000);
  }
  if(!wrap){ return; }
  function loadAnalytics(){
  fetch('/api/analytics').then(function(r){ return r.json(); }).then(function(d){
    if(!d.ok || !d.analytics){ wrap.innerHTML = '<p class="dim">洞察暂不可用</p>'; return; }
    var a = d.analytics, html = '';
    var ZCOL = {'轻松':'var(--color-state-success)','适中':'var(--color-accent)','偏重':'var(--color-state-warning)','过载':'var(--color-state-error)'};
    var cli = a.cli || {}, col = ZCOL[cli.zone] || 'var(--color-accent)';
    html += '<div class="inscell">'
      + '<div class="inshead">🧠 认知负荷指数<span class="insbig" style="color:' + col + '">' + (cli.index != null ? cli.index : '-') + '</span><span class="tag">' + (cli.zone || '-') + '</span></div>'
      + '<div class="bar"><div class="fill" style="width:' + (cli.index || 0) + '%;background:' + col + '"></div></div>'
      + '<p class="dim mt6">' + (cli.advice || '') + '</p></div>';
    /* v1.8 A3 微指标: 本周时间预算(预估 vs 实际) */
    var du = a.duration || {};
    html += '<div class="inscell"><div class="inshead">⏱ 本周时间预算</div>';
    if(!du.est_week_min){
      html += '<p class="dim">本周还没有带耗时预估的任务——在 daily 任务里写「≤45min」这类标注即可自动识别</p>';
    } else {
      html += '<div class="big" style="font-size:26px">' + du.est_week_min + '<small> 分钟(预估)</small></div>';
      if(du.status === 'ready'){
        html += '<p class="dim mt6">实际累计 <b>' + du.actual_week_min + '</b> 分钟(' + du.actual_samples + ' 次采样)</p>';
      } else {
        html += '<p class="dim mt6">' + (du.hint || '') + '</p>';
      }
      html += '<div class="mt10"><button class="btn btn-mini btn-ghost" id="btn-slot" style="margin-top:0">\uD83D\uDD2C 下一个任务排哪天?</button></div>';
    }
    html += '</div>';
    var stb = a.stability || {}, rows = stb.rows || [];
    html += '<div class="inscell"><div class="inshead">💎 知识稳固度<span class="insbig">' + (stb.overall != null ? stb.overall : '-') + '</span><span class="dim">按标签聚合保持率</span></div>';
    var i2;
    if(stb.status === 'empty' || !rows.length){
      html += '<p class="dim">' + (stb.advice || '暂无知识点档案——保存笔记后自动生成') + '</p>';
    } else {
      TAGROWS = rows;
      for(i2 = 0; i2 < rows.length && i2 < 5; i2++){
        var rr = rows[i2];
        var rc = rr.avg_retention >= 70 ? 'var(--color-state-success)' : (rr.avg_retention >= 40 ? 'var(--color-state-warning)' : 'var(--color-state-error)');
        html += '<div class="decay krow" data-tag="' + rr.tag + '" role="button" tabindex="0" title="点击展开概念明细">'
          + '<span class="karrow">▸</span><span class="dname" title="' + rr.tag + '">#' + rr.tag + '</span>'
          + '<div class="dbar"><div class="dfill" style="width:' + rr.avg_retention + '%;background:' + rc + '"></div></div>'
          + '<span class="dpct">' + rr.avg_retention + '%</span>'
          + '<div class="ksub"></div></div>';
      }
      var wt = stb.weakest_tag || '';
      html += '<p class="dim mt6">💡 最薄弱领域 #' + (wt || '-') + ' —— <a class="inslink" href="#pnl-review?tag=' + encodeURIComponent(wt) + '">去复习中心处理 →</a></p>';
    }
    html += '</div>';
    var fo = a.focus || {};
    html += '<div class="inscell"><div class="inshead">⏰ 最佳专注时段</div>';
    if(fo.status !== 'ready'){
      html += '<p class="dim">数据采集中：已记录 <b>' + (fo.samples || 0) + '</b> 次完成时刻，积累到 <b>' + (fo.need || 20) + '</b> 次后给出排期建议。<br>' + (fo.hint || '') + '</p>';
    } else {
      var j2, bs = fo.buckets || [], mx = 1;
      for(j2 = 0; j2 < bs.length; j2++){ mx = Math.max(mx, bs[j2].count); }
      for(j2 = 0; j2 < bs.length; j2++){
        var bb = bs[j2], hot = bb.label === fo.best_window;
        html += '<div class="decay"><span class="dname">' + bb.label + '</span>'
          + '<div class="dbar"><div class="dfill" style="width:' + Math.round(bb.count * 100 / mx) + '%;background:' + (hot ? 'var(--color-accent)' : 'var(--color-border-strong)') + '"></div></div>'
          + '<span class="dpct">' + bb.count + '</span></div>';
      }
      html += '<p class="dim mt6">💡 ' + (fo.advice || '') + '</p>';
    }
    html += '</div>';
    wrap.innerHTML = '<div class="insgrid">' + html + '</div>';
    bindKrows();
    try{ document.dispatchEvent(new CustomEvent('ins:cli', {detail: (a.cli || {}).index})); }catch(e){}
  }).catch(function(){
    wrap.innerHTML = '<p class="dim">静态快照不含洞察数据——双击「打开学习仪表盘.bat」进入交互模式查看</p>';
  });
  }
  document.addEventListener('ins:refresh', function(){ loadAnalytics(); });
  loadAnalytics();

  /* ---------- 模块D: 标签行点击 -> 子级概念懒渲染(max-height 过渡, 无库动画) ---------- */
  function bindKrows(){
    if(wrap.dataset.kbound){ return; }            // 只绑一次, 防 insight 重渲染时叠加监听
    wrap.dataset.kbound = '1';
    wrap.addEventListener('click', function(ev){
      var row = ev.target.closest('.krow');
      if(!row){ return; }
      var sub = row.querySelector('.ksub');
      if(!sub){ return; }
      if(!sub.dataset.built){                     // 懒渲染: 第一次展开才构建子 DOM
        var tag = row.getAttribute('data-tag'), rr2 = null, i3;
        for(i3 = 0; i3 < (TAGROWS || []).length; i3++){ if(TAGROWS[i3].tag === tag){ rr2 = TAGROWS[i3]; } }
        ((rr2 && rr2.concepts) || []).forEach(function(c){
          var kc = c.retention >= 70 ? 'var(--color-state-success)' : (c.retention >= 40 ? 'var(--color-state-warning)' : 'var(--color-state-error)');
          var line = document.createElement('div');
          line.className = 'kline';
          var qs = (c.quality != null) ? ' <span title="最近复习质量(0-5)" style="color:var(--color-text-muted)">q' + c.quality + '</span>' : '';
          var warn = c.flagged ? ' <span title="复习了但质量不高,加权稳固度已下调">⚠️</span>' : '';
          line.innerHTML = '<span class="kname" title="' + c.name + '">' + c.name + warn + '</span>'
            + '<div class="kbar"><div style="height:100%;width:' + c.retention + '%;background:' + kc + ';border-radius:999px"></div></div>'
            + '<span style="flex:0 0 52px;font-size:11px;color:var(--color-text-muted)">' + c.retention + '%' + qs + '</span>';
          sub.appendChild(line);
        });
        sub.dataset.built = '1';
      }
      var open = sub.classList.toggle('open');
      row.classList.toggle('open', open);
      var ar = row.querySelector('.karrow');
      if(ar){ ar.textContent = open ? '▾' : '▸'; }
    });
  }

  /* ---------- 模块A: hash 联动 -> 复习中心定位 + 标签卡片高亮 ---------- */
  function highlightTag(tag){
    var names = {};
    (TAGROWS || []).forEach(function(r){ if(r.tag === tag){ (r.concepts || []).forEach(function(c){ names[c.name] = 1; }); } });
    var hit = 0;
    document.querySelectorAll('#pnl-review .rec').forEach(function(card){
      var el = card.querySelector('[data-c]');
      var name = el ? el.getAttribute('data-c') : '';
      var match = !!names[name];
      card.classList.toggle('hl', match);
      if(match){ hit++; }
    });
    setTimeout(function(){
      document.querySelectorAll('#pnl-review .rec.hl').forEach(function(x){ x.classList.remove('hl'); });
    }, 4000);
    toast('#' + tag + (hit ? (' 已高亮 ' + hit + ' 张到期卡片') : ' 今日无到期卡片——建议明天优先复习'));
  }
  function applyHash(){
    var m = decodeURIComponent(location.hash || '').match(/^#pnl-review\?tag=(.+)$/);
    if(!m){ return; }
    var panel = document.getElementById('pnl-review');
    if(panel){ panel.scrollIntoView({behavior:'smooth', block:'start'}); }
    var waited = 0;
    var tick = setInterval(function(){       // TAGROWS 可能晚于 hash 到达, 就绪即高亮(最多等4s)
      waited += 200;
      if((TAGROWS && TAGROWS.length) || waited > 4000){ clearInterval(tick); highlightTag(m[1]); }
    }, 200);
  }
  window.addEventListener('hashchange', applyHash);
})();

/* ===== v1.7 交互层 IIFE: toast / done_at 补录 / 减负模式 (全部私有, 零全局污染) ===== */
(function(){
  var toastEl = document.getElementById('lhtoast'), toastTimer = null;
  function toast(msg){
    if(!toastEl){ return; }
    toastEl.textContent = msg;
    toastEl.classList.add('on');
    clearTimeout(toastTimer);
    toastTimer = setTimeout(function(){ toastEl.classList.remove('on'); }, 3000);
  }
  function post(url, body){
    return fetch(url, {method:'POST', headers:{'Content-Type':'application/json'}, body: JSON.stringify(body || {})}).then(function(r){ return r.json(); });
  }
  /* ---------- 模块B: 时间选择浮层 ---------- */
  var pickIds = [];
  var dtWrap = document.getElementById('dtpick'), dtIn = document.getElementById('dt-input');
  function localNow(){
    var d = new Date(), p2 = function(n){ return (n < 10 ? '0' : '') + n; };
    return d.getFullYear() + '-' + p2(d.getMonth() + 1) + '-' + p2(d.getDate()) + 'T' + p2(d.getHours()) + ':' + p2(d.getMinutes());
  }
  function dtOpen(ids, prefill){
    pickIds = ids || [];
    if(dtIn){ dtIn.value = prefill || localNow(); }
    var dta = document.getElementById('dt-actual');
    if(dta){ dta.value = ''; }                     // 每次打开重置实际耗时(非必填)
    var desc = document.getElementById('dt-desc');
    if(desc){ desc.textContent = '将为 ' + pickIds.length + ' 条已完成任务写入完成时刻(done_at)'; }
    if(dtWrap){ dtWrap.style.display = 'flex'; }
  }
  function dtClose(){ if(dtWrap){ dtWrap.style.display = 'none'; } }
  var applyBtn = document.getElementById('dt-apply');
  if(applyBtn){
    applyBtn.addEventListener('click', function(){
      var v = (dtIn && dtIn.value) || '';
      if(!v){ toast('请先选择时刻'); return; }
      var dta = document.getElementById('dt-actual');
      var am = (dta && dta.value) ? parseInt(dta.value, 10) : null;   // 非必填: 空则不带该字段
      if(am !== null && (isNaN(am) || am <= 0)){ am = null; }
      applyBtn.disabled = true;
      post('/api/tasks/patch-done-at', {ids: pickIds, done_at: v, actual_minutes: am}).then(function(d){
        applyBtn.disabled = false;
        if(d.ok){
          toast('已为 ' + d.patched.length + ' 条任务补录时刻' + (d.skipped.length ? '(跳过未完成 ' + d.skipped.length + ' 条)' : ''));
          document.querySelectorAll('#pnl-tasks label.task').forEach(function(lab){
            var cb = lab.querySelector('input[type=checkbox]');
            if(cb && d.patched.indexOf(cb.getAttribute('data-id')) >= 0 && !lab.querySelector('.dttag')){
              var sp = document.createElement('span');
              sp.className = 'tag dttag';
              sp.textContent = '🕐 ' + v.replace('T', ' ');
              lab.querySelector('.txt').appendChild(sp);
            }
          });
          dtClose();
          try{ document.dispatchEvent(new Event('ins:refresh')); }catch(e){}
        } else { toast(d.err || '补录失败'); }
      }).catch(function(){ applyBtn.disabled = false; toast('服务未运行? 请用 bat 启动交互模式'); });
    });
  }
  var cancelBtn = document.getElementById('dt-cancel');
  if(cancelBtn){ cancelBtn.addEventListener('click', dtClose); }
  if(dtWrap){ dtWrap.addEventListener('click', function(ev){ if(ev.target === dtWrap){ dtClose(); } }); }
  /* 场景② 批量补录入口: 取最新日期桶(≈今日)中已完成且缺时刻的任务
     为什么只扫今日桶: 历史多天缺时刻时统一标同一时刻会污染分布, 留给单条详情按需修正 */
  var bf = document.getElementById('btn-backfill');
  if(bf){
    bf.addEventListener('click', function(){
      bf.disabled = true;
      fetch('/api/state').then(function(r){ return r.json(); }).then(function(st){
        bf.disabled = false;
        var keys = Object.keys(st.days || {}).sort();
        var last = keys[keys.length - 1];
        var ids = ((last && st.days[last]) || []).filter(function(t){ return t.done && !t.done_at; }).map(function(t){ return t.id; });
        if(!ids.length){ toast('所有已完成任务都有时刻记录啦'); return; }
        dtOpen(ids);
      }).catch(function(){ bf.disabled = false; toast('读取任务状态失败'); });
    });
  }
  /* 场景① 夜间补勾主动询问: 运行时包装全局 tg(不改源码), ≥20点勾选时弹一次选择器 */
  if(typeof window.tg === 'function'){
    var _origTg = window.tg;
    window.tg = function(id, el){
      _origTg(id, el);
      if(el && el.checked && new Date().getHours() >= 20 && !pickIds.length){
        dtOpen([id], localNow());
      }
    };
  }
  /* ---------- 模块C: CLI 减负模式 ---------- */
  var redBox = document.getElementById('reducemode'),
      redOn = document.getElementById('red-on'),
      redBadge = document.getElementById('redbadge'),
      lastCli = null;
  function applyFatigue(active, cliIndex){
    document.body.classList.toggle('fatigue', !!active);     // CSS 折叠 P3(统计口径不变)
    if(redBadge){ redBadge.style.display = active ? '' : 'none'; }
    if(redBox){ redBox.style.display = (!active && typeof cliIndex === 'number' && cliIndex > 80) ? 'flex' : 'none'; }
  }
  function syncFatigue(){
    fetch('/api/fatigue').then(function(r){ return r.json(); }).then(function(d){
      applyFatigue(!!d.active, lastCli);
    }).catch(function(){});
  }
  document.addEventListener('ins:cli', function(ev){ lastCli = ev.detail; syncFatigue(); });
  syncFatigue();
  if(redOn){
    redOn.addEventListener('click', function(){
      redOn.disabled = true;
      post('/api/fatigue', {active: true}).then(function(d){
        if(!d.ok){ redOn.disabled = false; toast('开启失败'); return; }
        applyFatigue(true, lastCli);
        toast('减负模式已开启:P3 低优任务已折叠');
        return post('/api/review/snooze-all', {days: 3}).then(function(d2){
          redOn.disabled = false;
          if(d2.ok && d2.snoozed.length){ toast('已把 ' + d2.snoozed.length + ' 张到期复习推迟 3 天'); }
          else { toast('今天没有到期的复习卡片,无需推迟'); }
          try{ document.dispatchEvent(new Event('ins:refresh')); }catch(e){}
        });
      }).catch(function(){ redOn.disabled = false; toast('服务未运行? 请用 bat 启动'); });
    });
  }
  if(redBadge){
    redBadge.addEventListener('click', function(){
      post('/api/fatigue', {active: false}).then(function(){
        applyFatigue(false, lastCli);
        toast('减负模式已关闭(已推迟的复习不会自动恢复,可手动打卡)');
        try{ document.dispatchEvent(new Event('ins:refresh')); }catch(e){}
      });
    });
  }
})();

/* 勾选: 写回 + 划线动画 + 环形/完成度同步 */
function tg(id, el){
  var lab = el.closest('label.task');
  fetch('/api/toggle', {method:'POST', headers:{'Content-Type':'application/json'}, body: JSON.stringify({id:id, done:el.checked})})
    .then(function(r){return r.json();})
    .then(function(d){
      if(d.ok){
        if(lab){ lab.classList.toggle('completed', el.checked); }   // 划线+透明+右移动画
        upd(d.today_done, d.today_total);                            // 进度条+SVG环同步
      } else { el.checked = !el.checked; lhToast('保存失败'); }
    })
    .catch(function(){ el.checked = !el.checked; lhToast('服务未运行? 请用 bat 启动交互模式'); });
}
/* 完成度文本 + SVG 环 dashoffset 同步(UI-005: 大百分比/进度条已并入总览环) */
var CIRC = 2 * Math.PI * 52;
function upd(n, t){
  document.getElementById('taskcnt').textContent = n + ' / ' + t + ' 条';
  var fg = document.getElementById('ringfg');
  if(fg){ fg.setAttribute('stroke-dashoffset', (CIRC * (1 - (t ? n/t : 0))).toFixed(1)); }
  var rc = document.getElementById('ringcnt');
  if(rc){ rc.textContent = n + '/' + t; }
}
/* 收尾: 二次确认(产品内 modal, 非原生 confirm) → 顺延+规划, 弹窗带明日建议与疲劳提示 */
function rollover(){
  var undone = document.querySelectorAll('#pnl-tasks label.task:not(.completed)').length;
  var mb = document.getElementById('mbody');
  document.getElementById('mtitle').textContent = '🔄 确认收尾';
  mb.innerHTML = '<p>当前还有 <b>' + undone + '</b> 条未完成任务。</p>'
    + '<p class="dim">确认收尾后，这些任务将顺延到明日，并生成明日计划。</p>'
    + '<div><button class="btn btn-ghost" onclick="modalCancel()">取消</button> '
    + '<button class="btn" onclick="rolloverGo()">确认收尾</button></div>';
  document.getElementById('modal').style.display = 'flex';
  modalCopy(false);
  var cancel = mb.querySelector('.btn-ghost');
  if(cancel){ cancel.focus(); }
}
function modalCancel(){
  document.getElementById('modal').style.display = 'none';
}
/* 顶层共享轻提示(UI-010): 复用 #lhtoast DOM; 顶层函数(备份/导入/失败反馈)统一走此通道 */
function lhToast(msg){
  var t = document.getElementById('lhtoast');
  if(!t){ return; }
  t.textContent = msg;
  t.classList.add('on');
  setTimeout(function(){ t.classList.remove('on'); }, 3000);
}
/* ===== Phase3-T01: 可撤销操作的「撤销」提示(2026-08-31) =====
   破坏性/可逆操作(删除/顺延/改优先级/批量勾选/快捕)成功后, 显示内嵌
   「撤销」按钮的 toast, 点击走已有撤销栈(undo 后端)。按钮回调由调用方
   注入(undo 触发), 本函数只负责展示与自动关闭(30s, 长于普通 toast 给足
   点击窗口)。仅对「确认可撤销」的操作启用——见 batchDo/quickbar 接线。 */
function lhToastUndo(msg, undoLabel, onUndo){
  var t = document.getElementById('lhtoast');
  if(!t){ return; }
  t.innerHTML = '<span class="tmsg">' + String(msg) + '</span>'
    + '<button class="tundo" type="button" aria-label="' + String(undoLabel || '撤销') + '">'
    + String(undoLabel || '撤销') + '</button>';
  t.setAttribute('aria-live', 'polite');             // 读屏播报可撤销
  t.classList.add('on');
  t.classList.add('has-undo');                       // 容器可点击/可聚焦(覆盖父级 pointer-events:none)
  var timer = null, done = false;
  function clear(){
    t.removeAttribute('aria-live');
    t.classList.remove('on');
    t.classList.remove('has-undo');
    if(timer){ clearTimeout(timer); timer = null; }
    t.innerHTML = '';
  }
  var undoBtn = t.querySelector('.tundo');
  if(undoBtn){
    undoBtn.addEventListener('click', function(){ if(done){ return; } done = true; clear(); if(onUndo){ onUndo(); } });
    /* 聚焦撤销按钮: 操作后 reload 焦点在 body, 聚焦此需决策的通知按钮符合
       alert 语义; 30s 窗口内可 Tab/回车触发, 也覆盖鼠标。 */
    try{ undoBtn.focus(); }catch(e){}
  }
  timer = setTimeout(clear, 30000);                 // 30s 撤销窗口; 到点自动关闭
}
/* Phase3-T01: reload 后检查 sessionStorage 里的撤销提示, 弹出「撤销」toast。
   撤销按钮走 window.lhUndo(撤销栈)。30s 后清除(撤销窗口过期)。 */
function checkUndoOffer(){
  var raw = null;
  try{ raw = sessionStorage.getItem('lh_undo'); }catch(e){}
  if(!raw){ return; }
  try{ sessionStorage.removeItem('lh_undo'); }catch(e){}
  var info = null;
  try{ info = JSON.parse(raw); }catch(e){}
  var msg = (info && info.label) ? info.label : '操作完成';
  lhToastUndo(msg, '撤销', function(){ if(window.lhUndo){ window.lhUndo(); } });
}
if(document.readyState === 'loading'){
  document.addEventListener('DOMContentLoaded', checkUndoOffer);
} else {
  checkUndoOffer();
}
/* modal chrome(复制 Markdown)按上下文显隐: 仅周报/报告预览可复制 */
function modalCopy(show){
  var b = document.getElementById('mcopy');
  if(b){ b.style.display = show ? '' : 'none'; }
}
function rolloverGo(){
  fetch('/api/rollover', {method:'POST'})
    .then(function(r){return r.json();})
    .then(function(d){
      var m = d.desc || (d.ok ? '完成' : '失败');
      if(d.tomorrow){ m = m + ' | 明日建议 ' + d.tomorrow.predicted + ' 条'; }
      if(d.fatigue && d.fatigue.active){ m = m + ' | 疲劳模式中'; }
      document.getElementById('mtitle').textContent = '🔄 收尾结果';
      document.getElementById('mbody').innerHTML = '<p>' + m + '</p>'
        + '<div><button class="btn" onclick="location.reload()">完成并刷新</button></div>';
    });
}
/* 右键优先级菜单: 就地生效, 不刷新页面 */
var curId = null;
function ctxmenu(ev, id, pri){
  ev.preventDefault(); ev.stopPropagation();
  curId = id;
  var m = document.getElementById('ctxmenu');
  m.style.display = 'block';
  m.style.left = Math.min(ev.pageX, window.innerWidth - 160) + 'px';
  m.style.top  = Math.min(ev.pageY, window.innerHeight - 140) + 'px';
  m.dataset.pri = pri;
}
function hidectx(){ document.getElementById('ctxmenu').style.display = 'none'; }
document.addEventListener('click', hidectx);
document.addEventListener('scroll', hidectx, true);
function setpri(p){
  if(!curId){ return; }
  fetch('/api/priority', {method:'POST', headers:{'Content-Type':'application/json'}, body: JSON.stringify({id:curId, priority:p})})
    .then(function(r){return r.json();})
    .then(function(d){
      if(d.ok){
        var lab = document.querySelector('label.task[data-id="' + CSS.escape(curId) + '"]');
        if(lab){
          var s = lab.querySelector('.pptag');                       // 本地更新标签, 免刷新
          if(s){ s.textContent = 'P' + d.priority; s.style.display = (d.priority === 2) ? 'none' : 'inline-block'; }
          lab.dataset.pri = d.priority;
          lab.style.background = '#3b3b52';  // PENDING: [UI-Refactor-Phase5a] 临时闪反馈底色, 非语义 token, 保留
          setTimeout(function(){ lab.style.background = ''; }, 350); // 轻微反馈闪烁
        }
      }
      hidectx();
    });
}
/* ===== v0.6 热力图: fetch 数据渲染 SVG 方块矩阵(GitHub 风) ===== */
function loadHeatmap(){
  fetch('/api/heatmap').then(function(r){return r.json();}).then(function(d){
    var days = d.days || [];
    if(!days.length){ return; }
    var COLORS = ['#1F2022','rgba(94,106,210,0.2)','rgba(94,106,210,0.4)','rgba(94,106,210,0.65)','#5E6AD2'];
    var x = 0, y = new Date(days[0].date + 'T00:00:00').getDay();       // 首日星期对齐
    var cells = '';
    for(var i=0;i<days.length;i++){
      var dd = days[i];
      cells += '<rect x="'+(x*13)+'" y="'+(y*13)+'" width="11" height="11" rx="3" fill="'+COLORS[dd.level]+'">'
             + '<title>'+dd.date+' · 任务 '+dd.tasks+' 条 · 笔记 '+dd.words+' 字</title></rect>';
      y++; if(y===7){ y=0; x++; }
    }
    document.getElementById('hm').innerHTML =
      '<svg width="'+((x+1)*13)+'" height="'+(7*13)+'">'+cells+'</svg>';
  }).catch(function(){ document.getElementById('hm').textContent = '热力图加载失败'; });
}
loadHeatmap();
/* 周日呼吸灯提醒 */
(function(){ if(new Date().getDay() === 6){ var b = document.getElementById('btnweek'); if(b){ b.classList.add('glow'); } } })();
/* ===== v0.6 AI 周报: 模态框 + 一键复制 ===== */
function mdmini(src){
  var out = [], lines = src.split('\n'), inList = false;
  function cl(){ if(inList){ out.push('</ul>'); inList = false; } }
  for(var i=0;i<lines.length;i++){
    var ln = esc(lines[i]), m;
    if(/^\s*$/.test(ln)){ cl(); continue; }
    if(m = ln.match(/^###\s+(.*)/)){ cl(); out.push('<h3>'+m[1]+'</h3>'); continue; }
    if(m = ln.match(/^##\s+(.*)/)){ cl(); out.push('<h2 style="font-size:16px;color:var(--color-accent)">'+m[1]+'</h2>'); continue; }
    if(m = ln.match(/^#\s+(.*)/)){ cl(); out.push('<h2 style="font-size:19px">'+m[1]+'</h2>'); continue; }
    if(/^\s*-\s+/.test(ln)){ if(!inList){ out.push('<ul>'); inList = true; } out.push('<li>'+ln.replace(/^\s*-\s+/,'')+'</li>'); continue; }
    cl(); out.push('<p>'+ln+'</p>');
  }
  cl();
  return out.join('');
}
function weeklyReport(){
  var mb = document.getElementById('mbody');
  document.getElementById('mtitle').textContent = '🔄 周报复盘';
  mb.textContent = '正在聚合本周数据并生成周报…';
  document.getElementById('modal').style.display = 'flex';
  modalCopy(true);
  fetch('/api/weekly_report', {method:'POST'})
    .then(function(r){return r.json();})
    .then(function(d){
      if(!d.ok){ mb.textContent = '生成失败'; return; }
      window.__report_md = d.markdown;
      document.getElementById('mtitle').textContent = '周报复盘（' + (d.source === 'deepseek' ? 'DeepSeek 生成' : '本地数据模板') + '）';
      mb.innerHTML = mdmini(d.markdown);
    })
    .catch(function(e){ mb.textContent = '失败: ' + e; });
}
function copyReport(){
  var t = window.__report_md || '';
  if(navigator.clipboard && navigator.clipboard.writeText){ navigator.clipboard.writeText(t); }
  else {
    var ta = document.createElement('textarea'); ta.value = t; document.body.appendChild(ta);
    ta.select(); document.execCommand('copy'); ta.remove();
  }
}
/* ===== v0.8 知识图谱: 简易力导向(斥力+弹簧引力+阻尼, 固定100次迭代) ===== */
var KG_W = 760, KG_H = 420;
var GRAPH_EMPTY = window.LH_CONFIG.graphEmpty;
// DATA-VIS-COLORS: 图谱状态配色为数据可视化语义(状态→色), 强制 token 化会破坏映射, 整段保留
var KG_COLORS = { '新学': '#5E6AD2', '需复习': '#F2994A', '已巩固': '#4CB782', '巩固中': '#8B8B8B' };
function kEsc(s){ return String(s).replace(/&/g,'&amp;').replace(/</g,'&lt;').replace(/>/g,'&gt;'); }
/* ===== v1.2 图谱配色: 掌握分深浅(红<40 黄40~69 绿≥70 越高越实) ===== */
function masteryColor(s){
  if(s === undefined || s === null){ return null; }
  // DATA-VIS-COLORS: 掌握分连续色阶(红<40 黄40~69 绿≥70 且含透明度插值), 语义化会破坏渐变可读性, 保留
  if(s < 40){ return '#EB5757'; }
  if(s < 70){ return '#F2994A'; }
  var t = Math.max(0, Math.min(1, (s - 70) / 30));
  return 'rgba(76,183,130,' + (0.55 + 0.45 * t).toFixed(2) + ')';
}
function loadGraph(){
  fetch('/api/graph').then(function(r){ return r.json(); }).then(function(g){
    var wrap = document.getElementById('kgwrap');
    var gs = document.getElementById('gstats');
    var nodes = g.nodes || [], edges = g.edges || [];
    if(!nodes.length){
      wrap.innerHTML = GRAPH_EMPTY;
      gs.textContent = '';
      return;
    }
    fetch('/api/review_cards').then(function(r){ return r.json(); })
      .then(function(rc){ return rc; })
      .then(function(rc){
        var sm = {};
        (rc.cards || []).forEach(function(c){ sm[c.concept] = c.status; });
        fetch('/api/mastery').then(function(r){ return r.json(); })
          .then(function(mm){ return mm && mm.ok ? mm.scores : {}; })
          .catch(function(){ return {}; })
          .then(function(mm){
            renderGraph(nodes, edges, sm, g.summary || {}, wrap, gs, mm);
          });
      })
      .catch(function(){ renderGraph(nodes, edges, {}, g.summary || {}, wrap, gs, {}); });
  }).catch(function(){ document.getElementById('kgwrap').textContent = '图谱加载失败'; });
}
function renderGraph(nodesIn, edgesIn, stmap, summary, wrap, gs, mmap){
  var nodes = nodesIn.slice(), edges = edgesIn.slice();
  if(nodes.length > 50){                                       /* 防卡顿: 只保留连接数 top30 */
    nodes.sort(function(a,b){ return b.degree - a.degree; });
    nodes = nodes.slice(0, 30);
    var keep = {}; nodes.forEach(function(x){ keep[x.id] = 1; });
    edges = edges.filter(function(e){ return keep[e.source] && keep[e.target]; });
  }
  var idx = {};
  nodes.forEach(function(nd, i){
    idx[nd.id] = i;
    var ang = 2 * Math.PI * i / nodes.length;
    nd.px = KG_W/2 + 200 * Math.cos(ang); nd.py = KG_H/2 + 150 * Math.sin(ang);
    nd.vx = 0; nd.vy = 0;
  });
  var eidx = edges.map(function(e){ return [idx[e.source], idx[e.target], Math.min(e.weight, 4)]; })
                 .filter(function(p){ return p[0] !== undefined && p[1] !== undefined; });
  for(var it = 0; it < 100; it++){
    var i, j;
    for(i = 0; i < nodes.length; i++){
      for(j = i + 1; j < nodes.length; j++){
        var ax = nodes[j].px - nodes[i].px, ay = nodes[j].py - nodes[i].py;
        var d2 = ax*ax + ay*ay; if(d2 < 1){ ax = 1; ay = 0; d2 = 1; }
        var dd = Math.sqrt(d2), ff = 2600 / d2;                /* 库仑斥力 */
        nodes[i].vx -= ax/dd*ff; nodes[i].vy -= ay/dd*ff;
        nodes[j].vx += ax/dd*ff; nodes[j].vy += ay/dd*ff;
      }
    }
    eidx.forEach(function(pp){
      var p1 = nodes[pp[0]], p2 = nodes[pp[1]];
      var dx = p2.px - p1.px, dy = p2.py - p1.py;
      var dl = Math.sqrt(dx*dx + dy*dy) || 1;
      var fs = (dl - 110) * 0.02 * pp[2];                      /* 弹簧引力, 权重加强 */
      p1.vx += dx/dl*fs; p1.vy += dy/dl*fs;
      p2.vx -= dx/dl*fs; p2.vy -= dy/dl*fs;
    });
    nodes.forEach(function(nd){
      nd.vx *= 0.85; nd.vy *= 0.85;                            /* 阻尼 */
      nd.px = Math.max(26, Math.min(KG_W-26, nd.px + nd.vx));
      nd.py = Math.max(22, Math.min(KG_H-22, nd.py + nd.vy));
    });
  }
  /* DOM 构建: 保留元素引用, 拖拽时同步连线 */
  var NS = 'http://www.w3.org/2000/svg';
  var svg = document.createElementNS(NS, 'svg');
  svg.setAttribute('id', 'kgsvg');
  svg.setAttribute('viewBox', '0 0 ' + KG_W + ' ' + KG_H);
  svg.setAttribute('style', 'width:100%;height:auto');
  var lineEls = [], nodeEls = {}, lastMap = {};
  edges.forEach(function(e){
    var ln = document.createElementNS(NS, 'line');
    ln.style.stroke = 'var(--color-border-strong)';
    ln.setAttribute('stroke-width', Math.min(1 + e.weight * 0.8, 5));
    ln.setAttribute('opacity', '0.55');
    svg.appendChild(ln);
    lineEls.push({ el: ln, s: e.source, t: e.target });
  });
  nodes.forEach(function(nd){
    var rr = Math.min(6 + nd.count * 2.2, 16);
    var gEl = document.createElementNS(NS, 'g');
    gEl.setAttribute('class', 'kgn');
    gEl.setAttribute('data-id', nd.id);
    var cc = document.createElementNS(NS, 'circle');
    cc.setAttribute('cx', nd.px); cc.setAttribute('cy', nd.py);
    cc.setAttribute('r', rr);
    var mScore = mmap ? mmap[nd.id] : undefined;
    cc.setAttribute('fill', masteryColor(mScore) || KG_COLORS[stmap[nd.id]] || '#94a3b8');  // DATA-VIS-COLORS: 节点填色走数据色阶, 保留
    if(mScore !== undefined && mScore !== null){                    // 红队节点加描边警示
      cc.setAttribute('stroke', mScore < 40 ? '#EB5757' : '#050607');
      cc.setAttribute('stroke-width', mScore < 40 ? '3' : '1.5');
    } else {
      cc.setAttribute('stroke', '#11111b'); cc.setAttribute('stroke-width', '1.5');
    }
    var tt = document.createElementNS(NS, 'title');
    var msTxt = (mScore !== undefined && mScore !== null) ? ' · 掌握分 ' + mScore : '';
    tt.textContent = nd.id + msTxt + ' · 出现 ' + nd.count + ' 天 · 最近 ' + nd.dates[nd.dates.length-1] + ' · 状态 ' + (stmap[nd.id] || '巩固中');
    var tx = document.createElementNS(NS, 'text');
    tx.setAttribute('x', nd.px); tx.setAttribute('y', nd.py + rr + 13);
    tx.setAttribute('text-anchor', 'middle'); tx.setAttribute('font-size', '10'); tx.setAttribute('fill', '#9399b2');
    tx.textContent = kEsc(nd.id);
    gEl.appendChild(cc); gEl.appendChild(tt); gEl.appendChild(tx);
    svg.appendChild(gEl);
    nodeEls[nd.id] = { g: gEl, c: cc, t: tx };
    lastMap[nd.id] = nd.dates[nd.dates.length - 1];
  });
  wrap.innerHTML = ''; wrap.appendChild(svg);
  gs.innerHTML = '总概念 <b>' + summary.total_concepts + '</b> · 总关联 <b>' + summary.total_edges
               + '</b> · 最核心: <b class="good">' + kEsc(summary.core || '-') + '</b>'
               + ' <span class="dim">（悬停看详情 · 点击节点跳最近笔记 · 可拖拽节点）</span>';
  bindGraphDrag(nodes, idx, lineEls, nodeEls, lastMap);
}
/* 拖拽移动节点; 未发生位移视为点击 -> 跳最近出现笔记 */
function bindGraphDrag(nodes, idx, lineEls, nodeEls, lastMap){
  var svg = document.getElementById('kgsvg');
  var cur = null, sx = 0, sy = 0, moved = false;
  function place(nd){
    var o = nodeEls[nd.id];
    o.c.setAttribute('cx', nd.px); o.c.setAttribute('cy', nd.py);
    o.t.setAttribute('x', nd.px); o.t.setAttribute('y', nd.py + 18);
    lineEls.forEach(function(L){
      if(L.s === nd.id || L.t === nd.id){
        var pa = nodes[idx[L.s]], pb = nodes[idx[L.t]];
        L.el.setAttribute('x1', pa.px); L.el.setAttribute('y1', pa.py);
        L.el.setAttribute('x2', pb.px); L.el.setAttribute('y2', pb.py);
      }
    });
  }
  svg.addEventListener('pointerdown', function(ev){
    var gEl = ev.target.closest ? ev.target.closest('g.kgn') : null;
    if(!gEl){ return; }
    cur = { id: gEl.getAttribute('data-id'), nd: nodes[idx[gEl.getAttribute('data-id')]] };
    sx = ev.clientX; sy = ev.clientY; moved = false;
    ev.preventDefault();
  });
  window.addEventListener('pointermove', function(ev){
    if(!cur){ return; }
    if(Math.abs(ev.clientX - sx) + Math.abs(ev.clientY - sy) > 3){ moved = true; }
    if(!moved || !cur.nd){ return; }
    var rect = svg.getBoundingClientRect();
    cur.nd.px = Math.max(26, Math.min(KG_W-26, (ev.clientX - rect.left) * KG_W / rect.width));
    cur.nd.py = Math.max(22, Math.min(KG_H-22, (ev.clientY - rect.top) * KG_H / rect.height));
    place(cur.nd);
  });
  window.addEventListener('pointerup', function(){
    if(cur && !moved && lastMap[cur.id]){
      location.href = '/editor?date=' + lastMap[cur.id];
    }
    cur = null;
  });
}
loadGraph();
/* ===== v1.0 设置页: 自启开关 + 提醒偏好 + 主题占位 ===== */
var SETSTATE = null;
function setEsc(t){ return String(t).replace(/&/g,'&amp;').replace(/</g,'&lt;'); }
function loadSettings(){
  fetch('/api/settings').then(function(r){ return r.json(); }).then(function(d){
    if(!d.ok){ return; }
    SETSTATE = d;
    var s = d.settings, rem = s.reminders || {}, reg = d.autostart_registered;
    var adp = s.adaptive || {enabled:true,high_rate:0.9,high_run:3,boost:0.10,
                             low_rate:0.5,low_run:2,reduce:0.20};
    var box = document.getElementById('setcard');
    box.innerHTML =
      '<div style="display:flex;flex-direction:column;gap:8px;font-size:13px">'
      + '<label style="cursor:pointer"><input type="checkbox" id="opt_daily" '+(rem.daily_first_open?'checked':'')+'> 每日首次开机提醒（有未完成任务或到期知识点才弹）</label>'
      + '<label style="cursor:pointer"><input type="checkbox" id="opt_review" '+(rem.review_near?'checked':'')+'> 复习临近提醒（复习时段前30分钟）　时段 '
      + '<input type="time" id="opt_rtime" value="'+(rem.review_time||'20:00')+'"></label>'
      + '<label style="cursor:pointer"><input type="checkbox" id="opt_away" '+(rem.away_nudge?'checked':'')+'> 连续未打开提醒，阈值 '
      + '<input type="number" id="opt_adays" min="2" max="30" value="'+(rem.away_days||2)+'" style="width:52px"> 天</label>'
      + '<div>主题：<select id="opt_theme" onchange="changeTheme(this.value)">'
      + '<option value="dark">深空灰</option>'
      + '<option value="midnight-blue">午夜蓝</option>'
      + '<option value="ink-green">墨绿</option>'
      + '</select> <span class="dim">(选择即换肤, 无需刷新)</span></div>'
      + '<div style="border-top:1px dashed var(--color-border-subtle);padding-top:8px;margin-top:2px">'
      + '<b style="font-size:12px;color:var(--color-text-primary)">⚡ 学习节奏自适应</b> '
      + '<label style="cursor:pointer;font-size:12px"><input type="checkbox" id="ad_en" '
      + (adp.enabled ? 'checked' : '') + '> 启用</label><br>'
      + '<span class="dim" style="font-size:12px">连续 <input type="number" id="ad_hrn" min="2" max="7" value="'+adp.high_run+'" style="width:44px"> 天完成率≥ '
      + '<input type="number" id="ad_hr" min="50" max="100" value="'+Math.round(adp.high_rate*100)+'" style="width:48px">% → 次日 +'
      + '<input type="number" id="ad_b" min="0" max="50" value="'+Math.round(adp.boost*100)+'" style="width:44px">%<br>'
      + '连续 <input type="number" id="ad_lrn" min="1" max="7" value="'+adp.low_run+'" style="width:44px"> 天完成率≤ '
      + '<input type="number" id="ad_lr" min="10" max="80" value="'+Math.round(adp.low_rate*100)+'" style="width:48px">% → 次日 -'
      + '<input type="number" id="ad_red" min="0" max="50" value="'+Math.round(adp.reduce*100)+'" style="width:44px">% 并附休息建议</span><br>'
      + '<button class="btn" style="margin-top:6px;background:var(--color-state-warning)" onclick="saveAdaptive()">保存自适应参数</button>'
      + '</div>'
      + '<div style="display:flex;gap:10px;flex-wrap:wrap;margin-top:4px">'
      + '<button class="btn" style="margin-top:0;background:'+(reg?'var(--color-state-success)':'var(--color-accent)')+'" onclick="toggleAutostart()">开机自启：'+(reg?'已开启':'未开启')+'（点击切换）</button>'
      + '<button class="btn" style="margin-top:0;background:var(--color-state-success)" onclick="saveReminders()">保存提醒偏好</button>'
      + '</div>'
      + '<div style="display:flex;gap:10px;flex-wrap:wrap;margin-top:8px;padding-top:8px;border-top:1px dashed var(--color-border-subtle)">'
      + '<button class="btn" style="margin-top:0;background:var(--color-accent)" onclick="exportData()">⬇️ 导出数据</button>'
      + '<button class="btn" style="margin-top:0;background:var(--color-surface-elevated);color:var(--color-text-body)" onclick="document.getElementById(\'import_file\').click()">⬆️ 导入数据</button>'
      + '<input type="file" id="import_file" accept=".json,application/json" style="display:none" onchange="importData(this)">'
      + '<button class="btn" style="margin-top:0;background:var(--color-surface-elevated);color:var(--color-text-body)" onclick="backupNow()">💾 立即备份</button>'
      + '<button class="btn" style="margin-top:0;background:var(--color-surface-elevated);color:var(--color-text-body)" onclick="replayGuide()">🎓 新手引导</button>'
      + '</div>'
      + (reg ? '<div class="dim" style="word-break:break-all">注册表登记：'+setEsc(reg)+'</div>' : '')
      + '</div>';
    document.getElementById('opt_theme').value = s.theme || 'dark';
    document.getElementById('ad_en').checked = !!adp.enabled;
  }).catch(function(){
    var box = document.getElementById('setcard');
    if(box){ box.innerHTML = '<p class="dim">设置加载失败（服务未运行？）</p>'; }
  });
}
function postSettings(patch){
  fetch('/api/settings', {method:'POST', headers:{'Content-Type':'application/json'}, body: JSON.stringify(patch)})
    .then(function(r){ return r.json(); }).then(function(d){
      if(!d.ok){ lhToast('保存失败: '+(d.err||'')); return; }
      if(d.autostart_error){ lhToast('开机自启写注册表失败：'+d.autostart_error); }
      else if(patch.autostart !== undefined){ lhToast(d.autostart_registered ? '已开启开机自启' : '已关闭开机自启'); }
      loadSettings();
    }).catch(function(){ lhToast('保存失败（服务未运行?）'); });
}
function toggleAutostart(){
  postSettings({autostart: !(SETSTATE && SETSTATE.autostart_registered)});
}
function saveReminders(){
  postSettings({
    reminders: {
      daily_first_open: document.getElementById('opt_daily').checked,
      review_near: document.getElementById('opt_review').checked,
      review_time: document.getElementById('opt_rtime').value || '20:00',
      away_nudge: document.getElementById('opt_away').checked,
      away_days: parseInt(document.getElementById('opt_adays').value, 10) || 2
    }
  });
}
/* ===== v1.3 主题即时换肤: 拉覆盖层CSS原地替换, 不刷新页面 ===== */
function changeTheme(v){
  var el = document.getElementById('themecss');
  if(!el){ return; }
  fetch('/api/theme?name=' + encodeURIComponent(v))
    .then(function(r){ return r.json(); })
    .then(function(d){
      if(!d.ok){ return; }
      el.textContent = d.css;                       // 末位覆盖层整体替换, 即时生效
      postSettings({theme: d.name});                // 持久化归一化后的主题名
    })
    .catch(function(){ lhToast('换肤失败（服务未运行?）'); });
}
/* ===== v1.1 数据闭环: 复习打卡 / 报告预览 / 导出导入备份 ===== */
function markReview(btn){
  fetch('/api/mark_reviewed', {method:'POST', headers:{'Content-Type':'application/json'}, body: JSON.stringify({concept: btn.dataset.c})})
    .then(function(r){ return r.json(); })
    .then(function(d){ if(d.ok){ location.reload(); } else { lhToast('标记失败: '+(d.err||'')); } })
    .catch(function(){ lhToast('服务未运行?'); });
}
function openReport(name){
  var mb = document.getElementById('mbody');
  document.getElementById('mtitle').textContent = '📄 ' + name;
  mb.textContent = '加载中…';
  document.getElementById('modal').style.display = 'flex';
  modalCopy(true);
  fetch('/api/report?name=' + encodeURIComponent(name))
    .then(function(r){ return r.json(); })
    .then(function(d){
      if(!d.ok){ mb.textContent = d.err || '读取失败'; return; }
      var html = mdmini(d.markdown);
      if(d.name.indexOf('monthly_') === 0){                 // 月报预览: 内联配套趋势 SVG
        fetch('/api/report?name=' + d.name.replace('monthly_', 'trend_').replace('.md', '.svg'))
          .then(function(r){ return r.json(); })
          .then(function(sd){
            if(sd && sd.ok && sd.markdown && sd.markdown.indexOf('<svg') !== -1){
              html = '<div style="margin-bottom:8px">' + sd.markdown + '</div>' + html;
            }
            mb.innerHTML = html;
          }).catch(function(){ mb.innerHTML = html; });
      } else {
        mb.innerHTML = html;
      }
    }).catch(function(e){ mb.textContent = '失败: ' + e; });
}
function saveAdaptive(){
  var num = function(id, lo, hi, fb){
    var v = parseInt(document.getElementById(id).value, 10);
    if(isNaN(v)){ return fb; }
    return Math.max(lo, Math.min(hi, v));
  };
  postSettings({adaptive: {
    enabled: document.getElementById('ad_en').checked,
    high_rate: num('ad_hr', 50, 100, 90) / 100,
    high_run: num('ad_hrn', 2, 7, 3),
    boost: num('ad_b', 0, 50, 10) / 100,
    low_rate: num('ad_lr', 10, 80, 50) / 100,
    low_run: num('ad_lrn', 1, 7, 2),
    reduce: num('ad_red', 0, 50, 20) / 100
  }});
}
function backupNow(){
  fetch('/api/backup', {method:'POST'})
    .then(function(r){ return r.json(); })
    .then(function(d){ lhToast(d.ok ? ('已备份: ' + d.name) : '备份失败'); })
    .catch(function(){ lhToast('服务未运行?'); });
}
function exportData(){
  window.location.href = '/api/export';                     // 浏览器直接下载带时间戳文件名
}
function importData(input){
  var f = input.files && input.files[0];
  if(!f){ return; }
  var rd = new FileReader();
  rd.onload = function(){
    var bundle;
    try{ bundle = JSON.parse(rd.result); }catch(e){ lhToast('不是合法的导出 JSON'); return; }
    if(!confirm('导入流程: 先自动备份 → 同id覆盖/新id追加合并。继续？')){ input.value=''; return; }
    fetch('/api/import', {method:'POST', headers:{'Content-Type':'application/json'}, body: JSON.stringify(bundle)})
      .then(function(r){ return r.json(); })
      .then(function(d){
        if(!d.ok){ lhToast('导入失败: ' + (d.err || '')); return; }
        document.getElementById('mtitle').textContent = '📥 导入完成';
        document.getElementById('mbody').innerHTML = '<p>本次自动备份: ' + d.backup + '</p>'
          + '<p class="dim">明细: ' + JSON.stringify(d.sections) + '</p>'
          + '<p class="dim">警告: ' + (d.warnings.join('；') || '无') + '</p>'
          + '<div><button class="btn" onclick="location.reload()">完成并刷新</button></div>';
        document.getElementById('modal').style.display = 'flex';
        modalCopy(false);
      })
      .catch(function(){ lhToast('导入失败（服务未运行?）'); });
  };
  rd.readAsText(f, 'utf-8');
}
loadSettings();
/* ===== v1.3 键盘流 / 拖拽排序 / Shift 批量选择 ===== */
var KB = {idx: -1};
var SEL = {};
function taskRows(){ return Array.prototype.slice.call(document.querySelectorAll('#pnl-tasks label.task')); }
function kbClear(){ document.querySelectorAll('.kb-focus').forEach(function(x){ x.classList.remove('kb-focus'); }); }
function kbMove(d){
  var rows = taskRows(); if(!rows.length){ return; }
  KB.idx = (KB.idx + d + rows.length) % rows.length;
  kbClear();
  var el = rows[KB.idx];
  el.classList.add('kb-focus');
  try{ el.focus({preventScroll:true}); }catch(_e){ }
  el.scrollIntoView({block:'nearest', behavior:'smooth'});
}
function panelGo(n){
  var map = {'1':'pnl-tasks','2':'pnl-graph','3':'pnl-review','4':'setcard-wrap'};
  var el = document.getElementById(map[n]);
  if(!el){ return; }
  el.scrollIntoView({behavior:'smooth', block:'start'});
  el.classList.add('flash-panel');
  setTimeout(function(){ el.classList.remove('flash-panel'); }, 700);
}
document.addEventListener('keydown', function(e){
  if(e.ctrlKey && !e.altKey && !e.shiftKey && (e.key === 'k' || e.key === 'K')){
    e.preventDefault();
    var kw = document.getElementById('ksearch');
    if(kw.style.display === 'flex'){ ksClose(); } else { ksOpen(); }
    return;
  }
  if(e.key === 'Escape'){ ksClose(); }
  if(e.ctrlKey && !e.altKey && ['1','2','3','4'].indexOf(e.key) >= 0){
    e.preventDefault(); panelGo(e.key); return;
  }
  var tag = (document.activeElement && document.activeElement.tagName) || '';
  if(/INPUT|TEXTAREA|SELECT/.test(tag)){ return; }              // 输入控件内不劫持按键
  var rows = taskRows(); if(!rows.length){ return; }
  if(KB.idx < 0){ KB.idx = 0; }
  if(e.key === 'ArrowDown'){ e.preventDefault(); kbMove(1); }
  else if(e.key === 'ArrowUp'){ e.preventDefault(); kbMove(-1); }
  else if(e.key === ' '){
    var r0 = rows[KB.idx];
    if(r0){ e.preventDefault();
      var cb = r0.querySelector('input[type=checkbox]');
      if(cb){ cb.checked = !cb.checked; tg(cb.dataset.id, cb); } }
  }
  else if(e.key === 'Enter'){
    var r1 = rows[KB.idx];
    var td = r1 && r1.querySelector('.tdetail');
    if(td){ td.classList.toggle('open'); }
  }
  else if(e.key === 'Escape'){ clearSel(); }
});
/* ---- 拖拽排序(原生 HTML5 DnD, 落点=上/下半边决定插前/插后) ---- */
var DRAG = null;
function dragStart(ev, el){
  DRAG = {id: el.dataset.id};
  el.classList.add('dragging');
  ev.dataTransfer.effectAllowed = 'move';
  try{ ev.dataTransfer.setData('text/plain', el.dataset.id); }catch(_e){ }
}
function dragOver(ev, el){
  ev.preventDefault();
  if(!DRAG || el.dataset.id === DRAG.id){ return; }
  var rect = el.getBoundingClientRect();
  var top = ev.clientY < rect.top + rect.height / 2;
  el.classList.toggle('dropline-top', top);
  el.classList.toggle('dropline-bottom', !top);
}
function clearDrag(){
  document.querySelectorAll('.task').forEach(function(x){
    x.classList.remove('dropline-top', 'dropline-bottom', 'dragging'); });
}
function dropTask(ev, el){
  ev.preventDefault();
  var targetId = el.dataset.id;
  var ids = taskRows().map(function(x){ return x.dataset.id; });
  var from = ids.indexOf(DRAG.id), to = ids.indexOf(targetId);
  var rect = el.getBoundingClientRect();
  var insertBefore = ev.clientY < rect.top + rect.height / 2;
  clearDrag();
  if(from < 0 || to < 0 || from === to){ DRAG = null; return; }
  ids.splice(from, 1);
  ids.splice(ids.indexOf(targetId) + (insertBefore ? 0 : 1), 0, DRAG.id);
  fetch('/api/reorder', {method:'POST', headers:{'Content-Type':'application/json'},
    body: JSON.stringify({ids: ids})})
    .then(function(r){ return r.json(); })
    .then(function(d){ if(d.ok){ location.reload(); } else { lhToast('排序失败'); } })
    .catch(function(){ lhToast('服务未运行?'); });
  DRAG = null;
}
/* ---- Shift 多选 → 批量完成/删除/改优先级 ---- */
function selCount(){ return Object.keys(SEL).length; }
function renderBar(){
  var bar = document.getElementById('batchbar');
  bar.classList.toggle('on', selCount() > 0);
  document.getElementById('selcnt').textContent = selCount();
}
function toggleSel(id, row){
  if(SEL[id]){ delete SEL[id]; row.classList.remove('sel'); }
  else{ SEL[id] = 1; row.classList.add('sel'); }
  renderBar();
}
function clearSel(){
  SEL = {};
  document.querySelectorAll('.task.sel').forEach(function(x){ x.classList.remove('sel'); });
  renderBar();
}
document.addEventListener('click', function(ev){
  if(!ev.shiftKey){ return; }
  var row = ev.target.closest ? ev.target.closest('label.task') : null;
  if(!row || !row.closest('#pnl-tasks')){ return; }
  ev.preventDefault(); ev.stopPropagation();
  toggleSel(row.dataset.id, row);
}, true);
function batchDo(action, value){
  var ids = Object.keys(SEL);
  if(!ids.length){ return; }
  if(action === 'delete' && !confirm('删除所选 ' + ids.length + ' 条任务？(可撤销)')){ return; }
  fetch('/api/batch', {method:'POST', headers:{'Content-Type':'application/json'},
    body: JSON.stringify({action: action, ids: ids, value: value})})
    .then(function(r){ return r.json(); })
    .then(function(d){
      if(!d.ok){ lhToast('批量失败: ' + (d.err||'')); return; }
      /* Phase3-T01: 可撤销操作 → 记录撤销提示到 sessionStorage, reload 后由
         checkUndoOffer() 弹出「撤销」toast。保持立即 reload 使页面与服务端同步。 */
      if(['delete','done','snooze','priority'].indexOf(action) >= 0){
        var label = {delete:'已删除', done:'已完成', snooze:'已顺延',
                     priority:'已改优先级'}[action] || '已执行';
        try{ sessionStorage.setItem('lh_undo', JSON.stringify({label: label + ' ' + (d.affected||ids.length) + ' 项', ts: Date.now()})); }catch(e){}
      }
      location.reload();
    })
    .catch(function(){ lhToast('服务未运行?'); });
}
/* ===== v1.3 Ctrl+K 全文搜索 / 三步新手引导 ===== */
var KS = {timer: null, hits: [], hot: 0};
function ksOpen(){
  var w = document.getElementById('ksearch');
  w.style.display = 'flex';
  var inp = document.getElementById('ksinput');
  inp.value = ''; ksRender([]);
  setTimeout(function(){ inp.focus(); }, 30);
}
function ksClose(){ document.getElementById('ksearch').style.display = 'none'; }
function ksRender(hits){
  KS.hits = hits || [];
  var box = document.getElementById('ksres');
  if(!KS.hits.length){
    box.innerHTML = '<div class="kshint" style="border:none">没有匹配结果</div>';
    return;
  }
  var icons = {task:'✅', note:'📝', concept:'🧠', tag:'🏷'};
  box.innerHTML = KS.hits.map(function(h){
    return '<div class="ksitem" data-u="' + h.url + '">'
         + '<span class="kt">' + (icons[h.type] || '•') + ' ' + h.type + '</span>'
         + '<span class="kb"><b>' + h.title + '</b><br>' + h.snippet + '</span></div>';
  }).join('');
  Array.prototype.forEach.call(box.querySelectorAll('.ksitem'), function(el){
    el.addEventListener('click', function(){ location.href = el.dataset.u; });
  });
}
document.getElementById('ksinput').addEventListener('input', function(e){
  clearTimeout(KS.timer);
  var q = e.target.value.trim();
  if(!q){ ksRender([]); return; }
  KS.timer = setTimeout(function(){
    fetch('/api/search?q=' + encodeURIComponent(q) + '&limit=12')
      .then(function(r){ return r.json(); })
      .then(function(d){ if(d.ok){ ksRender(d.hits); } });
  }, 180);
});
var GUIDE_STEPS = [
  {e:'🖱️', t:'常驻与呼出', d:'程序住在任务栏托盘里。左键点托盘图标唤起控制台，任何界面按 Ctrl+Shift+L 都能呼出/隐藏；关闭窗口只是缩到托盘，不会退出。'},
  {e:'✅', t:'每日任务打卡', d:'在「今日任务」勾选即实时保存，未完成自动顺延明天；↑↓ 键移动、空格勾选、回车看详情，Shift+点击可多选批量操作。'},
  {e:'🧠', t:'笔记长出知识网', d:'写一篇笔记，系统自动提取知识点、生成遗忘曲线复习计划与知识图谱；随时按 Ctrl+K 全文搜索你写过的一切。'}
];
var GIDX = 1;
function guideShow(n){
  GIDX = Math.max(1, Math.min(GUIDE_STEPS.length, n));
  var s = GUIDE_STEPS[GIDX-1];
  document.querySelector('#guide .gestep').textContent = s.e;
  document.getElementById('gt').textContent = '第 ' + GIDX + ' 步 · ' + s.t;
  document.getElementById('gd').textContent = s.d;
  document.getElementById('gdir').style.display = (GIDX === GUIDE_STEPS.length) ? 'block' : 'none';
  document.getElementById('gprev').style.visibility = (GIDX === 1) ? 'hidden' : 'visible';
  document.getElementById('gnext').textContent = (GIDX === GUIDE_STEPS.length) ? '开始使用 🚀' : '下一步';
  document.getElementById('gdots').innerHTML =
    GUIDE_STEPS.map(function(_x, i){ return '<i class="'+(i+1===GIDX?'on':'')+'"></i>'; }).join('');
  document.getElementById('guide').style.display = 'flex';
}
function guideStep(d){ guideShow(GIDX + d); }
function guideNext(){
  if(GIDX >= GUIDE_STEPS.length){ guideFinish(); return; }
  guideShow(GIDX + 1);
}
function guideFinish(){
  document.getElementById('guide').style.display = 'none';
  var dir = (document.getElementById('gdir').value || '').trim() || 'AI Agent 开发';
  fetch('/api/firstrun', {method:'POST', headers:{'Content-Type':'application/json'},
    body: JSON.stringify({direction: dir})});               // 初始化结构+生成八周路线图
  fetch('/api/settings', {method:'POST', headers:{'Content-Type':'application/json'},
    body: JSON.stringify({guide_done: true})});
}
function replayGuide(){ guideShow(1); }
/* ===== v1.4 内置帮助: 复用周报/报告同一套弹窗渲染管线 ===== */
function openHelp(){
  var mb = document.getElementById('mbody');
  document.getElementById('mtitle').textContent = '❓ 使用帮助';
  mb.textContent = '加载中…';
  document.getElementById('modal').style.display = 'flex';
  modalCopy(false);
  fetch('/api/help')
    .then(function(r){ return r.json(); })
    .then(function(d){
      if(!d.ok){ mb.textContent = d.err || '加载失败'; return; }
      mb.innerHTML = mdmini(d.markdown);
    })
    .catch(function(e){ mb.textContent = '失败: ' + e; });
}
/* ===== v1.8 阶段二 IIFE: 今日焦点 / 排期建议 / 叙事周报 (零全局污染) ===== */
(function(){
  var toastEl = document.getElementById('lhtoast');
  function toast(m){ if(!toastEl) return; toastEl.textContent=m; toastEl.classList.add('on'); setTimeout(function(){ toastEl.classList.remove('on'); },3000); }

  /* ---------- B3: 顶栏今日焦点(5 分钟自刷, 关闭当天不再打扰, 次日自动恢复) ---------- */
  var df = document.getElementById('daily-focus');
  function dfToday(){
    var d = new Date();
    var p2 = function(n){ return (n < 10 ? '0' : '') + n; };
    return d.getFullYear() + '-' + p2(d.getMonth() + 1) + '-' + p2(d.getDate());
  }
  function dfHiddenToday(){
    try{ return localStorage.getItem('df_hidden') === dfToday(); }catch(e){ return false; }
  }
  function loadFocus(){
    if(!df || df.dataset.hidden === '1' || dfHiddenToday()){ return; }
    fetch('/api/daily-focus').then(function(r){ return r.json(); }).then(function(d){
      if(!d.ok){ return; }
      document.getElementById('df-icon').textContent = d.icon;
      document.getElementById('df-text').textContent = d.text;
      df.classList.remove('u-high','u-mid','u-low');
      df.classList.add('u-' + (d.urgency || 'mid'));
      df.style.display = '';
      df.onclick = function(){ location.hash = d.link_hash; };
    }).catch(function(){});
  }
  try{
    loadFocus();
    setInterval(function(){ if(df && df.dataset.hidden !== '1'){ loadFocus(); } }, 5*60*1000);
  }catch(e){ loadFocus(); }
  var dfc = document.getElementById('df-close');
  if(dfc){ dfc.addEventListener('click', function(ev){ ev.stopPropagation(); if(df){ df.dataset.hidden='1'; df.style.display='none'; } try{ localStorage.setItem('df_hidden', dfToday()); }catch(e){} }); }

  /* ---------- B1: 排期建议卡(事件委托, 兼容洞察面板重渲染) ---------- */
  document.addEventListener('click', function(ev){
    if(!ev.target || ev.target.id !== 'btn-slot'){ return; }
    var card = document.getElementById('slotcard');
    if(!card){ return; }
    var p1 = document.querySelector('#pnl-tasks label.task[data-pri="1"]');
    var q = p1 ? '?priority=P1' : '?priority=P2';
    card.style.display = 'block';
    card.innerHTML = '<span class="dim">🔮 正在计算排期建议…</span>';
    fetch('/api/suggest-slot' + q).then(function(r){ return r.json(); }).then(function(d){
      var sl = d.slot || d;
      var win = sl.suggested_window ? ' ' + sl.suggested_window : '';
      var weak = sl.weakness_alert ? '<div class="sc-weak">⚠️ 该领域当前最薄弱, 建议优先安排</div>' : '';
      card.innerHTML = '<div class="sc-head">🔮 建议排到 <b>' + (sl.suggested_day_label||'') + '(' + (sl.suggested_day||'') + ')' + win + '</b>'
        + '<span class="sc-conf ' + (sl.confidence||'low') + '">' + (sl.confidence||'low') + '</span></div>'
        + '<div>' + (sl.reason||'') + '</div>' + weak;
    }).catch(function(){ card.innerHTML = '<span class="dim">服务未运行? 用 bat 启动交互模式</span>'; });
  });

  /* ---------- B2: 叙事周报(展开懒加载 + 复制 Markdown) ---------- */
  function toMarkdown(rp){
    var md = '# 学习周报 (' + rp.period + ')\n\n## ' + rp.headline + '\n';
    (rp.highlights||[]).forEach(function(x){ md += '- ✦ ' + x + '\n'; });
    (rp.concerns||[]).forEach(function(x){ md += '- ⚠ ' + x + '\n'; });
    if(rp.focus_best){ md += '\n最佳专注时段: ' + rp.focus_best + '\n'; }
    md += '\n下周建议: ' + (rp.next_week_suggestion||'-') + '\n';
    return md;
  }
  var narr = document.getElementById('weekly-narr');
  if(narr){
    narr.addEventListener('toggle', function(){
      if(!narr.open || narr.dataset.loaded){ return; }
      var body = document.getElementById('narr-body');
      body.innerHTML = '<span class="dim">生成中…</span>';
      fetch('/api/weekly-report?week=current').then(function(r){ return r.json(); }).then(function(d){
        narr.dataset.loaded = '1';
        var rp = d.report || {};
        if(rp.status === 'collecting'){ body.innerHTML = '<p class="dim">' + (rp.message||'数据积累中') + '</p>'; return; }
        var h = '<div class="nhead">' + rp.headline + '</div><div class="dim">' + rp.period + '</div>';
        (rp.highlights||[]).forEach(function(x){ h += '<div class="nline" style="color:var(--color-state-success)">✦ ' + x + '</div>'; });
        (rp.concerns||[]).forEach(function(x){ h += '<div class="nline" style="color:var(--color-state-warning)">⚠ ' + x + '</div>'; });
        if(rp.focus_best){ h += '<div class="nline">⏰ 最佳专注时段: <b>' + rp.focus_best + '</b></div>'; }
        h += '<div class="nline" style="color:var(--color-accent)">➜ 下周建议: ' + (rp.next_week_suggestion||'-') + '</div>';
        var st = rp.stats || {};
        h += '<div class="dim mt6" style="font-size:11px">完成 ' + (st.done_tasks||0) + '/' + (st.total_tasks||0)
          + ' · 全清 ' + (st.full_days||0) + ' 天 · 复习 ' + (st.review_count||0) + ' 次'
          + ((st.avg_quality != null) ? ' · 质量均分 ' + st.avg_quality + '/5' : '') + '</div>';
        body.innerHTML = h;
        body.dataset.md = toMarkdown(rp);
      }).catch(function(){ body.innerHTML = '<p class="dim">生成失败: 服务未运行?</p>'; });
    });
  }
  var cp = document.getElementById('narr-copy');
  if(cp){
    cp.addEventListener('click', function(){
      var body = document.getElementById('narr-body');
      var md = (body && body.dataset.md) || '';
      if(!md){ toast('先展开周报再复制'); return; }
      try{ navigator.clipboard.writeText(md).then(function(){ toast('Markdown 已复制'); }); }
      catch(e){ toast('复制失败, 请手动选择文本'); }
    });
  }
})();

/* ===== v1.9 交互效率飞轮 IIFE: C1 命令面板 / C2 键盘 / C3 快捕 / C4 撤销 / C5 悬停 ===== */
(function(){
  var toastEl = document.getElementById('lhtoast');
  function toast(m){ if(!toastEl) return; toastEl.textContent=m; toastEl.classList.add('on'); setTimeout(function(){ toastEl.classList.remove('on'); },3000); }
  function post(url, body){ return fetch(url,{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify(body||{})}).then(function(r){return r.json();}); }

  /* ---------- C4: 撤销栈(Ctrl+Z -> 服务端按 operations_log 回滚) ---------- */
  function doUndo(){
    post('/api/undo', {}).then(function(d){
      toast(d.ok ? ('↩️ 已撤销: ' + (d.label||'')) : (d.err||'没有可撤销的操作'));
      if(d.ok){ try{ document.dispatchEvent(new Event('ins:refresh')); }catch(e){} setTimeout(function(){ location.reload(); }, 600); }
    }).catch(function(){ toast('服务未运行?'); });
  }
  /* Phase3-T01: 暴露全局撤销入口, 供「撤销」toast 按钮复用同一撤销栈 */
  window.lhUndo = doUndo;

  /* ---------- C3: 快速捕获条 ---------- */
  var qb = document.getElementById('quickbar'), qc = document.getElementById('qc-input');
  function openQC(){ if(!qb) return; qb.style.display='block'; qb.classList.add('open'); if(qc){ qc.focus(); qc.select(); } }
  function closeQC(){ if(qb){ qb.style.display='none'; qb.classList.remove('open'); } }
  var bcap = document.getElementById('btn-capture');
  if(bcap){ bcap.addEventListener('click', function(){ openQC(); }); }
  if(qc){
    qc.addEventListener('keydown', function(e){
      e.stopPropagation();                                  // 不触发全局快捷键
      if(e.key === 'Escape'){ closeQC(); }
      if(e.key === 'Enter'){
        var text = qc.value.trim();
        if(!text){ return; }
        post('/api/quick-capture', {text:text}).then(function(d){
          if(!d.ok){ toast(d.err||'创建失败'); return; }
          var p = d.parsed || {};
          var bits = ['已创建:' + p.title];
          if(p.day_label || d.day!==undefined) bits.push(p.day_label||'今天');
          if(p.window) bits.push(p.window);
          if(p.est_minutes) bits.push('⏱'+p.est_minutes+'m');
          if((p.tags||[]).length) bits.push('#'+p.tags.join(' #'));
          toast('✅ ' + bits.join(' '));
          qc.value=''; closeQC();
          /* Phase3-T01: 快捕可撤销 → 记录撤销提示, reload 后弹出 */
          try{ sessionStorage.setItem('lh_undo', JSON.stringify({label:'创建任务', ts: Date.now()})); }catch(e){}
          setTimeout(function(){ location.reload(); }, 500);   // 新任务入列(带徽章)
        }).catch(function(){ toast('服务未运行? 用 bat 启动'); });
      }
    });
  }

  /* ---------- C1: 命令面板 ---------- */
  var ck = document.getElementById('cmdk'), ckin = document.getElementById('cmdk-input'),
      ckr = document.getElementById('cmdk-res'), ckSel = 0, ckItems = [], stateCache = null;
  function ckOpen(){ if(!ck) return; ck.style.display='flex'; if(ckin){ ckin.value=''; ckin.focus(); } renderCK(''); }
  function ckClose(){ if(ck){ ck.style.display='none'; } }
  function getState(cb){
    if(stateCache && Date.now()-stateCache.t < 30000){ cb(stateCache.v); return; }
    fetch('/api/state').then(function(r){return r.json();}).then(function(v){ stateCache={t:Date.now(),v:v}; cb(v); }).catch(function(){ cb({days:{}}); });
  }
  function allTasks(st){ var out=[]; Object.keys(st.days||{}).sort().reverse().forEach(function(k){ (st.days[k]||[]).forEach(function(t){ out.push({id:t.id,text:t.text,done:t.done,pri:t.priority,est:t.est_minutes,date:k}); }); }); return out; }
  var ACTIONS = [
    {i:'🎯', t:'打开今日任务', run:function(){ location.hash='#pnl-tasks'; }},
    {i:'🧠', t:'打开复习中心', run:function(){ location.hash='#pnl-review'; }},
    {i:'📊', t:'打开洞察面板', run:function(){ location.hash='#pnl-insight'; }},
    {i:'🔥', t:'查看热力图', run:function(){ location.hash='#pnl-heatmap'; }},
    {i:'📋', t:'展开本周叙事周报', run:function(){ var n=document.getElementById('weekly-narr'); if(n){ n.open=true; n.scrollIntoView({behavior:'smooth'}); } }},
    {i:'➕', t:'添加任务(自然语言)', run:function(){ openQC(); }},
    {i:'🛡️', t:'切换减负模式', run:function(){ fetch('/api/fatigue').then(function(r){return r.json();}).then(function(s){ post('/api/fatigue',{active:!s.active}).then(function(){ toast(s.active?'减负已关闭':'减负已开启'); location.reload(); }); }); }},
    {i:'♻️', t:'刷新数据', run:function(){ location.reload(); }},
    {i:'❓', t:'快捷键帮助', run:function(){ var k=document.getElementById('keyhelp'); if(k){ k.style.display='flex'; } }}
  ];
  var histKey = 'cmd_history';
  function getHist(){ try{ return JSON.parse(localStorage.getItem(histKey)||'[]'); }catch(e){ return []; } }
  function pushHist(t){ try{ var h=getHist().filter(function(x){return x!==t;}); h.unshift(t); localStorage.setItem(histKey, JSON.stringify(h.slice(0,20))); }catch(e){} }
  function ckRenderList(items){
    ckItems = items.slice(0,12); ckSel = 0;
    var extra = items.length > 12 ? '<div class="ckitem" style="cursor:default"><span class="cx">还有 '+(items.length-12)+' 条…</span></div>' : '';
    ckr.innerHTML = ckItems.map(function(it,idx){
      return '<div class="ckitem'+(idx===ckSel?' sel':'')+'" data-i="'+idx+'"><span class="ci">'+it.i+'</span><span class="ct">'+it.t+'</span><span class="cx">'+(it.x||'')+'</span></div>';
    }).join('') + (items.length ? '' : '') + extra;
    var selEl = ckr.querySelector('.ckitem.sel'); if(selEl){ selEl.scrollIntoView({block:'nearest'}); }
  }
  function renderCK(q){
    q = (q||'').trim();
    var items = [];
    if(q.charAt(0) === '#'){
      var tagq = q.slice(1).toLowerCase();
      fetch('/api/analytics').then(function(r){return r.json();}).then(function(d){
        ((d.analytics&&d.analytics.stability.rows)||[]).forEach(function(row){
          if(row.tag.toLowerCase().indexOf(tagq)>=0){ items.push({i:'🏷️', t:'#'+row.tag+' · '+row.n_concepts+' 概念', x:row.avg_retention+'%', run:function(){ location.hash='#pnl-insight'; }}); }
        });
        ckRenderList(items);
      }).catch(function(){ ckRenderList([]); });
      ckRenderList([{i:'⏳',t:'标签加载中…'}]); return;
    }
    if(q.charAt(0) === '@'){
      var nq = q.slice(1).trim();
      fetch('/api/search?q='+encodeURIComponent(nq||'笔记')).then(function(r){return r.json();}).then(function(d){
        (d.results||d.items||[]).slice(0,10).forEach(function(x){
          items.push({i:'📄', t:(x.title||x.text||x.name||'结果'), x:(x.date||''), run:function(){ if(x.date){ window.open('/editor?date='+x.date); } else { toast('该结果暂不支持直达'); } }});
        });
        ckRenderList(items.length?items:[{i:'📄',t:'未找到相关笔记'}]);
      }).catch(function(){ ckRenderList([{i:'📄',t:'搜索失败(需服务运行)'}]); });
      return;
    }
    ACTIONS.forEach(function(a){ if(!q || a.t.indexOf(q)>=0){ items.push({i:a.i,t:a.t,run:a.run,x:'命令'}); } });
    if(q.length >= 2){
      getState(function(st){
        allTasks(st).forEach(function(t){
          if(t.text.toLowerCase().indexOf(q.toLowerCase())>=0){
            items.push({i:t.done?'✅':(t.pri===1?'🔴':'⚪'), t:'[P'+(t.pri||2)+'] '+t.text, x:t.est?('⏱'+t.est+'m'):'', run:function(){ location.hash='#pnl-tasks'; setTimeout(function(){ var lab=document.querySelector('label.task[data-id="'+CSS.escape(t.id)+'"]'); if(lab){ lab.scrollIntoView({behavior:'smooth',block:'center'}); lab.classList.add('kb-focus'); } },400); }});
          }
        });
        if(!items.length){ items.push({i:'📝', t:'未找到, 按 Enter 创建任务「'+q+'」', run:function(){ post('/api/quick-capture',{text:q}).then(function(d){ toast(d.ok?'✅ 已创建':'创建失败'); setTimeout(function(){location.reload();},500); }); }}); }
        ckRenderList(items);
      });
      ckRenderList(items);
      return;
    }
    getHist().forEach(function(t){
      var a = ACTIONS.filter(function(x){ return x.t===t; })[0];
      if(a){ items.push({i:a.i,t:a.t,run:a.run,x:'最近'}); }
    });
    if(!q){ ACTIONS.forEach(function(a){ if(!items.some(function(x){return x.t===a.t;})){ items.push(a); } }); }
    ckRenderList(items);
  }
  function ckExec(){ var it = ckItems[ckSel]; if(!it){ return; } pushHist(it.t.replace(/^(✅|🔴|⚪)\s*/,'')); ckClose(); try{ it.run(); }catch(e){} }
  if(ck){
    ck.addEventListener('click', function(ev){
      if(ev.target === ck){ ckClose(); return; }
      var el = ev.target.closest('.ckitem[data-i]');
      if(el){ ckSel = parseInt(el.getAttribute('data-i'),10); ckExec(); }
    });
  }
  if(ckin){
    var deb = null;
    ckin.addEventListener('input', function(e){ e.stopPropagation(); clearTimeout(deb); deb=setTimeout(function(){ renderCK(ckin.value); },150); });
    ckin.addEventListener('keydown', function(e){
      e.stopPropagation();
      if(e.key==='ArrowDown'){ ckSel=Math.min(ckSel+1,ckItems.length-1); }
      else if(e.key==='ArrowUp'){ ckSel=Math.max(ckSel-1,0); }
      else if(e.key==='Enter'){ ckExec(); return; }
      else if(e.key==='Escape'){ ckClose(); return; }
      else { return; }
      e.preventDefault();
      ckr.querySelectorAll('.ckitem').forEach(function(x,i){ x.classList.toggle('sel', i===ckSel); if(i===ckSel){ x.scrollIntoView({block:'nearest'}); } });
    });
  }
  function openCmdk(){ ckOpen(); }

  /* ---------- C2/C4/C5: 全局键盘 + 批量模式 + 悬停委托 ---------- */
  function taskRows(){ return Array.prototype.slice.call(document.querySelectorAll('#pnl-tasks label.task')); }
  function curFocus(){ return document.querySelector('.kb-focus'); }
  function moveFocus(d){
    var rows = taskRows(); if(!rows.length){ return; }
    /* 2026-08-31 修复: 键盘导航启用 kbmode —— CSS 依 body.kbmode 揭示
       .task.kb-focus 行的动作按钮(✓⏭✏️); 此前 JS 从未添加该类,
       规则空挂, 键盘用户看不到行内操作按钮(浏览器实测 display:none)。 */
    document.body.classList.add('kbmode');
    var idx = rows.indexOf(curFocus());
    idx = idx<0 ? 0 : Math.min(Math.max(idx+d,0), rows.length-1);
    rows.forEach(function(r){ r.classList.remove('kb-focus'); });
    var el = rows[idx]; el.classList.add('kb-focus'); el.scrollIntoView({block:'nearest'});
  }
  function focusCB(){ var f=curFocus(); return f?f.querySelector('input[type=checkbox]'):null; }
  function setPri(pri){ var f=curFocus(); if(!f){ return; } var id=f.getAttribute('data-id'); post('/api/priority',{id:id,priority:pri}).then(function(d){ toast(d.ok?('优先级已设为 P'+pri):'设置失败'); f.setAttribute('data-pri', pri); }).catch(function(){ toast('服务未运行?'); }); }
  function snoozeOne(days){ var f=curFocus(); if(!f){ return; } var id=f.getAttribute('data-id'); post('/api/batch',{action:'snooze',ids:[id],value:days}).then(function(d){ toast(d.ok?('已顺延 '+days+' 天'):'顺延失败'); setTimeout(function(){location.reload();},500); }); }
  function delOne(){ var f=curFocus(); if(!f){ return; } var id=f.getAttribute('data-id'); if(!confirm('删除这条任务?(可 Ctrl+Z 撤销)')){ return; } post('/api/batch',{action:'delete',ids:[id]}).then(function(d){ toast(d.ok?'↩️ 已删除(可撤销)':'删除失败'); setTimeout(function(){location.reload();},500); }); }

  document.addEventListener('keydown', function(e){
    var tag = (document.activeElement && document.activeElement.tagName) || '';
    var typing = /INPUT|TEXTAREA|SELECT/.test(tag);
    if((e.ctrlKey||e.metaKey) && !e.altKey && (e.key==='p'||e.key==='P')){ e.preventDefault(); openCmdk(); return; }
    if((e.ctrlKey||e.metaKey) && !e.altKey && (e.key==='n'||e.key==='N')){ e.preventDefault(); openQC(); return; }
    if((e.ctrlKey||e.metaKey) && !e.altKey && (e.key==='z'||e.key==='Z') && !typing){ e.preventDefault(); doUndo(); return; }
    if((e.ctrlKey||e.metaKey) && !e.altKey && (e.key==='r'||e.key==='R') && !typing){ e.preventDefault(); location.reload(); return; }
    if(typing){ return; }
    if(e.key==='?'){ var kh=document.getElementById('keyhelp'); if(kh){ kh.style.display = kh.style.display==='flex'?'none':'flex'; e.preventDefault(); } return; }
    if(e.key==='Escape'){ ['cmdk','keyhelp','snomenu'].forEach(function(id){ var el=document.getElementById(id); if(el){ el.style.display='none'; } }); closeQC(); }
    var inBatchMode = document.body.classList.contains('batchmode');
    if(e.key==='j'||e.key==='J'){ moveFocus(1); e.preventDefault(); return; }
    if(e.key==='k'||e.key==='K'){ moveFocus(-1); e.preventDefault(); return; }
    var f = curFocus();
    if(!f){ return; }
    if(e.key===' '||e.key==='Enter'||e.key==='d'||e.key==='D'){
      e.preventDefault(); var cb=focusCB(); if(cb){ cb.click(); } return;
    }
    if(e.key==='s'||e.key==='S'){ snoozeOne(1); return; }
    if(e.key==='Delete'){ delOne(); return; }
    if(['1','2','3'].indexOf(e.key)>=0){ setPri(parseInt(e.key,10)); return; }
  });

  /* 批量模式开关 + batchbar 增强(全选/反选/顺延) */
  var bmBtn = document.getElementById('btn-batchmode');
  if(bmBtn){
    bmBtn.addEventListener('click', function(){
      var on = document.body.classList.toggle('batchmode');
      bmBtn.innerHTML = '<i class="ni">☑</i>' + (on ? '退出批量' : '批量模式');
      var bh = document.querySelector('.batchhint'); if(bh){ bh.style.display = on?'':'none'; }
      if(on){ toast('批量模式: 单击任务行选择(上限50), 底部操作栏执行'); }
    });
  }
  var MAXBATCH = 50;
  var origBatchDo = window.batchDo;
  window.batchDo = function(action, value){
    var sel = document.querySelectorAll('.task.sel');
    if(sel.length > MAXBATCH){ toast('一次最多处理 '+MAXBATCH+' 项, 请缩小范围'); return; }
    origBatchDo(action, value);
  };
  window.snoPick = function(days){
    var ids = []; document.querySelectorAll('.task.sel').forEach(function(x){ var cb=x.querySelector('input[type=checkbox]'); if(cb&&!cb.checked){ ids.push(cb.getAttribute('data-id')); } });
    if(!ids.length){ toast('先选中要顺延的任务'); return; }
    post('/api/batch',{action:'snooze',ids:ids,value:days}).then(function(d){ toast(d.ok?('已顺延 '+d.affected+' 条到 '+d.to_date):'顺延失败'); setTimeout(function(){location.reload();},500); });
  };
  window.addEventListener('load', function(){
    var bb = document.getElementById('batchbar');
    if(bb && !bb.dataset.enhanced){
      bb.dataset.enhanced = '1';
      var mk = function(txt,fn){ var b=document.createElement('button'); b.className='btn btn-mini'; b.style.margin='0'; b.textContent=txt; b.addEventListener('click',fn); bb.insertBefore(b, bb.children[1]); };
      mk('全选', function(){ document.querySelectorAll('#pnl-tasks label.task:not(.completed)').forEach(function(x){ x.classList.add('sel'); }); document.getElementById('selcnt').textContent = document.querySelectorAll('.task.sel').length; });
      mk('反选', function(){ document.querySelectorAll('#pnl-tasks label.task').forEach(function(x){ x.classList.toggle('sel'); }); document.getElementById('selcnt').textContent = document.querySelectorAll('.task.sel').length; });
      mk('顺延', function(){ window.snoPick(1); });
    }
  });

  /* ---------- C5: 任务行悬停动作(事件委托, 触屏由 CSS 隐藏) ---------- */
  document.addEventListener('click', function(ev){
    var b5 = ev.target.closest && ev.target.closest('.hact button');
    if(!b5){ return; }
    var lab = ev.target.closest('label.task');
    if(!lab){ return; }
    var act = b5.getAttribute('data-a'), cb = lab.querySelector('input[type=checkbox]');
    if(act==='done' && cb){ cb.click(); }
    else if(act==='edit'){ var td=lab.querySelector('.tdetail'); if(td){ td.classList.add('open'); toast('详细编辑请在 daily 笔记中进行'); } }
    else if(act==='snooze'){ var r=lab.getBoundingClientRect(); var m=document.getElementById('snomenu'); if(m){ m.style.display='block'; m.style.left=Math.round(r.left)+'px'; m.style.top=Math.round(r.bottom+window.scrollY+2)+'px'; m.dataset.target=lab.getAttribute('data-id'); } }
  });
  var snom = document.getElementById('snomenu');
  if(snom){
    snom.addEventListener('click', function(ev){
      var days = parseInt(ev.target.getAttribute('onclick','')&&'',10) || 0;
      if(ev.target.textContent.indexOf('1 天')>=0){ days=1; }
      else if(ev.target.textContent.indexOf('3 天')>=0){ days=3; }
      else if(ev.target.textContent.indexOf('下周')>=0){ days=7; }
      var tid = snom.dataset.target;
      snom.style.display='none';
      if(tid && days){ post('/api/batch',{action:'snooze',ids:[tid],value:days}).then(function(d){ toast(d.ok?('已顺延 '+days+' 天'):'顺延失败'); setTimeout(function(){location.reload();},500); }); }
    });
    document.addEventListener('click', function(ev){ if(!ev.target.closest('#snomenu') && !ev.target.closest('[data-a=snooze]')){ snom.style.display='none'; } });
  }
  /* 复习卡快捷评分条(hover 渲染, 点击带 quality 打卡) */
  document.addEventListener('click', function(ev){
    var qb5 = ev.target.closest && ev.target.closest('.qbar button');
    if(!qb5){ return; }
    var rec = qb5.closest('.rec');
    var con = rec && rec.querySelector('[data-c]');
    if(!con){ return; }
    var q = parseInt(qb5.getAttribute('data-q'),10);
    post('/api/mark_reviewed', {concept: con.getAttribute('data-c'), quality: q}).then(function(d){
      if(d.ok){ rec.style.opacity='.45'; toast('已评分 '+q+'/5 并打卡 ✓'); }
    }).catch(function(){ toast('服务未运行?'); });
  });
})();

if(!window.LH_CONFIG.guideDone){ guideShow(1); }                              // 首次运行自动弹三步引导
