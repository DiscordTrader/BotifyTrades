"""
License Validation Server
FastAPI-based license validation service with PostgreSQL backend
Keeps SECRET_KEY server-side only - never ships to clients

ENDPOINTS (all use singular /api/v1/license/):
- POST /api/v1/license/trial      - Request trial license
- POST /api/v1/license/activate   - First-time activation
- POST /api/v1/license/validate   - Validate license key
- POST /api/v1/license/deactivate - Deactivate license
- GET  /api/v1/license/status     - Server status check
"""

from fastapi import FastAPI, HTTPException, Depends, Header
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel
from typing import Optional
import os
import hmac
import hashlib
import secrets
from datetime import datetime, timedelta
import jwt
from sqlalchemy import create_engine, Column, String, Integer, DateTime, Boolean, Text
from sqlalchemy.ext.declarative import declarative_base
from sqlalchemy.orm import sessionmaker, Session

app = FastAPI(title="BotifyTrades License Server", version="2.0.0")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

DATABASE_URL = os.getenv("DATABASE_URL", "postgresql://localhost/licenses")
SECRET_KEY = os.getenv("LICENSE_SECRET_KEY", secrets.token_hex(32))
JWT_SECRET = os.getenv("JWT_SECRET", secrets.token_hex(32))
ADMIN_API_KEY = os.getenv("ADMIN_API_KEY", secrets.token_hex(16))
TRIAL_DAYS = int(os.getenv("TRIAL_DAYS", "7"))

engine = create_engine(DATABASE_URL)
SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)
Base = declarative_base()

class License(Base):
    __tablename__ = "licenses"
    
    id = Column(Integer, primary_key=True, index=True)
    license_key = Column(String, unique=True, index=True, nullable=False)
    customer_id = Column(String, nullable=False)
    license_type = Column(String, default="subscription")
    machine_id = Column(String, nullable=True)
    machine_info = Column(Text, nullable=True)
    max_activations = Column(Integer, default=1)
    activation_count = Column(Integer, default=0)
    status = Column(String, default="active")
    issued_at = Column(DateTime, default=datetime.utcnow)
    expires_at = Column(DateTime, nullable=False)
    last_validated = Column(DateTime, nullable=True)
    notes = Column(String, nullable=True)

Base.metadata.create_all(bind=engine)

class TrialRequest(BaseModel):
    machine_id: str
    machine_info: Optional[dict] = None

class ActivateRequest(BaseModel):
    license_key: str
    machine_id: str
    machine_info: Optional[dict] = None

class ValidateRequest(BaseModel):
    license_key: str
    machine_id: str

class DeactivateRequest(BaseModel):
    license_key: str
    machine_id: str

class AdminLicenseCreate(BaseModel):
    customer_id: str
    days: int = 30
    max_activations: int = 1
    notes: Optional[str] = None
    license_type: Optional[str] = "subscription"

def get_db():
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()

def verify_admin_key(x_api_key: str = Header(...)):
    if not hmac.compare_digest(x_api_key, ADMIN_API_KEY):
        raise HTTPException(status_code=403, detail="Invalid API key")
    return True

def generate_license_key(prefix: str = "BTF") -> str:
    """Generate BTF-XXXX-XXXX-XXXX format license key"""
    parts = [secrets.token_hex(2).upper() for _ in range(3)]
    return f"{prefix}-{'-'.join(parts)}"

def create_signed_token(license_key: str, machine_id: str, expires_hours: int = 48) -> str:
    """Create signed JWT token for offline grace period validation."""
    payload = {
        "license_key": license_key,
        "machine_id": machine_id,
        "exp": datetime.utcnow() + timedelta(hours=expires_hours),
        "iat": datetime.utcnow(),
        "type": "offline_grace"
    }
    return jwt.encode(payload, JWT_SECRET, algorithm="HS256")

@app.get("/")
async def root():
    return {
        "service": "BotifyTrades License Server",
        "version": "2.0.0",
        "status": "operational"
    }

