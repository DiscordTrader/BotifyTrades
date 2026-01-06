# BotifyTrades License Server

## Overview

FastAPI-based license validation service for BotifyTrades. This server handles all license operations and should be deployed separately from the bot application.

## Features

- **Trial Licenses** - 7-day trials bound to machine ID
- **Subscription Licenses** - Configurable duration with machine binding
- **Offline Grace Period** - 48-hour JWT tokens for offline validation
- **Machine Binding** - Licenses tied to specific hardware
- **Remote Revocation** - Instantly revoke pirated copies
- **Admin CLI** - Command-line license management

---

## Quick Start

### 1. Install Dependencies

```bash
pip install -r requirements.txt
```

### 2. Set Environment Variables

```bash
export DATABASE_URL="postgresql://user:password@localhost/licenses"
export LICENSE_SECRET_KEY="your_64_char_secret_key"
export JWT_SECRET="your_64_char_jwt_secret"
export ADMIN_API_KEY="your_32_char_admin_key"
export TRIAL_DAYS="7"
```

Generate secure keys:
```python
import secrets
print(f"LICENSE_SECRET_KEY={secrets.token_hex(32)}")
print(f"JWT_SECRET={secrets.token_hex(32)}")
print(f"ADMIN_API_KEY={secrets.token_hex(16)}")
```

### 3. Run Server

```bash
# Development
python main.py

# Production
gunicorn main:app -w 4 -k uvicorn.workers.UvicornWorker --bind 0.0.0.0:5000
```

Server runs at: `http://localhost:5000`

---

## API Reference

### Client Endpoints

Used by the bot application for license validation.

#### `GET /api/v1/license/status`

Check server health.

**Response:**
```json
{
  "status": "online",
  "version": "2.0.0",
  "timestamp": "2026-01-06T12:00:00"
}
```

#### `POST /api/v1/license/trial`

Request a trial license.

**Request:**
```json
{
  "machine_id": "abc123def456",
  "machine_info": {"os": "Windows", "hostname": "PC-001"}
}
```

**Response:**
```json
{
  "success": true,
  "license_key": "BTT-A1B2-C3D4-E5F6",
  "expires_at": "2026-01-13T12:00:00",
  "days_remaining": 7,
  "license_type": "trial",
  "signed_token": "eyJhbGciOiJIUzI1NiIs..."
}
```

#### `POST /api/v1/license/activate`

Activate a license on a machine.

**Request:**
```json
{
  "license_key": "BTF-XXXX-XXXX-XXXX",
  "machine_id": "abc123def456",
  "machine_info": {"os": "Windows", "hostname": "PC-001"}
}
```

**Response:**
```json
{
  "success": true,
  "is_valid": true,
  "customer_id": "john@email.com",
  "expires_at": "2026-02-06T12:00:00",
  "days_remaining": 30,
  "license_type": "subscription",
  "signed_token": "eyJhbGciOiJIUzI1NiIs..."
}
```

#### `POST /api/v1/license/validate`

Validate a license (periodic check).

**Request:**
```json
{
  "license_key": "BTF-XXXX-XXXX-XXXX",
  "machine_id": "abc123def456"
}
```

**Response (Success):**
```json
{
  "is_valid": true,
  "success": true,
  "customer_id": "john@email.com",
  "expires_at": "2026-02-06T12:00:00",
  "days_remaining": 30,
  "license_type": "subscription",
  "signed_token": "eyJhbGciOiJIUzI1NiIs..."
}
```

**Response (Error):**
```json
{
  "is_valid": false,
  "error": "License revoked"
}
```

#### `POST /api/v1/license/deactivate`

Deactivate license from machine (allows transfer).

**Request:**
```json
{
  "license_key": "BTF-XXXX-XXXX-XXXX",
  "machine_id": "abc123def456"
}
```

---

### Admin Endpoints

Require `X-API-Key` header with `ADMIN_API_KEY` value.

#### `POST /api/v1/admin/licenses`

Create new license.

**Request:**
```json
{
  "customer_id": "john@email.com",
  "days": 30,
  "max_activations": 1,
  "license_type": "subscription",
  "notes": "Monthly subscription"
}
```

**Response:**
```json
{
  "success": true,
  "license_key": "BTF-A1B2-C3D4-E5F6",
  "customer_id": "john@email.com",
  "expires_at": "2026-02-06T12:00:00",
  "days": 30,
  "license_type": "subscription"
}
```

#### `GET /api/v1/admin/licenses`

List all licenses.

#### `GET /api/v1/admin/licenses/{license_key}`

Get license details.

#### `POST /api/v1/admin/licenses/{license_key}/revoke`

Revoke a license (immediate block).

#### `POST /api/v1/admin/licenses/{license_key}/extend?days=30`

Extend license expiration.

#### `POST /api/v1/admin/licenses/{license_key}/clear-activation`

Clear machine binding (allows re-activation).

#### `POST /api/v1/admin/licenses/{license_key}/set-device-limit?limit=2`

Set max device limit.

---

## Database Schema

```sql
CREATE TABLE licenses (
    id SERIAL PRIMARY KEY,
    license_key VARCHAR UNIQUE NOT NULL,
    customer_id VARCHAR NOT NULL,
    license_type VARCHAR DEFAULT 'subscription',
    machine_id VARCHAR,
    machine_info TEXT,
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
CREATE INDEX idx_machine_id ON licenses(machine_id);
```

---

## License Key Formats

| Prefix | Type | Example |
|--------|------|---------|
| `BTF-` | Subscription | `BTF-A1B2-C3D4-E5F6` |
| `BTT-` | Trial | `BTT-A1B2-C3D4-E5F6` |

---

## Security Features

- **HMAC Signing** - All responses cryptographically signed
- **JWT Tokens** - 48-hour offline grace period tokens
- **Machine Binding** - License tied to hardware ID
- **Rate Limiting** - Add nginx/Cloudflare for protection
- **HTTPS Required** - TLS encryption for all traffic

---

## Environment Variables

| Variable | Required | Description |
|----------|----------|-------------|
| `DATABASE_URL` | Yes | PostgreSQL connection string |
| `LICENSE_SECRET_KEY` | Yes | 64-char HMAC signing key |
| `JWT_SECRET` | Yes | 64-char JWT signing key |
| `ADMIN_API_KEY` | Yes | 32-char admin access key |
| `TRIAL_DAYS` | No | Trial duration (default: 7) |
| `PORT` | No | Server port (default: 5000) |

---

## Deployment Options

### Replit (Recommended for simplicity)

1. Create new private Python repl
2. Copy files and set secrets
3. Run: `uvicorn main:app --host 0.0.0.0 --port 5000`

### VPS (For maximum control)

See `SETUP_NEW_PROJECT.md` for detailed VPS deployment guide.

### Cloud Platforms

- **DigitalOcean App Platform** - $7/mo
- **Render** - Free tier available
- **Railway** - Usage-based pricing
- **Heroku** - $7/mo

---

## Monitoring

The server logs all validation attempts. Monitor for:

- Multiple failed validations (potential cracking)
- Same license on multiple machines (sharing)
- Unusual validation patterns

Consider adding:
- Sentry/Rollbar for error tracking
- UptimeRobot for availability monitoring
- DataDog for performance metrics
