#!/usr/bin/env bash
# End-to-end demonstration against two REAL running servers.
# Usage:  ./demo.sh          (starts both servers, runs the flows, stops them)
set -uo pipefail
cd "$(dirname "$0")"

PY=.venv/bin/python
export ENCRYPTION_KEY="ZGVtby1rZXktdGhpcnR5LXR3by1ieXRlcy0xMjM0NTY3OA=="
export WEBHOOK_SECRET="demo-webhook-secret"
export APP_BASE_URL="http://127.0.0.1:8000"
export MOCK_PLATFORM_URL="http://127.0.0.1:9000"
export MOCK_WEBHOOK_DELAY="1.0"
export DATABASE_URL="sqlite:///$(pwd)/data/demo_app.db"
export SCHEDULER_DB_URL="sqlite:///$(pwd)/data/demo_sched.db"
export PUBLISH_TIMEOUT_SECONDS=3

rm -f data/demo_app.db data/demo_sched.db data/mock_platform.db

hdr() { echo; echo "=============================================================="; echo "== $1"; echo "=============================================================="; }

$PY -m uvicorn mock_platform.main:app --port 9000 --log-level warning >/tmp/mock.log 2>&1 &
MOCK_PID=$!
$PY -m uvicorn app.main:app --port 8000 --log-level info >/tmp/app.log 2>&1 &
APP_PID=$!
trap 'kill $MOCK_PID $APP_PID 2>/dev/null' EXIT

for i in $(seq 1 40); do
  curl -sf http://127.0.0.1:9000/health >/dev/null && \
  curl -sf http://127.0.0.1:8000/health >/dev/null && break
  sleep 0.5
done

hdr "1. HEALTH"
curl -s http://127.0.0.1:8000/health | $PY -m json.tool
curl -s http://127.0.0.1:9000/health | $PY -m json.tool

hdr "2. CREATE CAMPAIGN"
CAMPAIGN=$(curl -s -X POST http://127.0.0.1:8000/campaigns \
  -H 'Content-Type: application/json' \
  -d '{"title":"Why idempotency keys beat retry counters",
       "body":"Every social API will eventually accept your post and then fail to tell you about it. A retry counter guesses; an idempotency key knows. We derive one deterministic key per social post row and reuse it on every attempt, so a lost response costs a round trip and never a duplicate post.",
       "url":"https://example.com/blog/idempotency-keys"}')
echo "$CAMPAIGN" | $PY -m json.tool
CID=$(echo "$CAMPAIGN" | $PY -c 'import json,sys;print(json.load(sys.stdin)["id"])')
echo "campaign_id=$CID"

hdr "3. GENERATED IMAGE DIMENSIONS"
$PY - "$CID" <<'EOF'
import sys, glob
from PIL import Image
cid = sys.argv[1]
for path in sorted(glob.glob(f"artifacts/*/{cid}_*.png")):
    with Image.open(path) as im:
        print(f"{path:70s} {im.size[0]}x{im.size[1]}")
EOF

hdr "4. IDEMPOTENCY: PUBLISH TWICE"
echo "--- publish #1 ---"
curl -s -X POST "http://127.0.0.1:8000/campaigns/$CID/publish" | $PY -m json.tool
echo "--- publish #2 (same idempotency keys) ---"
curl -s -X POST "http://127.0.0.1:8000/campaigns/$CID/publish" | $PY -m json.tool
echo "--- mock platform post counts (expect 1 each) ---"
curl -s http://127.0.0.1:9000/platform/instagram/posts | $PY -c 'import json,sys;d=json.load(sys.stdin);print("instagram count =",d["count"],[p["id"] for p in d["posts"]])'
curl -s http://127.0.0.1:9000/platform/x/posts | $PY -c 'import json,sys;d=json.load(sys.stdin);print("x count         =",d["count"],[p["id"] for p in d["posts"]])'

hdr "5. WEBHOOK ROUND TRIP: STATUS AFTER SIGNED DELIVERY CALLBACK"
sleep 2
curl -s "http://127.0.0.1:8000/campaigns/$CID" > /tmp/campaign.json
$PY - <<'PYEOF'
import json
for p in json.load(open("/tmp/campaign.json"))["social_posts"]:
    print("{:10s} status={:11s} external={} published_at={}".format(
        p["platform"], p["status"], p["external_post_id"], p["published_at"]))
PYEOF

