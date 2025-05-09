from Crypto.Cipher import AES
from Crypto.Random import get_random_bytes
from base64 import b64encode, b64decode
import hashlib

def generate_shared_key(ip1, port1, ip2, port2):
    endpoints = sorted([f"{ip1}:{port1}", f"{ip2}:{port2}"])
    shared_secret = "supersecurepassword"
    raw = (endpoints[0] + endpoints[1] + shared_secret).encode()
    return hashlib.sha256(raw).digest()[:16]  # AES-128

def encrypt(key, plaintext):
    cipher = AES.new(key, AES.MODE_EAX)
    ciphertext, tag = cipher.encrypt_and_digest(plaintext.encode())
    return b64encode(cipher.nonce + tag + ciphertext).decode()

def decrypt(key, encoded):
    raw = b64decode(encoded)
    nonce, tag, ciphertext = raw[:16], raw[16:32], raw[32:]
    cipher = AES.new(key, AES.MODE_EAX, nonce)
    return cipher.decrypt_and_verify(ciphertext, tag).decode()