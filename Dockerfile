# 知源学伴云端容器：纯标准库 Python，无 pip 依赖
FROM python:3.12-slim
WORKDIR /app
ENV PYTHONDONTWRITEBYTECODE=1 \
    ZY_HOST=0.0.0.0 \
    ZY_AUTH=1
COPY backend ./backend
COPY frontend ./frontend
COPY data/knowledge ./data/knowledge
COPY data/bank ./data/bank
COPY data/rubrics ./data/rubrics
COPY data/vocab ./data/vocab
COPY server.py .
# 构建期校验：确保打包进来的是最新代码（防止缓存/旧包），并清理无关 pyc
RUN find /app -name '__pycache__' -type d -exec rm -rf {} + ; \
    python - <<'EOF'
import sys
sys.path.insert(0, '/app')
from backend import http_app
src = open('/app/backend/http_app.py', encoding='utf-8').read()
assert "route_name == 'bootstrap'" in src, 'OLD http_app.py!'
assert 'RLock' in open('/app/backend/store.py', encoding='utf-8').read(), 'OLD store.py!'
print('[build-check] code is current, bootstrap bypass present')
EOF
EXPOSE 3000
CMD ["python", "server.py", "3000"]
