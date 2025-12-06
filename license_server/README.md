# License Validation Server

## Strong Protection Architecture

This server handles license validation for your Discord trading bot, ensuring **SECRET_KEY never leaves the server**.

### Security Features

- ✅ **Server-Side Validation** - All license checks happen on your server
- ✅ **Machine Binding** - Licenses tied to specific hardware
- ✅ **Remote Revocation** - Block pirated copies instantly
- ✅ **Offline Grace Period** - 24hr JWT tokens for offline use
- ✅ **Audit Logging** - Track all validation attempts
- ✅ **HMAC Signing** - Cryptographically secure license keys

---

## Quick Start

### 1. Local Development

```bash
# Install dependencies
cd license_server
pip install -r requirements.txt

# Set environment variables
export LICENSE_SECRET_KEY="your_secret_key_here"
export JWT_SECRET="your_jwt_secret_here"
export ADMIN_API_KEY="your_admin_api_key_here"
export DATABASE_URL="postgresql://user:password@localhost/licenses"

# Run server
python main.py
```

Server runs at: `http://localhost:8000`

### 2. Production Deployment

#### Option A: DigitalOcean App Platform ($7/month)

1. Create new App on DigitalOcean
2. Connect your GitHub repo (`license_server/` folder)
3. Add PostgreSQL database ($7/mo)
4. Set environment variables in App settings
5. Deploy!

#### Option B: Heroku ($7/month)

```bash
heroku create your-license-server
heroku addons:create heroku-postgresql:mini
heroku config:set LICENSE_SECRET_KEY="..."
heroku config:set JWT_SECRET="..."
heroku config:set ADMIN_API_KEY="..."
git push heroku main
```

#### Option C: AWS/Render/Railway (Similar process)

---

## API Endpoints

### Public Endpoints

#### `POST /api/v1/licenses/validate`
Validate a license key and get 24hr validation token

**Request:**
```json
{
  "license_key": "customer_id:1234567890:abc123:signature",
  "machine_id": "abc123def456",
  "client_version": "1.0.0"
}
```

**Response (Success):**
```json
{
  "valid": true,
  "customer_id": "john_doe",
  "expires_at": "2025-12-15T00:00:00",
  "days_remaining": 30,
  "validation_token": "eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9...",
  "token_expires_hours": 24
}
```

**Response (Error):**
```json
{
  "detail": "License expired"
}
```

---

### Admin Endpoints

**Authentication:** Include header `X-API-Key: your_admin_api_key`

#### `POST /api/v1/admin/licenses`
Create new license

**Request:**
```json
{
  "customer_id": "john_doe",
  "days": 30,
  "max_activations": 1,
  "notes": "Monthly subscription"
}
```

**Response:**
```json
{
  "license_key": "john_doe:1702598400:8a7f2c:signature",
  "customer_id": "john_doe",
  "expires_at": "2025-12-15T00:00:00",
  "days": 30
}
```

#### `POST /api/v1/admin/licenses/{license_key}/revoke`
Revoke a license (blocks immediately)

**Response:**
```json
{
  "revoked": true,
  "license_key": "..."
}
```

#### `GET /api/v1/admin/licenses`
List all licenses

**Response:**
```json
{
  "total": 5,
  "licenses": [
    {
      "customer_id": "john_doe",
      "status": "active",
      "issued_at": "2025-11-15T00:00:00",
      "expires_at": "2025-12-15T00:00:00",
      "machine_id": "abc123def456",
      "activation_count": 1,
      "last_validated": "2025-11-15T12:30:00"
    }
  ]
}
```

---

## Environment Variables

| Variable | Description | Example |
|----------|-------------|---------|
| `LICENSE_SECRET_KEY` | HMAC signing key (NEVER share!) | `abc123...` (64 chars) |
| `JWT_SECRET` | JWT token signing key | `def456...` (64 chars) |
| `ADMIN_API_KEY` | API key for admin endpoints | `ghi789...` (32 chars) |
| `DATABASE_URL` | PostgreSQL connection string | `postgresql://user:pass@host/db` |

**Generate secure keys:**
```python
import secrets
print(f"LICENSE_SECRET_KEY={secrets.token_hex(32)}")
print(f"JWT_SECRET={secrets.token_hex(32)}")
print(f"ADMIN_API_KEY={secrets.token_hex(16)}")
```

---

## Database Schema

```sql
CREATE TABLE licenses (
    id SERIAL PRIMARY KEY,
    license_key VARCHAR UNIQUE NOT NULL,
    customer_id VARCHAR NOT NULL,
    machine_id VARCHAR,
    max_activations INTEGER DEFAULT 1,
    activation_count INTEGER DEFAULT 0,
    status VARCHAR DEFAULT 'active',
    issued_at TIMESTAMP DEFAULT NOW(),
    expires_at TIMESTAMP NOT NULL,
    last_validated TIMESTAMP,
    notes TEXT
);

CREATE INDEX idx_license_key ON licenses(license_key);
CREATE INDEX idx_customer_id ON licenses(customer_id);
CREATE INDEX idx_status ON licenses(status);
```

---

## Security Best Practices

1. **HTTPS Only** - Use TLS certificate (Let's Encrypt free)
2. **Rate Limiting** - Add nginx/Cloudflare rate limiting
3. **Firewall** - Restrict database access
4. **Backups** - Daily PostgreSQL backups
5. **Monitoring** - Set up uptime monitoring (UptimeRobot free)
6. **Secrets Rotation** - Rotate keys every 6-12 months

---

## Testing

```bash
# Test validation endpoint
curl -X POST http://localhost:8000/api/v1/licenses/validate \
  -H "Content-Type: application/json" \
  -d '{
    "license_key": "test_customer:1234567890:abc:signature",
    "machine_id": "test_machine_123"
  }'

# Test admin create license
curl -X POST http://localhost:8000/api/v1/admin/licenses \
  -H "Content-Type: application/json" \
  -H "X-API-Key: your_admin_key" \
  -d '{
    "customer_id": "test_user",
    "days": 7
  }'
```

---

## Monitoring & Logs

The server logs all validation attempts. Monitor for:
- Multiple failed validation attempts (potential cracking)
- Same license on multiple machines (sharing/piracy)
- Unusual validation patterns

Consider adding:
- Sentry/Rollbar for error tracking
- DataDog/New Relic for performance
- Custom analytics dashboard

---

## Cost Breakdown

| Service | Provider | Monthly Cost |
|---------|----------|--------------|
| **API Server** | DigitalOcean Apps | $7 |
| **PostgreSQL** | DigitalOcean Managed | $7 |
| **Domain + SSL** | Cloudflare | Free |
| **Monitoring** | UptimeRobot | Free |
| **Total** | | **$14/month** |

Scale up as needed (100+ concurrent users ~ $20-30/mo)

---

## Next Steps

1. Deploy server to DigitalOcean/Heroku
2. Update client `license_manager.py` to call this API
3. Test end-to-end validation flow
4. Add PyArmor obfuscation to client
5. Distribute exe to customers

Your SECRET_KEY never leaves the server! 🔒