hdr "6. RATE LIMITING (429 + Retry-After)"
curl -s -X POST http://127.0.0.1:9000/platform/x/reset >/dev/null
curl -s -X POST http://127.0.0.1:9000/platform/x/rate-limit -H 'Content-Type: application/json' -d '{"count":1,"retry_after":2}' | $PY -m json.tool
CAMPAIGN2=$(curl -s -X POST http://127.0.0.1:8000/campaigns -H 'Content-Type: application/json' \
  -d '{"title":"Backpressure is a feature","body":"A 429 is the platform telling you the truth about its capacity. Honour Retry-After exactly and you get to keep your API access.","url":"https://example.com/blog/backpressure","platforms":["x"]}')
CID2=$(echo "$CAMPAIGN2" | $PY -c 'import json,sys;print(json.load(sys.stdin)["id"])')
echo "campaign_id=$CID2  (429 armed, Retry-After: 2)"
START=$(date +%s.%N)
curl -s -X POST "http://127.0.0.1:8000/campaigns/$CID2/publish" | $PY -m json.tool
END=$(date +%s.%N)
echo "elapsed: $($PY -c "print(f'{$END-$START:.2f}s  (>= 2s proves Retry-After was honoured)')")"
echo "--- mock x post count (expect 1, the retry did not duplicate) ---"
curl -s http://127.0.0.1:9000/platform/x/posts | $PY -c 'import json,sys;print("x count =",json.load(sys.stdin)["count"])'

hdr "7. TIMEOUT RECOVERY (response dropped AFTER server-side create)"
curl -s -X POST http://127.0.0.1:9000/platform/instagram/reset >/dev/null
curl -s -X POST http://127.0.0.1:9000/platform/instagram/simulate-timeout -H 'Content-Type: application/json' -d '{"count":1,"delay":6}' | $PY -m json.tool
CAMPAIGN3=$(curl -s -X POST http://127.0.0.1:8000/campaigns -H 'Content-Type: application/json' \
  -d '{"title":"The lost response problem","body":"The platform created your post and then the connection died. Only an idempotency key can tell the retry from a duplicate.","url":"https://example.com/blog/lost-response","platforms":["instagram"]}')
CID3=$(echo "$CAMPAIGN3" | $PY -c 'import json,sys;print(json.load(sys.stdin)["id"])')
curl -s -X POST "http://127.0.0.1:8000/campaigns/$CID3/publish" | $PY -m json.tool
echo "--- mock instagram post count (expect exactly 1) ---"
curl -s http://127.0.0.1:9000/platform/instagram/posts | $PY -c 'import json,sys;d=json.load(sys.stdin);print("instagram count =",d["count"],[p["id"] for p in d["posts"]])'

hdr "8. FORGED WEBHOOK -> 400, STATUS UNCHANGED"
# Hold back automatic delivery so this post stays in 'publishing' while we
# attempt the forgery - otherwise the real signed callback would race us.
curl -s -X POST http://127.0.0.1:9000/platform/x/webhook-delay -H 'Content-Type: application/json' -d '{"delay":600}' >/dev/null
curl -s -X POST http://127.0.0.1:9000/platform/x/reset >/dev/null
curl -s -X POST http://127.0.0.1:9000/platform/x/webhook-delay -H 'Content-Type: application/json' -d '{"delay":600}' >/dev/null
CAMPAIGN4=$(curl -s -X POST http://127.0.0.1:8000/campaigns -H 'Content-Type: application/json' \
  -d '{"title":"An unsigned webhook is an unauthenticated state change","body":"Anyone who can reach your callback URL can claim your post went live. Verify the HMAC over the raw body, in constant time, before you touch a single row.","url":"https://example.com/blog/webhook-security","platforms":["x"]}')
CID4=$(echo "$CAMPAIGN4" | $PY -c 'import json,sys;print(json.load(sys.stdin)["id"])')
curl -s -X POST "http://127.0.0.1:8000/campaigns/$CID4/publish" >/dev/null
POST_JSON=$(curl -s "http://127.0.0.1:8000/campaigns/$CID4" | $PY -c 'import json,sys;p=json.load(sys.stdin)["social_posts"][0];print(json.dumps(p))')
PID=$(echo "$POST_JSON" | $PY -c 'import json,sys;print(json.load(sys.stdin)["id"])')
IDEM=$(echo "$POST_JSON" | $PY -c 'import json,sys;print(json.load(sys.stdin)["idempotency_key"])')
EXT=$(echo "$POST_JSON" | $PY -c 'import json,sys;print(json.load(sys.stdin)["external_post_id"])')
echo "target social_post: $PID"
echo "status before: $(curl -s http://127.0.0.1:8000/social-posts/$PID | $PY -c 'import json,sys;print(json.load(sys.stdin)["status"])')"
BODY="{\"platform\":\"x\",\"external_post_id\":\"$EXT\",\"idempotency_key\":\"$IDEM\",\"status\":\"delivered\"}"
echo "-- HTTP status with a forged signature:"
curl -s -o /tmp/forged.json -w '%{http_code}\n' -X POST http://127.0.0.1:8000/webhook/social-delivery \
  -H 'Content-Type: application/json' -H "X-Signature: sha256=0000000000000000000000000000000000000000000000000000000000000000" \
  -d "$BODY"
