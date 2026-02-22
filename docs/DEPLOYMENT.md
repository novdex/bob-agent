# Deployment Guide

## Production Deployment

### Prerequisites

- Python 3.10+
- PostgreSQL (recommended) or SQLite
- Redis (optional, for caching)
- Domain name with SSL certificate

### Environment Setup

1. **Create virtual environment:**
```bash
python -m venv venv
source venv/bin/activate  # Linux/Mac
# or
venv\Scripts\activate  # Windows
```

2. **Install dependencies:**
```bash
pip install -e ".[prod]"
```

3. **Set environment variables:**
```bash
export ENVIRONMENT=production
export KIMI_API_KEY=your_api_key
export TELEGRAM_BOT_TOKEN=your_bot_token
export WEBHOOK_BASE_URL=https://your-domain.com
export DATABASE_URL=postgresql://user:pass@localhost/mindclone
```

### Database Setup

**PostgreSQL:**
```sql
CREATE DATABASE mindclone;
CREATE USER mindclone WITH PASSWORD 'secure_password';
GRANT ALL PRIVILEGES ON DATABASE mindclone TO mindclone;
```

**Initialize:**
```bash
python -c "from mind_clone.database.session import init_db; init_db()"
```

### Running with Systemd

Create `/etc/systemd/system/mind-clone.service`:

```ini
[Unit]
Description=Mind Clone Agent
After=network.target

[Service]
Type=simple
User=mindclone
WorkingDirectory=/opt/mind-clone
Environment=PATH=/opt/mind-clone/venv/bin
Environment=ENVIRONMENT=production
EnvironmentFile=/opt/mind-clone/.env
ExecStart=/opt/mind-clone/venv/bin/uvicorn mind_clone.api.factory:create_app --factory --host 0.0.0.0 --port 8000
Restart=always
RestartSec=10

[Install]
WantedBy=multi-user.target
```

Enable and start:
```bash
sudo systemctl enable mind-clone
sudo systemctl start mind-clone
```

### Running with Docker

**Dockerfile:**
```dockerfile
FROM python:3.11-slim

WORKDIR /app

COPY pyproject.toml .
RUN pip install -e ".[prod]"

COPY src/ ./src/

EXPOSE 8000

CMD ["uvicorn", "mind_clone.api.factory:create_app", "--factory", "--host", "0.0.0.0", "--port", "8000"]
```

**Build and run:**
```bash
docker build -t mind-clone .
docker run -d \
  -p 8000:8000 \
  -e KIMI_API_KEY=your_key \
  -e TELEGRAM_BOT_TOKEN=your_token \
  -v mindclone-data:/data \
  mind-clone
```

### Running with Docker Compose

```yaml
version: '3.8'

services:
  app:
    build: .
    ports:
      - "8000:8000"
    environment:
      - DATABASE_URL=postgresql://postgres:password@db:5432/mindclone
      - KIMI_API_KEY=${KIMI_API_KEY}
      - TELEGRAM_BOT_TOKEN=${TELEGRAM_BOT_TOKEN}
    depends_on:
      - db
      - redis
    volumes:
      - app-data:/app/data

  db:
    image: postgres:15
    environment:
      - POSTGRES_USER=postgres
      - POSTGRES_PASSWORD=password
      - POSTGRES_DB=mindclone
    volumes:
      - postgres-data:/var/lib/postgresql/data

  redis:
    image: redis:7-alpine
    volumes:
      - redis-data:/data

  nginx:
    image: nginx:alpine
    ports:
      - "80:80"
      - "443:443"
    volumes:
      - ./nginx.conf:/etc/nginx/nginx.conf
      - ./ssl:/etc/nginx/ssl
    depends_on:
      - app

volumes:
  app-data:
  postgres-data:
  redis-data:
```

### Nginx Configuration

```nginx
upstream mindclone {
    server localhost:8000;
}

server {
    listen 80;
    server_name your-domain.com;
    return 301 https://$server_name$request_uri;
}

server {
    listen 443 ssl http2;
    server_name your-domain.com;

    ssl_certificate /etc/nginx/ssl/cert.pem;
    ssl_certificate_key /etc/nginx/ssl/key.pem;

    location / {
        proxy_pass http://mindclone;
        proxy_http_version 1.1;
        proxy_set_header Upgrade $http_upgrade;
        proxy_set_header Connection 'upgrade';
        proxy_set_header Host $host;
        proxy_set_header X-Real-IP $remote_addr;
        proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;
        proxy_set_header X-Forwarded-Proto $scheme;
        proxy_cache_bypass $http_upgrade;
    }

    location /ui/events/stream {
        proxy_pass http://mindclone;
        proxy_http_version 1.1;
        proxy_set_header Connection '';
        proxy_buffering off;
        cache_control no-cache;
        chunked_transfer_encoding on;
    }
}
```

### Telegram Webhook Setup

1. **Set webhook URL:**
```bash
curl -X POST "https://api.telegram.org/bot<TOKEN>/setWebhook" \
  -H "Content-Type: application/json" \
  -d '{"url": "https://your-domain.com/telegram/webhook"}'
```

2. **Verify webhook:**
```bash
curl "https://api.telegram.org/bot<TOKEN>/getWebhookInfo"
```

### Health Checks

**Endpoint:**
```
GET /heartbeat
```

**Expected response:**
```json
{
  "status": "alive",
  "db_healthy": true,
  "timestamp": "..."
}
```

### Monitoring

**Prometheus metrics** (if enabled):
```
GET /metrics
```

**Key metrics to monitor:**
- Request latency
- Error rate
- LLM API calls
- Tool execution count
- Database connections

### Backup Strategy

**Database:**
```bash
# Automated daily backup
pg_dump mindclone > backup_$(date +%Y%m%d).sql

# Or for SQLite
cp mind_clone.db backup_$(date +%Y%m%d).db
```

**File storage:**
```bash
rsync -av /opt/mind-clone/data/ /backup/mind-clone/
```

### Updates

1. **Backup current data**
2. **Pull new code:**
```bash
git pull origin main
```
3. **Update dependencies:**
```bash
pip install -e ".[prod]" --upgrade
```
4. **Run migrations:**
```bash
python -c "from mind_clone.database.session import init_db; init_db()"
```
5. **Restart service:**
```bash
sudo systemctl restart mind-clone
```

### Security Checklist

- [ ] Change default secrets
- [ ] Enable HTTPS
- [ ] Configure firewall (allow only 80, 443, 22)
- [ ] Set up fail2ban
- [ ] Enable audit logging
- [ ] Regular security updates
- [ ] Database backups encrypted
- [ ] API rate limiting enabled

### Troubleshooting

**Service won't start:**
```bash
sudo journalctl -u mind-clone -f
```

**Database connection issues:**
```bash
# Test connection
python -c "from mind_clone.database.session import check_db_health; print(check_db_health())"
```

**High memory usage:**
- Check tool execution limits
- Reduce conversation history size
- Enable memory pruning

**Slow responses:**
- Enable caching
- Check LLM API latency
- Optimize database queries
