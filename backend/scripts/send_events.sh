#!/usr/bin/env bash
# Sends the three sample PR events to the running SAM API and prints each response.
API=${API:-http://127.0.0.1:3000}
cd "$(dirname "$0")/.."
send() {  # file, expected
  echo "=== $1  (expected: $2)"
  curl -s -X POST "$API/github-webhook" \
    -H "Content-Type: application/json" -H "X-GitHub-Event: pull_request" \
    -d @"events/$1"
  echo; echo
}
send ready.json          "Ready for review"
send needs_changes.json  "Needs changes"
send low_value.json      "Low-value or unclear"
echo "=== GET /prs"
curl -s "$API/prs"; echo
