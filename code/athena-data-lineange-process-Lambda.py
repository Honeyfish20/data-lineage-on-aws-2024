import json
import boto3
import os

def lambda_handler(event, context):
    # Set up S3 client
    s3 = boto3.client('s3')

    # Get input and output paths from environment variables
    input_bucket = os.environ['INPUT_BUCKET']
    input_key = os.environ['INPUT_KEY']
    output_bucket = os.environ['OUTPUT_BUCKET']
    output_key = os.environ['OUTPUT_KEY']

    # Define helper function
    def dbt_nodename_format(node_name):
        return node_name.split(".")[-1]

    # Read input JSON file from S3
    response = s3.get_object(Bucket=input_bucket, Key=input_key)
    file_content = response['Body'].read().decode('utf-8')
    data = json.loads(file_content)
    lineage_map = data["child_map"]
    node_dict = {}
    dbt_lineage_map = {}

    # Process data
    for item in lineage_map:
        lineage_map[item] = [dbt_nodename_format(child) for child in lineage_map[item]]
        node_dict[item] = dbt_nodename_format(item)

    # Update key names
    lineage_map = {node_dict[old]: value for old, value in lineage_map.items()}
    dbt_lineage_map["lineage_map"] = lineage_map

    # Convert result to JSON string
    result_json = json.dumps(dbt_lineage_map)

    # Write JSON string to S3
    s3.put_object(Body=result_json, Bucket=output_bucket, Key=output_key)
    print(f"Data written to s3://{output_bucket}/{output_key}")

    return {
        'statusCode': 200,
        'body': json.dumps('Athena data lineage processing completed successfully')
    }
