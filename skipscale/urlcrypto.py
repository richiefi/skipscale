import base64
from urllib.parse import quote

from Cryptodome.Cipher import AES
from Cryptodome.Hash import SHA1

def encrypt_url(key: bytes, tenant: str, url: str) -> str:
    # strip 'https://' from urls to save space
    if url.startswith("https://"):
        url = url[8:]
    
    # Some customers send image URLs with unencoded UTF-8, but can't actually serve
    # those URLs. Encode input unless it already looks percent-escaped.
    # https://stackoverflow.com/a/6618858
    if '%' not in url:
        url = quote(url, safe='~@#$&()*!+=:;,.?/\'')

    url_bytes = url.encode("utf-8")
    nonce = SHA1.new(data=url_bytes).digest()[:12] # per-input stable nonce, truncated to 12 bytes
    cipher = AES.new(key, AES.MODE_GCM, nonce=nonce, mac_len=4)
    cipher.update(tenant.encode('utf-8'))
    ciphertext, tag = cipher.encrypt_and_digest(url_bytes)
    payload = nonce + ciphertext + tag
    return base64.urlsafe_b64encode(payload).decode('utf-8').rstrip("=")

def decrypt_url(key: bytes, tenant: str, ciphertext: str) -> str:
    cipher_bytes = base64.urlsafe_b64decode(ciphertext)
    nonce = cipher_bytes[:12]
    plaintext = cipher_bytes[12:-4]
    tag = cipher_bytes[-4:]
    cipher = AES.new(key, AES.MODE_GCM, nonce=nonce, mac_len=4)
    cipher.update(tenant.encode('utf-8'))
    url_bytes = cipher.decrypt_and_verify(plaintext, tag) # raises ValueError if MAC check fails
    url = url_bytes.decode('utf-8')
    if not url.startswith('https://') and not url.startswith('http://'):
        return "https://" + url
    return url
