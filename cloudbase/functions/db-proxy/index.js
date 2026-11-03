// 知源学伴 数据代理：Python 后端（云托管）通过它读写 CloudBase NoSQL
// 鉴权：直连模式要求 event.dbtoken === ACCESS_TOKEN；HTTP 模式要求 Bearer ACCESS_TOKEN
const CloudBase = require('@cloudbase/node-sdk');

const app = CloudBase.init({ env: CloudBase.SYMBOL_CURRENT_ENV });
const TOKEN = process.env.ACCESS_TOKEN || '';

let _colsReady = null;
function ensureCols() {
  if (!_colsReady) {
    _colsReady = Promise.all(
      ['zy_store', 'zy_users'].map(cn => app.database().createCollection(cn).catch(() => {}))
    );
  }
  return _colsReady;
}

function wrap(statusCode, obj) {
  return {
    statusCode,
    headers: { 'Content-Type': 'application/json; charset=utf-8' },
    body: JSON.stringify(obj),
  };
}

exports.main = async function (event) {
  let req = event;
  if (event && event.httpMethod) {
    const rawAuth = (event.headers && (event.headers.authorization || event.headers.Authorization)) || '';
    if (TOKEN && rawAuth !== 'Bearer ' + TOKEN) return wrap(401, { ok: false, error: 'invalid token' });
    let raw = event.body || '{}';
    if (event.isBase64Encoded) raw = Buffer.from(raw, 'base64').toString('utf-8');
    try { req = JSON.parse(raw); } catch (e) { return wrap(400, { ok: false, error: 'bad json' }); }
  } else {
    if (TOKEN && req.dbtoken !== TOKEN) return { ok: false, error: 'invalid dbtoken' };
  }

  const op = req.op;
  const col = String(req.col || 'zy_store').slice(0, 40);
  try {
    await ensureCols();
    const db = app.database();
    const c = db.collection(col);
    if (op === 'get') {
      const r = await c.where({ key: String(req.key) }).limit(1).get();
      return { ok: true, doc: (r.data && r.data[0]) || null };
    }
    if (op === 'set') {
      const key = String(req.key).slice(0, 200);
      const val = req.val;
      const r = await c.where({ key: key }).update({ val: val, up: Date.now() });
      if (!r.stats || r.stats.updated === 0) {
        await c.add({ key: key, val: val, up: Date.now() });
      }
      return { ok: true };
    }
    if (op === 'del') {
      await c.where({ key: String(req.key) }).remove();
      return { ok: true };
    }
    if (op === 'prefix') {
      // 列出 key 前缀下的所有文档（如 students.json 的分片、papers/<sid>/...）
      const r = await c.where({ key: db.regexp({ regexp: '^' + String(req.prefix).replace(/[.*+?^${}()|[\]\\]/g, '\\$&'), options: 'i' }) }).limit(100).get();
      return { ok: true, docs: r.data || [] };
    }
    if (op === 'user-get') {
      const r = await c.where({ name: String(req.name || '').slice(0, 40) }).limit(1).get();
      return { ok: true, doc: (r.data && r.data[0]) || null };
    }
    if (op === 'user-add') {
      await c.add({ uid: String(req.uid), name: String(req.name), salt: String(req.salt), hash: String(req.hash), created: Date.now() });
      return { ok: true };
    }
    if (op === 'user-list') {
      const r = await c.field({ uid: true, name: true, created: true }).limit(200).get();
      return { ok: true, docs: r.data || [] };
    }
    return { ok: false, error: 'unknown op: ' + op };
  } catch (e) {
    return { ok: false, error: String((e && e.message) || e).slice(0, 300) };
  }
};
