
import hashlib
import hmac
import json
import uuid

from dotenv import dotenv_values
from urllib.error import HTTPError
from urllib.request import Request, urlopen


config = dotenv_values(".env")
secret = config.get("WEBHOOK_SECRET")

if not secret:
    raise RuntimeError("WEBHOOK_SECRET is missing from .env")

payment_id = int(input("Enter a PENDING payment ID: "))

payload = {
    "id": f"evt_local_test_{uuid.uuid4().hex}",
    "type": "payment.succeeded",
    "data": {
        "payment_id": payment_id,
    },
}

# Sign the exact raw bytes that will be sent.
raw_body = json.dumps(
    payload,
    separators=(",", ":"),
).encode("utf-8")

signature = "sha256=" + hmac.new(
    secret.encode("utf-8"),
    raw_body,
    hashlib.sha256,
).hexdigest()

request = Request(
    "http://127.0.0.1:8000/api/webhooks/payment/",
    data=raw_body,
    headers={
        "Content-Type": "application/json",
        "X-Webhook-Signature": signature,
    },
    method="POST",
)


def send_request():
    try:
        with urlopen(request, timeout=10) as response:
            print("HTTP status:", response.status)
            print("Response:", response.read().decode("utf-8"))
    except HTTPError as error:
        print("HTTP status:", error.code)
        print("Response:", error.read().decode("utf-8"))


print("\nFirst request:")
send_request()

print("\nDuplicate request with the same event ID:")
send_request()
