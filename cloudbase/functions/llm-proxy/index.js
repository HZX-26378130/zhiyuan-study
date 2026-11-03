// 知源学伴 LLM 代理：基于 CloudBase AI+（混元模型），OpenAI 兼容接口
const CloudBase = require('@cloudbase/node-sdk');

const app = CloudBase.init({ env: CloudBase.SYMBOL_CURRENT_ENV });
const TOKEN = process.env.ACCESS_TOKEN || '';
const DAILY_LIMIT = parseInt(process.env.DAILY_LIMIT || '300', 10);

// 每日调用限额（存环境数据库 llm_usage 集合；数据库不可用时放行，不阻塞主链路）
async function quotaOk() {
  try {
    const db = app.database();
    const col = db.collection('llm_usage');
    const day = new Date().toISOString().slice(0, 10);
    const bumped = await col.where({ day: day }).update({ count: db.command.inc(1) });
    if (!bumped || !bumped.stats || bumped.stats.updated === 0) {
      await col.add({ day: day, count: 1 });
      return 1 <= DAILY_LIMIT;
    }
    const got = await col.where({ day: day }).limit(1).get();
    const n = (got && got.data && got.data[0] && got.data[0].count) || 0;
    return n <= DAILY_LIMIT;
  } catch (e) {
    return true;
  }
}

function json(statusCode, obj) {
  return {
    statusCode,
    headers: {
      'Content-Type': 'application/json; charset=utf-8',
      'Access-Control-Allow-Origin': '*',
      'Access-Control-Allow-Headers': 'Content-Type,Authorization',
    },
    body: JSON.stringify(obj),
  };
}

function pickAi() {
  // 不同 SDK 版本的 AI 入口探测（官方推荐：ai.createModel("cloudbase").generateText）
  try {
    if (typeof app.ai === 'function') {
      const a = app.ai();
      if (a) {
        if (typeof a.createModel === 'function') {
          return {
            ai: a,
            call: async (p) => {
              const m = a.createModel('cloudbase');
              const r = await m.generateText({ model: p.model, messages: p.messages });
              return { choices: [{ message: { role: 'assistant', content: r.text } }], usage: r.usage };
            },
          };
        }
        if (typeof a.chatCompletions === 'function') return { ai: a, call: (p) => a.chatCompletions(p) };
        if (a.chat && a.chat.completions && typeof a.chat.completions.create === 'function')
          return { ai: a, call: (p) => a.chat.completions.create(p) };
        if (typeof a.createChatCompletion === 'function') return { ai: a, call: (p) => a.createChatCompletion(p) };
        return { ai: a, call: null };
      }
    }
  } catch (e) {
    return { ai: null, call: null, err: String(e) };
  }
  return { ai: null, call: null };
}

function health() {
  const probe = pickAi();
  return json(200, {
    ok: true,
    service: 'zhiyuan-llm-proxy',
    sdk: (CloudBase && CloudBase.version) || 'unknown',
    aiReady: !!probe.call,
    aiKeys: probe.ai ? Object.keys(probe.ai).slice(0, 20) : [],
    aiErr: probe.err || '',
  });
}

async function runChat(req, bare) {
  // bare=true 时返回裸 OpenAI 对象（直连模式下网关把返回值原样作为响应体）
  const out = (code, obj) => (bare ? obj : json(code, obj));
  const messages = Array.isArray(req.messages) ? req.messages : null;
  if (!messages || !messages.length) {
    return out(400, { error: { message: 'messages is required' } });
  }

  const model = req.model || 'hy3';
  const probe = pickAi();
  if (!probe.call) {
    return out(500, {
      error: {
        message: 'AI 接口不可用：SDK 缺少 AI 入口（需 @cloudbase/node-sdk>=3.16 并开启 AI+）',
        debug: { sdk: (CloudBase && CloudBase.version) || 'unknown', aiKeys: probe.ai ? Object.keys(probe.ai).slice(0, 20) : [], err: probe.err || '' },
      },
    });
  }

  if (DAILY_LIMIT > 0) {
    const ok = await quotaOk();
    if (!ok) {
      return out(429, { error: { message: '今日调用额度已用尽（上限 ' + DAILY_LIMIT + ' 次），请明天再试或切换其他免费通道' } });
    }
  }

  try {
    const res = await probe.call({
      model: model,
      messages: messages,
      stream: false,
    });
    let content = '';
    if (res && res.choices && res.choices[0]) {
      content = (res.choices[0].message && res.choices[0].message.content) || res.choices[0].text || '';
    } else if (res && res.data && res.data.choices && res.data.choices[0]) {
      content = (res.data.choices[0].message && res.data.choices[0].message.content) || '';
    } else if (typeof res === 'string') {
      content = res;
    } else if (res && typeof res.content === 'string') {
      content = res.content;
    } else {
      content = JSON.stringify(res);
    }
    return out(200, {
      id: 'zh' + Date.now(),
      object: 'chat.completion',
      model: model,
      choices: [{ index: 0, message: { role: 'assistant', content: String(content) }, finish_reason: 'stop' }],
      usage: (res && res.usage) || {},
    });
  } catch (e) {
    const detail = { message: String((e && e.message) || e) };
    for (const k of ['code', 'codeMessage', 'requestId', 'statusCode', 'raw']) {
      if (e && e[k] !== undefined && e[k] !== null) detail[k] = String(e[k]).slice(0, 400);
    }
    return out(500, { error: detail });
  }
}

exports.main = async function (event) {
  // 模式 A：HTTP 网关路径访问（事件带 httpMethod/headers/body）
  if (event && event.httpMethod) {
    const method = String(event.httpMethod).toUpperCase();
    if (method === 'GET' || method === 'OPTIONS') return health();

    const rawAuth = (event.headers && (event.headers.authorization || event.headers.Authorization)) || '';
    if (TOKEN && rawAuth !== 'Bearer ' + TOKEN) {
      return json(401, { error: { message: 'invalid token' } });
    }

    let raw = event.body || '{}';
    if (event.isBase64Encoded) raw = Buffer.from(raw, 'base64').toString('utf-8');
    let req;
    try {
      req = JSON.parse(raw);
    } catch (e) {
      return json(400, { error: { message: 'invalid json body' } });
    }
    return runChat(req);
  }

  // 模式 B：HTTP API 直连调用（tcloudbasegateway /v1/functions/llm-proxy）
  // 网关层已用 API Key 完成鉴权，事件体即 {model, messages}
  if (!event || typeof event !== 'object') return health();
  if (event.ping) return health();
  return runChat(event, true);
};