cat /tmp/forged.json; echo
echo "status after forgery: $(curl -s http://127.0.0.1:8000/social-posts/$PID | $PY -c 'import json,sys;print(json.load(sys.stdin)["status"])')"

hdr "9. VALID WEBHOOK -> 200, STATUS BECOMES published"
SIG=$($PY -c "
import hmac,hashlib,os,sys
body=sys.argv[1].encode()
print('sha256='+hmac.new(os.environ['WEBHOOK_SECRET'].encode(),body,hashlib.sha256).hexdigest())
" "$BODY")
echo "computed signature: $SIG"
curl -s -o /tmp/valid.json -w 'HTTP %{http_code}\n' -X POST http://127.0.0.1:8000/webhook/social-delivery \
  -H 'Content-Type: application/json' -H "X-Signature: $SIG" -d "$BODY"
cat /tmp/valid.json; echo
curl -s "http://127.0.0.1:8000/social-posts/$PID" | $PY -m json.tool

hdr "10. DURABLE SCHEDULING"
curl -s -X POST "http://127.0.0.1:8000/campaigns/$CID/schedule" -H 'Content-Type: application/json' -d '{"delay_seconds":3600}' | $PY -m json.tool
echo "--- rows physically present in the scheduler sqlite jobstore ---"
$PY -c "
import sqlite3
c=sqlite3.connect('data/demo_sched.db')
for r in c.execute('SELECT id, next_run_time FROM apscheduler_jobs'):
    print(' ', r)
"

hdr "10b. CRASH RECOVERY: SCHEDULED JOB SURVIVES A FULL RESTART"
echo "--- killing the app process (simulated crash) ---"
kill $APP_PID 2>/dev/null; wait $APP_PID 2>/dev/null
echo "app stopped."
$PY -m uvicorn app.main:app --port 8000 --log-level warning >/tmp/app2.log 2>&1 &
APP_PID=$!
trap 'kill $MOCK_PID $APP_PID 2>/dev/null' EXIT
for i in $(seq 1 40); do curl -sf http://127.0.0.1:8000/health >/dev/null && break; sleep 0.5; done
echo "--- app restarted; jobs reloaded from the sqlite jobstore ---"
curl -s http://127.0.0.1:8000/scheduler/jobs | $PY -m json.tool

hdr "11. TOKEN ENCRYPTION AT REST"
$PY - <<'EOF'
from app.security.encryption import encrypt_token, decrypt_token
t = "SUPER-SECRET-PLATFORM-TOKEN-abcdef123456"
a = encrypt_token(t); b = encrypt_token(t)
print("plaintext            :", t)
print("iv #1 (hex)          :", a.iv.hex(), f"({len(a.iv)} bytes)")
print("iv #2 (hex)          :", b.iv.hex(), f"({len(b.iv)} bytes)")
print("ivs differ           :", a.iv != b.iv)
print("ciphertexts differ   :", a.ciphertext != b.ciphertext)
print("ciphertext #1 (hex)  :", a.ciphertext.hex())
print("plaintext in cipher  :", t.encode() in a.ciphertext)
print("decrypt roundtrip ok :", decrypt_token(a.ciphertext, a.iv) == t)
EOF
echo "--- grep the live application sqlite file for any bearer token ---"
$PY - <<'EOF'
import pathlib, re
raw = pathlib.Path("data/demo_app.db").read_bytes()
hits = re.findall(rb"access_token|Bearer [A-Za-z0-9_-]{20,}", raw)
print("token-like byte sequences found in data/demo_app.db:", len(hits))
EOF

hdr "12. APP LOG TAIL (tokens must be absent)"
tail -20 /tmp/app.log
echo "--- post-restart log ---"
tail -10 /tmp/app2.log

echo
echo "== demo complete =="