@app.get("/api/v1/license/status")
async def server_status():
    """Check server status - used by client health checks"""
    return {
        "status": "online",
        "version": "2.0.0",
        "timestamp": datetime.utcnow().isoformat()
    }

@app.post("/api/v1/license/trial")
async def request_trial(req: TrialRequest, db: Session = Depends(get_db)):
    """
    Request a trial license for a new machine.
    Returns a trial license valid for TRIAL_DAYS.
    """
    existing = db.query(License).filter(
        License.machine_id == req.machine_id,
        License.license_type == "trial"
    ).first()
    
    if existing:
        if existing.status == "active" and existing.expires_at > datetime.utcnow():
            days_remaining = (existing.expires_at - datetime.utcnow()).days
            return {
                "success": True,
                "license_key": existing.license_key,
                "expires_at": existing.expires_at.isoformat(),
                "days_remaining": days_remaining,
                "message": "Existing trial found",
                "signed_token": create_signed_token(existing.license_key, req.machine_id)
            }
        else:
            return {
                "success": False,
                "error": "Trial already used on this machine",
                "message": "Trial expired or already used"
            }
    
    license_key = generate_license_key("BTT")
    expires_at = datetime.utcnow() + timedelta(days=TRIAL_DAYS)
    
    machine_info_str = str(req.machine_info) if req.machine_info else None
    
    license_record = License(
        license_key=license_key,
        customer_id=f"trial_{req.machine_id[:8]}",
        license_type="trial",
        machine_id=req.machine_id,
        machine_info=machine_info_str,
        max_activations=1,
        activation_count=1,
        expires_at=expires_at,
        last_validated=datetime.utcnow()
    )
    
    db.add(license_record)
    db.commit()
    db.refresh(license_record)
    
    return {
        "success": True,
        "license_key": license_key,
        "expires_at": expires_at.isoformat(),
        "days_remaining": TRIAL_DAYS,
        "license_type": "trial",
        "signed_token": create_signed_token(license_key, req.machine_id)
    }

@app.post("/api/v1/license/activate")
async def activate_license(req: ActivateRequest, db: Session = Depends(get_db)):
    """
    First-time activation of a license key on a machine.
    Binds the license to the machine_id.
    """
    license_record = db.query(License).filter(
        License.license_key == req.license_key
    ).first()
    
    if not license_record:
        return {"success": False, "error": "License not found"}
    
    if license_record.status != "active":
        return {"success": False, "error": f"License {license_record.status}"}
    
    if license_record.expires_at < datetime.utcnow():
        license_record.status = "expired"
        db.commit()
        return {"success": False, "error": "License expired"}
    
    if license_record.machine_id:
        if license_record.machine_id == req.machine_id:
            days_remaining = (license_record.expires_at - datetime.utcnow()).days
            return {
                "success": True,
                "is_valid": True,
                "message": "License already activated on this machine",
                "customer_id": license_record.customer_id,
                "expires_at": license_record.expires_at.isoformat(),
                "days_remaining": days_remaining,
                "license_type": license_record.license_type,
                "signed_token": create_signed_token(req.license_key, req.machine_id)
            }
        else:
            return {
                "success": False,
                "error": "License already activated on another machine",
                "message": "Contact support to transfer license"
            }
    
    if license_record.activation_count >= license_record.max_activations:
        return {"success": False, "error": "Maximum activations reached"}
    
    machine_info_str = str(req.machine_info) if req.machine_info else None
    
    license_record.machine_id = req.machine_id
    license_record.machine_info = machine_info_str
    license_record.activation_count += 1
    license_record.last_validated = datetime.utcnow()
    db.commit()
    
    days_remaining = (license_record.expires_at - datetime.utcnow()).days
    
    return {
        "success": True,
        "is_valid": True,
        "customer_id": license_record.customer_id,
        "expires_at": license_record.expires_at.isoformat(),
        "days_remaining": days_remaining,
        "license_type": license_record.license_type,
        "signed_token": create_signed_token(req.license_key, req.machine_id)
    }

