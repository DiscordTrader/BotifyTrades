"""
License Validation Server
FastAPI-based license validation service with PostgreSQL backend
Keeps SECRET_KEY server-side only - never ships to clients
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
from sqlalchemy import create_engine, Column, String, Integer, DateTime, Boolean
from sqlalchemy.ext.declarative import declarative_base
from sqlalchemy.orm import sessionmaker, Session

app = FastAPI(title="Trading Bot License Server", version="1.0.0")

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

engine = create_engine(DATABASE_URL)
SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)
Base = declarative_base()

class License(Base):
    __tablename__ = "licenses"
    
    id = Column(Integer, primary_key=True, index=True)
    license_key = Column(String, unique=True, index=True, nullable=False)
    customer_id = Column(String, nullable=False)
    machine_id = Column(String, nullable=True)
    max_activations = Column(Integer, default=1)
    activation_count = Column(Integer, default=0)
    status = Column(String, default="active")
    issued_at = Column(DateTime, default=datetime.utcnow)
    expires_at = Column(DateTime, nullable=False)
    last_validated = Column(DateTime, nullable=True)
    notes = Column(String, nullable=True)

Base.metadata.create_all(bind=engine)

class ValidationRequest(BaseModel):
    license_key: str
    machine_id: str
    client_version: Optional[str] = "1.0.0"

class ActivationRequest(BaseModel):
    license_key: str
    machine_id: str
    customer_email: Optional[str] = None

class AdminLicenseCreate(BaseModel):
    customer_id: str
    days: int = 30
    max_activations: int = 1
    notes: Optional[str] = None

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

def generate_license_key(customer_id: str, expires_at: datetime) -> str:
    """Generate cryptographically secure license key"""
    data = f"{customer_id}:{int(expires_at.timestamp())}:{secrets.token_hex(8)}"
    signature = hmac.new(
        SECRET_KEY.encode(),
        data.encode(),
        hashlib.sha256
    ).hexdigest()
    return f"{data}:{signature}"

def is_database_only_key(license_key: str) -> bool:
    """Check if this is a BT- or BTF- format key (stored in database, no signature)"""
    return license_key.startswith('BT-') or license_key.startswith('BTF-')

def verify_license_key_signature(license_key: str) -> tuple[bool, dict]:
    """Verify license key HMAC signature"""
    try:
        # BT- and BTF- format keys are database-only (no embedded signature)
        # They are validated by database lookup, not signature verification
        if is_database_only_key(license_key):
            return True, {"database_only": True}
        
        parts = license_key.split(":")
        if len(parts) != 4:
            return False, {}
        
        customer_id, expiry_ts, nonce, signature = parts
        data = f"{customer_id}:{expiry_ts}:{nonce}"
        
        expected_sig = hmac.new(
            SECRET_KEY.encode(),
            data.encode(),
            hashlib.sha256
        ).hexdigest()
        
        if not hmac.compare_digest(signature, expected_sig):
            return False, {}
        
        return True, {
            "customer_id": customer_id,
            "expires_at": datetime.fromtimestamp(int(expiry_ts))
        }
    except Exception:
        return False, {}

def create_validation_token(license_key: str, machine_id: str, expires_hours: int = 24) -> str:
    """Create short-lived JWT token for offline grace period"""
    payload = {
        "license_key": license_key,
        "machine_id": machine_id,
        "exp": datetime.utcnow() + timedelta(hours=expires_hours),
        "iat": datetime.utcnow()
    }
    return jwt.encode(payload, JWT_SECRET, algorithm="HS256")

@app.get("/")
async def root():
    return {
        "service": "Trading Bot License Server",
        "version": "1.0.0",
        "status": "operational"
    }

@app.post("/api/v1/licenses/validate")
async def validate_license(req: ValidationRequest, db: Session = Depends(get_db)):
    """
    Validate license key and machine ID
    Returns short-lived JWT token for offline grace period
    """
    valid_sig, key_data = verify_license_key_signature(req.license_key)
    if not valid_sig:
        raise HTTPException(status_code=401, detail="Invalid license key signature")
    
    license_record = db.query(License).filter(
        License.license_key == req.license_key
    ).first()
    
    if not license_record:
        raise HTTPException(status_code=404, detail="License not found")
    
    if license_record.status != "active":
        raise HTTPException(status_code=403, detail=f"License {license_record.status}")
    
    if license_record.expires_at < datetime.utcnow():
        license_record.status = "expired"
        db.commit()
        raise HTTPException(status_code=403, detail="License expired")
    
    if license_record.machine_id and license_record.machine_id != req.machine_id:
        raise HTTPException(status_code=403, detail="Machine ID mismatch - license bound to different machine")
    
    if not license_record.machine_id:
        if license_record.activation_count >= license_record.max_activations:
            raise HTTPException(status_code=403, detail="Maximum activations reached")
        license_record.machine_id = req.machine_id
        license_record.activation_count += 1
    
    license_record.last_validated = datetime.utcnow()
    db.commit()
    
    validation_token = create_validation_token(req.license_key, req.machine_id)
    
    days_remaining = (license_record.expires_at - datetime.utcnow()).days
    
    return {
        "valid": True,
        "customer_id": license_record.customer_id,
        "expires_at": license_record.expires_at.isoformat(),
        "days_remaining": days_remaining,
        "validation_token": validation_token,
        "token_expires_hours": 24
    }

@app.post("/api/v1/licenses/activate")
async def activate_license(req: ActivationRequest, db: Session = Depends(get_db)):
    """First-time activation of a license"""
    valid_sig, key_data = verify_license_key_signature(req.license_key)
    if not valid_sig:
        raise HTTPException(status_code=401, detail="Invalid license key")
    
    license_record = db.query(License).filter(
        License.license_key == req.license_key
    ).first()
    
    if not license_record:
        raise HTTPException(status_code=404, detail="License not found")
    
    if license_record.machine_id:
        raise HTTPException(status_code=403, detail="License already activated")
    
    if license_record.status != "active":
        raise HTTPException(status_code=403, detail=f"License {license_record.status}")
    
    if license_record.expires_at < datetime.utcnow():
        raise HTTPException(status_code=403, detail="License expired")
    
    license_record.machine_id = req.machine_id
    license_record.activation_count = 1
    license_record.last_validated = datetime.utcnow()
    db.commit()
    
    return {
        "activated": True,
        "customer_id": license_record.customer_id,
        "expires_at": license_record.expires_at.isoformat()
    }

@app.post("/api/v1/admin/licenses", dependencies=[Depends(verify_admin_key)])
async def create_license(req: AdminLicenseCreate, db: Session = Depends(get_db)):
    """Admin: Create new license"""
    expires_at = datetime.utcnow() + timedelta(days=req.days)
    license_key = generate_license_key(req.customer_id, expires_at)
    
    license_record = License(
        license_key=license_key,
        customer_id=req.customer_id,
        max_activations=req.max_activations,
        expires_at=expires_at,
        notes=req.notes
    )
    
    db.add(license_record)
    db.commit()
    db.refresh(license_record)
    
    return {
        "license_key": license_key,
        "customer_id": req.customer_id,
        "expires_at": expires_at.isoformat(),
        "days": req.days
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
    
    return {"revoked": True, "license_key": license_key}

@app.get("/api/v1/admin/licenses", dependencies=[Depends(verify_admin_key)])
async def list_licenses(db: Session = Depends(get_db)):
    """Admin: List all licenses"""
    licenses = db.query(License).all()
    return {
        "total": len(licenses),
        "licenses": [
            {
                "license_key": lic.license_key,
                "customer_id": lic.customer_id,
                "status": lic.status,
                "issued_at": lic.issued_at.isoformat(),
                "expires_at": lic.expires_at.isoformat(),
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
    """Admin: Get detailed license info including machine ID"""
    license_record = db.query(License).filter(
        License.license_key == license_key
    ).first()
    
    if not license_record:
        raise HTTPException(status_code=404, detail="License not found")
    
    days_remaining = max(0, (license_record.expires_at - datetime.utcnow()).days)
    
    return {
        "license_key": license_record.license_key,
        "customer_id": license_record.customer_id,
        "status": license_record.status,
        "machine_id": license_record.machine_id,
        "machine_info": license_record.notes if license_record.notes and "machine_info" in str(license_record.notes) else None,
        "activation_count": license_record.activation_count,
        "max_activations": license_record.max_activations,
        "issued_at": license_record.issued_at.isoformat(),
        "expires_at": license_record.expires_at.isoformat(),
        "days_remaining": days_remaining,
        "last_validated": license_record.last_validated.isoformat() if license_record.last_validated else None
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

if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=8000)
