# Windows PowerShell equivalent of create_table.sh (assumes LocalStack is running: docker compose up -d)
$env:AWS_ACCESS_KEY_ID = "test"; $env:AWS_SECRET_ACCESS_KEY = "test"; $env:AWS_DEFAULT_REGION = "us-east-1"
$endpoint = "http://localhost:4566"
aws --endpoint-url $endpoint dynamodb describe-table --table-name PRAnalysis 2>$null | Out-Null
if ($LASTEXITCODE -eq 0) { Write-Host "Table PRAnalysis already exists."; exit 0 }
aws --endpoint-url $endpoint dynamodb create-table `
  --table-name PRAnalysis `
  --attribute-definitions AttributeName=repoPrKey,AttributeType=S `
  --key-schema AttributeName=repoPrKey,KeyType=HASH `
  --billing-mode PAY_PER_REQUEST | Out-Null
Write-Host "Table PRAnalysis created."
