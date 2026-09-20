"""DynamoDB access (LocalStack locally, real AWS if DYNAMODB_ENDPOINT is empty)."""
import os
from decimal import Decimal


def get_table():
    import boto3  # imported lazily so unit tests run without boto3

    kwargs = {"region_name": os.environ.get("AWS_REGION", "us-east-1")}
    endpoint = os.environ.get("DYNAMODB_ENDPOINT")
    if endpoint:
        kwargs.update(endpoint_url=endpoint, aws_access_key_id="test", aws_secret_access_key="test")
    return boto3.resource("dynamodb", **kwargs).Table(os.environ.get("TABLE_NAME", "PRAnalysis"))


def save_analysis(analysis):
    """Insert, or overwrite the existing item for the same repoPrKey."""
    get_table().put_item(Item=analysis)


def list_analyses():
    table = get_table()
    resp = table.scan()
    items = resp.get("Items", [])
    while "LastEvaluatedKey" in resp:
        resp = table.scan(ExclusiveStartKey=resp["LastEvaluatedKey"])
        items.extend(resp.get("Items", []))
    items.sort(key=lambda i: i.get("updated_at", ""), reverse=True)
    return items


def json_default(o):
    """json.dumps hook: DynamoDB returns numbers as Decimal (and sets) - make them JSON-safe."""
    if isinstance(o, Decimal):
        return int(o) if o == o.to_integral_value() else float(o)
    if isinstance(o, (set, frozenset)):
        return sorted(o)
    raise TypeError(f"Not serializable: {type(o)}")
