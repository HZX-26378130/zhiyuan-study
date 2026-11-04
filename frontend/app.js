/* 知源学伴 前端逻辑（原生JS，无构建依赖） */
'use strict';

const state = {
  sid: localStorage.getItem('zy_sid') || null,
  students: [],
  boot: null,
  quiz: null,          // 进行中的词汇测验
  paper: null,         // 当前查看的试卷
  handoff: {},         // 跨页面传参（如从仪表盘带知识点去出卷/讲义）
};

const $ = s => document.querySelector(s);
const esc = s => String(s ?? '').replace(/[&<>"']/g, c => ({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));
const fmtTime = ts => ts ? new Date(ts * 1000).toLocaleString('zh-CN', {hour12:false, month:'2-digit', day:'2-digit', hour:'2-digit', minute:'2-digit'}) : '';

async function api(path, opts = {}) {
  const url = '/api/' + path + (opts.query ? '?' + new URLSearchParams(opts.query) : '');
  const init = {method: opts.method || 'GET', headers: {}};
  const token = localStorage.getItem('zy_token');
  if (token) init.headers['Authorization'] = 'Bearer ' + token;
  if (opts.body !== undefined) {
    if (opts.body instanceof FormData) init.body = opts.body;
    else { init.headers['Content-Type'] = 'application/json'; init.body = JSON.stringify(opts.body); }
  }
  // 请求超时：默认 90s（容纳批改/出卷等长任务）；卡住时给出可重试的错误而非永远转圈
  const timeoutMs = opts.timeout || 90000;
  const ctl = new AbortController();
  const timer = setTimeout(() => ctl.abort(), timeoutMs);
  init.signal = ctl.signal;
  let resp;
  try {
    resp = await fetch(url, init);
  } catch (e) {
    clearTimeout(timer);
    throw new Error(e.name === 'AbortError' ? '请求超时了，点重试或检查网络' : '网络连接失败，请检查网络');
  }
  clearTimeout(timer);
  let data = {};
  try { data = await resp.json(); } catch (e) { /* empty */ }
  if (resp.status === 401 && path !== 'auth/login' && path !== 'auth/register') {
    localStorage.removeItem('zy_token');
    localStorage.removeItem('zy_sid');
    state.sid = null;
    if (state.boot && state.boot.auth) { renderLogin('登录已过期，请重新登录'); throw new Error(data.error || '请先登录'); }
  }
  if (!resp.ok) throw new Error(data.error || ('HTTP ' + resp.status));
  return data;
}

function toast(msg, isErr = false) {
  const t = $('#toast');
  t.textContent = msg;
  t.className = 'show' + (isErr ? ' err' : '');
  clearTimeout(t._h);
  t._h = setTimeout(() => t.className = '', 2600);
}

/* 极简 Markdown 渲染（标题/列表/加粗/引用/行内代码） */
function md(text) {
  const lines = String(text ?? '').split('\n');
  let html = '', inUl = false, inOl = false, inQuote = false;
  const closeAll = () => { if (inUl){html+='</ul>';inUl=false;} if (inOl){html+='</ol>';inOl=false;} if (inQuote){html+='</blockquote>';inQuote=false;} };
  const inline = s => esc(s)
    .replace(/`([^`]+)`/g, '<code>$1</code>')
    .replace(/\*\*([^*]+)\*\*/g, '<b>$1</b>')
    .replace(/\*([^*]+)\*/g, '<i>$1</i>');
  for (let raw of lines) {
    const line = raw.trimEnd();
    let m;
    if ((m = line.match(/^#{1,6}\s+(.*)/))) { closeAll(); html += `<h3>${inline(m[1])}</h3>`; }
    else if (/^\s*[-*•]\s+/.test(line)) {
      if (inQuote){html+='</blockquote>';inQuote=false;}
      if (inOl){html+='</ol>';inOl=false;}
      if (!inUl){html+='<ul>';inUl=true;}
      html += `<li>${inline(line.replace(/^\s*[-*•]\s+/,''))}</li>`;
    } else if ((m = line.match(/^\s*\d+[.、)]\s+(.*)/))) {
      if (inQuote){html+='</blockquote>';inQuote=false;}
      if (inUl){html+='</ul>';inUl=false;}
      if (!inOl){html+='<ol>';inOl=true;}
      html += `<li>${inline(m[1])}</li>`;
    } else if ((m = line.match(/^>\s?(.*)/))) {
      if (inUl){html+='</ul>';inUl=false;}
      if (inOl){html+='</ol>';inOl=false;}
      if (!inQuote){html+='<blockquote>';inQuote=true;}
      html += inline(m[1]) + '<br>';
    } else if (line === '') { closeAll(); }
    else { closeAll(); html += `<p>${inline(line)}</p>`; }
  }
  closeAll();
  return html;
}

function levelBadge(level) {
  const map = {'薄弱':'red', '一般':'amber', '良好':'gray', '掌握':'green', '未诊断':'gray'};
  return `<span class="pill ${map[level]||'gray'}">${esc(level)}</span>`;
}

/* 纯 SVG 雷达图：labels[] 名称，values[] 0-100（null=未诊断） */
function radarSVG(labels, values, size = 300) {
  const n = labels.length;
  if (n < 3) return '<div class="muted">维度太少，无法绘制雷达图</div>';
  const cx = size / 2, cy = size / 2 + 4, R = size / 2 - 52;
  const pt = (i, r) => {
    const a = -Math.PI / 2 + i * 2 * Math.PI / n;
    return [cx + r * Math.cos(a), cy + r * Math.sin(a)];
  };
  let rings = '';
  for (let lv = 1; lv <= 4; lv++) {
    const r = R * lv / 4;
    rings += `<polygon points="${labels.map((_, i) => pt(i, r).map(v => v.toFixed(1)).join(',')).join(' ')}" fill="none" stroke="#e3e8f2"/>`;
    if (lv < 4) rings += `<text x="${cx + 4}" y="${(cy - r).toFixed(1)}" font-size="9" fill="#b6bfce">${lv * 25}</text>`;
  }
  let axes = '', lbls = '';
  labels.forEach((lb, i) => {
    const [x, y] = pt(i, R);
    axes += `<line x1="${cx}" y1="${cy}" x2="${x.toFixed(1)}" y2="${y.toFixed(1)}" stroke="#e3e8f2"/>`;
    const [lx, ly] = pt(i, R + 18);
    const anchor = Math.abs(lx - cx) < 14 ? 'middle' : (lx > cx ? 'start' : 'end');
    const v = values[i];
    const short = lb.length > 6 ? lb.slice(0, 6) + '…' : lb;
    lbls += `<title>${esc(lb)}${v == null ? '（未诊断）' : '：' + Math.round(v)}</title><text x="${lx.toFixed(1)}" y="${ly.toFixed(1)}" text-anchor="${anchor}" dominant-baseline="middle" font-size="10.5" fill="${v == null ? '#9aa4b8' : '#3c465c'}" font-weight="${v != null && v < 40 ? '700' : '400'}">${esc(short)}</text>`;
  });
  const val = i => Math.max(0.02, (values[i] == null ? 0 : values[i]) / 100);
  const dataPts = labels.map((_, i) => pt(i, R * val(i)).map(v => v.toFixed(1)).join(',')).join(' ');
  const dots = labels.map((_, i) => {
    const [x, y] = pt(i, R * val(i));
    const v = values[i];
    return `<circle cx="${x.toFixed(1)}" cy="${y.toFixed(1)}" r="3.2" fill="${v == null ? '#fff' : (v < 40 ? '#dc2626' : '#2f5fe8')}" stroke="${v == null ? '#9aa4b8' : '#2f5fe8'}" stroke-width="1.5"/>`;
  }).join('');
  return `<svg viewBox="-30 -14 ${size + 60} ${size + 20}" style="width:100%;max-width:420px;display:block;margin:0 auto">
    ${rings}${axes}
    <polygon points="${dataPts}" fill="rgba(47,95,232,.15)" stroke="#2f5fe8" stroke-width="2" stroke-linejoin="round"/>
    ${dots}${lbls}
  </svg>`;
}

function feedbackBox(module, target) {
  const id = 'fb_' + Math.random().toString(36).slice(2, 8);
  setTimeout(() => {
    const box = document.getElementById(id);
    if (!box) return;
    box.querySelectorAll('button[data-r]').forEach(b => b.onclick = async () => {
      const comment = box.querySelector('input').value.trim();
      await api('feedback', {method:'POST', body:{sid: state.sid, module, target: String(target).slice(0,100), rating: +b.dataset.r, comment}});
      box.innerHTML = '<span class="sent">✓ 已记录反馈，AI 将在反思时吸收</span>';
      toast('反馈已保存');
    });
  });
  return `<div class="fb" id="${id}">
    <button data-r="1" title="有帮助">👍</button><button data-r="-1" title="没帮助">👎</button>
    <input type="text" placeholder="想对AI说的话（可选），如：再举一个例题">
  </div>`;
}

/* ---------------- 导航 ---------------- */
const NAV = [
  {id:'dashboard', icon:'📊', label:'学习仪表盘'},
  {id:'points', icon:'🎯', label:'任务积分'},
  {id:'qa', icon:'🧮', label:'AI 知识问答'},
  {id:'external', icon:'📥', label:'外部AI 引导'},
  {id:'english', icon:'✍️', label:'英语批改'},
  {id:'vocab', icon:'🔤', label:'四六级词汇'},
  {id:'paper', icon:'📝', label:'诊断卷'},
  {id:'bank', icon:'🏦', label:'题库组卷'},
  {id:'plan', icon:'📅', label:'学习计划'},
  {id:'wrongbook', icon:'📕', label:'错题本'},
  {id:'notes', icon:'📖', label:'讲义生成'},
  {id:'kg', icon:'🕸️', label:'知识图谱'},
  {id:'materials', icon:'📁', label:'校本资料库'},
  {id:'memory', icon:'🧠', label:'学习记忆'},
];
const TITLES = {
  dashboard: ['学习仪表盘', '测 · 诊 · 学闭环总览：掌握度、薄弱点与近期动态'],
  points: ['🎯 任务积分', '积分只来自真实学习行为：问答/测验/批改/诊断卷/讲义自动发分，系统任务自动完成'],
  qa: ['AI 知识问答', '线性代数 / 数学分析 · 苏格拉底式引导，先想一步再给答案'],
  external: ['📥 外部AI 引导（借力模式）', '生成引导式提示词 → 带去 DeepSeek 等网页AI → 回答拿回来收纳总结，随时可查'],
  english: ['英语批改', '四六级作文与段落翻译 · 评分标准逐句精批 + 范文'],
  vocab: ['四六级词汇检测', '基于开源词库（CET-4 7508词 / CET-6 5651词），错词自动进生词本'],
  paper: ['知识诊断卷', '按薄弱点自动命题 · 交卷自动批改，错因回写画像'],
  bank: ['🏦 大学数学题库 · 组卷工作台', '本地化大学数学题库：浏览/录入/智能组卷，一键转为可批改试卷'],
  plan: ['📅 学习计划（定路线）', '输入目标与时间 → 逐日课程排期，按掌握度与前置依赖定制，完成发分'],
  wrongbook: ['错题本 · 自动归纳', '批改/测验的错题自动按知识点与错误类型归类，可标记掌握、一键巩固'],
  notes: ['讲义生成', '针对薄弱知识点生成个性化讲义，可结合校本资料'],
  kg: ['知识图谱', '线代 / 数分考点地图与前置依赖'],
  materials: ['校本资料库', '上传本校课件/习题（.txt/.md/.docx/.pdf），问答出卷自动引用'],
  memory: ['学习记忆 · 自我迭代', '偏好指令 + 反馈积累 → 反思策略卡，反哺每次教学（均可编辑修改）'],
  report: ['诊断精讲报告', '错题逐题精讲：考点精讲 · 易错警示 · 同类例题 · 参考资料'],
  admin: ['🛠 管理端', '用户数 · 调用量 · 反馈质量 · 全班薄弱点 · 长期复盘'],
};

function navItems() {
  // 管理端只对管理员本人可见：普通学生连导航项都看不到
  const items = NAV.slice();
  const a = state.boot && state.boot.admin;
  if (a && a.is_admin) {
    items.push({id: 'admin', icon: '🛠', label: '管理端'});
  }
  return items;
}

function renderNav(current) {
  $('#nav').innerHTML = navItems().map(n =>
    `<a href="#/${n.id}" class="${n.id===current?'active':''}"><span>${n.icon}</span><span>${n.label}</span></a>`).join('');
}

async function route() {
  const path = (location.hash || '#/dashboard').replace(/^#\//, '');
  const [view, arg] = path.split('/');
  // 深链：#/settings 直接打开设置弹窗（不占用导航项）
  if (view === 'settings') {
    if (window.__openSettings) window.__openSettings();
    location.replace('#/dashboard');
    return;
  }
  renderNav(view);
  const [t, sub] = TITLES[view] || ['诊断精讲报告', '错题逐题精讲：考点 · 易错 · 同类例题'];
  $('#main').innerHTML = `<h1 class="page-title">${t}</h1><p class="page-sub">${sub}</p><div class="loading">加载中…</div>`;
  try {
    await VIEWS[view](arg);
  } catch (e) {
    $('#main').innerHTML += `<div class="card">加载失败：${esc(e.message)}</div>`;
  }
  const loading = $('#main').querySelector('.loading');
  if (loading) loading.remove();
  window.scrollTo(0, 0);
}

/* 图片上传助手 */
async function uploadImage(sid, file) {
  const fd = new FormData();
  fd.append('sid', sid);
  fd.append('file', file);
  const r = await api('upload/image', {method: 'POST', body: fd});
  const res = r.results && r.results[0];
  if (!res || res.error) throw new Error((res && res.error) || '图片上传失败');
  return res;
}

/* 图片附件组件：返回 {html, bind} */
function imagePicker(id) {
  const st = {file: null, previewUrl: ''};
  return {
    state: st,
    html: `<div class="rowline noprint">
      <input type="file" id="${id}-file" accept="image/png,image/jpeg,image/webp" style="display:none">
      <button class="btn small ghost" id="${id}-btn" type="button">📷 拍照/截图上传题目图片</button>
      <span class="muted" id="${id}-name"></span>
      <img id="${id}-prev" style="display:none;max-height:64px;border-radius:8px;border:1px solid var(--line)">
      <button class="btn small danger" id="${id}-clear" style="display:none" type="button">移除</button>
    </div>`,
    bind(onChange) {
      const btn = document.getElementById(id + '-btn');
      const input = document.getElementById(id + '-file');
      btn.onclick = () => input.click();
      input.onchange = async () => {
        if (!input.files.length) return;
        try {
          const r = await uploadImage(state.sid, input.files[0]);
          st.file = r.file;
          st.previewUrl = r.url;
          document.getElementById(id + '-name').textContent = '已上传：' + r.name;
          const prev = document.getElementById(id + '-prev');
          prev.src = r.url; prev.style.display = '';
          document.getElementById(id + '-clear').style.display = '';
          if (onChange) onChange(st.file);
          toast('图片已上传' + (state.boot.llm ? '' : '（离线模式无法识别图片文字，可先配好API）'));
        } catch (e) { toast(e.message, true); }
      };
      document.getElementById(id + '-clear').onclick = () => {
        st.file = null;
        document.getElementById(id + '-prev').style.display = 'none';
        document.getElementById(id + '-name').textContent = '';
        document.getElementById(id + '-clear').style.display = 'none';
        if (onChange) onChange(null);
      };
    }
  };
}

/* ---------------- 初始化 ---------------- */
function renderLogin(msg) {
  $('#main').innerHTML = `
    <div class="card" style="max-width:420px;margin:60px auto">
      <h3>🔐 登录 知源学伴</h3>
      ${msg ? `<div class="mt muted">${esc(msg)}</div>` : ''}
      <div class="mt"><label>用户名</label><input id="li-name" style="width:100%;padding:9px 12px;border:1px solid #d5dae8;border-radius:8px" placeholder="2-20个字符"></div>
      <div class="mt"><label>密码</label><input id="li-pass" type="password" style="width:100%;padding:9px 12px;border:1px solid #d5dae8;border-radius:8px" placeholder="至少6位"></div>
      <div class="mt rowline">
        <button class="btn" id="li-go">登录</button>
        <button class="btn ghost" id="li-reg">注册新账号</button>
      </div>
      <div id="li-msg" class="mt muted"></div>
      <div class="mt muted" style="font-size:12px">云端模式：注册即创建独立学习档案，数据存云端数据库。</div>
    </div>`;
  const go = async (isReg) => {
    const name = $('#li-name').value.trim(), pass = $('#li-pass').value;
    if (!name || !pass) { $('#li-msg').textContent = '请填写用户名和密码'; return; }
    $('#li-msg').textContent = isReg ? '注册中…' : '登录中…';
    try {
      const r = await api(isReg ? 'auth/register' : 'auth/login', {method: 'POST', body: {name, password: pass}});
      localStorage.setItem('zy_token', r.token);
      localStorage.setItem('zy_sid', r.uid);
      state.sid = r.uid;
      toast((isReg ? '注册' : '登录') + '成功：' + r.name);
      state.boot = await api('bootstrap');
      await loadStudents();
      location.hash = '#/dashboard';
      route();
      if (!localStorage.getItem('zy_tour_done')) setTimeout(() => startTour(0), 900);
    } catch (e) { $('#li-msg').textContent = e.message; }
  };
  $('#li-go').onclick = () => go(false);
  $('#li-reg').onclick = () => go(true);
  $('#li-pass').addEventListener('keydown', e => { if (e.key === 'Enter') go(false); });
}

async function init() {
  state.boot = await api('bootstrap');
  // 本地存过管理员口令时，向服务端确认「我到底是不是管理员」，确认后才显示入口
  if (state.boot.admin && state.boot.admin.mode === 'token' && localStorage.getItem('zy_admin_token')) {
    try {
      const a = await api('admin/whoami', {query: adminQ()});
      state.boot.admin = a;
      if (!a.is_admin) localStorage.removeItem('zy_admin_token');
    } catch (e) { localStorage.removeItem('zy_admin_token'); }
  }
  const badge = $('#llm-badge');
  if (state.boot.llm) { badge.className = 'badge-on'; badge.textContent = '● 大模型已接入'; }
  if (state.boot.auth) {
    const token = localStorage.getItem('zy_token');
    if (!token) { renderLogin(); window.addEventListener('hashchange', route); setupSettings();
      $('#btn-tour').onclick = () => startTour(0);   // 登录页提前返回，也要绑上引导按钮
      return; }
    // 账号模式：显示账号信息与退出按钮，但**必须保留** #student-select / #btn-add-student
    // （隐藏起来即可）。早先这里直接重写 #student-box 的 innerHTML 会把它们一起删掉，
    // 随后 loadStudents() 写 #student-select.innerHTML 就是 null → 登录后必然崩。
    $('#student-box').innerHTML = `<label>账号</label>
      <div class="row"><input value="已登录" disabled style="flex:1"></div>
      <button id="btn-logout" title="退出登录" style="margin-top:6px;width:100%;border:none;border-radius:8px;padding:6px;background:#f2f4fa;cursor:pointer;font-size:12px">退出登录</button>
      <div style="display:none"><select id="student-select"></select><button id="btn-add-student" title="新建档案">＋</button></div>`;
    const lo = document.getElementById('btn-logout');
    if (lo) lo.onclick = () => { localStorage.removeItem('zy_token'); localStorage.removeItem('zy_sid'); location.reload(); };
  }
  await loadStudents();
  if (!state.sid && state.students.length) { state.sid = state.students[0].id; localStorage.setItem('zy_sid', state.sid); }
  const selBox = $('#student-select');
  if (selBox) {
    selBox.value = state.sid || '';
    selBox.onchange = e => { state.sid = e.target.value; localStorage.setItem('zy_sid', state.sid); route(); };
  }
  const addBtn = $('#btn-add-student');
  if (addBtn) addBtn.onclick = async () => {
    const name = prompt('新档案名称（学生姓名）：');
    if (!name) return;
    const r = await api('students', {method:'POST', body:{name}});
    await loadStudents();
    state.sid = r.id; localStorage.setItem('zy_sid', state.sid);
    if ($('#student-select')) $('#student-select').value = state.sid;
    toast('已创建档案：' + name);
    route();
  };
  window.addEventListener('hashchange', route);
  setupSettings();
  $('#btn-tour').onclick = () => startTour(0);
  if (state.boot.auth && !state.sid) { renderLogin(); return; }
  route();
  if (!localStorage.getItem('zy_tour_done')) setTimeout(() => startTour(0), 900);
}

/* ---------------- API 接入设置弹窗 ---------------- */
const PRESETS = {
  zhipu: {base: 'https://open.bigmodel.cn/api/paas/v4', model: 'glm-4-flash', vision: 'glm-4v-flash',
          note: '🆓 智谱开放平台 <a href="https://open.bigmodel.cn" target="_blank">open.bigmodel.cn</a> 注册即送额度，glm-4-flash / glm-4v-flash 长期免费（推荐，国内直连稳定）'},
  pollinations: {base: 'https://text.pollinations.ai/openai', model: 'openai', vision: 'openai',
                 note: '🆓 <b>完全免Key</b>（Pollinations 公益服务，无需注册）。公共通道速度/稳定性一般，且依赖网络环境；视觉能力视其后端而定。点「测试连接」验证当前网络可用性。'},
  siliconflow: {base: 'https://api.siliconflow.cn/v1', model: 'Qwen/Qwen2.5-7B-Instruct', vision: 'Qwen/Qwen2.5-VL-7B-Instruct',
                note: '🆓 硅基流动 <a href="https://cloud.siliconflow.cn" target="_blank">cloud.siliconflow.cn</a> 注册送额度，小模型免费档'},
  deepseek: {base: 'https://api.deepseek.com', model: 'deepseek-chat', vision: '',
             note: 'DeepSeek <a href="https://platform.deepseek.com" target="_blank">platform.deepseek.com</a> 官方API价格低；网页版无法直接接入，请使用API Key'},
  qwen: {base: 'https://dashscope.aliyuncs.com/compatible-mode/v1', model: 'qwen-plus', vision: 'qwen-vl-plus',
         note: '阿里云百炼 <a href="https://bailian.console.aliyun.com" target="_blank">bailian.console.aliyun.com</a> 新用户有免费额度'},
  ollama: {base: 'http://127.0.0.1:11434/v1', model: 'qwen2.5:7b', vision: '',
           note: '🆓 本地 Ollama：<a href="https://ollama.com" target="_blank">ollama.com</a> 安装后 `ollama pull qwen2.5:7b`，完全免Key、离线、免费（需要本机安装运行）'},
  // 自建 CloudBase 网关等自托管代理，请用下面的「自定义」填自己的地址与 Key
  custom: {base: '', model: '', vision: '', note: '填写任意 OpenAI 兼容接口（含自建代理/中转/本地部署）'},
};

function setupSettings() {
  const modal = $('#settings-modal');
  const badge = $('#llm-badge');
  const open = async () => {
    const c = await api('config');
    $('#cfg-base').value = c.llm.base_url || '';
    $('#cfg-model').value = c.llm.model || '';
    $('#cfg-vmodel').value = c.llm.vision_model || '';
    $('#cfg-key').value = '';
    $('#cfg-key').placeholder = c.llm.has_key ? ('已保存：' + c.llm.key_masked + '（留空保留）') : '粘贴你的 API Key';
    $('#cfg-skey').value = '';
    $('#cfg-skey').placeholder = c.search.has_key ? '已保存搜索Key（留空保留）' : 'bocha api key';
    $('#cfg-test-result').textContent = '';
    applyPreset($('#cfg-preset').value, false);
    renderFallback(c.llm.fallback || []);
    renderChannels(c.channels);
    modal.style.display = 'flex';
  };

  /* ---------- 兜底通道链可视化编辑 ---------- */
  function fbRow(it = {}) {
    const row = document.createElement('div');
    row.className = 'fb-row';
    row.style.cssText = 'display:grid;grid-template-columns:1.4fr 1fr 1fr auto;gap:6px;margin-bottom:6px;align-items:center';
    row.innerHTML = `
      <input type="text" class="fb-base" placeholder="base_url（https://…）" value="${esc(it.base_url || '')}"
             style="padding:7px 9px;border:1px solid #d5dae8;border-radius:7px;font-size:12px">
      <input type="text" class="fb-model" placeholder="model" value="${esc(it.model || '')}"
             style="padding:7px 9px;border:1px solid #d5dae8;border-radius:7px;font-size:12px">
      <input type="text" class="fb-vision" placeholder="vision_model（可空）" value="${esc(it.vision_model || '')}"
             style="padding:7px 9px;border:1px solid #d5dae8;border-radius:7px;font-size:12px">
      <button type="button" class="btn small danger fb-del" title="删除这条">✕</button>`;
    row.querySelector('.fb-del').onclick = () => row.remove();
    // 该条通道自己的 Key（留空=免 Key 端点，或不继承主 Key）
    const keyInput = document.createElement('input');
    keyInput.type = 'password';
    keyInput.className = 'fb-key';
    keyInput.placeholder = it.has_key ? '已保存 Key（留空保留）' : 'api_key（免 Key 端点可空）';
    keyInput.style.cssText = 'grid-column:1 / span 3;padding:6px 9px;border:1px solid #eef0f6;border-radius:7px;font-size:12px;margin-top:-2px';
    row.appendChild(keyInput);
    return row;
  }

  function renderFallback(list) {
    const box = $('#cfg-fb-list');
    if (!box) return;
    box.innerHTML = '';
    (list || []).forEach(it => box.appendChild(fbRow(it)));
    if (!(list || []).length) {
      box.innerHTML = '<div class="muted" style="font-size:12px;margin-bottom:4px">' +
        '当前没有兜底通道（主通道失败就直接报错）</div>';
    }
  }

  function collectFallback() {
    const out = [];
    document.querySelectorAll('#cfg-fb-list .fb-row').forEach(row => {
      const base = row.querySelector('.fb-base').value.trim();
      if (!base) return;                        // 空行忽略
      const it = {
        base_url: base,
        model: row.querySelector('.fb-model').value.trim(),
        vision_model: row.querySelector('.fb-vision').value.trim(),
      };
      const key = row.querySelector('.fb-key').value.trim();
      if (key) it.api_key = key;                // 留空 = 不覆盖已保存的 Key
      out.push(it);
    });
    return out;
  }

  const addBtn = $('#cfg-fb-add');
  if (addBtn) addBtn.onclick = () => {
    const box = $('#cfg-fb-list');
    if (box.querySelector('.muted')) box.innerHTML = '';
    box.appendChild(fbRow({}));
  };
  /* 主通道 + 免费兜底链的实时状态：欠费/限流会显示熔断倒计时 */
  function renderChannels(chans) {
    const box = $('#cfg-channels');
    if (!box) return;
    if (!chans || !chans.length) { box.innerHTML = ''; return; }
    box.innerHTML = '<div class="muted" style="margin-bottom:4px">调用链（失败自动降级）</div>' +
      chans.map(c => {
        const state = c.tripped_for > 0
          ? `<span style="color:#c0392b">✗ 失败，${c.tripped_for}s 后重试</span>`
          : '<span style="color:#27ae60">● 可用</span>';
        return `<div>${c.role === '主通道' ? '①' : '↳'} <b>${esc(c.name)}</b>` +
               `${c.model ? ' · ' + esc(c.model) : ''} ${state}</div>`;
      }).join('');
  }
  badge.onclick = open;
  $('#btn-settings').onclick = open;
  window.__openSettings = open;      // 支持 #/settings 深链直接打开设置弹窗
  $('#settings-close').onclick = () => modal.style.display = 'none';
  modal.onclick = e => { if (e.target === modal) modal.style.display = 'none'; };
  function applyPreset(key, showNote = true) {
    const p = PRESETS[key] || PRESETS.custom;
    if (p.base) $('#cfg-base').value = p.base;
    if (p.model) $('#cfg-model').value = p.model;
    $('#cfg-vmodel').value = p.vision || '';
    if (p.key) { $('#cfg-key').value = p.key; $('#cfg-key').placeholder = '已自动填入共享Key'; }
    $('#cfg-links').innerHTML = p.note || '';
  }
  $('#cfg-preset').onchange = e => applyPreset(e.target.value);
  $('#cfg-save').onclick = async () => {
    const body = {llm: {base_url: $('#cfg-base').value.trim(), model: $('#cfg-model').value.trim(),
                        vision_model: $('#cfg-vmodel').value.trim(),
                        fallback: collectFallback()},   // 可视化编辑的兜底链，整条覆盖
                  search: {provider: $('#cfg-skey').value.trim() ? 'bocha' : ''}};
    if ($('#cfg-key').value.trim()) body.llm.api_key = $('#cfg-key').value.trim();
    if ($('#cfg-skey').value.trim()) body.search.api_key = $('#cfg-skey').value.trim();
    await api('config', {method: 'POST', body});
    await refreshBoot();
    modal.style.display = 'none';
    toast(state.boot.llm ? '已接入大模型 ✓' : '已保存（当前离线模式）');
    route();
  };
  $('#cfg-test').onclick = async () => {
    $('#cfg-test-result').textContent = '测试中…';
    if ($('#cfg-key').value.trim()) {
      await api('config', {method: 'POST', body: {llm: {base_url: $('#cfg-base').value.trim(), model: $('#cfg-model').value.trim(), api_key: $('#cfg-key').value.trim()}}});
    }
    const r = await api('config/test', {method: 'POST', body: {}});
    $('#cfg-test-result').textContent = r.ok ? ('✓ 连接成功：' + r.reply + (r.channel ? '（' + r.channel + '）' : '')) : ('✗ ' + r.error);
    renderChannels(r.channels);
    if (r.ok) await refreshBoot();
  };
  $('#cfg-backup').onclick = () => { window.open('/api/backup'); toast('已开始下载学习数据备份 zip'); };
}

async function refreshBoot() {
  state.boot = await api('bootstrap');
  const badge = $('#llm-badge');
  if (state.boot.llm) { badge.className = 'badge-on'; badge.textContent = '● 大模型已接入'; }
  else { badge.className = 'badge-off'; badge.textContent = '● 离线演示模式'; }
}

async function loadStudents() {
  const r = await api('students');
  state.students = r.students;
  if (!state.students.length) {
    const r2 = await api('students', {method:'POST', body:{name:'我的档案'}});
    state.students = [r2.summary];
    state.sid = r2.id; localStorage.setItem('zy_sid', state.sid);
  }
  if (!state.students.find(s => s.id === state.sid)) state.sid = state.students[0].id;
  const sel = $('#student-select');
  if (sel) {   // 账号模式下该元素被隐藏但仍在，这里再做一层防御
    sel.innerHTML = state.students.map(s => `<option value="${s.id}">${esc(s.name)}</option>`).join('');
    sel.value = state.sid || '';
  }
  $('#student-select').value = state.sid || '';
}

const VIEWS = {};

/* ================= 仪表盘 ================= */
VIEWS.dashboard = async () => {
  const d = await api('dashboard', {query:{sid: state.sid}});
  let radarSubject = sessionStorage.getItem('zy_radar_subject') || 'linear_algebra';
  let kgData = await api('knowledge', {query:{sid: state.sid, subject: radarSubject}});
  const s = d.summary;
  const stat = (num, lbl) => `<div class="stat"><div class="num">${num}</div><div class="lbl">${lbl}</div></div>`;
  const subjMeters = Object.entries(s.avg_by_subject).map(([k, v]) => {
    const name = (state.boot.subjects[k] || '英语') + ' 平均';
    return `<div class="stat"><div class="num">${v}</div><div class="lbl">${esc(name)}（0-100）</div>
      <div class="meter"><i style="width:${Math.max(3,v)}%"></i></div></div>`;
  }).join('') || '<div class="muted">暂无掌握度数据，先去问答或测验吧</div>';
  const weakRows = d.weak.length ? d.weak.map((w, i) => `
    <tr><td>${esc(w.name)}</td><td>${esc(state.boot.subjects[w.subject]||w.subject)}</td>
    <td>${w.score} ${levelBadge(w.level)}</td>
    <td class="noprint">
      <button class="btn small ghost" onclick="window.__toNotes('${w.subject}','${w.id}')">讲义</button>
      <button class="btn small ghost" onclick="window.__toPaper('${w.subject}','${w.id}')">出卷</button>
      <button class="btn small ghost" title="加入今日任务，完成后自动得分" onclick="window.__weakToTask(${i})">➕任务</button>
    </td></tr>`).join('') : '<tr><td colspan="4" class="muted">暂无薄弱点数据</td></tr>';
  const events = d.history.map(h => {
    const map = {qa:'💬 问答', quiz:'🔤 词汇', paper_grade:'📝 试卷批改', english:'✍️ 批改', reflect:'🧠 反思', material:'📁 资料上传'};
    let txt = h.q || h.summary || h.name || '';
    if (h.type === 'quiz') txt = `${h.level.toUpperCase()} 答对 ${h.right}/${h.total}`;
    if (h.type === 'paper_grade') txt = `得分 ${h.score}`;
    if (h.type === 'english') txt = `${h.kind==='writing'?'作文':'翻译'} 得分 ${h.score ?? '—'}`;
    return `<li><span class="t">${fmtTime(h.ts)}</span>${map[h.type]||h.type} ${esc(String(txt).slice(0,60))}</li>`;
  }).join('') || '<li class="muted">暂无动态</li>';
  const mem = d.memory;
  $('#main').innerHTML += `
    <div class="grid c3">
      ${stat(s.kp_count, '触及知识点数')}${stat(s.stats.qa, 'AI 问答次数')}${stat(s.stats.graded, '批改次数')}
      ${stat(s.stats.quiz_done, '词汇测验次数')}${stat(s.stats.papers_done, '完成诊断卷')}${stat(s.stats.notes, '生成讲义')}
    </div>
    <div class="mt"></div>
    <div class="grid c2">
      <div>
        <div class="card"><div class="rowline" style="justify-content:space-between;align-items:center"><h3 style="margin:0">🕸️ 知识点雷达图</h3><div class="rowline" id="radar-subjects"></div></div>
          <div id="radar-box"></div>
          <div class="muted">数值 = 掌握度（0-100）；灰点 = 未诊断；红点 = 薄弱（&lt;40）。悬停看全名，薄弱方向越凹越要补。</div>
        </div>
        <div class="card"><h3>各科目平均掌握度</h3>${subjMeters}</div>
        <div class="card"><h3>🎯 薄弱点 TOP（点击直接出讲义/诊断卷）</h3>
          <table class="tbl"><tr><th>知识点</th><th>科目</th><th>掌握度</th><th class="noprint">行动</th></tr>${weakRows}</table></div>
      </div>
      <div>
        ${d.points ? `<div class="card"><h3>🎯 任务积分</h3>
          <div class="rowline" style="gap:18px">
            <div><span class="muted">可用</span><b style="font-size:20px;color:var(--brand)">${d.points.balance}</b></div>
            <div><span class="muted">今日</span><b>${d.points.today}${d.points.goal ? '/' + d.points.goal : ''}</b></div>
            <div><span class="muted">连续达标</span><b>${d.points.streak} 天</b></div>
          </div>
          <div class="mt"><button class="btn small" onclick="location.hash='#/points'">去任务积分 →</button></div>
        </div>` : ''}
        <div id="dash-plan-slot"></div>
        <div id="dash-review-slot"></div>
        <div class="card"><h3>📋 AI 学习周报</h3>
          <div class="muted">汇总近 7 天问答/测验/批改/积分/错题行为，生成亮点、薄弱信号与下周建议。</div>
          <div id="wk-box" class="mt"></div>
          <div class="mt"><button class="btn small" id="wk-btn">生成本周报告</button></div>
        </div>
        <div class="card"><h3>🧠 学习记忆（自我迭代）</h3>
          <div class="muted">持久指令 ${mem.preferences.length} 条 · 反馈 ${mem.feedback.length} 条</div>
          ${mem.strategy ? `<h4>当前策略卡（${fmtTime(mem.strategy_updated)}）</h4><div class="md">${md(mem.strategy)}</div>` : '<div class="muted mt">尚无策略卡，积累反馈后点击「反思」生成</div>'}
          <div class="mt"><button class="btn ghost" onclick="location.hash='#/memory'">管理记忆 / 触发反思</button></div>
        </div>
        <div class="card"><h3>🕐 近期动态</h3><ul class="timeline">${events}</ul></div>
      </div>
    </div>
    ${d.llm ? '' : '<div class="offline-tip">💡 当前为离线演示模式：内置知识图谱、启发式批改与开源词库均可使用。在 config.json 填入大模型 API Key 后即可获得完整 AI 能力。</div>'}`;
  window.__toNotes = (subject, kid) => { state.handoff.notesKps = [kid]; state.handoff.notesSubject = subject; location.hash = '#/notes'; };
  window.__toPaper = (subject, kid) => { state.handoff.paperKps = [kid]; state.handoff.paperSubject = subject; location.hash = '#/paper'; };
  window.__weakToTask = async (i) => {
    const w = d.weak[i];
    if (!w) return;
    try {
      await api('points/task', {method: 'POST', body: {sid: state.sid,
        title: '复习「' + w.name + '」（讲义 + 诊断卷）', cat: '学习', pri: 1, pts: 10,
        repeat: 'day', dueT: '21:00', source: 'zy:kp:' + w.subject + ':' + w.id}});
      toast('已加入今日任务（完成讲义/诊断卷后自动得分）');
    } catch (e) { toast(e.message, true); }
  };
  // 计划/复习摘要异步填充（后端已从 dashboard 主数据解耦，不阻塞首屏）
  const planSlot = document.getElementById('dash-plan-slot');
  const revSlot = document.getElementById('dash-review-slot');
  if (planSlot) api('plan', {query: {sid: state.sid}}).then(r => {
    const p = r.plan;
    if (!p) {
      planSlot.innerHTML = `<div class="card"><h3>📅 学习计划</h3>
        <div class="muted">还没有逐日计划。输入目标与时间，自动排出每天该学什么。</div>
        <div class="mt"><button class="btn small" onclick="location.hash='#/plan'">创建学习计划 →</button></div></div>`;
      return;
    }
    planSlot.innerHTML = `<div class="card"><h3>📅 今日学习</h3>
      <div class="muted">${esc(p.subject_name)} · 进度 ${p.done_n}/${p.total_n} 天</div>
      <div class="mt"><b>D${p.today_day || '✓'}</b> ${esc(p.today_title)}</div>
      ${p.pace_warning ? `<div class="muted mt" style="color:var(--bad)">${esc(p.pace_warning)}</div>` : ''}
      <div class="mt"><button class="btn small" onclick="location.hash='#/plan'">去学习计划 →</button></div></div>`;
  }).catch(() => { planSlot.innerHTML = ''; });
  if (revSlot) api('review/due', {query: {sid: state.sid}}).then(r => {
    if (!r.due_n) { revSlot.innerHTML = ''; return; }
    revSlot.innerHTML = `<div class="card"><h3>🔁 今日复习</h3>
      <div class="muted"><b style="color:var(--bad)">${r.due_n}</b> 道错题到了遗忘曲线复做点（1/3/7/14 天）：</div>
      <ul class="mt" style="margin:6px 0 0">${(r.items || []).slice(0, 3).map(x =>
        `<li>${esc((x.kp_name || x.category) + '：' + x.stem.slice(0, 26))}${x.due_days_ago > 0.2 ? `<span class="muted">（过期 ${Math.round(x.due_days_ago)} 天）</span>` : ''}</li>`).join('')}</ul>
      <div class="mt"><button class="btn small" onclick="location.hash='#/wrongbook'">去复习（AI变式重练）→</button></div></div>`;
  }).catch(() => { revSlot.innerHTML = ''; });
  const wkBtn = document.getElementById('wk-btn');
  if (wkBtn) wkBtn.onclick = async () => {
    wkBtn.disabled = true;
    wkBtn.textContent = '生成中…（聚合行为数据 + AI 撰写）';
    try {
      const r = await api('weekly', {query: {sid: state.sid}});
      document.getElementById('wk-box').innerHTML = `<div class="md">${md(r.report)}</div>
        <div class="muted" style="margin-top:6px">${r.offline ? '（离线规则版 · 接入AI后更智能）' : 'AI 生成'} · 本周错题 +${r.metrics.wrongNew}/解决 ${r.metrics.wrongResolved} · 未解决 ${r.metrics.wrongOpen}</div>`;
      wkBtn.textContent = '重新生成';
    } catch (e) {
      document.getElementById('wk-box').innerHTML = `<span class="muted">${esc(e.message || '生成失败')}</span>`;
      wkBtn.textContent = '生成本周报告';
    }
    wkBtn.disabled = false;
  };
  function renderRadar() {
    const box = $('#radar-subjects');
    if (!box) return;
    box.innerHTML = Object.entries(state.boot.subjects).map(([k, v]) =>
      `<button class="btn small ${k === radarSubject ? '' : 'ghost'}" data-rs="${k}">${v}</button>`).join('');
    $('#radar-box').innerHTML = radarSVG(kgData.kps.map(k => k.name), kgData.kps.map(k => k.score));
    box.querySelectorAll('button[data-rs]').forEach(b => b.onclick = async () => {
      radarSubject = b.dataset.rs;
      sessionStorage.setItem('zy_radar_subject', radarSubject);
      kgData = await api('knowledge', {query: {sid: state.sid, subject: radarSubject}});
      renderRadar();
    });
  }
  renderRadar();
};

/* ================= 任务积分 ================= */
let _ptsFilter = '全部';
let _ptsTimer = null;
const _dayKey = ts => new Date(ts).toLocaleDateString('sv');

function _dueOf(t) {
  if (!t.repeat || t.repeat === 'none') return t.due || null;
  if (!t.dueT) return null;
  const [h, mi] = t.dueT.split(':').map(Number);
  const d = new Date();
  if (t.repeat === 'day') { d.setHours(h, mi, 0, 0); return d.getTime(); }
  d.setDate(d.getDate() + ((t.dueW == null ? 1 : t.dueW) - ((d.getDay() + 6) % 7)));
  d.setHours(h, mi, 0, 0);
  return d.getTime();
}

function _cdText(ms) {
  if (ms <= 0) return '<span class="pill red">已逾期</span>';
  const s = Math.floor(ms / 1000), d = Math.floor(s / 86400), h = Math.floor(s % 86400 / 3600), m = Math.floor(s % 3600 / 60), x = s % 60;
  const p = n => String(n).padStart(2, '0');
  return d ? `<span class="pill red">剩 ${d}天 ${p(h)}:${p(m)}:${p(x)}</span>` : `剩 ${p(h)}:${p(m)}:${p(x)}`;
}

function _goSource(src) {
  const parts = src.split(':');
  if (src.startsWith('zy:kp:')) {
    state.handoff.notesKps = [parts[3]];
    state.handoff.notesSubject = parts[2];
    location.hash = '#/notes';
  } else if (src === 'zy:paper') location.hash = '#/paper';
  else if (src === 'zy:quiz') location.hash = '#/vocab';
  else if (src === 'zy:english') location.hash = '#/english';
  else if (src === 'zy:qa') location.hash = '#/qa';
  else if (src === 'zy:notes') location.hash = '#/notes';
}

VIEWS.points = async () => {
  $('#main').innerHTML += `<div id="pts-wrap"></div>`;
  let D = null;
  async function refresh() {
    D = await api('points', {query: {sid: state.sid}});
    render();
  }
  async function act(path, body, confirmMsg) {
    if (confirmMsg && !confirm(confirmMsg)) return;
    try {
      D = await api(path, {method: 'POST', body: Object.assign({sid: state.sid}, body)});
      render();
    } catch (e) { toast(e.message, true); }
  }

  function tipInfo() {
    const st = D.stats, g = st.goal, tp = st.today;
    if (g <= 0) return {c: 'warn', h: '还没设置<b>每日积分要求</b>：设置后这里会显示连续达标天数。'};
    const runs = st.runs || [], last = runs[runs.length - 1];
    const tk = _dayKey(Date.now()), yk = _dayKey(Date.now() - 86400000);
    if (last && _dayKey(last.end) === tk) return {c: 'ok', h: `✅ 今日已达标（${tp}/${g} 分），已连续 <b>${last.n}</b> 天。`};
    if (last && _dayKey(last.end) === yk) return {c: 'warn', h: `⚠️ 已连续 <b>${last.n}</b> 天达标，今天还差 <b>${g - tp}</b> 分（${tp}/${g}）。今天不完成，连击将在 24:00 中断。`};
    if (last) return {c: 'bad', h: `💔 连续达标中断了：上次连续 <b>${last.n}</b> 天。今天拿满 ${g} 分即可重新开始（也可在下方补签，每周 2 次）。`};
    return {c: 'warn', h: '今天还没有积分（0/' + g + '）：做一次问答 / 词汇测验 / 批改，就开始第一天的连续达标。'};
  }

  function render() {
    if (_ptsTimer) { clearInterval(_ptsTimer); _ptsTimer = null; }
    const st = D.stats, tip = tipInfo();
    const today = _dayKey(Date.now());
    // 14 天柱状图
    const g = st.goal;
    const days = [];
    for (let i = 13; i >= 0; i--) {
      const d = new Date(); d.setDate(d.getDate() - i);
      const k = _dayKey(d);
      days.push({k, v: (st.dayMap || {})[k] || 0, lb: (d.getMonth() + 1) + '/' + d.getDate(), tk: k === today});
    }
    const max = Math.max(g, 1, ...days.map(x => x.v));
    const chart = days.map(x => `<div class="col" title="${x.k}：${x.v} 分">
      <div class="bwrap"><i class="${x.v >= g && g > 0 ? 'hit' : ''} ${x.tk ? 'today' : ''}" style="height:${x.v ? Math.max(4, x.v / max * 100) : 0}%"></i></div>
      <span class="lb">${x.lb}</span></div>`).join('');
    const gline = g > 0 ? `<div class="gline" style="bottom:${20 + g / max * 108}px"><span>目标 ${g}</span></div>` : '';
    // 热力图（近16周）
    const hm = [];
    const start = new Date(); start.setDate(start.getDate() - 111);
    while (start.getTime() <= Date.now()) {
      const k = _dayKey(start), v = (st.dayMap || {})[k] || 0;
      const lv = !v ? 0 : (g >= 1 ? (v >= g ? 3 : (v >= g / 2 ? 2 : 1)) : 3);
      hm.push(`<i class="l${lv}${k === today ? ' today' : ''}" title="${k}：${v} 分"></i>`);
      start.setDate(start.getDate() + 1);
    }
    // 任务
    const f = _ptsFilter;
    const isRep = t => t.repeat === 'day' || t.repeat === 'week';
    const inCat = t => f === '全部' || (t.cat || '默认') === f;
    const tucked = D.tasks.filter(t => inCat(t) && isRep(t) && t.done);
    const arr = D.tasks.filter(t => inCat(t) && !((isRep(t) && t.done)))
      .sort((a, b) => (a.done - b.done) || (a.pri - b.pri) || ((_dueOf(a) ?? 9e15) - (_dueOf(b) ?? 9e15)));
    const bar = tucked.length ? `<div class="muted" style="background:var(--brand-soft);border-radius:8px;padding:6px 10px;margin-bottom:6px">✅ 本周期已完成 ${tucked.length} 项重复任务，到点自动重置（历史积分保留）</div>` : '';
    const catChips = ['全部', ...D.cats].map(c =>
      `<button class="btn small ${c === f ? '' : 'ghost'}" data-act="filter" data-cat="${esc(c)}">${esc(c)}</button>`).join('');
    const taskRows = arr.length ? arr.map(t => {
      const due = _dueOf(t);
      const srcBtn = t.source ? `<button class="btn small" data-act="goto" data-src="${esc(t.source)}">去做 →</button> <span class="pill gray">系统任务</span>` : '';
      return `<li>
      <input type="checkbox" data-act="toggle" data-id="${t.id}" data-title="${esc(t.title)}" ${t.done ? 'checked' : ''} style="width:18px;height:18px;accent-color:var(--ok)">
      <div class="grow ${t.done ? 'done' : ''}">
        <div>${esc(t.title)}</div>
        <div class="dim"><span class="pill ${t.pri === 1 ? 'red' : t.pri === 2 ? 'amber' : 'gray'}">${['', '高', '中', '低'][t.pri]}</span>
        <span class="pill gray">${esc(t.cat || '默认')}</span>
        ${t.repeat !== 'none' ? `<span class="pill gray">🔁${t.repeat === 'day' ? '每日' : '每周'}${t.dueT ? ' ' + t.dueT : ''}</span>` : ''}
        <span class="pts">+${t.pts}分</span>
        ${t.done ? '<span class="muted">已完成</span>' : (due ? `<span data-due="${due}"></span> <span class="muted">· ${new Date(due).toLocaleString('zh-CN', {month: '2-digit', day: '2-digit', hour: '2-digit', minute: '2-digit'})}</span>` : '')}</div>
      </div>
      ${srcBtn}
      <button class="btn small danger" data-act="delTask" data-id="${t.id}">✕</button></li>`;
    }).join('') : '<div class="muted" style="padding:6px 0">当前分类下没有任务</div>';
    // 奖励
    const rewardRows = D.rewards.length ? D.rewards.map(r => {
      const used = D.spent.filter(x => x.rid === r.id && (r.period === 'none' || (r.period === 'day' ? _dayKey(x.t) === today : x.t >= _weekStartTs()))).length;
      const limited = r.period !== 'none';
      const left = limited ? Math.max(0, r.limit - used) : Infinity;
      const can = st.balance >= r.cost && (!limited || left > 0);
      return `<li>
      <div class="grow">🎁 ${esc(r.name)} <b class="pts">${r.cost} 分</b>
        <span class="muted">已兑 ${used}${limited ? '/' + r.limit : '/∞'}</span>
        ${limited && left <= 0 ? '<span class="pill red">已达上限</span>' : ''}</div>
      <select class="btn small ghost" data-act="rw" data-id="${r.id}" data-k="period" style="width:auto">
        <option value="none"${r.period === 'none' ? ' selected' : ''}>不限购</option>
        <option value="day"${r.period === 'day' ? ' selected' : ''}>每日限</option>
        <option value="week"${r.period === 'week' ? ' selected' : ''}>每周限</option>
        <option value="total"${r.period === 'total' ? ' selected' : ''}>总共限</option>
      </select>
      <input class="btn small ghost" type="number" min="1" value="${r.limit || 1}" data-act="rw" data-id="${r.id}" data-k="limit" style="width:60px" ${limited ? '' : 'disabled'}>
      <button class="btn small ${can ? '' : 'ghost'}" data-act="redeem" data-id="${r.id}" ${can ? '' : 'disabled'}>兑换</button>
      <button class="btn small danger" data-act="delReward" data-id="${r.id}">✕</button></li>`;
    }).join('') : '<div class="muted" style="padding:6px 0">还没有奖励，添加一个吧</div>';
    // 记录
    const log = D.earn.map(e => ({t: e.t, h: `✅ ${esc(e.title)} <span class="pill gray">${esc(e.cat || '默认')}</span> <b class="pts">+${e.pts}</b>`}))
      .concat(D.spent.map(x => ({t: x.t, h: `🎁 兑换「${esc(x.name)}」 <b style="color:var(--bad)">-${x.cost}</b> <button class="btn small ghost" data-act="unspend" data-id="${x.id}">撤销</button>`})))
      .sort((a, b) => b.t - a.t).slice(0, 60)
      .map(i => `<li><div class="grow">${i.h}</div><span class="muted">${fmtTime(i.t)}</span></li>`).join('');
    $('#pts-wrap').innerHTML = `
      <div class="tip ${tip.c === 'ok' ? 'offline-tip' : 'offline-tip'}" style="border-color:${tip.c === 'ok' ? '#9ed9bd' : tip.c === 'bad' ? '#eaa8b0' : '#f5d488'};background:${tip.c === 'ok' ? '#e8f7ef' : tip.c === 'bad' ? '#fdecee' : '#fff7e6'}">${tip.h}</div>
      <div class="card">
        <div class="stat">
          <div><span>可用积分</span><b>${st.balance}</b></div>
          <div><span>今日获得</span><b>${st.today}</b></div>
          <div><span>本周获得</span><b>${st.week}</b></div>
          <div><span>连续达标</span><b>${st.streak} 天</b></div>
          <div><span>累计 / 已兑换</span><b style="font-size:16px">${st.earnCount} / ${st.spentCount} 笔</b></div>
        </div>
        <div class="barLabel"><span>今日进度</span><span>${g ? st.today + ' / ' + g + (st.today >= g ? ' ✅' : '（还差 ' + (g - st.today) + '）') : '未设置'}</span></div>
        <div class="bar"><i style="width:${g ? Math.min(100, st.today / g * 100) : 0}%"></i></div>
        <div class="barLabel"><span>本周进度</span><span>${st.weekGoal ? st.week + ' / ' + st.weekGoal + (st.week >= st.weekGoal ? ' ✅' : '') : '未设置'}</span></div>
        <div class="bar"><i style="width:${st.weekGoal ? Math.min(100, st.week / st.weekGoal * 100) : 0}%"></i></div>
      </div>
      <div class="card"><b>最近 14 天积分</b>
        <div class="chartWrap"><div class="chart">${chart}</div>${gline}</div>
      </div>
      <div class="card"><b>打卡热力图（近 16 周）</b>
        <div class="heat">${hm.join('')}</div>
        <div class="rowline" style="justify-content:space-between;margin-top:6px">
          <span class="muted">${_dayKey(new Date(Date.now() - 111 * 86400000))} ~ ${today} · 共 ${hm.length} 天</span>
          <span class="heatKey"><b></b>0 <b class="l1"></b>未过半 <b class="l2"></b>过半 <b class="l3"></b>达标</span>
        </div>
      </div>
      <div class="card">
        <div class="rowline" style="justify-content:space-between"><b>任务</b><div class="rowline">${catChips}</div></div>
        ${bar}
        <form id="pts-tf" class="rowline" style="margin:10px 0;align-items:flex-end">
          <div style="flex:1;min-width:170px"><label class="f">任务内容</label><input type="text" id="pt-title" placeholder="如：背 50 个单词" required></div>
          <div style="width:110px"><label class="f">分类</label><select id="pt-cat">${D.cats.map(c => `<option>${esc(c)}</option>`).join('')}</select></div>
          <div style="width:92px"><label class="f">优先级</label><select id="pt-pri"><option value="1">高</option><option value="2" selected>中</option><option value="3">低</option></select></div>
          <div style="width:104px"><label class="f">重复方式</label><select id="pt-rep"><option value="none">只做一次</option><option value="day">每天重置</option><option value="week">每周重置</option></select></div>
          <div style="width:170px"><label class="f" id="pt-dueLb">截止时间（可留空）</label>
            <div class="rowline"><input type="datetime-local" id="pt-due" style="width:auto"><input type="time" id="pt-time" style="display:none;width:auto"><select id="pt-week" style="display:none;width:auto"><option value="0">周一</option><option value="1">周二</option><option value="2">周三</option><option value="3">周四</option><option value="4">周五</option><option value="5">周六</option><option value="6">周日</option></select></div></div>
          <div style="width:90px"><label class="f">完成得几分</label><input type="number" id="pt-val" value="5" min="0"></div>
          <button class="btn" style="height:37px">添加任务</button>
        </form>
        <div class="muted" style="font-size:12.5px;margin-bottom:6px">💡 带来源的系统任务（来自仪表盘薄弱点）由真实学习行为自动完成；手动任务勾选得分后<b>不可撤销</b>（防刷分）。</div>
        <ul style="list-style:none;margin:0;padding:0">${taskRows}</ul>
      </div>
      <div class="card">
        <b>奖励兑换</b>
        <form id="pts-rf" class="rowline" style="margin:10px 0;align-items:flex-end">
          <div style="flex:1;min-width:140px"><label class="f">奖励名称</label><input type="text" id="pr-name" placeholder="如：看一集剧" required></div>
          <div style="width:100px"><label class="f">需要多少分</label><input type="number" id="pr-cost" value="20" min="1"></div>
          <div style="width:100px"><label class="f">限购周期</label><select id="pr-period"><option value="none">不限购</option><option value="day">每天限</option><option value="week">每周限</option><option value="total">总共限</option></select></div>
          <div style="width:84px"><label class="f">限购次数</label><input type="number" id="pr-limit" value="1" min="1" disabled></div>
          <button class="btn" style="height:37px">添加奖励</button>
        </form>
        <ul style="list-style:none;margin:0;padding:0">${rewardRows}</ul>
      </div>
      <div class="card"><b>记录</b><ul style="list-style:none;margin:8px 0 0;padding:0">${log || '<span class="muted">暂无记录</span>'}</ul></div>
      <div class="card">
        <b>设置与数据</b>
        <div class="rowline mt">
          <div style="width:110px"><label class="f">每日积分要求</label><input type="number" id="ps-goal" value="${st.goal}" min="0"></div>
          <div style="width:110px"><label class="f">每周积分目标</label><input type="number" id="ps-wgoal" value="${st.weekGoal}" min="0"></div>
          <button class="btn small ghost" data-act="saveSettings">保存目标</button>
          <button class="btn small ghost" data-act="makeup">补签昨天（周限2次）</button>
          <button class="btn small ghost" data-act="simulate" data-confirm="模拟跨天：重复任务恢复未完成，用于测试重置逻辑。继续？">测试：模拟跨天</button>
        </div>
        <div class="rowline mt">
          <button class="btn small ghost" data-act="export">导出 JSON 备份</button>
          <input type="file" id="pts-imp" accept=".json,application/json" hidden>
          <button class="btn small ghost" data-act="import">导入 task-points 备份</button>
          <span class="muted">数据保存在知源学伴本地后端（data/db），换浏览器不丢；原 task-points 的备份可直接导入。</span>
        </div>
      </div>`;
    bind();
    _ptsTimer = setInterval(() => {
      document.querySelectorAll('#pts-wrap [data-due]').forEach(el => {
        el.innerHTML = _cdText(+el.dataset.due - Date.now());
      });
    }, 1000);
  }

  function _weekStartTs() {
    const d = new Date(); d.setHours(0, 0, 0, 0);
    d.setDate(d.getDate() - ((d.getDay() + 6) % 7));
    return d.getTime();
  }

  function bind() {
    const wrap = $('#pts-wrap');
    wrap.addEventListener('click', async e => {
      const el = e.target.closest('[data-act]');
      if (!el || el.tagName === 'SELECT' || el.tagName === 'INPUT') return;
      const act = el.dataset.act;
      if (act === 'filter') { _ptsFilter = el.dataset.cat; render(); }
      else if (act === 'toggle') { /* handled in change */ }
      else if (act === 'delTask') await act2('points/task/delete', {id: el.dataset.id}, '确认删除该任务？');
      else if (act === 'goto') _goSource(el.dataset.src);
      else if (act === 'redeem') { const r = D.rewards.find(x => x.id === el.dataset.id); await act2('points/reward/redeem', {id: el.dataset.id}, r ? `兑换「${r.name}」扣除 ${r.cost} 分，确认？` : null); }
      else if (act === 'delReward') await act2('points/reward/delete', {id: el.dataset.id});
      else if (act === 'unspend') await act2('points/spent/undo', {id: el.dataset.id});
      else if (act === 'saveSettings') await act2('points/settings', {goal: +$('#ps-goal').value || 0, weekGoal: +$('#ps-wgoal').value || 0});
      else if (act === 'makeup') await act2('points/makeup', {});
      else if (act === 'simulate') await act2('points/simulate', {}, '模拟跨天：重复任务恢复未完成（历史积分保留）。继续？');
      else if (act === 'export') {
        const blob = new Blob([JSON.stringify({tasks: D.tasks, rewards: D.rewards, earn: D.earn, spent: D.spent, cats: D.cats, goal: D.stats.goal, weekGoal: D.stats.weekGoal}, null, 2)], {type: 'application/json'});
        const a = document.createElement('a');
        a.href = URL.createObjectURL(blob);
        a.download = '任务积分备份-' + _dayKey(Date.now()) + '.json';
        a.click();
      } else if (act === 'import') $('#pts-imp').click();
    });
    wrap.addEventListener('change', async e => {
      const el = e.target;
      if (el.dataset.act === 'toggle') {
        await act2('points/task/toggle', {id: el.dataset.id}, el.checked ? `确认完成「${el.dataset.title}」？\n积分计入后不可撤销（防刷分机制）。` : null);
      } else if (el.dataset.act === 'rw') {
        await act2('points/reward/update', {id: el.dataset.id, k: el.dataset.k, v: el.value});
      } else if (el.id === 'pts-imp' && el.files.length) {
        const f = el.files[0];
        const text = await f.text();
        try {
          const data = JSON.parse(text);
          await act2('points/import', {data}, '导入会覆盖当前任务积分数据，确认？');
        } catch (err) { toast('文件格式不对', true); }
        el.value = '';
      } else if (el.id === 'pt-rep') {
        const rep = el.value, once = rep === 'none';
        $('#pt-due').style.display = once ? '' : 'none';
        $('#pt-time').style.display = once ? 'none' : '';
        $('#pt-week').style.display = rep === 'week' ? '' : 'none';
        $('#pt-dueLb').textContent = once ? '截止时间（可留空）' : rep === 'day' ? '每天几点前' : '每周几点前';
      } else if (el.id === 'pr-period') {
        document.getElementById('pr-limit').disabled = el.value === 'none';
      }
    });
    wrap.addEventListener('submit', async e => {
      e.preventDefault();
      if (e.target.id === 'pts-tf') {
        const rep = $('#pt-rep').value;
        const body = {title: $('#pt-title').value.trim(), cat: $('#pt-cat').value, pri: +$('#pt-pri').value,
                      pts: +$('#pt-val').value || 0, repeat: rep};
        if (rep === 'none') { if ($('#pt-due').value) body.due = new Date($('#pt-due').value).getTime(); }
        else { body.dueT = $('#pt-time').value || null; if (rep === 'week') body.dueW = +$('#pt-week').value; }
        if (!body.title) return;
        D = await api('points/task', {method: 'POST', body: Object.assign({sid: state.sid}, body)});
        render();
      } else if (e.target.id === 'pts-rf') {
        const name = $('#pr-name').value.trim();
        if (!name) return;
        D = await api('points/reward', {method: 'POST', body: {sid: state.sid, name, cost: +$('#pr-cost').value || 1,
          period: $('#pr-period').value, limit: +$('#pr-limit').value || 1}});
        render();
      }
    });
  }
  async function act2(path, body, confirmMsg) {
    if (confirmMsg && !confirm(confirmMsg)) return;
    try {
      D = await api(path, {method: 'POST', body: Object.assign({sid: state.sid}, body)});
      render();
    } catch (e) { toast(e.message, true); }
  }
  await refresh();
};

/* ================= AI 问答 ================= */
VIEWS.qa = async () => {
  const picker = imagePicker('qa-img');
  $('#main').innerHTML += `
    <div class="card">
      <div class="rowline">
        <select id="qa-subject" style="width:150px"><option value="">自动识别科目</option>
          ${Object.entries(state.boot.subjects).map(([k,v])=>`<option value="${k}">${v}</option>`).join('')}</select>
        <select id="qa-mode" style="width:150px"><option value="guide">引导模式（不直接给答案）</option><option value="explain">讲解模式（完整推导）</option></select>
        <label class="checkline"><input type="checkbox" id="qa-web" checked> 联网检索辅助</label>
      </div>
      <label class="f">输入你的问题（可整段粘贴题目，也可直接传题图）</label>
      <textarea id="qa-input" placeholder="例：老师，求 A=[2 1;1 2] 的特征值和特征向量，我总忘记验算…&#10;（手写题可以直接拍照上传，接入视觉模型后自动读题）"></textarea>
      ${picker.html}
      <div class="mt"><button class="btn" id="qa-ask">提问</button></div>
      ${state.boot.llm ? '' : '<div class="offline-tip mt">当前离线模式：内置知识图谱 + 免费联网搜索照常可用；点「⚙ 接入设置」填 API Key（智谱 glm-4-flash 免费）后解锁完整AI与图片读题。</div>'}
    </div>
    <div id="qa-list"></div>`;
  picker.bind();
  $('#qa-ask').onclick = ask;
  $('#qa-input').addEventListener('keydown', e => { if (e.key === 'Enter' && (e.ctrlKey || e.metaKey)) ask(); });
  if (state.handoff.qaPrefill) { $('#qa-input').value = '围绕「' + state.handoff.qaPrefill + '」开始今天的学习：'; state.handoff.qaPrefill = null; }
  async function ask() {
    const q = $('#qa-input').value.trim();
    if (!q && !picker.state.file) return toast('请输入问题或上传题目图片', true);
    const btn = $('#qa-ask'); btn.disabled = true; btn.textContent = '思考中…';
    // 流式直播容器
    const live = document.createElement('div');
    live.className = 'chat-item';
    live.innerHTML = `<div class="q">🙋 ${esc(q || '（图片题）')}</div>
      <div class="a"><span class="pill">🫧 AI 流式作答中…</span><div class="qa-live md mt"></div></div>`;
    $('#qa-list').prepend(live);
    const liveBox = live.querySelector('.qa-live');
    let acc = '', lastRender = 0;
    const paint = () => { liveBox.innerHTML = md(acc); };
    try {
      const token = localStorage.getItem('zy_token');
      const resp = await fetch('/api/qa/stream', {method: 'POST',
        headers: Object.assign({'Content-Type': 'application/json'},
          token ? {Authorization: 'Bearer ' + token} : {}),
        body: JSON.stringify({question: q, subject: $('#qa-subject').value || null,
          mode: $('#qa-mode').value, image: picker.state.file,
          use_web: $('#qa-web').checked, sid: state.sid})});
      if (!resp.ok || !resp.body) {
        const data = await resp.json().catch(() => ({}));
        if (resp.status === 401) { localStorage.removeItem('zy_token'); }
        throw new Error(data.error || ('HTTP ' + resp.status));
      }
      const reader = resp.body.getReader();
      const dec = new TextDecoder('utf-8');
      let buf = '', finalData = null, errMsg = null;
      while (true) {
        const {done, value} = await reader.read();
        if (done) break;
        buf += dec.decode(value, {stream: true});
        let idx;
        while ((idx = buf.indexOf('\n\n')) >= 0) {
          const frame = buf.slice(0, idx); buf = buf.slice(idx + 2);
          let ev = 'message', data = '';
          for (const line of frame.split('\n')) {
            if (line.startsWith('event:')) ev = line.slice(6).trim();
            else if (line.startsWith('data:')) data += line.slice(5).trim();
          }
          if (!data) continue;
          let j; try { j = JSON.parse(data); } catch (e) { continue; }
          if (ev === 'delta' && j.t) {
            acc += j.t;
            const now = Date.now();
            if (now - lastRender > 120) { lastRender = now; paint(); }
          } else if (ev === 'final') finalData = j;
          else if (ev === 'error') errMsg = j.message;
        }
      }
      if (errMsg) throw new Error(errMsg);
      if (finalData) {
        live.remove();
        renderAnswer(q || '（图片题）', finalData);
        if (finalData.awarded) toast('🎯 积分 +' + finalData.awarded);
      } else { if (!acc) acc = '（无输出，请重试）'; paint(); }
      $('#qa-input').value = '';
      document.getElementById('qa-img-clear').click();
    } catch (e) {
      if (acc) paint(); else { live.remove(); toast(e.message, true); }
    }
    btn.disabled = false; btn.textContent = '提问';
  }
  function renderAnswer(q, r) {
    const el = document.createElement('div');
    el.className = 'chat-item';
    el.innerHTML = `
      <div class="q">🙋 ${esc(q)}</div>
      <div class="a">
        ${r.kp_name ? `<span class="pill">考点：${esc(r.kp_name)}</span>` : '<span class="pill amber">未精确匹配考点，以下为通用引导</span>'}
        ${r.offline ? '<span class="pill amber">离线演示</span>' : ''}
        ${r.image_note ? `<span class="pill gray">${esc(r.image_note)}</span>` : ''}
        <h4>引导步骤</h4><ol class="guidance">${(r.guidance||[]).map(g=>`<li>${esc(g)}</li>`).join('')}</ol>
        ${(r.counter_questions||[]).length ? `<h4>💬 老师的反问（先自己想一想）</h4>
          ${r.counter_questions.map(f=>`<button class="followup" style="background:#fff7e6;color:#8a5a00">${esc(f)}</button>`).join('')}` : ''}
        <h4>解析</h4><div class="md">${md(r.explanation)}</div>
        ${(r.key_points||[]).length ? `<h4>关键结论</h4><ul>${r.key_points.map(k=>`<li>${esc(k)}</li>`).join('')}</ul>` : ''}
        ${(r.followups||[]).length ? `<div class="mt">${r.followups.map(f=>`<button class="followup">${esc(f)}</button>`).join('')}</div>` : ''}
        ${(r.web_results||[]).length ? `<h4>🌐 联网检索（点击可查看原文）</h4>
          ${r.web_results.map(w=>`<div class="src"><a href="${esc(w.url)}" target="_blank">${esc(w.title)}</a><br><span>${esc((w.snippet||'').slice(0,120))}</span></div>`).join('')}` : ''}
        ${(r.sources||[]).length ? `<div class="src">📚 来源：${r.sources.map(s=>s.note&&s.note.startsWith('http')?`<a href="${esc(s.note)}" target="_blank">${esc(s.title)}</a>`:esc(s.title)).join(' · ')}</div>` : ''}
        ${(r.material_refs||[]).length ? `<div class="src">📁 引用校本资料：${r.material_refs.map(m=>esc(m.material)).join('、')}</div>` : ''}
        ${feedbackBox('qa', q)}
      </div>`;
    el.querySelectorAll('.followup').forEach(b => b.onclick = () => { $('#qa-input').value = b.textContent; $('#qa-input').focus(); });
    $('#qa-list').prepend(el);
  }
};

/* ================= 学习计划（定路线） ================= */
VIEWS.plan = async () => {
  $('#main').innerHTML += `<div id="plan-wrap"><div class="card muted">加载中…</div></div>`;
  async function render() {
    const d = await api('plan', {query: {sid: state.sid}});
    const P = d.plan;
    if (!P) {
      $('#plan-wrap').innerHTML = `
        <div class="card" style="max-width:560px">
          <h3>📅 创建学习计划</h3>
          <div class="muted">输入目标与可用时间，我按知识图谱的前置依赖 + 你的薄弱点排出一套逐日课程（每天 15~180 分钟）。完成后自动发分、自动更新画像。</div>
          <label class="f mt">科目</label>
          <select id="pl-subject" style="width:100%">${Object.entries(state.boot.subjects).map(([k, v]) => `<option value="${k}">${v}</option>`).join('')}</select>
          <label class="f mt">目标（可选）</label>
          <input id="pl-goal" style="width:100%" placeholder="如：期末考 85 分 / 期末不挂科">
          <label class="f mt">考试日期（可选，用于节奏预警）</label>
          <input id="pl-date" type="date" style="width:100%">
          <div class="rowline mt">
            <div style="flex:1"><label class="f">每天可用时间（分钟）</label>
            <input id="pl-min" type="number" value="40" min="15" max="180" style="width:100%"></div>
            <div style="flex:1"><label class="f">起点</label>
            <select id="pl-level" style="width:100%"><option value="review">复习（跳过已掌握≥85）</option><option value="zero">零基础（全部学）</option></select></div>
          </div>
          <div class="mt"><button class="btn" id="pl-create">✨ 生成逐日计划</button></div>
        </div>`;
      $('#pl-create').onclick = async () => {
        const btn = $('#pl-create');
        btn.disabled = true; btn.textContent = '规划中…（排课 + AI 润色目标）';
        try {
          await api('plan/create', {method: 'POST', body: {sid: state.sid,
            subject: $('#pl-subject').value, goal: $('#pl-goal').value.trim(),
            exam_date: $('#pl-date').value, daily_minutes: +$('#pl-min').value || 40,
            level: $('#pl-level').value}});
          toast('计划已生成，开始今天的第一课吧');
          render();
        } catch (e) { toast(e.message, true); btn.disabled = false; btn.textContent = '✨ 生成逐日计划'; }
      };
      return;
    }
    const todayDay = P.today;
    const rows = P.days.map(d => {
      const isToday = d.day === todayDay;
      const done = d.status === 'done';
      return `<div class="paper-q result-item ${done ? '' : isToday ? 'tour-hot-now' : ''}" style="${done ? 'opacity:.6' : ''}">
        <div class="rowline" style="justify-content:space-between">
          <span><b>D${d.day}</b> ${esc(d.title)} ${done ? '<span class="pill" style="background:#e6f7ec;color:#0a7">✓ 已完成</span>' : isToday ? '<span class="pill amber">📍 今天</span>' : ''}
          ${d.score != null ? `<span class="muted">练习 ${d.score} 分</span>` : ''}</span>
          <span class="muted">${d.minutes} 分钟</span>
        </div>
        ${d.objectives && d.objectives.length ? `<ul class="mt" style="margin:6px 0 0">${d.objectives.map(o => `<li>${esc(o)}</li>`).join('')}</ul>` : ''}
        <div class="mt rowline noprint">
          ${isToday ? `<button class="btn small" data-go-qa="${esc(d.title)}">💬 去问答学习</button>
                       <button class="btn small ghost" data-go-paper="${esc(d.kp_ids.join(','))}">📝 出诊断卷验收</button>
                       <button class="btn small" data-done="${d.day}">✓ 标记完成（+8分）</button>` : ''}
          ${!done && !isToday && d.day < (todayDay || 999) ? `<button class="btn small ghost" data-done="${d.day}">补标完成</button>` : ''}
        </div>
      </div>`;
    }).join('');
    $('#plan-wrap').innerHTML = `
      <div class="plan-cols">
        <div class="plan-main">
          <div id="daily-zone"></div>
          <div class="mt"></div>
          ${rows}
        </div>
        <div class="plan-side" id="plan-side"></div>
      </div>`;
    renderSide(P);
    $('#pl-del').onclick = async () => {
      if (!confirm('删除当前学习计划？（学习记录保留，积分不回收）')) return;
      await api('plan/delete', {method: 'POST', body: {sid: state.sid}});
      render();
    };
    $('#plan-wrap').querySelectorAll('button[data-done]').forEach(b => b.onclick = async () => {
      try {
        const r = await api('plan/done', {method: 'POST', body: {sid: state.sid, day: +b.dataset.done}});
        toast(r.awarded ? '🎯 完成打卡，积分 +' + r.awarded : '已标记完成');
        render();
      } catch (e) { toast(e.message, true); }
    });
    $('#plan-wrap').querySelectorAll('button[data-go-qa]').forEach(b => b.onclick = () => {
      state.handoff.qaPrefill = b.dataset.goQa;
      location.hash = '#/qa';
    });
    $('#plan-wrap').querySelectorAll('button[data-go-paper]').forEach(b => b.onclick = () => {
      state.handoff.paperKps = b.dataset.goPaper.split(',').filter(Boolean);
      state.handoff.paperSubject = P.subject;
      location.hash = '#/paper';
    });
    renderDaily(P);
  }
  let viewingDay = null;
  function renderSide(P) {
    const side = document.getElementById('plan-side');
    if (!side) return;
    const meter = `<div class="meter" style="height:10px"><i style="width:${Math.round(100 * P.done_n / Math.max(P.total_n, 1))}%"></i></div>
      <div class="muted" style="font-size:12.5px;margin-top:6px">进度 ${P.done_n}/${P.total_n} 天${P.exam_date ? ' · 考试 ' + esc(P.exam_date) : ''}</div>
      ${P.pace_warning ? `<div class="muted" style="font-size:12.5px;color:var(--bad);margin-top:4px">${esc(P.pace_warning)}</div>` : ''}`;
    const nav = P.days.map(d => {
      const done = d.status === 'done';
      const cls = d.day === viewingDay ? 'cur' : '';
      const st = done ? '<span class="st" style="color:#0a7">✓</span>' : (d.day === P.today ? '<span class="st" style="color:#c77700">📍</span>' : '');
      return `<button class="${cls}" data-nav="${d.day}"><span>D${d.day} ${esc(d.title.slice(0, 13))}</span>${st}</button>`;
    }).join('');
    side.innerHTML = `
      <div class="card"><h4>🗓️ ${esc(P.subject_name)}</h4>${meter}
        ${P.today ? '' : '<div class="muted" style="font-size:12.5px;color:var(--ok);margin-top:6px">🎉 全部完成</div>'}
        <div class="mt"><button class="btn small danger" id="pl-del" style="width:100%">删除重排</button></div>
      </div>
      <div class="card"><h4>📆 课程天导航（点击查看讲义）</h4><div class="plan-daynav">${nav}</div></div>
      <div id="plan-side-review"></div>`;
    side.querySelectorAll('button[data-nav]').forEach(b => b.onclick = () => {
      viewingDay = +b.dataset.nav;
      side.querySelectorAll('.plan-daynav button').forEach(x => x.classList.toggle('cur', +x.dataset.nav === viewingDay));
      showCourse(viewingDay, false);
    });
    $('#pl-del').onclick = async () => {
      if (!confirm('删除当前学习计划？（学习记录保留，积分不回收）')) return;
      await api('plan/delete', {method: 'POST', body: {sid: state.sid}});
      render();
    };
    api('review/due', {query: {sid: state.sid}}).then(r => {
      const box = document.getElementById('plan-side-review');
      if (!box) return;
      box.innerHTML = r.due_n ? `<div class="card"><h4>🔁 到期待复习</h4>
        <div class="muted" style="font-size:12.5px"><b style="color:var(--bad)">${r.due_n}</b> 道错题到了复做点</div>
        <div class="mt"><button class="btn small" style="width:100%" onclick="location.hash='#/wrongbook'">去复习 →</button></div></div>` : '';
    }).catch(() => {});
  }
  function renderDaily(P) {
    const zone = document.getElementById('daily-zone');
    if (!zone) return;
    zone.innerHTML = '<div class="card"><h3>📖 今日课程</h3><div class="muted">加载中…</div></div>';
    api('daily', {query: {sid: state.sid}}).then(ds => {
      if (!zone.isConnected) return;   // 视图已被重建，丢弃过期渲染
      if (!ds) { zone.innerHTML = ''; return; }
      const dayNo = ds.day || P.today;
      const genDays = (ds.generated || []);
      const opts = genDays.map(g => `<option value="${g.day}" ${g.day === dayNo ? 'selected' : ''}>D${g.day} ${esc(g.title.slice(0, 18))}</option>`).join('');
      if (!ds.has_course) {
        zone.innerHTML = `
          <div class="card">
            <div class="rowline" style="justify-content:space-between;align-items:center">
              <h3 style="margin:0">📖 今日课程 ${ds.title ? '· ' + esc(ds.title) : ''}</h3>
              ${genDays.length ? `<select id="dl-switch" style="width:auto">${opts}</select>` : ''}
            </div>
            <div class="muted mt">还没有备出今天的课程。四步法讲义：概念讲解 → 完整例题（每步理由）→ 同构填步题 → 变式验收卷。</div>
            <div class="mt"><button class="btn" id="dl-gen">✨ 备课（生成今日课程 + 验收卷）</button></div>
          </div>`;
        document.getElementById('dl-gen').onclick = () => showCourse(dayNo, true);
        const sw = document.getElementById('dl-switch');
        if (sw) sw.onchange = () => showCourse(+sw.value, false);
        return;
      }
      showCourse(dayNo, false, ds.quiz_pid);
    }).catch(e => { if (zone.isConnected) zone.innerHTML = '<div class="card muted">课程加载失败：' + esc(String((e && e.message) || e)) + '</div>'; });
  }
  async function showCourse(dayNo, generate, quizPid) {
    const zone = document.getElementById('daily-zone');
    if (!zone || !zone.isConnected) return;
    zone.innerHTML = '<div class="card"><h3>📖 今日课程（D' + dayNo + '）</h3><div class="muted">' +
      (generate ? '备课中…（讲解 + 例题 + 填步题 + 验收卷，约 20 秒）' : '加载中…') + '</div></div>';
    let c;
    try {
      c = generate
        ? await api('daily/generate', {method: 'POST', body: {sid: state.sid, day: dayNo}})
        : await api('daily/course', {query: {sid: state.sid, day: dayNo}});
    } catch (e) { zone.innerHTML = `<div class="card"><h3>📖 今日课程</h3><div class="muted">${esc(e.message)}</div></div>`; return; }
    const L = c.lesson || {};
    const WE = L.worked_example || {};
    const FS = L.fill_steps || {};
    if (!zone.isConnected) return;   // 视图已被重建，丢弃过期渲染
    viewingDay = c.day;
    document.querySelectorAll('.plan-daynav button').forEach(x => x.classList.toggle('cur', +x.dataset.nav === viewingDay));
    zone.innerHTML = `
      <div class="card lesson-wrap">
        <div class="lesson-head">
          <div class="rowline" style="justify-content:space-between;align-items:center">
            <h3>📖 今日课程 · D${c.day}</h3>
            <span class="muted" style="font-size:12px">${(c.kp_names || []).map(esc).join(' · ')}</span>
          </div>
          <div class="mt" style="font-weight:700;font-size:14.5px;color:#22315e">${esc(c.title || '')}</div>
        </div>
        <div class="lesson-step"><span class="step-badge">1</span><span class="step-title">概 念 讲 解</span></div>
        <div class="lesson-prose md">${md(L.concept || '')}</div>
        <div class="lesson-step"><span class="step-badge">2</span><span class="step-title">完 整 例 题（每步带理由）</span></div>
        <div class="lesson-prose"><div class="answer-ref">${md(WE.q || '')}</div></div>
        <details class="lesson-ex"><summary>展开解题步骤（先自己试一遍）</summary>
          <ol class="guidance">${(WE.steps || []).map(s => `<li>${esc(s)}</li>`).join('')}</ol>
          <div class="answer-ref"><b>最终答案：</b>${esc(WE.answer || '')}</div>
        </details>
        ${FS.q ? `
        <div class="lesson-step"><span class="step-badge">3</span><span class="step-title">同 构 填 步 题</span></div>
        <div class="lesson-prose"><div class="answer-ref">${md(FS.q)}</div>
        ${FS.hint ? `<div class="lesson-muted">提示：${esc(FS.hint)}</div>` : ''}</div>
        <details class="lesson-ex"><summary>显示填空答案</summary>
          <div class="answer-ref">${((FS.blanks || []).map((b, i) => `${i + 1}. ${esc(b)}`).join('　')) || '——'}</div>
        </details>` : ''}
        ${L.recap ? `
        <div class="lesson-step"><span class="step-badge">4</span><span class="step-title">回 顾 连 接</span></div>
        <div class="lesson-prose md">${md(L.recap)}</div>` : ''}
        <div class="lesson-step"><span class="step-badge">5</span><span class="step-title">变 式 验 收</span></div>
        <div class="rowline">
          ${c.quiz_pid ? `<button class="btn" id="dl-quiz">📝 做 4 题验收小卷（自动批改）</button>` : ''}
          <button class="btn small ghost" onclick="location.hash='#/plan';location.reload()">刷新</button>
        </div>
        ${c.quiz_pid ? '' : '<div class="lesson-muted mt">验收卷生成失败，可用下方"出诊断卷验收"按钮手动出卷。</div>'}
      </div>`;
    const qb = document.getElementById('dl-quiz');
    if (qb) qb.onclick = () => { location.hash = '#/paper/' + c.quiz_pid; };
  }
  await render();
};

/* ================= 外部AI 引导（借力模式） ================= */
VIEWS.external = async () => {
  const picker = imagePicker('ex-img');
  $('#main').innerHTML += `
    <div class="offline-tip">⚠️ <b>这是阉割版</b>：把提示词带去网页 AI 只是借外部模型的手——它记不住你的档案、不会自动改作业、无法持续跟进。
    真正的学习模型需要 <b>agent 驱动多个 skill 协同</b>（定路线 → 逐日讲解 → 错题管理 → 变式出题），参考：
    <a href="https://github.com/yoli-mi/good-learning-skill" target="_blank">good-learning</a> ·
    <a href="https://github.com/Miaotofu01/Study-Mate" target="_blank">Study-Mate</a> ·
    <a href="https://github.com/EricWang1358/dsh-web-studyhub/releases" target="_blank">dsh-web-studyhub</a>。
    知源学伴的完整闭环（画像/错题本/积分/全班反馈学习）正在向这个方向演进。</div>
    <div class="grid c2">
      <div class="card">
        <h3>① 生成引导式提示词</h3>
        <label class="f">你想搞懂什么问题？</label>
        <textarea id="ex-question" style="min-height:80px" placeholder="例：线性方程组什么时候无解/有无穷多解？总是搞混判定条件"></textarea>
        <div class="rowline mt">
          <select id="ex-subject" style="width:150px"><option value="">自动识别科目</option>
            ${Object.entries(state.boot.subjects).map(([k,v])=>`<option value="${k}">${v}</option>`).join('')}</select>
          <select id="ex-mode" style="width:170px"><option value="guide">引导模式（AI 不直接给答案）</option><option value="explain">讲解模式（完整推导）</option></select>
        </div>
        <div class="mt"><button class="btn" id="ex-gen">✨ 生成提示词</button></div>
        <div id="ex-prompt-box" class="mt" style="display:none">
          <label class="f">复制下面整段 → 打开 DeepSeek/任意网页AI → 粘贴发送：</label>
          <textarea id="ex-prompt" readonly style="min-height:240px;font-size:12.5px"></textarea>
          <div class="mt rowline">
            <button class="btn small" id="ex-copy">📋 一键复制</button>
            <a class="btn small ghost" href="https://chat.deepseek.com/" target="_blank">打开 DeepSeek ↗</a>
          </div>
        </div>
      </div>
      <div class="card">
        <h3>② 回收外部 AI 的回答</h3>
        <div class="muted">聊完后，把外部 AI 的回答复制粘贴回这里，我帮你收纳、总结、归档（关联考点，随时可查）。</div>
        <label class="f mt">外部 AI 的回答</label>
        <textarea id="ex-answer" style="min-height:150px" placeholder="粘贴外部 AI 的完整回复…"></textarea>
        <div class="rowline mt"><input id="ex-model" placeholder="用的哪个模型（如 DeepSeek网页版）" style="flex:1">
          <button class="btn" id="ex-save">📥 提交收纳</button></div>
        <div id="ex-result"></div>
      </div>
    </div>
    <div class="card">
      <h3>🗂️ 收纳册（<span id="ex-count">0</span> 条，随时可查）</h3>
      <div id="ex-list"><div class="muted">加载中…</div></div>
    </div>`;
  async function loadList() {
    const d = await api('external', {query:{sid: state.sid}});
    document.getElementById('ex-count').textContent = d.total;
    const lst = d.items.length ? d.items.map(it => `
      <details class="answer-ref" style="margin-top:8px;border-radius:8px;background:#f7f8fc">
        <summary style="cursor:pointer"><b>${esc((it.question || '').slice(0, 40))}</b>
          ${it.kp_name ? `<span class="pill">${esc(it.kp_name)}</span>` : ''}
          <span class="muted" style="font-size:12px">${esc(it.model)} · ${fmtTime(it.ts)}</span></summary>
        <div class="md mt">${it.tldr ? md('**收纳总结：** ' + it.tldr) : ''}</div>
        <div class="mt"><a href="javascript:void(0)" data-detail="${esc(it.id)}">查看全文与总结 →</a>
          <a href="javascript:void(0)" data-del="${esc(it.id)}" style="color:var(--bad)">删除</a></div>
      </details>`).join('') : '<div class="muted mt">还没有收纳记录。走一遍上面两步，外部 AI 的学习成果就会沉淀在这里。</div>';
    document.getElementById('ex-list').innerHTML = lst;
    document.querySelectorAll('#ex-list [data-detail]').forEach(a => a.onclick = async () => {
      const it = await api('external/item', {query:{sid: state.sid, id: a.dataset.detail}});
      document.getElementById('ex-list').querySelector(`[data-detail="${it.id}"]`).closest('details').innerHTML =
        `<summary style="cursor:pointer"><b>${esc((it.question || '').slice(0, 40))}</b></summary>
         <div class="md mt">${md('**收纳总结：** ' + (it.tldr || '（无）'))}</div>
         ${(it.key_points || []).length ? `<h4>📌 要点</h4><ul>${it.key_points.map(k => `<li>${esc(k)}</li>`).join('')}</ul>` : ''}
         ${it.quality_note ? `<div class="answer-ref">质检：${esc(it.quality_note)}（${it.quality}/5）</div>` : ''}
         ${it.followup ? `<div class="answer-ref">➡️ 建议下一步：${esc(it.followup)}</div>` : ''}
         <h4>外部 AI 原回答</h4><div class="md" style="max-height:300px;overflow:auto">${md(it.answer)}</div>`;
    });
    document.querySelectorAll('#ex-list [data-del]').forEach(a => a.onclick = async () => {
      if (!confirm('删除这条收纳记录？')) return;
      await api('external/item', {method: 'DELETE', body: {sid: state.sid, id: a.dataset.del}});
      toast('已删除');
      loadList();
    });
  }
  $('#ex-gen').onclick = async () => {
    const q = $('#ex-question').value.trim();
    if (!q) return toast('先写下你的问题', true);
    const btn = $('#ex-gen'); btn.disabled = true; btn.textContent = '生成中…';
    try {
      const r = await api('external/prompt', {method:'POST', body:{sid: state.sid, question: q,
        subject: $('#ex-subject').value || null, mode: $('#ex-mode').value}});
      $('#ex-prompt').value = r.prompt;
      document.getElementById('ex-prompt-box').style.display = '';
      toast(r.kp_name ? ('已按考点《' + r.kp_name + '》定制提示词') : '提示词已生成');
    } catch (e) { toast(e.message, true); }
    btn.disabled = false; btn.textContent = '✨ 生成提示词';
  };
  $('#ex-copy').onclick = async () => {
    const ta = $('#ex-prompt');
    try { await navigator.clipboard.writeText(ta.value); toast('已复制，去 DeepSeek 粘贴吧'); }
    catch (e) { ta.select(); document.execCommand('copy'); toast('已复制'); }
  };
  $('#ex-save').onclick = async () => {
    const ans = $('#ex-answer').value.trim();
    if (!ans) return toast('先把外部 AI 的回答粘贴进来', true);
    const btn = $('#ex-save'); btn.disabled = true; btn.textContent = '收纳总结中…';
    try {
      const it = await api('external/save', {method:'POST', body:{sid: state.sid,
        question: $('#ex-question').value.trim(), subject: $('#ex-subject').value || null,
        answer: ans, model: $('#ex-model').value.trim()}});
      document.getElementById('ex-result').innerHTML = `
        <div class="card mt" style="background:#f2fbf4">
          <h3>✅ 已收纳（关联考点：${esc(it.kp_name || '通用')}）</h3>
          <div class="md">${md('**总结：** ' + (it.tldr || '——'))}</div>
          ${(it.key_points || []).length ? `<ul class="mt">${it.key_points.map(k => `<li>${esc(k)}</li>`).join('')}</ul>` : ''}
          ${it.quality_note ? `<div class="answer-ref">质检：${esc(it.quality_note)}（${it.quality}/5）</div>` : ''}
          ${it.followup ? `<div class="answer-ref">➡️ 建议下一步：${esc(it.followup)}</div>` : ''}
        </div>`;
      $('#ex-answer').value = '';
      loadList();
      toast('已归档，随时可在收纳册查看');
    } catch (e) { toast(e.message, true); }
    btn.disabled = false; btn.textContent = '📥 提交收纳';
  };
  await loadList();
};

/* ================= 英语批改 ================= */
VIEWS.english = async () => {
  const [wp, ti] = [state.boot.writing_prompts, state.boot.translation_items];
  const picker = imagePicker('en-img');
  $('#main').innerHTML += `
    <div class="card">
      <div class="rowline">
        <select id="en-kind" style="width:140px"><option value="writing">✍️ 作文批改</option><option value="translation">🔤 段落翻译批改</option></select>
        <select id="en-level" style="width:110px"><option value="cet4">CET-4</option><option value="cet6">CET-6</option></select>
        <select id="en-prompt" style="width:auto;flex:1"><option value="">— 选择题目（可选） —</option></select>
      </div>
      <div id="en-prompt-info" class="muted mt"></div>
      <label class="f" id="en-text-label">粘贴或输入你的作文</label>
      <textarea id="en-text" style="min-height:180px" placeholder="In the age of AI, ...（手写作文可拍照上传；电子稿可直接传 .txt/.md/.docx 文档）"></textarea>
      ${picker.html}
      <input type="file" id="en-doc" accept=".txt,.md,.docx" hidden>
      <div class="rowline"><button class="btn small ghost" id="en-doc-btn" type="button">📄 上传作文/译文文档 (.txt/.md/.docx)</button><span class="muted" id="en-doc-name"></span></div>
      <div class="mt"><button class="btn" id="en-grade">开始批改</button></div>
    </div>
    <div id="en-result"></div>`;
  const kindSel = $('#en-kind'), levelSel = $('#en-level'), promptSel = $('#en-prompt');
  picker.bind();
  $('#en-doc-btn').onclick = () => $('#en-doc').click();
  $('#en-doc').onchange = async () => {
    const f = $('#en-doc').files[0];
    if (!f) return;
    const fd = new FormData();
    fd.append('sid', state.sid);
    fd.append('file', f);
    try {
      const r = await api('upload/extract', {method: 'POST', body: fd});
      $('#en-text').value = r.text;
      $('#en-doc-name').textContent = '已导入：' + r.name;
      toast('文档内容已导入，确认无误后点批改');
    } catch (e) { toast(e.message, true); }
    $('#en-doc').value = '';
  };
  function fillPrompts() {
    const kind = kindSel.value, level = levelSel.value;
    const list = (kind === 'writing' ? wp : ti).filter(p => !level || p.level === level);
    promptSel.innerHTML = '<option value="">— 选择题目（可选） —</option>' +
      list.map(p => {
        const label = kind === 'writing'
          ? (p.year ? `[${p.year}·${p.tag}] ` : '') + (p.topic_cn || '')
          : (p.year ? `[${p.year}·${p.tag}] ` : '') + (p.topic || p.source_cn.slice(0, 14));
        return `<option value="${p.id}">${esc(label)}</option>`;
      }).join('');
    $('#en-text-label').textContent = kind === 'writing' ? '粘贴或输入你的作文' : '输入你的英文译文（对照左侧原文题目）';
  }
  kindSel.onchange = levelSel.onchange = fillPrompts;
  promptSel.onchange = () => {
    const kind = kindSel.value;
    const p = (kind === 'writing' ? wp : ti).find(x => x.id === promptSel.value);
    $('#en-prompt-info').innerHTML = p ? (kind === 'writing'
      ? `📌 ${esc(p.directions)}${p.topic_cn ? '（' + esc(p.topic_cn) + '）' : ''}`
      : `📌 原文：${esc(p.source_cn)}<br><button class="btn small ghost mt" id="en-show-ref">查看参考译文与关键表达</button><div id="en-ref" class="md mt" style="display:none"></div>`) : '';
    if (p && kind === 'translation') {
      const btn = $('#en-show-ref');
      if (btn) btn.onclick = () => {
        const box = $('#en-ref');
        box.style.display = box.style.display === 'none' ? '' : 'none';
        box.innerHTML = md('参考译文：' + p.reference_en + '\n\n关键表达：\n' + p.key_points.map(k=>'- '+k).join('\n') + '\n\n常见错误：\n' + p.common_mistakes.map(k=>'- '+k).join('\n'));
      };
    }
  };
  fillPrompts();
  $('#en-grade').onclick = async () => {
    const text = $('#en-text').value.trim();
    if (!text && !picker.state.file) return toast('请先输入内容或上传答卷图片', true);
    const btn = $('#en-grade'); btn.disabled = true; btn.textContent = '批改中…';
    try {
      const r = await api('english/grade', {method:'POST', body:{sid: state.sid,
        kind: kindSel.value, level: levelSel.value, prompt_id: promptSel.value || null,
        text, image: picker.state.file}});
      renderResult(r, kindSel.value);
      if (r.awarded) toast('🎯 积分 +' + r.awarded);
    } catch (e) { toast(e.message, true); }
    btn.disabled = false; btn.textContent = '开始批改';
  };
  function renderResult(r, kind) {
    const score = r.score ?? 0, pct = Math.round(score / 15 * 100);
    $('#en-result').innerHTML = `
      <div class="card">
        <div class="rowline" style="align-items:flex-start">
          <div class="score-ring" style="--pct:${pct}"><b>${score}<span style="font-size:12px;color:#5a6478">/15</span></b></div>
          <div style="flex:1;min-width:220px">
            <b>${kind==='writing'?'作文':'翻译'}批改结果</b>
            ${r.year ? `<span class="pill">${esc(r.year)} ${esc(r.tag||'')}</span>` : ''}
            ${r.image_note ? `<span class="pill gray">${esc(r.image_note)}</span>` : ''}
            ${r.offline ? '<span class="pill amber">离线启发式批改</span>' : '<span class="pill green">AI 精批</span>'}
            <div class="muted mt">${esc(r.band_desc)}</div>
            <div class="muted mt">${esc(r.summary)}</div>
          </div>
        </div>
        <h4>分维度点评</h4>
        <table class="corr-table"><tr><th style="width:140px">维度</th><th>评价</th></tr>
          ${(r.dims||[]).map(d=>`<tr><td>${esc(d.name)}</td><td>${esc((d.score||'') + ' ' + (d.comment||''))}</td></tr>`).join('')}</table>
        ${(r.corrections||[]).length ? `<h4>逐条修改（${r.corrections.length} 处）</h4>
          <table class="corr-table"><tr><th>原文</th><th>建议</th><th>类型</th><th>说明</th></tr>
          ${r.corrections.map(c=>`<tr><td class="orig">${esc(c.original)}</td><td class="rev">${esc(c.revised)}</td><td>${esc(c.type)}</td><td>${esc(c.note)}</td></tr>`).join('')}</table>` : ''}
        ${(r.strengths||[]).length ? `<h4>✨ 亮点</h4><ul>${r.strengths.map(s=>`<li>${esc(s)}</li>`).join('')}</ul>` : ''}
        ${(r.phrases||[]).length ? `<h4>💬 值得积累的表达</h4>${r.phrases.map(p=>`<span class="pill gray">${esc(p.en)} — ${esc(p.cn)}</span>`).join(' ')}` : ''}
        ${r.model_essay ? `<details class="model" open><summary>📄 ${kind==='writing'?'范文':'参考译文优化'}</summary><div class="md">${md(r.model_essay)}</div></details>` : ''}
        ${feedbackBox('english', kind === 'writing' ? '作文' : '翻译')}
      </div>`;
    $('#en-result').scrollIntoView({behavior:'smooth'});
  }
};

/* ================= 四六级词汇 ================= */
VIEWS.vocab = async () => {
  $('#main').innerHTML += `
    <div class="card">
      <div class="rowline">
        <select id="v-level" style="width:110px"><option value="cet4">CET-4</option><option value="cet6">CET-6</option></select>
        <select id="v-count" style="width:110px"><option>5</option><option selected>10</option><option>15</option><option>20</option></select>
        <label class="checkline"><input type="checkbox" id="v-llm"> AI 生成语境例句填空（需大模型）</label>
        <button class="btn" id="v-start">开始测验</button>
      </div>
      <div class="muted mt">错过的词会加权重出；答错的词自动进入生词本。</div>
    </div>
    <div id="v-quiz"></div>
    <div id="v-result"></div>
    <div class="card"><h3>📕 我的生词本</h3><div id="v-wordbook" class="muted">加载中…</div></div>`;
  loadWordbook();
  $('#v-start').onclick = async () => {
    const btn = $('#v-start'); btn.disabled = true; btn.textContent = '出题中…';
    try {
      const r = await api('vocab/quiz', {method:'POST', body:{sid: state.sid, level: $('#v-level').value,
        count: +$('#v-count').value, llm_sentences: $('#v-llm').checked}});
      state.quiz = r;
      renderQuiz(r);
    } catch (e) { toast(e.message, true); }
    btn.disabled = false; btn.textContent = '开始测验';
  };
  function renderQuiz(r) {
    $('#v-quiz').innerHTML = `<div class="card"><h3>测验进行中（${r.count} 题）</h3>` +
      r.questions.map((q, i) => `
        <div class="vocab-q">
          <div class="word">${i+1}. ${esc(q.word)} <span class="pill gray">${esc(q.pos||'')}</span> <span class="pill">${q.mode==='cloze'?'语境':'词义'}</span></div>
          ${q.sentence ? `<div class="sent">${esc(q.sentence)}</div>` : (q.phrase ? `<div class="sent">搭配：${esc(q.phrase)}</div>` : '')}
          ${q.options.map(o => `<label class="opt"><input type="radio" name="q${i}" value="${o.key}"><b>${o.key}.</b> ${esc(o.meaning)}</label>`).join('')}
        </div>`).join('') +
      `<button class="btn" id="v-submit">交卷</button></div>`;
    $('#v-submit').onclick = async () => {
      const answers = {};
      r.questions.forEach((q, i) => {
        const sel = document.querySelector(`input[name=q${i}]:checked`);
        if (sel) answers[i] = sel.value;
      });
      try {
        const res = await api('vocab/submit', {method:'POST', body:{sid: state.sid, quiz_id: r.quiz_id, answers}});
        renderQuizResult(res);
        if (res.awarded) toast('🎯 积分 +' + res.awarded);
        loadWordbook();
        state.quiz = null;
      } catch (e) { toast(e.message, true); }
    };
  }
  function renderQuizResult(res) {
    $('#v-quiz').innerHTML = '';
    $('#v-result').innerHTML = `
      <div class="card">
        <h3>成绩：${res.right} / ${res.total}（${res.score_pct} 分）</h3>
        ${res.results.map(r0 => `
          <div class="vocab-q">
            <div class="word">${r0.word} ${r0.correct?'<span class="pill green">✓</span>':`<span class="pill red">✗ 正确答案含：${esc(r0.meaning)}</span>`}</div>
            ${r0.sentence ? `<div class="sent">${esc(r0.sentence)}<br>答案：${esc(r0.word)}</div>` : ''}
            <div class="muted">释义：${esc(r0.meaning)}${r0.phrase ? ' · 搭配：' + esc(r0.phrase) : ''}</div>
          </div>`).join('')}
      </div>`;
  }
  async function loadWordbook() {
    const r = await api('vocab/wordbook', {query:{sid: state.sid}});
    $('#v-wordbook').innerHTML = r.words.length ? `
      <table class="tbl"><tr><th>单词</th><th>释义</th><th>级别</th><th>对/错</th><th>最近</th></tr>
      ${r.words.map(w=>`<tr><td><b>${esc(w.word)}</b></td><td>${esc(w.meaning)}</td><td>${esc((w.level||'').toUpperCase())}</td>
        <td>${w.right||0} / ${w.wrong||0}</td><td class="muted">${fmtTime(w.last)}</td></tr>`).join('')}</table>`
      : '<span class="muted">生词本为空，做一次测验吧</span>';
  }
};

/* ================= 大学数学题库 · 组卷工作台 =================
   参考 JudgePeach/math-question-bank（稳定ID / 知识点标注 / 只读Agent取题 / 候选两级读取） */
VIEWS.bank = async () => {
  $('#main').innerHTML += `<div id="bank-wrap"><div class="card muted">加载中…</div></div>`;
  let CAP = null, _tab = 'browse';
  const cap = async () => { if (!CAP) CAP = await api('bank/capabilities', {query:{sid: state.sid}}); return CAP; };
  const typeCn = {choice: '选择题', fill: '填空题', solve: '解答题'};
  const diffCn = {basic: '基础', mid: '中等', hard: '较难'};

  async function render() {
    const c = await cap();
    const tabs = [['browse', '📚 题库浏览'], ['add', '➕ 录入题目'], ['compose', '🧾 组卷工作台']]
      .map(([k, v]) => `<button class="btn small ${_tab === k ? '' : 'ghost'}" data-tab="${k}">${v}</button>`).join('');
    $('#bank-wrap').innerHTML = `
      <div class="card"><div class="rowline" style="justify-content:space-between;align-items:center">
        <span>共 <b>${c.total}</b> 题 · 线代 ${c.counts_by_subject.linear_algebra || 0} / 数分 ${c.counts_by_subject.calculus || 0} ·
        选择 ${c.counts_by_type.choice} / 填空 ${c.counts_by_type.fill} / 解答 ${c.counts_by_type.solve}</span>
        <span class="rowline">${tabs}</span></div></div>
      <div id="bank-body" class="mt"></div>`;
    $('#bank-wrap').querySelectorAll('button[data-tab]').forEach(b => b.onclick = () => { _tab = b.dataset.tab; render(); });
    if (_tab === 'browse') await renderBrowse(c);
    else if (_tab === 'add') await renderAdd(c);
    else await renderCompose(c);
  }

  /* ---- 题库浏览 ---- */
  const _f = {subject: '', type: '', difficulty: '', q: '', page: 1};
  async function renderBrowse(c) {
    const body = $('#bank-body');
    const subjOpts = [['', '全部科目']].concat(Object.entries(c.subjects)).map(([k, v]) =>
      `<option value="${k}" ${_f.subject === k ? 'selected' : ''}>${v}</option>`).join('');
    const typeOpts = [['', '全部题型']].concat(Object.entries(typeCn)).map(([k, v]) =>
      `<option value="${k}" ${_f.type === k ? 'selected' : ''}>${v}</option>`).join('');
    const diffOpts = [['', '全部难度']].concat(Object.entries(diffCn)).map(([k, v]) =>
      `<option value="${k}" ${_f.difficulty === k ? 'selected' : ''}>${v}</option>`).join('');
    body.innerHTML = `
      <div class="card">
        <div class="rowline">
          <select id="bk-subject" style="width:130px">${subjOpts}</select>
          <select id="bk-type" style="width:110px">${typeOpts}</select>
          <select id="bk-diff" style="width:110px">${diffOpts}</select>
          <input id="bk-q" placeholder="搜题干/答案/解析关键词" style="flex:1">
          <button class="btn small" id="bk-go">搜索</button>
        </div>
        <div id="bk-list" class="mt"><div class="muted">加载中…</div></div>
      </div>`;
    const load = async () => {
      _f.subject = $('#bk-subject').value; _f.type = $('#bk-type').value;
      _f.difficulty = $('#bk-diff').value; _f.q = $('#bk-q').value.trim();
      const r = await api('bank/search', {query: Object.assign({sid: state.sid, page: _f.page}, _f)});
      $('#bk-list').innerHTML = (r.total ? `<div class="muted">共 ${r.total} 题 · 第 ${r.page} 页</div>` : '<div class="muted">没有匹配的题目</div>') +
        r.items.map(it => `
          <details class="bank-item" data-id="${it.id}">
            <summary style="cursor:pointer"><b>${it.id}</b>
              <span class="pill">${it.type_name}</span><span class="pill gray">${it.difficulty_name}</span>
              ${it.kp_names.map(k => `<span class="pill amber">${esc(k)}</span>`).join('')}</summary>
            <div class="muted bk-ex">${esc(it.stem_excerpt)}</div>
            <div class="bk-full mt"></div>
          </details>`).join('') +
        (r.next_page ? `<div class="mt"><button class="btn small ghost" id="bk-more">下一页 →</button></div>` : '');
      $('#bk-list').querySelectorAll('details.bank-item').forEach(d => d.addEventListener('toggle', async () => {
        if (!d.open || d.dataset.loaded) return;
        d.dataset.loaded = '1';
        const it = await api('bank/item', {query: {sid: state.sid, id: d.dataset.id}});
        d.querySelector('.bk-full').innerHTML = `<div class="md">${md(it.stem)}</div>
          ${(it.options || []).length ? `<div class="mt">${it.options.map(o => `<div><b>${o.key}.</b> ${esc(o.text)}</div>`).join('')}</div>` : ''}
          <details class="lesson-ex"><summary>显示答案与解析（教师视角）</summary>
            <div class="answer-ref"><b>答案：</b>${esc(it.answer)}</div>
            <div class="answer-ref md"><b>解析：</b>${md(it.solution || '（无）')}</div></details>
          <div class="mt rowline"><button class="btn small danger" data-del="${it.id}">删除</button>
            <span class="muted" style="font-size:12px">来源：${esc(it.source || '—')}</span></div>`;
        const del = d.querySelector('[data-del]');
        if (del) del.onclick = async () => {
          if (!confirm('删除题目 ' + it.id + '？')) return;
          await api('bank/delete', {method: 'POST', body: {sid: state.sid, id: it.id}});
          toast('已删除');
          render();
        };
      }));
      const more = document.getElementById('bk-more');
      if (more) more.onclick = () => { _f.page = r.next_page; load(); };
    };
    ['bk-subject', 'bk-type', 'bk-diff'].forEach(id => $('#' + id).onchange = () => { _f.page = 1; load(); });
    $('#bk-go').onclick = () => { _f.page = 1; load(); };
    $('#bk-q').addEventListener('keydown', e => { if (e.key === 'Enter') { _f.page = 1; load(); } });
    await load();
  }

  /* ---- 录入题目 ---- */
  async function renderAdd(c) {
    const body = $('#bank-body');
    const subjOpts = Object.entries(c.subjects).map(([k, v]) => `<option value="${k}">${v}</option>`).join('');
    body.innerHTML = `
      <div class="card">
        <h3>➕ 录入新题目（大学数学）</h3>
        <div class="rowline mt">
          <select id="ba-subject" style="width:140px">${subjOpts}</select>
          <select id="ba-type" style="width:120px">${Object.entries(typeCn).map(([k, v]) => `<option value="${k}">${v}</option>`).join('')}</select>
          <select id="ba-diff" style="width:110px">${Object.entries(diffCn).map(([k, v]) => `<option value="${k}">${v}</option>`).join('')}</select>
        </div>
        <label class="f mt">考查知识点（可多选，第一个为主考查点）</label>
        <div id="ba-kps" class="rowline" style="flex-wrap:wrap"></div>
        <label class="f mt">题干（数学式用 $...$ LaTeX）</label>
        <textarea id="ba-stem" style="min-height:70px" placeholder="例：计算 $\\begin{vmatrix}2&1\\\\3&4\\end{vmatrix}$ 的值"></textarea>
        <div id="ba-opts" class="mt">
          <label class="f">选项（选择题）</label>
          ${'ABCD'.split('').map(k => `<div class="rowline mt"><b style="width:20px">${k}.</b><input class="ba-opt" data-key="${k}" style="flex:1"></div>`).join('')}
        </div>
        <label class="f mt">答案</label>
        <input id="ba-answer" style="width:100%" placeholder="选择题填选项字母；填空/解答填最终答案">
        <label class="f mt">解析（可含 LaTeX）</label>
        <textarea id="ba-solution" style="min-height:70px"></textarea>
        <div class="rowline mt"><input id="ba-source" placeholder="来源（如：自编 / 期末真题）" style="flex:1">
          <button class="btn" id="ba-save">保存入库</button></div>
        <div class="muted mt" style="font-size:12px">入库后可用「组卷工作台」选入试卷。云端模式下新增题目随容器临时盘（重部署回退种子集）；本地模式永久保存。</div>
      </div>`;
    const catOf = () => CAP.catalog.filter(x => x.subject === $('#ba-subject').value);
    const drawKps = () => {
      $('#ba-kps').innerHTML = catOf().map(x =>
        `<label class="checkline"><input type="checkbox" value="${x.id}"> ${esc(x.name)}</label>`).join('');
    };
    $('#ba-subject').onchange = drawKps;
    $('#ba-type').onchange = () => { $('#ba-opts').style.display = $('#ba-type').value === 'choice' ? '' : 'none'; };
    drawKps();
    $('#ba-save').onclick = async () => {
      const kps = [...$('#ba-kps').querySelectorAll('input:checked')].map(x => x.value);
      const body = {sid: state.sid, subject: $('#ba-subject').value, type: $('#ba-type').value,
        difficulty: $('#ba-diff').value, stem: $('#ba-stem').value.trim(),
        answer: $('#ba-answer').value.trim(), solution: $('#ba-solution').value.trim(),
        source: $('#ba-source').value.trim() || '教师录入', kp_ids: kps,
        options: $('#ba-type').value === 'choice' ? [...$('#ba-opts').querySelectorAll('.ba-opt')].map(x => ({key: x.dataset.key, text: x.value.trim()})).filter(o => o.text) : []};
      try {
        const r = await api('bank/add', {method: 'POST', body});
        toast('已入库：' + r.id);
        _tab = 'browse'; render();
      } catch (e) { toast(e.message, true); }
    };
  }

  /* ---- 组卷工作台 ---- */
  async function renderCompose(c) {
    const body = $('#bank-body');
    const subjOpts = Object.entries(c.subjects).map(([k, v]) => `<option value="${k}">${v}</option>`).join('');
    body.innerHTML = `
      <div class="card">
        <h3>🧾 智能组卷</h3>
        <div class="rowline mt">
          <select id="bc-subject" style="width:150px">${subjOpts}</select>
          <input id="bc-title" placeholder="试卷标题（默认自动）" style="flex:1">
          <input id="bc-duration" type="number" value="90" min="15" max="240" style="width:90px" title="考试时长（分钟）">
        </div>
        <label class="f mt">考查知识点（不选 = 全库随机）</label>
        <div id="bc-kps" class="rowline" style="flex-wrap:wrap"></div>
        <label class="f mt">题型与数量（每题 10 分，难度梯度自动配：基础 40% / 中等 40% / 较难 20%）</label>
        <div class="rowline">
          ${Object.entries(typeCn).map(([k, v]) => `<span class="rowline"><b style="margin:0 4px">${v}</b>
            <input id="bc-${k}" type="number" min="0" max="12" value="${k === 'choice' ? 4 : k === 'fill' ? 3 : 2}" style="width:64px"></span>`).join('')}
          <button class="btn" id="bc-gen">✨ 生成试卷预览</button>
        </div>
        <div id="bc-preview" class="mt"></div>
      </div>`;
    const drawKps = () => {
      $('#bc-kps').innerHTML = CAP.catalog.filter(x => x.subject === $('#bc-subject').value).map(x =>
        `<label class="checkline"><input type="checkbox" value="${x.id}"> ${esc(x.name)}<span class="muted" style="font-size:11px">(${x.questions})</span></label>`).join('');
    };
    $('#bc-subject').onchange = drawKps;
    drawKps();
    let draft = null;
    $('#bc-gen').onclick = async () => {
      const counts = {choice: +$('#bc-choice').value || 0, fill: +$('#bc-fill').value || 0, solve: +$('#bc-solve').value || 0};
      const kps = [...$('#bc-kps').querySelectorAll('input:checked')].map(x => x.value);
      $('#bc-preview').innerHTML = '<div class="muted">组卷中…</div>';
      try {
        draft = await api('bank/compose', {method: 'POST', body: {sid: state.sid,
          subject: $('#bc-subject').value, kp_ids: kps, counts,
          duration: +$('#bc-duration').value || 90, title: $('#bc-title').value.trim()}});
        drawSheet(false);
      } catch (e) { $('#bc-preview').innerHTML = `<div class="muted">${esc(e.message)}</div>`; }
    };
    function drawSheet(teacher) {
      if (!draft) return;
      let n = 0;
      const secHtml = draft.sections.map(sec => `
        <div class="a4-sec"><b>${sec.type_name}</b>（共 ${sec.items.length} 题，${sec.note}）</div>
        ${sec.items.map(it => {
          n += 1;
          const q = it.question;
          return `<div class="a4-q"><b>${n}.</b> <span class="md">${md(q.stem)}</span>
            ${(q.options || []).length ? `<div class="a4-opts">${q.options.map(o => `<span><b>${o.key}.</b> ${esc(o.text)}</span>`).join('　')}</div>` : ''}
            ${teacher ? `<div class="a4-ans"><b>【答案】</b>${esc(q.answer)}${q.solution ? `<br><b>【解析】</b><span class="md">${md(q.solution)}</span>` : ''}</div>` : ''}
            </div>`;
        }).join('')}`).join('');
      $('#bc-preview').innerHTML = `
        <div class="rowline mt" style="justify-content:space-between">
          <span class="rowline">
            <button class="btn small ${teacher ? 'ghost' : ''}" id="bc-stu">👤 学生版</button>
            <button class="btn small ${teacher ? '' : 'ghost'}" id="bc-tea">🧑‍🏫 教师版（含答案解析）</button>
          </span>
          <span class="rowline">
            <button class="btn small" id="bc-print">🖨 打印 / 导出 PDF</button>
            <button class="btn small" id="bc-topaper">📝 转为作答卷（自动批改+错题本）</button>
          </span>
        </div>
        <div class="a4-sheet mt" id="a4-zone">
          <div class="a4-head">${esc(draft.title)}<br>
            <span style="font-size:12px">时长 ${draft.duration} 分钟 · 满分 ${draft.total_score} 分 · 共 ${draft.total_n} 题</span></div>
          ${secHtml}
          <div class="a4-end">—— 试卷结束 ——</div>
        </div>`;
      $('#bc-stu').onclick = () => drawSheet(false);
      $('#bc-tea').onclick = () => drawSheet(true);
      $('#bc-print').onclick = () => window.print();
      $('#bc-topaper').onclick = async () => {
        try {
          const r = await api('bank/to_paper', {method: 'POST', body: {sid: state.sid, draft}});
          toast('已转为作答卷，进入诊断卷列表');
          location.hash = '#/paper/' + r.paper_id;
        } catch (e) { toast(e.message, true); }
      };
    }
  }

  await render();
};

/* ================= 诊断卷 ================= */
VIEWS.paper = async (pid) => {
  const subjects = {...state.boot.subjects, english: '英语（四六级）'};
  $('#main').innerHTML += `
    <div class="card">
      <h3>组卷设置</h3>
      <div class="rowline">
        <select id="p-subject" style="width:170px">${Object.entries(subjects).map(([k,v])=>`<option value="${k}">${v}</option>`).join('')}</select>
        <select id="p-diff" style="width:150px"><option value="easy">难度：基础</option><option value="mid" selected>难度：常规</option><option value="hard">难度：提升</option></select>
        <label class="checkline"><input type="checkbox" id="p-auto" checked> 自动按薄弱点选知识点</label>
      </div>
      <div id="p-kps" class="mt"></div>
      <div id="p-english-opts" style="display:none" class="mt rowline">
        <select id="p-level" style="width:110px"><option value="cet4">CET-4</option><option value="cet6">CET-6</option></select>
        <span class="muted">英语卷 = 词汇选择 + 段落翻译 + 写作</span>
      </div>
      <div class="mt"><button class="btn" id="p-gen">生成诊断卷</button></div>
    </div>
    <div id="p-list" class="card"></div>
    <div id="paper-view"></div>`;
  const subjSel = $('#p-subject');
  async function renderKps() {
    const isEn = subjSel.value === 'english';
    $('#p-english-opts').style.display = isEn ? '' : 'none';
    $('#p-kps').style.display = isEn ? 'none' : '';
    if (isEn) return;
    const r = await api('knowledge', {query:{sid: state.sid, subject: subjSel.value}});
    const pre = new Set(state.handoff.paperKps && state.handoff.paperSubject === subjSel.value ? state.handoff.paperKps : []);
    $('#p-kps').innerHTML = r.kps.map(k => `
      <label class="checkline"><input type="checkbox" value="${k.id}" ${pre.has(k.id)?'checked':''}>
        ${esc(k.name)} ${k.score!==null ? levelBadge(k.level) : ''}</label>`).join('');
  }
  subjSel.onchange = renderKps;
  renderKps();
  state.handoff.paperKps = null;
  $('#p-gen').onclick = async () => {
    const btn = $('#p-gen'); btn.disabled = true; btn.textContent = '命题中…';
    try {
      const body = {sid: state.sid, subject: subjSel.value, difficulty: $('#p-diff').value};
      if (subjSel.value === 'english') body.counts = {level: $('#p-level').value, vocab: 6};
      else if (!$('#p-auto').checked) body.kp_ids = [...$('#p-kps').querySelectorAll('input:checked')].map(i => i.value);
      const r = await api('paper/generate', {method:'POST', body});
      if (r.error) throw new Error(r.error);
      state.paper = r;
      renderPaper(r);
    } catch (e) { toast(e.message, true); }
    btn.disabled = false; btn.textContent = '生成诊断卷';
  };
  loadPaperList();
  if (pid) {
    try {
      state.paper = await api('paper', {query: {sid: state.sid, id: pid}});
      renderPaper(state.paper);
      setTimeout(() => $('#paper-view')?.scrollIntoView({behavior: 'smooth'}), 100);
    } catch (e) { toast(e.message, true); }
  }
  async function loadPaperList() {
    const r = await api('paper/list', {query:{sid: state.sid}});
    $('#p-list').innerHTML = `<h3>历史试卷</h3>` + (r.papers.length ? r.papers.map(p => `
      <div class="rowline" style="justify-content:space-between; padding:6px 0; border-bottom:1px solid var(--line)">
        <span>${esc(p.subject_name||p.subject)} · ${fmtTime(p.created)} ${p.status==='graded'?`<span class="pill green">已批改 ${p.score}分</span>`:'<span class="pill amber">待完成</span>'}</span>
        <button class="btn small ghost" onclick="window.__openPaper('${p.id}')">查看</button>
      </div>`).join('') : '<span class="muted">还没有试卷</span>');
    window.__openPaper = async id => {
      state.paper = await api('paper', {query:{sid: state.sid, id}});
      renderPaper(state.paper);
      $('#paper-view').scrollIntoView({behavior:'smooth'});
    };
  }
  function renderPaper(p) {
    const graded = p.status === 'graded';
    const results = graded ? {} : null;
    if (graded) p.results.forEach(r0 => results[r0.id] = r0);
    $('#paper-view').innerHTML = `
      <div class="card">
        <div class="rowline" style="justify-content:space-between">
          <h3 style="margin:0">${esc(p.subject_name)} 诊断卷 ${p.offline?'<span class="pill amber">离线题库</span>':''}</h3>
          <span class="muted">考点：${esc((p.kp_names||[]).join('、')) || '—'}</span>
        </div>
        ${graded ? `<div class="mt"><b>得分：${p.score}</b> <span class="muted">${fmtTime(p.graded_at)}</span></div>` : ''}
        <div class="mt">
        ${p.questions.map((q, i) => {
          const rs = graded ? results[q.id] : null;
          return `<div class="paper-q ${graded ? 'result-item' + (rs && !rs.correct ? ' bad' : '') : ''}">
            <div class="stem">${i+1}. [${typeCn(q.type)}] ${md(q.stem)}</div>
            ${q.options ? `<div class="opts">${q.options.map(o=>`
              <label class="opt ${graded ? (o.key===q.answer?'right':(rs&&rs.your_answer===o.key?'wrong':'')) : ''}">
                <input type="radio" name="pq${q.id}" value="${o.key}" ${graded&&rs&&rs.your_answer===o.key?'checked':''} ${graded?'disabled':''}>
                <b>${o.key}.</b> ${esc(o.text)}</label>`).join('')}</div>`
              : (graded ? `<div class="answer-ref">你的作答：${esc(rs?rs.your_answer:'（未作答）')}</div>`
                        : `<textarea class="short" id="pa-${q.id}" placeholder="在此作答"></textarea>`)}
            ${graded ? `<div class="answer-ref"><b>参考答案：</b>${esc(q.answer)}\n${esc(q.analysis||'')}<br><b>本题反馈：</b>${esc(rs?rs.feedback:'')}</div>` : ''}
          </div>`; }).join('')}
        </div>
        ${graded
          ? `<div class="card" style="background:var(--brand-soft)"><b>批改建议：</b>${esc(state.paper._advice || (p._advice||''))}
             <div class="mt rowline noprint">
               <button class="btn" onclick="location.hash='#/report/${p.id}'">📋 进入诊断精讲报告</button>
               <button class="btn ghost" onclick="window.__notesFromPaper()">为错题知识点生成讲义</button>
               <button class="btn ghost" onclick="location.reload()">再来一卷</button>
             </div></div>`
          : `<button class="btn" id="p-submit">交卷批改</button>`}
      </div>`;
    const subBtn = $('#p-submit');
    if (subBtn) subBtn.onclick = async () => {
      const answers = {};
      p.questions.forEach(q => {
        if (q.options) {
          const sel = document.querySelector(`input[name=pq${q.id}]:checked`);
          if (sel) answers[q.id] = sel.value;
        } else {
          const t = document.getElementById('pa-' + q.id);
          if (t) answers[q.id] = t.value;
        }
      });
      if (!confirm('确认交卷？主观题将由 AI 按步骤给分（离线模式按要点覆盖率估分）。')) return;
      subBtn.disabled = true; subBtn.textContent = '批改中…';
      try {
        const r = await api('paper/submit', {method:'POST', body:{sid: state.sid, paper_id: p.id, answers}});
        state.paper = await api('paper', {query:{sid: state.sid, id: p.id}});
        state.paper._advice = r.advice + (r.wrong_kps.length ? '（薄弱：' + r.wrong_kps.join('、') + '）' : '');
        window.__paperWrongKps = {subject: p.subject, kps: r.wrong_kps};
        renderPaper(state.paper);
        loadPaperList();
        toast('批改完成：' + r.score + ' 分' + (r.awarded ? '，🎯 积分 +' + r.awarded : ''));
        $('#paper-view').scrollIntoView({behavior:'smooth'});
      } catch (e) { toast(e.message, true); subBtn.disabled = false; subBtn.textContent = '交卷批改'; }
    };
    window.__notesFromPaper = () => {
      const w = window.__paperWrongKps;
      if (!w || !w.kps.length) return toast('本次没有明显薄弱点，可直接抽查讲义', true);
      state.handoff.notesKps = w.kps; state.handoff.notesSubject = w.subject;
      location.hash = '#/notes';
    };
  }
  function typeCn(t) { return {choice:'单选', fill:'简答', solve:'解答', translation:'翻译', writing:'写作'}[t] || t; }
};

/* ================= 诊断精讲报告 ================= */
VIEWS.report = async (pid) => {
  if (!pid) { $('#main').innerHTML += '<div class="card">缺少试卷 ID</div>'; return; }
  const p = await api('paper', {query:{sid: state.sid, id: pid}});
  if (p.status !== 'graded') { $('#main').innerHTML += '<div class="card">该试卷尚未批改</div>'; return; }
  const report = p.report || [];
  // 雷达：本卷各考点得分率
  const kpAgg = {};
  (p.questions || []).forEach(q => {
    const r = (p.results || []).find(x => x.id === q.id);
    if (!r) return;
    const name = q.kp_name || q.kp_id || '综合';
    (kpAgg[name] = kpAgg[name] || []).push(r.score / (r.full || 10) * 100);
  });
  const rLabels = Object.keys(kpAgg).slice(0, 10);
  const rValues = rLabels.map(k => kpAgg[k].reduce((a, b) => a + b, 0) / kpAgg[k].length);
  $('#main').innerHTML += `
    <div class="card" style="background:var(--brand-soft)">
      <b>${esc(p.subject_name)} 诊断精讲报告</b>
      <span class="muted">得分 ${p.score} · 错题 ${report.length} 道 · ${fmtTime(p.graded_at)}</span>
      <div class="muted mt">逐题展开：考点精讲 → 易错警示 → 同类例题 → 参考资料。吃透一道，勾掉一个薄弱点。</div>
    </div>
    ${rLabels.length >= 3 ? `<div class="card"><h3>🕸️ 本卷考点得分率雷达</h3>
      ${radarSVG(rLabels, rValues, 280)}
      <div class="muted">数值 = 该考点题目得分率（%），越凹的轴越要回头练。</div></div>` : ''}
    ${report.length ? report.map((r, i) => `
      <div class="paper-q result-item bad">
        <div class="stem">${i+1}. [${typeCn(r.type)}] 考点：${esc(r.kp_name)}</div>
        <div class="answer-ref" style="margin-top:6px">${esc(r.stem)}</div>
        <div class="mt"><b>你的作答：</b><span class="md">${md(r.your_answer || '（未作答）')}</span></div>
        <div class="answer-ref"><b>✅ 参考答案：</b>${esc(r.answer)}</div>
        <h4>📖 考点精讲</h4>
        ${(r.key_points||[]).length ? `<ul>${r.key_points.map(k=>`<li>${esc(k)}</li>`).join('')}</ul>` : '<span class="muted">'+esc(r.analysis||'见参考答案解析')+'</span>'}
        ${(r.common_errors||[]).length ? `<h4>⚠️ 易错警示</h4><ul>${r.common_errors.map(k=>`<li>${esc(k)}</li>`).join('')}</ul>` : ''}
        ${(r.similar||[]).length ? `<h4>✏️ 同类例题（先自己做再看解析）</h4>
          ${r.similar.map(s=>`<details><summary style="cursor:pointer;color:var(--brand)">${esc(s.q)}</summary>
            <div class="answer-ref">${esc(s.a)}</div></details>`).join('')}` : ''}
        ${(r.material_refs||[]).length ? `<h4>📁 校本资料相关片段</h4>
          ${r.material_refs.map(m=>`<div class="answer-ref"><b>【${esc(m.material)}】</b>${esc(m.text)}</div>`).join('')}` : ''}
        ${(r.sources||[]).length ? `<div class="src mt">📚 资料：${r.sources.map(s=>s.note&&s.note.startsWith('http')?`<a href="${esc(s.note)}" target="_blank">${esc(s.title)}</a>`:esc(s.title)).join(' · ')}</div>` : ''}
        <div class="mt rowline noprint">
          <button class="btn small ghost" onclick="location.hash='#/notes'">为「${esc(r.kp_name)}」生成讲义</button>
        </div>
      </div>`).join('') : '<div class="card">本次没有错题，太棒了！🎉 可以提升难度再来一卷。</div>'}
    <div class="rowline noprint">
      <button class="btn ghost" onclick="location.hash='#/paper'">返回诊断卷</button>
      <button class="btn" onclick="window.print()">打印报告</button>
    </div>`;
  function typeCn(t) { return {choice:'单选', fill:'简答', solve:'解答', translation:'翻译', writing:'写作'}[t] || t; }
};

/* ================= 错题本 ================= */
let _wbCat = '', _wbKind = '';

VIEWS.wrongbook = async () => {
  $('#main').innerHTML += `<div id="wb-wrap"></div>`;
  const kindCn = {math: '数学', english: '英语', vocab: '词汇'};
  async function render() {
    const d = await api('wrongbook', {query: {sid: state.sid}});
    const items = d.items.filter(x => (!_wbKind || x.kind === _wbKind) && (!_wbCat || x.category === _wbCat));
    const kindChips = [['', '全部'], ['math', '数学'], ['english', '英语'], ['vocab', '词汇']].map(([k, v]) =>
      `<button class="btn small ${_wbKind === k ? '' : 'ghost'}" data-kind="${k}">${v} ${_wbKind === k ? '· ' + items.length : d.byKind[k] ? '· ' + d.byKind[k] : ''}</button>`).join('');
    const catChips = d.byCategory.slice(0, 12).map(([c, n]) =>
      `<button class="btn small ${_wbCat === c ? '' : 'ghost'}" data-cat="${esc(c)}">${esc(c)} ×${n}</button>`).join('');
    const list = items.length ? items.map(it => `
      <div class="paper-q result-item ${it.count > 1 ? 'bad' : ''}">
        <div class="rowline" style="justify-content:space-between">
          <span><span class="pill">${kindCn[it.kind] || it.kind}</span> <b>${esc(it.category)}</b>
          ${it.count > 1 ? `<span class="pill red">错 ${it.count} 次</span>` : ''}
          ${it.overdue ? `<span class="pill red">📅 复做到期${it.due_days_ago > 0.2 ? ' ' + Math.round(it.due_days_ago) + ' 天' : ''}</span>` : (it.review_label ? `<span class="pill gray">${esc(it.review_label)}</span>` : '')}</span>
          <span class="muted">${fmtTime(it.last)}</span>
        </div>
        <div class="mt md">${md(it.stem)}</div>
        ${it.kind === 'math' ? `<details><summary style="cursor:pointer;color:var(--brand);font-size:13px">你的作答 / 参考答案 / 解析</summary>
          <div class="answer-ref mt"><b>你的作答：</b>${esc(it.your || '（未作答）')}</div>
          <div class="answer-ref"><b>参考答案：</b>${esc(it.answer)}</div>
          <div class="answer-ref">${esc(it.note || '')}</div></details>`
        : `<div class="answer-ref mt"><b>改为：</b>${esc(it.answer)}</div>${it.note ? `<div class="muted mt">${esc(it.note)}</div>` : ''}`}
        <div class="mt rowline noprint">
          ${it.kind === 'math' && it.kp_id ? `<button class="btn small ghost" data-go="notes" data-subject="${esc(it.subject)}" data-kp="${esc(it.kp_id)}" data-cat="${esc(it.category)}">生成该考点讲义</button>` : ''}
          ${it.kind === 'vocab' ? `<button class="btn small ghost" data-go="vocab">去词汇测验巩固</button>` : ''}
          ${it.kind === 'english' ? `<button class="btn small ghost" data-go="english">去英语批改练习</button>` : ''}
          <button class="btn small" data-practice="${it.id}">🔁 AI变式重练</button>
          <button class="btn small" data-resolve="${it.id}">✓ 已掌握</button>
        </div>
        <div class="wb-practice" id="wb-practice-${it.id}"></div>
      </div>`).join('') : '<div class="card muted">没有未掌握的错题 🎉（错题来自诊断卷、词汇测验和英语批改的自动归纳）</div>';
    $('#wb-wrap').innerHTML = `
      <div class="grid c2">
        <div class="card"><h3>📊 自动归纳</h3>
          <div class="muted">未掌握错题 <b style="color:var(--bad)">${d.total}</b> 道（数学 ${d.byKind.math || 0} · 英语 ${d.byKind.english || 0} · 词汇 ${d.byKind.vocab || 0}），反复出错的自动置顶并标红。${d.due_n ? `其中 <b style="color:var(--bad)">${d.due_n}</b> 道已到遗忘曲线复做点，排在最前。` : ''}</div>
          <div class="rowline mt">${kindChips}</div>
          <div class="rowline mt">${catChips || '<span class="muted">暂无分类数据</span>'}
            ${(_wbCat || _wbKind) ? '<button class="btn small ghost" data-cat="">✕ 清除筛选</button>' : ''}</div>
        </div>
        <div class="card"><h3>🎯 一键巩固</h3>
          <div class="muted">把筛选出的数学错题考点组成一份诊断卷；词汇错词在测验中已加权重出。</div>
          <div class="mt rowline">
            <button class="btn small" id="wb-paper">数学考点组卷巩固</button>
            <button class="btn small ghost" data-go="vocab">去词汇测验</button>
            <button class="btn small ghost" data-go="english">去英语批改</button>
          </div>
        </div>
      </div>
      <div id="wb-list">${list}</div>`;
    $('#wb-wrap').querySelectorAll('button[data-kind]').forEach(b => b.onclick = () => { _wbKind = b.dataset.kind; render(); });
    $('#wb-wrap').querySelectorAll('button[data-cat]').forEach(b => b.onclick = () => { _wbCat = b.dataset.cat; render(); });
    $('#wb-wrap').querySelectorAll('button[data-resolve]').forEach(b => b.onclick = async () => {
      try {
        await api('wrongbook/resolve', {method: 'POST', body: {sid: state.sid, id: b.dataset.resolve}});
        toast('已标记掌握 ✓');
        render();
      } catch (e) {
        toast(e.message || '需要先完成变式重练', true);
        openPractice(b.dataset.resolve);
      }
    });
    $('#wb-wrap').querySelectorAll('button[data-practice]').forEach(b => b.onclick = () => openPractice(b.dataset.practice));
    async function openPractice(id) {
      const box = document.getElementById('wb-practice-' + id);
      if (!box) return;
      if (box.dataset.open) { box.innerHTML = ''; box.dataset.open = ''; return; }
      box.dataset.open = '1';
      box.innerHTML = '<div class="muted mt">出题中…（AI 正在根据错题生成同考点变式题）</div>';
      let vs;
      try {
        const r = await api('wrongbook/variants', {method: 'POST', body: {sid: state.sid, id}});
        vs = r.variants || [];
      } catch (e) { box.innerHTML = `<div class="muted mt">${esc(e.message || '生成失败')}</div>`; return; }
      if (!vs.length) { box.innerHTML = '<div class="muted mt">变式题生成失败：请确认已接入大模型，或稍后再试。</div>'; return; }
      box.innerHTML = vs.map((v, i) => `
        <div class="answer-ref mt" style="background:#f7f8fc;border-radius:8px">
          <b>变式 ${i + 1}：</b><span class="md">${md(v.q)}</span>
          ${v.answer ? `<div class="rowline mt"><input class="wb-ans" data-i="${i}" placeholder="输入你的答案" style="flex:1;padding:6px 10px;border:1px solid #d5dae8;border-radius:8px"><button class="btn small" data-submit="${i}">提交</button></div>`
                     : `<div class="rowline mt muted">（离线参考题，无自动判卷）<button class="btn small" data-self="1" data-i="${i}">我做对了</button><button class="btn small ghost" data-self="0" data-i="${i}">没做出来</button></div>`}
          <div class="wb-fb" data-fb="${i}"></div>
        </div>`).join('');
      box.querySelectorAll('button[data-submit]').forEach(sb => sb.onclick = async () => {
        const i = +sb.dataset.submit;
        const inp = box.querySelector(`input.wb-ans[data-i="${i}"]`);
        const fb = box.querySelector(`[data-fb="${i}"]`);
        sb.disabled = true; sb.textContent = '判卷中…';
        try {
          const pr = await api('wrongbook/practice', {method: 'POST', body: {sid: state.sid, id, idx: i, answer: inp.value}});
          if (pr.correct) {
            const rv = pr.review || {};
            fb.innerHTML = `<div class="mt" style="color:var(--ok)">✓ ${esc(pr.feedback || '回答正确')}</div>` +
              (rv.graduated ? `<div class="muted">🎓 间隔复习毕业（连过 4 轮）——可以放心标记掌握了</div>`
               : rv.next_days != null ? `<div class="muted">📅 ${rv.next_days} 天后自动安排复做</div>` : '');
            toast('变式重练通过 ✓ 现在可以标记掌握了');
          } else {
            fb.innerHTML = `<div class="mt" style="color:var(--bad)">✗ ${esc(pr.feedback || '再想一想')} ${pr.expected ? '（参考答案：' + esc(pr.expected) + '）' : ''}</div><div class="muted">📅 已重置：明天再练一次这道</div>`;
            sb.disabled = false; sb.textContent = '提交';
          }
        } catch (e) {
          fb.innerHTML = `<div class="muted mt">${esc(e.message || '提交失败')}</div>`;
          sb.disabled = false; sb.textContent = '提交';
        }
      });
      box.querySelectorAll('button[data-self]').forEach(sb => sb.onclick = async () => {
        const i = +sb.dataset.i;
        const fb = box.querySelector(`[data-fb="${i}"]`);
        try {
          const pr = await api('wrongbook/practice', {method: 'POST', body: {sid: state.sid, id, idx: i, answer: '', self_correct: sb.dataset.self === '1'}});
          fb.innerHTML = pr.correct ? `<div class="mt" style="color:var(--ok)">✓ 已记录通过。${esc(pr.feedback || '')}</div>` : `<div class="mt muted">已记录：未掌握，建议查看参考解法后稍后再练。</div>`;
        } catch (e) { fb.innerHTML = `<div class="muted mt">${esc(e.message || '提交失败')}</div>`; }
      });
    }
    $('#wb-wrap').querySelectorAll('button[data-go]').forEach(b => b.onclick = () => {
      const g = b.dataset.go;
      if (g === 'notes') { state.handoff.notesKps = [b.dataset.kp]; state.handoff.notesSubject = b.dataset.subject; location.hash = '#/notes'; }
      else if (g === 'vocab') location.hash = '#/vocab';
      else if (g === 'english') location.hash = '#/english';
    });
    const pb = document.getElementById('wb-paper');
    if (pb) pb.onclick = () => {
      const kps = [...new Set(items.filter(x => x.kind === 'math' && x.kp_id).map(x => x.kp_id))].slice(0, 6);
      if (!kps.length) return toast('筛选结果中没有带知识点标签的数学错题', true);
      state.handoff.paperKps = kps;
      state.handoff.paperSubject = items.find(x => x.kind === 'math').subject || 'linear_algebra';
      location.hash = '#/paper';
    };
  }
  await render();
};

/* ================= 讲义 ================= */
VIEWS.notes = async () => {
  const subjSel0 = state.handoff.notesSubject || 'linear_algebra';
  $('#main').innerHTML += `
    <div class="card">
      <div class="rowline">
        <select id="n-subject" style="width:170px">${Object.entries(state.boot.subjects).map(([k,v])=>`<option value="${k}" ${k===subjSel0?'selected':''}>${v}</option>`).join('')}</select>
        <label class="checkline"><input type="checkbox" id="n-mat" checked> 结合校本资料</label>
        <button class="btn" id="n-gen">生成讲义</button>
      </div>
      <div id="n-kps" class="mt"></div>
    </div>
    <div id="note-view"></div>`;
  const subjSel = $('#n-subject');
  async function renderKps() {
    const r = await api('knowledge', {query:{sid: state.sid, subject: subjSel.value}});
    const pre = new Set(state.handoff.notesKps && state.handoff.notesSubject === subjSel.value ? state.handoff.notesKps : []);
    $('#n-kps').innerHTML = r.kps.map(k => `
      <label class="checkline"><input type="checkbox" value="${k.id}" ${pre.has(k.id)?'checked':''}>
        ${esc(k.name)} ${k.score!==null?levelBadge(k.level):''}</label>`).join('');
  }
  subjSel.onchange = renderKps;
  renderKps();
  state.handoff.notesKps = null;
  $('#n-gen').onclick = async () => {
    const kps = [...$('#n-kps').querySelectorAll('input:checked')].map(i => i.value);
    if (!kps.length) return toast('请选择至少一个知识点', true);
    const btn = $('#n-gen'); btn.disabled = true; btn.textContent = '编写中…';
    try {
      const r = await api('notes/generate', {method:'POST', body:{sid: state.sid, subject: subjSel.value, kp_ids: kps, include_materials: $('#n-mat').checked}});
      if (r.error) throw new Error(r.error);
      renderNote(r);
      if (r.awarded) toast('🎯 积分 +' + r.awarded);
    } catch (e) { toast(e.message, true); }
    btn.disabled = false; btn.textContent = '生成讲义';
  };
  function renderNote(n) {
    $('#note-view').innerHTML = `
      <div class="card">
        <div class="rowline" style="justify-content:space-between">
          <h3 style="margin:0">${esc(n.title)} ${n.offline?'<span class="pill amber">离线拼装</span>':''}</h3>
          <div class="rowline noprint">
            <button class="btn small ghost" id="n-download">下载 .md</button>
            <button class="btn small ghost" onclick="window.print()">打印</button>
          </div>
        </div>
        <div class="md mt">${md(n.markdown)}</div>
      </div>`;
    $('#n-download').onclick = () => {
      const blob = new Blob([n.markdown], {type:'text/markdown;charset=utf-8'});
      const a = document.createElement('a');
      a.href = URL.createObjectURL(blob);
      a.download = n.title + '.md';
      a.click();
    };
    $('#note-view').scrollIntoView({behavior:'smooth'});
  }
};

/* ================= 知识图谱 ================= */
VIEWS.kg = async () => {
  let subject = sessionStorage.getItem('zy_kg_subject') || 'linear_algebra';
  $('#main').innerHTML += `<div class="card" id="kg-wrap"></div>`;
  async function render() {
    const r = await api('knowledge', {query:{sid: state.sid, subject}});
    sessionStorage.setItem('zy_kg_subject', subject);
    $('#kg-wrap').innerHTML = `
      <div class="rowline">${Object.entries(r.subjects).map(([k,v]) =>
        `<button class="btn small ${k===subject?'':'ghost'}" data-s="${k}">${v}</button>`).join('')}</div>
      <div class="grid c2 mt">${r.kps.map(k => `
        <div class="kp-card">
          <div class="head"><b>${esc(k.name)}</b><span>${k.score!==null?levelBadge(k.level):'<span class="pill gray">未诊断</span>'}</span></div>
          ${k.score!==null?`<div class="meter"><i style="width:${k.score}%"></i></div>`:''}
          <div class="muted mt">${esc(k.description)}</div>
          <details><summary>要点 / 易错 / 例题</summary>
            <b>关键要点</b><ul>${k.key_points.map(p=>`<li>${esc(p)}</li>`).join('')}</ul>
            <b>常见易错</b><ul>${k.common_errors.map(p=>`<li>${esc(p)}</li>`).join('')}</ul>
            ${(k.samples&&k.samples.length)?`<b>例题（${k.samples.length} 道，点击展开解答）</b>
              ${k.samples.map((s,i)=>`<details style="margin:6px 0"><summary style="cursor:pointer;color:var(--brand);font-size:13px">例${i+1}（${s.type==='compute'?'计算':'概念'}）${esc(s.q.slice(0,36))}${s.q.length>36?'…':''}</summary>
                <div style="margin-top:4px">${esc(s.q)}</div>
                <div class="answer-ref" style="margin-top:6px"><b>解：</b>${esc(s.a)}</div></details>`).join('')}`:''}
          </details>
        </div>`).join('')}</div>`;
    $('#kg-wrap').querySelectorAll('button[data-s]').forEach(b => b.onclick = () => { subject = b.dataset.s; render(); });
  }
  await render();
};

/* ================= 校本资料库 ================= */
VIEWS.materials = async () => {
  $('#main').innerHTML += `
    <div class="card">
      <h3>上传本校资料（.txt / .md / .docx / .pdf）</h3>
      <div class="rowline">
        <input type="file" id="m-file" multiple accept=".txt,.md,.docx,.pdf">
        <input type="file" id="m-folder" webkitdirectory multiple title="选择整个文件夹批量导入">
      </div>
      <div class="muted mt">第二个按钮可选择整个资料文件夹批量导入（如北航网盘下载的「5系学习资料」中的 docx/文本文件）</div>
      <h4>或直接粘贴文本（教学大纲 / 习题集片段）</h4>
      <input type="text" id="m-name" placeholder="资料名称，如：高数期中试卷 2025">
      <textarea id="m-text" class="short" placeholder="粘贴内容…"></textarea>
      <div class="mt"><button class="btn" id="m-add">保存资料</button><span class="muted" id="m-progress" style="margin-left:10px"></span></div>
    </div>
    <div class="card"><h3>检索测试（模拟问答时的引用）</h3>
      <div class="rowline"><input type="text" id="m-q" placeholder="输入关键词，如：基础解系" style="flex:1">
      <button class="btn ghost" id="m-search">检索</button></div>
      <div id="m-results" class="mt"></div>
    </div>
    <div class="card"><h3>已存资料</h3><div id="m-list"></div></div>
    <div class="card"><h3>📚 高校资料 / 开源题库索引</h3>
      <div class="muted">问答与诊断报告会自动推荐下列来源；网盘类链接需手动下载后用上方按钮批量导入。</div>
      <div id="m-sources" class="mt" style="line-height:2"></div>
    </div>`;
  await loadList();
  const ACCEPT = ['.txt', '.md', '.docx', '.pdf'];
  async function uploadMany(files, tag) {
    const ok = [...files].filter(f => ACCEPT.includes(f.name.slice(f.name.lastIndexOf('.')).toLowerCase()));
    const prog = $('#m-progress');
    let done = 0;
    for (const f of ok) {
      prog.textContent = `${tag}上传中 ${++done}/${ok.length}：${f.name}`;
      const fd = new FormData();
      fd.append('sid', state.sid);
      fd.append('file', f);
      try { await api('materials', {method: 'POST', body: fd}); } catch (e) { /* 跳过失败文件 */ }
    }
    prog.textContent = `完成：导入 ${ok.length} 个文件`;
    toast(`已导入 ${ok.length} 个文件`);
    await loadList();
  }
  $('#m-file').onchange = e => { if (e.target.files.length) uploadMany(e.target.files, ''); e.target.value = ''; };
  $('#m-folder').onchange = e => { if (e.target.files.length) uploadMany(e.target.files, '文件夹'); e.target.value = ''; };
  $('#m-add').onclick = async () => {
    const text = $('#m-text').value.trim();
    if (text) {
      await api('materials', {method:'POST', body:{sid: state.sid, name: $('#m-name').value || '未命名资料', text}});
    } else {
      return toast('请选择文件或粘贴文本', true);
    }
    toast('资料已保存');
    $('#m-text').value = ''; $('#m-name').value = '';
    await loadList();
  };
  $('#m-search').onclick = async () => {
    const q = $('#m-q').value.trim();
    if (!q) return;
    const r = await api('materials/search', {method:'POST', body:{sid: state.sid, query: q}});
    $('#m-results').innerHTML = r.chunks.length ? r.chunks.map(c =>
      `<div class="answer-ref"><b>【${esc(c.material)}】</b>${esc(c.text.slice(0, 220))}…</div>`).join('')
      : '<span class="muted">没有匹配内容</span>';
  };
  async function loadList() {
    const r = await api('materials', {query:{sid: state.sid}});
    $('#m-list').innerHTML = r.materials.length ? r.materials.map(m => `
      <div class="rowline" style="justify-content:space-between; padding:6px 0; border-bottom:1px solid var(--line)">
        <span>📄 ${esc(m.name)} <span class="muted">${m.size}字 · ${m.chunks}块</span></span>
        <button class="btn small danger" onclick="window.__delMat('${m.id}')">删除</button>
      </div>`).join('') : '<span class="muted">还没有资料。上传本校课件后，问答、出卷、讲义都会优先引用它。</span>';
    window.__delMat = async id => {
      if (!confirm('确认删除该资料？')) return;
      await api('materials', {method:'DELETE', query:{sid: state.sid, id}});
      loadList();
    };
    const s = await api('sources');
    $('#m-sources').innerHTML = s.sources.map(x =>
      `<div><a href="${esc(x.url)}" target="_blank"><b>${esc(x.name)}</b></a> — <span class="muted">${esc(x.note||'')}</span></div>`).join('');
  }
};

/* ================= 学习记忆 ================= */
let _memEditingTs = null;
let _memEditingStrategy = false;
let _sysEditing = false;

VIEWS.memory = async () => {
  $('#main').innerHTML += `<div id="mem-wrap"></div>`;
  async function render() {
    const m = await api('memory', {query:{sid: state.sid}});
    let sys = null;
    try { sys = await api('system/insight', {query:{sid: state.sid}}); } catch (e) { /* 云端不可用时隐藏 */ }
    const stars = r => r > 0 ? '👍 有帮助' : (r < 0 ? '👎 没帮助' : '· 一般');
    const sysCard = sys ? `
      <div class="card">
        <h3>🌐 全班反馈学习（系统级自我迭代）</h3>
        <div class="muted">已聚合 <b>${sys.live.users}</b> 位同学的档案 · <b>${sys.live.feedback_n}</b> 条反馈与近期问题。全局策略注入每个人的 AI 问答提示词。</div>
        ${sys.live.neg_feedback.length ? `<h4 class="mt">👎 待改进诉求</h4>
          ${sys.live.neg_feedback.slice(-4).map(f => `<div class="answer-ref">${esc(f.name)}：${esc(f.comment || f.module || '（未留文字）')}</div>`).join('')}` : ''}
        ${sys.live.weak_top.length ? `<h4 class="mt">📉 全班共性薄弱点</h4>
          <div class="rowline" style="flex-wrap:wrap">${sys.live.weak_top.slice(0, 5).map(w =>
            `<span class="pill amber">${esc(w.name)} ${w.score}分/${w.users}人</span>`).join('')}</div>` : ''}
        ${sys.live.questions_recent.length ? `<h4 class="mt">💬 近期问题（用于提炼共性）</h4>
          <div class="muted">${sys.live.questions_recent.slice(-4).map(q => esc(q.q)).join('；')}</div>` : ''}
        ${_sysEditing ? `
          <textarea id="sys-strategy-text" class="mt" style="min-height:130px;width:100%">${esc(sys.strategy || '')}</textarea>
          <div class="mt rowline">
            <button class="btn small" id="sys-strategy-save">保存策略</button>
            <button class="btn small ghost" id="sys-strategy-cancel">取消</button>
          </div>`
        : (sys.strategy ? `<h4 class="mt">🧭 当前全局教学策略（${fmtTime(sys.updated)}）</h4><div class="md">${md(sys.strategy)}</div>`
          : '<div class="muted mt">尚无全局策略。同学们使用并反馈后，点下方按钮自动学习生成。</div>')}
        <div class="mt rowline">
          ${_sysEditing ? '' : '<button class="btn small ghost" id="sys-strategy-edit">✏️ 手动编辑</button>'}
          <button class="btn small" id="sys-reflect">🔄 重新学习全班反馈${sys.updated ? '（上次 ' + fmtTime(sys.updated) + '）' : ''}</button>
        </div>
      </div>` : '';
    $('#mem-wrap').innerHTML = `
      ${sysCard}
      <div class="grid c2">
        <div class="card">
          <h3>📌 持久指令（每次教学都会遵守）</h3>
          <div class="rowline"><input type="text" id="mem-pref" placeholder="如：讲题先给直觉再给证明 / 别直接给最终答案" style="flex:1">
            <button class="btn small" id="mem-add">添加</button></div>
          <div class="mt">${m.preferences.length ? m.preferences.map(p =>
            `<div class="rowline" style="justify-content:space-between;padding:5px 0;border-bottom:1px solid var(--line)">
              <span>${esc(p)}</span><button class="btn small danger" data-del="${esc(p)}">删</button></div>`).join('')
            : '<span class="muted">还没有指令。告诉AI你希望它怎么教你。</span>'}</div>
          <h4>💡 这些指令会注入问答、批改、出卷、讲义的所有提示词</h4>
        </div>
        <div class="card">
          <h3>🧠 教学策略卡（自我反思产物，可手动编辑）</h3>
          ${_memEditingStrategy ? `
            <textarea id="mem-strategy-text" style="min-height:160px">${esc(m.strategy || '')}</textarea>
            <div class="mt rowline">
              <button class="btn small" id="mem-strategy-save">保存</button>
              <button class="btn small ghost" id="mem-strategy-cancel">取消</button>
            </div>`
          : (m.strategy ? `<div class="md">${md(m.strategy)}</div><div class="muted mt">更新于 ${fmtTime(m.strategy_updated)}${m.llm?'':'（离线统计版）'}</div>`
            : '<span class="muted">尚无策略卡。积累反馈后「触发反思」，或直接手动编写。</span>')}
          <div class="mt rowline">
            ${_memEditingStrategy ? '' : `<button class="btn small ghost" id="mem-strategy-edit">✏️ 编辑</button>`}
            <button class="btn" id="mem-reflect">触发反思（复盘反馈与错因）</button>
          </div>
          ${m.llm ? '' : '<div class="muted mt">离线模式下反思为统计汇总；配置大模型后可深度总结并提炼新偏好。</div>'}
        </div>
      </div>
      <div class="card">
        <h3>🗨️ 反馈记录（${m.feedback.length}）· 可编辑修改</h3>
        ${m.feedback.length ? m.feedback.map(f => _memEditingTs === f.ts ? `
          <div style="padding:8px 0;border-bottom:1px solid var(--line)">
            <div class="rowline">
              <select id="fb-rating" style="width:130px">
                <option value="1" ${f.rating>0?'selected':''}>👍 有帮助</option>
                <option value="0" ${f.rating===0?'selected':''}>· 一般</option>
                <option value="-1" ${f.rating<0?'selected':''}>👎 没帮助</option>
              </select>
              <input type="text" id="fb-comment" style="flex:1" value="${esc(f.comment||'')}" placeholder="修改意见…">
            </div>
            <div class="mt rowline">
              <button class="btn small" data-fbsave="${f.ts}">保存修改</button>
              <button class="btn small ghost" data-fbcancel="1">取消</button>
            </div>
          </div>`
        : `
          <div style="padding:6px 0;border-bottom:1px solid var(--line);font-size:13.5px">
            ${stars(f.rating)} <b>${esc(f.module)}</b> ${esc(f.target.slice(0,40))}
            ${f.comment?`<span class="muted">“${esc(f.comment)}”</span>`:''} <span class="muted">${fmtTime(f.ts)}${f.edited?'（已编辑）':''}</span>
            <button class="btn small ghost" data-fbedit="${f.ts}">改</button>
            <button class="btn small danger" data-fbdel="${f.ts}">删</button>
          </div>`).join('')
        : '<span class="muted">在问答与批改结果下方点 👍/👎 即可积累反馈。</span>'}
      </div>`;
    $('#mem-add').onclick = async () => {
      const v = $('#mem-pref').value.trim();
      if (!v) return;
      await api('memory/preference', {method:'POST', body:{sid: state.sid, text: v}});
      $('#mem-pref').value = '';
      render();
    };
    $('#mem-wrap').querySelectorAll('button[data-del]').forEach(b => b.onclick = async () => {
      await api('memory/preference/delete', {method:'POST', body:{sid: state.sid, text: b.dataset.del}});
      render();
    });
    $('#mem-reflect').onclick = async () => {
      const btn = $('#mem-reflect');
      btn.disabled = true; btn.textContent = '反思中…';
      try { await api('memory/reflect', {method:'POST', body:{sid: state.sid}}); _memEditingStrategy = false; toast('策略卡已更新'); render(); }
      catch (e) { toast(e.message, true); btn.disabled = false; btn.textContent = '触发反思（复盘反馈与错因）'; }
    };
    const se = document.getElementById('mem-strategy-edit');
    if (se) se.onclick = () => { _memEditingStrategy = true; render(); };
    const ss = document.getElementById('mem-strategy-save');
    if (ss) ss.onclick = async () => {
      await api('memory/strategy', {method:'POST', body:{sid: state.sid, text: $('#mem-strategy-text').value}});
      _memEditingStrategy = false;
      toast('策略卡已保存，将注入后续教学');
      render();
    };
    const sc = document.getElementById('mem-strategy-cancel');
    if (sc) sc.onclick = () => { _memEditingStrategy = false; render(); };
    const sr = document.getElementById('sys-reflect');
    if (sr) sr.onclick = async () => {
      sr.disabled = true; sr.textContent = '学习中…（聚合全班数据 + AI 提炼）';
      try { await api('system/reflect', {method:'POST', body:{sid: state.sid}}); _sysEditing = false; toast('全局策略已更新，将注入每位同学的 AI 教学'); render(); }
      catch (e) { toast(e.message, true); sr.disabled = false; sr.textContent = '🔄 重新学习全班反馈'; }
    };
    const se2 = document.getElementById('sys-strategy-edit');
    if (se2) se2.onclick = () => { _sysEditing = true; render(); };
    const ss2 = document.getElementById('sys-strategy-save');
    if (ss2) ss2.onclick = async () => {
      await api('system/strategy', {method:'POST', body:{sid: state.sid, text: $('#sys-strategy-text').value}});
      _sysEditing = false;
      toast('全局策略已保存');
      render();
    };
    const sc2 = document.getElementById('sys-strategy-cancel');
    if (sc2) sc2.onclick = () => { _sysEditing = false; render(); };
    $('#mem-wrap').querySelectorAll('button[data-fbedit]').forEach(b => b.onclick = () => { _memEditingTs = parseFloat(b.dataset.fbedit); render(); });
    $('#mem-wrap').querySelectorAll('button[data-fbcancel]').forEach(b => b.onclick = () => { _memEditingTs = null; render(); });
    $('#mem-wrap').querySelectorAll('button[data-fbsave]').forEach(b => b.onclick = async () => {
      await api('memory/feedback/update', {method:'POST', body:{sid: state.sid, ts: parseFloat(b.dataset.fbsave),
        rating: parseInt(document.getElementById('fb-rating').value), comment: document.getElementById('fb-comment').value}});
      _memEditingTs = null;
      toast('反馈已修改');
      render();
    });
    $('#mem-wrap').querySelectorAll('button[data-fbdel]').forEach(b => b.onclick = async () => {
      if (!confirm('删除这条反馈记录？')) return;
      await api('memory/feedback/delete', {method:'POST', body:{sid: state.sid, ts: parseFloat(b.dataset.fbdel)}});
      render();
    });
  }
  await render();
};

/* ---------------- 新手引导 ---------------- */
const TOUR_STEPS = [
  {title: '👋 欢迎使用 知源学伴',
   desc: '这是一个"先引导、后答案"的 AI 学习伙伴。用 1 分钟看完 7 步，马上上手核心玩法。'},
  {sel: 'a[href="#/qa"]', title: '🧮 AI 知识问答（核心）',
   desc: '粘贴任何数学 / C语言 / 生物 / 化学题目即可。引导模式用反问带你一步步想通（不直接给答案）；讲解模式给完整推导。支持拍照传题图，AI 回答逐字流式输出，公式自动排版。'},
  {sel: 'a[href="#/wrongbook"]', title: '📕 错题本（变式重练闭环）',
   desc: '批改和测验的错题自动归类。每道错题可生成 AI 变式题，做对了才允许标记"已掌握"——真学会为止。'},
  {sel: 'a[href="#/paper"]', title: '📝 诊断卷',
   desc: '按你的薄弱点自动出卷，交卷自动批改，批改后进入精讲报告：得分率雷达图 + 逐题讲解。'},
  {sel: 'a[href="#/points"]', title: '🎯 任务积分',
   desc: '积分只来自真实学习行为（问答/测验/批改/讲义），每天达标攒连续记录，用积分兑换你自定义的奖励。'},
  {sel: 'a[href="#/english"]', title: '✍️ 英语批改',
   desc: '四六级作文/翻译逐句改错打分（内置近三年真题），手写作文可以直接拍照上传。'},
  {sel: 'a[href="#/memory"]', title: '🧠 反馈会改变系统',
   desc: '每次 AI 回答下方都能 👍👎 评价。你的反馈会与全班同学的反馈一起被 AI 学习，提炼成"全局教学策略"，自动改进每个人的教学方式。也可以写下持久指令，让 AI 按你的习惯教学。'},
  {sel: '#btn-settings', title: '⚙️ 接入设置',
   desc: state_boot_llm() ? '云端版 AI 已内置，开箱即用；本机版也可在这里换免费通道（智谱 glm-4-flash 等）。' : '当前离线模式：点这里选免费通道（智谱 glm-4-flash 注册即免费），解锁完整 AI 能力。'},
];

function state_boot_llm() { return !!(state.boot && state.boot.llm); }

function startTour(idx = 0) {
  $('#tour-layer')?.remove();
  if (idx >= TOUR_STEPS.length) {
    localStorage.setItem('zy_tour_done', '1');
    toast('🎉 引导完成，开始学习吧！');
    return;
  }
  const step = TOUR_STEPS[idx];
  const show = () => {
    const target = step.sel ? document.querySelector(step.sel) : null;
    if (target) target.scrollIntoView({block: 'center', inline: 'center'});   // 手机横向导航：先把目标滑进可视区（瞬时滚动，定位测量才准）
    const layer = document.createElement('div');
    layer.id = 'tour-layer';
    layer.innerHTML = `
      <div style="position:fixed;inset:0;background:rgba(8,12,26,.62);z-index:200"></div>
      <div id="tour-card" style="position:fixed;z-index:202;background:#fff;border-radius:14px;max-width:360px;width:calc(100vw - 40px);padding:18px 20px;box-shadow:0 18px 60px rgba(10,16,40,.35)">
        <h3 style="margin:0">${esc(step.title)}</h3>
        <p style="margin:10px 0 0;line-height:1.75;font-size:13.5px;color:#3a4260">${esc(step.desc)}</p>
        <div class="rowline" style="justify-content:space-between;margin-top:14px;align-items:center">
          <span class="muted" style="font-size:12px">${idx + 1} / ${TOUR_STEPS.length}</span>
          <span class="rowline">
            <button class="btn small ghost" id="tour-skip">跳过</button>
            ${idx > 0 ? '<button class="btn small ghost" id="tour-prev">上一步</button>' : ''}
            <button class="btn small" id="tour-next">${idx === TOUR_STEPS.length - 1 ? '完成 🎉' : '下一步 →'}</button>
          </span>
        </div>
      </div>`;
    document.body.appendChild(layer);
    if (target) {
      target.classList.add('tour-hot');
      const r = target.getBoundingClientRect();
      const card = layer.querySelector('#tour-card');
      const cw = Math.min(360, window.innerWidth - 40);
      let left = Math.min(Math.max(12, r.left), window.innerWidth - cw - 12);
      let top = r.bottom + 12;
      if (top + 230 > window.innerHeight) top = Math.max(12, r.top - 238);
      card.style.left = left + 'px';
      card.style.top = top + 'px';
    } else {
      const card = layer.querySelector('#tour-card');
      card.style.left = '50%';
      card.style.top = '38%';
      card.style.transform = 'translateX(-50%)';
    }
    layer.querySelector('#tour-skip').onclick = () => { cleanup(); localStorage.setItem('zy_tour_done', '1'); };
    layer.querySelector('#tour-next').onclick = () => { cleanup(); startTour(idx + 1); };
    const pv = layer.querySelector('#tour-prev');
    if (pv) pv.onclick = () => { cleanup(); startTour(idx - 1); };
    function cleanup() { layer.remove(); document.querySelectorAll('.tour-hot').forEach(el => el.classList.remove('tour-hot')); }
  };
  if (step.sel && !document.querySelector(step.sel)) {
    const hash = (step.sel.match(/#\/(\w+)/) || [])[0];
    if (hash) { location.hash = hash; setTimeout(show, 900); return; }
  }
  show();
}

/* KaTeX 公式渲染：监视主区 DOM 变化，自动渲染 $...$ / $$...$$ / \(...\) / \[...\]。
   CDN 不可用时静默降级为纯文本。 */
(function () {
  let timer = null;
  const main = document.getElementById('main');
  if (!main || !('MutationObserver' in window)) return;
  new MutationObserver(() => {
    if (!window.renderMathInElement) return;
    clearTimeout(timer);
    timer = setTimeout(() => {
      try {
        window.renderMathInElement(main, {
          delimiters: [
            {left: '$$', right: '$$', display: true},
            {left: '\\[', right: '\\]', display: true},
            {left: '$', right: '$', display: false},
            {left: '\\(', right: '\\)', display: false},
          ],
          throwOnError: false,
          ignoredTags: ['script', 'noscript', 'style', 'textarea', 'pre', 'code', 'option'],
        });
      } catch (e) { /* 渲染失败保持原文 */ }
    }, 80);
  }).observe(main, {childList: true, subtree: true});
})();

/* ================= 管理端 ================= */
// 需要口令时：把 token 存 localStorage，之后所有 admin 请求带上 ?token=
function adminQ(extra) {
  const tok = localStorage.getItem('zy_admin_token') || '';
  const q = Object.assign({}, extra || {});
  if (tok) q.token = tok;
  return q;
}

function adminKpi(label, value, sub) {
  return `<div class="stat"><div class="num">${value}</div>
    <div class="lbl">${esc(label)}${sub ? `<br><span class="muted">${esc(sub)}</span>` : ''}</div></div>`;
}

function adminBars(rows, key, label) {
  const max = Math.max(1, ...rows.map(r => r[key] || 0));
  return `<div style="display:flex;align-items:flex-end;gap:3px;height:110px;margin-top:6px">
    ${rows.map(r => {
      const v = r[key] || 0;
      const h = Math.max(2, Math.round((v / max) * 100));
      return `<div style="flex:1;display:flex;flex-direction:column;justify-content:flex-end;align-items:center" title="${r.day}：${v}">
        <div style="width:100%;height:${h}%;background:var(--brand);opacity:.85;border-radius:3px 3px 0 0;min-height:2px"></div>
      </div>`;
    }).join('')}
  </div>
  <div class="muted" style="display:flex;justify-content:space-between;font-size:11px;margin-top:4px">
    <span>${rows.length ? rows[0].day : ''}</span><span>${esc(label)}</span>
    <span>${rows.length ? rows[rows.length - 1].day : ''}</span>
  </div>`;
}

VIEWS.admin = async () => {
  const meta = state.boot.admin || {};
  const tok = localStorage.getItem('zy_admin_token') || '';

  // 不是管理员本人：只给「怎么成为管理员」的说明，绝不显示任何统计数据
  if (!meta.is_admin) {
    if (meta.mode === 'token') {
      $('#main').innerHTML += `<div class="card" style="max-width:520px">
        <h3>需要管理员口令</h3>
        <p class="muted">管理端只对管理员开放。请填后端 <code>ZY_ADMIN_TOKEN</code> 对应的口令。</p>
        <label class="f">管理员口令</label>
        <input type="password" id="adm-token" placeholder="ZY_ADMIN_TOKEN 的值" style="width:100%;padding:9px 12px;border:1px solid #d5dae8;border-radius:8px">
        <div class="mt rowline"><button class="btn" id="adm-go">进入管理端</button>
          <span id="adm-msg" class="muted"></span></div>
      </div>`;
      $('#adm-go').onclick = async () => {
        const v = ($('#adm-token').value || '').trim();
        if (!v) return;
        localStorage.setItem('zy_admin_token', v);
        try {
          const r = await api('admin/whoami', {query: adminQ()});
          if (!r.is_admin) throw new Error('口令不正确');
          state.boot.admin = r;
          toast('口令正确');
          route();
        } catch (e) {
          localStorage.removeItem('zy_admin_token');
          $('#adm-msg').textContent = e.message;
        }
      };
      return;
    }
    // mode = user / off
    const hint = meta.mode === 'user'
      ? `管理端只对管理员账号（<b>${esc(meta.admin_user || '')}</b>）开放，当前登录账号无权访问。`
      : '管理端未启用。后端设置 <code>ZY_ADMIN_USER=你的账号名</code>（推荐）或 <code>ZY_ADMIN_TOKEN</code> 后重启即可。';
    $('#main').innerHTML += `<div class="card" style="max-width:560px">
      <h3>🔒 无权访问管理端</h3><p>${hint}</p></div>`;
    return;
  }

  const [ov, dl, us, lt] = await Promise.all([
    api('admin/overview', {query: adminQ()}),
    api('admin/daily', {query: adminQ({days: 30})}),
    api('admin/users', {query: adminQ()}),
    api('admin/longterm', {query: adminQ()}),
  ]);

  const llm = ov.llm, fb = ov.feedback, c = ov.content;
  const days = dl.days || [];
  const chRows = (ov.channels || []).map(ch => `<tr>
      <td>${esc(ch.channel)}</td><td>${ch.calls}</td>
      <td>${ch.fail}${ch.fail ? ` <span style="color:var(--bad)">(${ch.fail_rate}%)</span>` : ''}</td>
      <td>${ch.ms_avg} ms</td></tr>`).join('') ||
    '<tr><td colspan="4" class="muted">还没有调用记录</td></tr>';

  const userRows = (us.users || []).map(u => {
    const la = u.last_active ? fmtTime(u.last_active) : '从未';
    return `<tr>
      <td>${esc(u.name)}</td>
      <td>${u.qa}</td><td>${u.llm_calls}${u.llm_fail ? ` <span style="color:var(--bad)">✗${u.llm_fail}</span>` : ''}</td>
      <td>${u.feedback}</td>
      <td>${u.avg_score == null ? '—' : u.avg_score}</td>
      <td>${u.weak_count ? `<span style="color:var(--bad)">${u.weak_count}</span>` : 0}</td>
      <td class="muted">${la}</td></tr>`;
  }).join('') || '<tr><td colspan="7" class="muted">还没有学员</td></tr>';

  const weakRows = (us.weak || []).map(w => `<tr>
      <td>${esc(w.name)}</td><td>${esc(state.boot.subjects[w.subject] || w.subject || '—')}</td>
      <td>${w.students}</td><td>${w.avg_score}</td></tr>`).join('') ||
    '<tr><td colspan="4" class="muted">数据不足（需要学生做过诊断卷/问答）</td></tr>';

  $('#main').innerHTML += `
    <div class="grid c3">
      ${adminKpi('学员数', ov.users, `近7天活跃 ${ov.active_7d} 人`)}
      ${adminKpi('近30天 AI 调用', llm.calls, `今天 ${llm.today} 次 · 平均 ${llm.ms_avg}ms`)}
      ${adminKpi('调用成功率', llm.ok_rate + '%', llm.fail ? `失败 ${llm.fail} 次` : '无失败')}
      ${adminKpi('反馈条数', fb.total, fb.total ? `👍${fb.up} / 👎${fb.down}` : '还没有反馈')}
      ${adminKpi('内容产出', c.qa + c.graded + c.papers, `问答${c.qa} 批改${c.graded} 卷${c.papers}`)}
      ${adminKpi('错题 / 积分', c.wrongbook, `积分发放 ${c.points_total}`)}
    </div>

    <div class="grid c2 mt">
      <div class="card"><h3>📈 AI 调用趋势（近 30 天）</h3>
        ${days.length ? adminBars(days, 'llm_calls', '每日调用次数') : '<div class="muted">暂无数据（指标从本版本开始记录）</div>'}
      </div>
      <div class="card"><h3>💬 问答量趋势（近 30 天）</h3>
        ${days.length ? adminBars(days, 'qa', '每日问答次数') : '<div class="muted">暂无数据</div>'}
      </div>
    </div>

    <div class="grid c2 mt">
      <div class="card"><h3>🔌 通道健康度（近 30 天）</h3>
        <table class="tbl"><tr><th>通道</th><th>调用</th><th>失败</th><th>均耗时</th></tr>${chRows}</table>
        <div class="muted mt">失败率高说明该通道限流/欠费，可在「接入设置」换通道。</div>
      </div>
      <div class="card"><h3>🎯 全班共性薄弱点</h3>
        <table class="tbl"><tr><th>考点</th><th>科目</th><th>薄弱人数</th><th>均分</th></tr>${weakRows}</table>
        <div class="muted mt">掌握度低于 60 才计入。人数最多的 2-3 个考点建议集中讲一次。</div>
      </div>
    </div>

    <div class="card mt"><h3>👥 学员明细（${(us.users || []).length}）</h3>
      <div style="overflow:auto;max-height:420px">
        <table class="tbl">
          <tr><th>学员</th><th>问答</th><th>AI调用</th><th>反馈</th><th>均分</th><th>薄弱</th><th>最后活跃</th></tr>
          ${userRows}
        </table>
      </div>
    </div>

    <div class="card mt"><h3>🧭 长期总结</h3>
      <div id="adm-summary" class="md">${md(lt.text || '')}</div>
      <div class="mt rowline">
        <button class="btn small" id="adm-ai">让 AI 写一份教学复盘</button>
        <button class="btn small ghost" id="adm-prune">清理 90 天前明细</button>
        <span id="adm-note" class="muted"></span>
      </div>
    </div>`;

  $('#adm-ai').onclick = async () => {
    const box = $('#adm-summary'), note = $('#adm-note');
    note.textContent = 'AI 生成中…（可能要十几秒）';
    $('#adm-ai').disabled = true;
    try {
      const r = await api('admin/ai-summary', {method: 'POST', body: {}, query: adminQ(), timeout: 180000});
      box.innerHTML = md(r.text || '');
      note.textContent = r.ok ? '已生成（AI 复盘）' : (r.detail || '已回退到规则版');
    } catch (e) {
      note.textContent = e.message;
    } finally {
      $('#adm-ai').disabled = false;
    }
  };
  $('#adm-prune').onclick = async () => {
    try {
      const r = await api('admin/prune', {method: 'POST', body: {days: 90}, query: adminQ()});
      $('#adm-note').textContent = `已清理 ${r.removed} 条过期明细`;
    } catch (e) { $('#adm-note').textContent = e.message; }
  };
};

init();
