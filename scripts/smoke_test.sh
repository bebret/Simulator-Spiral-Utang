#!/usr/bin/env bash
# Smoke test: rangkaian curl untuk membuktikan status code sesuai spesifikasi.
# Jalankan setelah stack hidup:
#   ./scripts/smoke_test.sh
#   BASE_URL=http://localhost:8010 ./scripts/smoke_test.sh   # port lain

set -u

BASE_URL="${BASE_URL:-http://localhost:8000}"
PASS=0
FAIL=0

check() {
  local expected="$1" label="$2" actual="$3"
  if [ "$actual" = "$expected" ]; then
    printf '  [OK]   %-42s %s\n' "$label" "$actual"
    PASS=$((PASS + 1))
  else
    printf '  [FAIL] %-42s %s (harusnya %s)\n' "$label" "$actual" "$expected"
    FAIL=$((FAIL + 1))
  fi
}

request() {
  local method="$1" path="$2" data="${3:-}"
  if [ -n "$data" ]; then
    curl -s -w '\n%{http_code}' -X "$method" "$BASE_URL$path" \
      -H 'Content-Type: application/json' -d "$data"
  else
    curl -s -w '\n%{http_code}' -X "$method" "$BASE_URL$path"
  fi
}

body_of() { printf '%s' "${1%$'\n'*}"; }
code_of() { printf '%s' "${1##*$'\n'}"; }

echo "Smoke test ke $BASE_URL"
echo

response=$(request GET /health)
check 200 "GET /health" "$(code_of "$response")"

response=$(request POST /players '{"nickname":"smoke_test"}')
check 201 "POST /players" "$(code_of "$response")"
PLAYER_ID=$(body_of "$response" | grep -o '"id":[0-9]*' | head -n1 | cut -d: -f2)

if [ -z "$PLAYER_ID" ]; then
  echo "Gagal mendapatkan player id, sisa uji dilewati."
  exit 1
fi

response=$(request GET "/players/$PLAYER_ID")
check 200 "GET /players/{id}" "$(code_of "$response")"

response=$(request POST "/players/$PLAYER_ID/loans" '{"amount":500000}')
check 201 "POST /players/{id}/loans (500.000)" "$(code_of "$response")"

response=$(request POST "/players/$PLAYER_ID/loans" '{"amount":123456}')
check 422 "POST /players/{id}/loans (nominal salah)" "$(code_of "$response")"

response=$(request POST "/players/$PLAYER_ID/bets" '{"amount":10000}')
check 201 "POST /players/{id}/bets (10.000)" "$(code_of "$response")"

response=$(request POST "/players/$PLAYER_ID/bets" '{"amount":999999999}')
check 400 "POST /players/{id}/bets (saldo kurang)" "$(code_of "$response")"

response=$(request POST "/players/$PLAYER_ID/advance-days" '{"days":5}')
check 201 "POST /players/{id}/advance-days (5 hari)" "$(code_of "$response")"

response=$(request POST "/players/$PLAYER_ID/advance-days" '{"days":0}')
check 422 "POST /players/{id}/advance-days (0 hari)" "$(code_of "$response")"

response=$(request POST "/players/$PLAYER_ID/repayments" '{"amount":50000}')
check 201 "POST /players/{id}/repayments (50.000)" "$(code_of "$response")"

response=$(request GET "/players/$PLAYER_ID/ledger")
check 200 "GET /players/{id}/ledger" "$(code_of "$response")"

response=$(request GET "/players/$PLAYER_ID/summary")
check 200 "GET /players/{id}/summary" "$(code_of "$response")"

response=$(request GET "/players/999999")
check 404 "GET /players/999999 (tidak ada)" "$(code_of "$response")"

response=$(request DELETE "/players/$PLAYER_ID")
check 204 "DELETE /players/{id} (reset)" "$(code_of "$response")"

response=$(request GET "/players/$PLAYER_ID")
check 404 "GET /players/{id} setelah reset" "$(code_of "$response")"

echo
echo "Hasil: $PASS lulus, $FAIL gagal"
[ "$FAIL" -eq 0 ]
