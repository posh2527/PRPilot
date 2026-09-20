#!/usr/bin/env bash
# Starts LocalStack if it isn't running, then creates the PRAnalysis table (safe to re-run).
set -u
ENDPOINT=${DYNAMODB_ENDPOINT_HOST:-http://localhost:4566}
export AWS_ACCESS_KEY_ID=test AWS_SECRET_ACCESS_KEY=test AWS_DEFAULT_REGION=us-east-1
cd "$(dirname "$0")/.."

if ! curl -s -o /dev/null "$ENDPOINT/_localstack/health"; then
  echo "LocalStack not reachable - starting it with docker compose..."
  docker compose up -d || { echo "Could not start LocalStack"; exit 1; }
  for i in $(seq 1 30); do
    curl -s -o /dev/null "$ENDPOINT/_localstack/health" && break
    sleep 2
  done
fi

if aws --endpoint-url "$ENDPOINT" dynamodb describe-table --table-name PRAnalysis >/dev/null 2>&1; then
  echo "Table PRAnalysis already exists - nothing to do."
  exit 0
fi

aws --endpoint-url "$ENDPOINT" dynamodb create-table \
  --table-name PRAnalysis \
  --attribute-definitions AttributeName=repoPrKey,AttributeType=S \
  --key-schema AttributeName=repoPrKey,KeyType=HASH \
  --billing-mode PAY_PER_REQUEST >/dev/null && echo "Table PRAnalysis created."
