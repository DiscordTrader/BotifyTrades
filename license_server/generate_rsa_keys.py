"""
Generate RSA Key Pair for License Signing
Run this ONCE to generate keys for your license server
"""

from cryptography.hazmat.primitives.asymmetric import rsa
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.backends import default_backend

def generate_rsa_keypair():
    """Generate RSA 2048-bit key pair"""
    print("Generating RSA 2048-bit key pair...")
    
    private_key = rsa.generate_private_key(
        public_exponent=65537,
        key_size=2048,
        backend=default_backend()
    )
    
    public_key = private_key.public_key()
    
    private_pem = private_key.private_bytes(
        encoding=serialization.Encoding.PEM,
        format=serialization.PrivateFormat.PKCS8,
        encryption_algorithm=serialization.NoEncryption()
    )
    
    public_pem = public_key.public_bytes(
        encoding=serialization.Encoding.PEM,
        format=serialization.PublicFormat.SubjectPublicKeyInfo
    )
    
    print("=" * 80)
    print("RSA PRIVATE KEY (keep SECRET on server only!)")
    print("=" * 80)
    print(private_pem.decode())
    print()
    print("Save this to environment variable: RSA_PRIVATE_KEY")
    print()
    print("=" * 80)
    print("RSA PUBLIC KEY (embed in client code)")
    print("=" * 80)
    print(public_pem.decode())
    print()
    print("Copy this to src/license_client.py RSA_PUBLIC_KEY_PEM constant")
    print()
    print("=" * 80)
    print("✓ Keys generated successfully!")
    print("=" * 80)
    
    with open('rsa_private.pem', 'w') as f:
        f.write(private_pem.decode())
    
    with open('rsa_public.pem', 'w') as f:
        f.write(public_pem.decode())
    
    print("\nKeys also saved to:")
    print("  - rsa_private.pem (KEEP SECRET!)")
    print("  - rsa_public.pem (distribute with client)")

if __name__ == "__main__":
    generate_rsa_keypair()