@app.post("/api/v1/license/validate")
async def validate_license(req: ValidateRequest, db: Session = Depends(get_db)):
    """
    Validate a license key and machine ID.
    Returns signed token for offline grace period.
    """
    license_record = db.query(License).filter(
        License.license_key == req.license_key
    ).first()
    
    if not license_record:
        return {"is_valid": False, "error": "License not found"}
    
    if license_record.status == "revoked":
        return {"is_valid": False, "error": "License revoked"}
    
    if license_record.status == "suspended":
        return {"is_valid": False, "error": "License suspended"}
    
    if license_record.status != "active":
        return {"is_valid": False, "error": f"License {license_record.status}"}
    
    if license_record.expires_at < datetime.utcnow():
        license_record.status = "expired"
        db.commit()
        return {"is_valid": False, "error": "License expired"}
    
    if license_record.machine_id and license_record.machine_id != req.machine_id:
        return {
            "is_valid": False,
            "error": "Machine ID mismatch - license bound to different machine"
        }
    
    if not license_record.machine_id:
        return {
            "is_valid": False,
            "error": "License not activated - please activate first"
        }
    
    license_record.last_validated = datetime.utcnow()
    db.commit()
    
    days_remaining = (license_record.expires_at - datetime.utcnow()).days
    
    return {
        "is_valid": True,
        "success": True,
        "customer_id": license_record.customer_id,
        "expires_at": license_record.expires_at.isoformat(),
        "days_remaining": days_remaining,
        "license_type": license_record.license_type,
        "signed_token": create_signed_token(req.license_key, req.machine_id, 48)
    }

@app.post("/api/v1/license/deactivate")
async def deactivate_license(req: DeactivateRequest, db: Session = Depends(get_db)):
    """
    Deactivate a license from a machine.
    Allows re-activation on another machine.
    """
    license_record = db.query(License).filter(
        License.license_key == req.license_key
    ).first()
    
    if not license_record:
        return {"success": False, "error": "License not found"}
    
    if license_record.machine_id != req.machine_id:
        return {"success": False, "error": "Machine ID mismatch"}
    
    old_machine = license_record.machine_id
    license_record.machine_id = None
    license_record.machine_info = None
    db.commit()
    
    return {
        "success": True,
        "message": "License deactivated - can be activated on another machine",
        "old_machine_id": old_machine
    }

@app.post("/api/v1/admin/licenses", dependencies=[Depends(verify_admin_key)])
async def create_license(req: AdminLicenseCreate, db: Session = Depends(get_db)):
    """Admin: Create new license"""
    expires_at = datetime.utcnow() + timedelta(days=req.days)
    license_key = generate_license_key("BTF")
    
    license_record = License(
        license_key=license_key,
        customer_id=req.customer_id,
        license_type=req.license_type or "subscription",
        max_activations=req.max_activations,
        expires_at=expires_at,
        notes=req.notes
    )
    
    db.add(license_record)
    db.commit()
    db.refresh(license_record)
    
    return {
        "success": True,
        "license_key": license_key,
        "customer_id": req.customer_id,
        "expires_at": expires_at.isoformat(),
        "days": req.days,
        "license_type": req.license_type
    }

@app.post("/api/v1/admin/licenses/{license_key}/revoke", dependencies=[Depends(verify_admin_key)])
async def revoke_license(license_key: str, db: Session = Depends(get_db)):
    """Admin: Revoke a license"""
    license_record = db.query(License).filter(
        License.license_key == license_key
    ).first()
    
    if not license_record:
        raise HTTPException(status_code=404, detail="License not found")
    
    license_record.status = "revoked"
    db.commit()
    
    return {"success": True, "revoked": True, "license_key": license_key}

@app.post("/api/v1/admin/licenses/{license_key}/extend", dependencies=[Depends(verify_admin_key)])
async def extend_license(license_key: str, days: int = 30, db: Session = Depends(get_db)):
    """Admin: Extend license expiration"""
    license_record = db.query(License).filter(
        License.license_key == license_key
    ).first()
    
    if not license_record:
        raise HTTPException(status_code=404, detail="License not found")
    
    old_expires = license_record.expires_at
    
    if license_record.expires_at < datetime.utcnow():
        license_record.expires_at = datetime.utcnow() + timedelta(days=days)
    else:
        license_record.expires_at = license_record.expires_at + timedelta(days=days)
    
    license_record.status = "active"
    db.commit()
    
    return {
        "success": True,
        "license_key": license_key,
        "old_expires_at": old_expires.isoformat(),
        "new_expires_at": license_record.expires_at.isoformat(),
        "days_added": days
    }

@app.post("/api/v1/admin/licenses/{license_key}/clear-activation", dependencies=[Depends(verify_admin_key)])
async def clear_license_activation(license_key: str, db: Session = Depends(get_db)):
    """Admin: Clear machine activation to allow re-activation on new machine"""
    license_record = db.query(License).filter(
        License.license_key == license_key
    ).first()
    
    if not license_record:
        raise HTTPException(status_code=404, detail="License not found")
    
    old_machine_id = license_record.machine_id
    license_record.machine_id = None
    license_record.machine_info = None
    license_record.activation_count = 0
    db.commit()
    
    return {
        "success": True,
        "message": "Activation cleared - license can now be activated on a new machine",
        "license_key": license_key,
        "old_machine_id": old_machine_id
    }

@app.post("/api/v1/admin/licenses/{license_key}/set-device-limit", dependencies=[Depends(verify_admin_key)])
async def set_device_limit(license_key: str, limit: int = 1, db: Session = Depends(get_db)):
    """Admin: Update device/activation limit for a license"""
    license_record = db.query(License).filter(
        License.license_key == license_key
    ).first()
    
    if not license_record:
        raise HTTPException(status_code=404, detail="License not found")
    
    old_limit = license_record.max_activations
    license_record.max_activations = limit
    db.commit()
    
    return {
        "success": True,
        "license_key": license_key,
        "old_limit": old_limit,
        "new_limit": limit
    }

@app.get("/api/v1/admin/licenses", dependencies=[Depends(verify_admin_key)])
async def list_licenses(db: Session = Depends(get_db)):
    """Admin: List all licenses"""
    licenses = db.query(License).order_by(License.id.desc()).all()
    return {
        "total": len(licenses),
        "licenses": [
            {
                "id": lic.id,
                "license_key": lic.license_key,
                "customer_id": lic.customer_id,
                "license_type": lic.license_type,
                "status": lic.status,
                "issued_at": lic.issued_at.isoformat(),
                "expires_at": lic.expires_at.isoformat(),
                "days_remaining": max(0, (lic.expires_at - datetime.utcnow()).days),
                "machine_id": lic.machine_id or "Not activated",
                "activation_count": lic.activation_count,
                "max_activations": lic.max_activations,
                "last_validated": lic.last_validated.isoformat() if lic.last_validated else None
            }
            for lic in licenses
        ]
    }

@app.get("/api/v1/admin/licenses/{license_key}", dependencies=[Depends(verify_admin_key)])
async def get_license_details(license_key: str, db: Session = Depends(get_db)):
    """Admin: Get detailed license info"""
    license_record = db.query(License).filter(
        License.license_key == license_key
    ).first()
    
    if not license_record:
        raise HTTPException(status_code=404, detail="License not found")
    
    days_remaining = max(0, (license_record.expires_at - datetime.utcnow()).days)
    
    return {
        "id": license_record.id,
        "license_key": license_record.license_key,
        "customer_id": license_record.customer_id,
        "license_type": license_record.license_type,
        "status": license_record.status,
        "machine_id": license_record.machine_id,
        "machine_info": license_record.machine_info,
        "activation_count": license_record.activation_count,
        "max_activations": license_record.max_activations,
        "issued_at": license_record.issued_at.isoformat(),
        "expires_at": license_record.expires_at.isoformat(),
        "days_remaining": days_remaining,
        "last_validated": license_record.last_validated.isoformat() if license_record.last_validated else None,
        "notes": license_record.notes
    }

if __name__ == "__main__":
    import uvicorn
    port = int(os.getenv("PORT", 5000))
    uvicorn.run(app, host="0.0.0.0", port=port)
