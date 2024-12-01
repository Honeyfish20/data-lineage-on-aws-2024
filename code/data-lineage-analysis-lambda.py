import json
import boto3
import os
import urllib.request
import urllib.error
from botocore.auth import SigV4Auth
from botocore.awsrequest import AWSRequest
from botocore.credentials import get_credentials
from botocore.session import Session
from concurrent.futures import ThreadPoolExecutor, as_completed

def read_s3_file(s3_client, bucket, key):
    try:
        response = s3_client.get_object(Bucket=bucket, Key=key)
        data = json.loads(response['Body'].read().decode('utf-8'))
        return data.get("lineage_map", {})
    except Exception as e:
        print(f"Error reading S3 file {bucket}/{key}: {str(e)}")
        raise

def merge_data(athena_data, redshift_data):
    return {**athena_data, **redshift_data}

def sign_request(request):
    credentials = get_credentials(Session())
    auth = SigV4Auth(credentials, 'neptune-db', os.environ['AWS_REGION'])
    auth.add_auth(request)
    return dict(request.headers)

def send_request(url, headers, data):
    req = urllib.request.Request(url, data=data.encode('utf-8'), headers=headers, method='POST')
    try:
        with urllib.request.urlopen(req) as response:
            return response.read().decode('utf-8')
    except urllib.error.HTTPError as e:
        print(f"HTTP Error: {e.code} - {e.reason}")
        print(e.read().decode('utf-8'))
        raise

def write_to_neptune(data):
    endpoint = 'https://your neptune endpoint name:8182/gremlin'
    # replace with your neptune endpoint name
    # Clear Neptune database
    clear_query = "g.V().drop()"
    request = AWSRequest(method='POST', url=endpoint, data=json.dumps({'gremlin': clear_query}))
    signed_headers = sign_request(request)
    response = send_request(endpoint, signed_headers, json.dumps({'gremlin': clear_query}))
    print(f"Clear database response: {response}")

    # Verify if the database is empty
    verify_query = "g.V().count()"
    request = AWSRequest(method='POST', url=endpoint, data=json.dumps({'gremlin': verify_query}))
    signed_headers = sign_request(request)
    response = send_request(endpoint, signed_headers, json.dumps({'gremlin': verify_query}))
    print(f"Vertex count after clearing: {response}")
    
    def process_node(node, children):
        # Add node
        query = f"g.V().has('lineage_node', 'node_name', '{node}').fold().coalesce(unfold(), addV('lineage_node').property('node_name', '{node}'))"
        request = AWSRequest(method='POST', url=endpoint, data=json.dumps({'gremlin': query}))
        signed_headers = sign_request(request)
        response = send_request(endpoint, signed_headers, json.dumps({'gremlin': query}))
        print(f"Add node response for {node}: {response}")

        for child_node in children:
            # Add child node
            query = f"g.V().has('lineage_node', 'node_name', '{child_node}').fold().coalesce(unfold(), addV('lineage_node').property('node_name', '{child_node}'))"
            request = AWSRequest(method='POST', url=endpoint, data=json.dumps({'gremlin': query}))
            signed_headers = sign_request(request)
            response = send_request(endpoint, signed_headers, json.dumps({'gremlin': query}))
            print(f"Add child node response for {child_node}: {response}")

            # Add edge
            query = f"g.V().has('lineage_node', 'node_name', '{node}').as('a').V().has('lineage_node', 'node_name', '{child_node}').coalesce(inE('lineage_edge').where(outV().as('a')), addE('lineage_edge').from('a').property('edge_name', ' '))"
            request = AWSRequest(method='POST', url=endpoint, data=json.dumps({'gremlin': query}))
            signed_headers = sign_request(request)
            response = send_request(endpoint, signed_headers, json.dumps({'gremlin': query}))
            print(f"Add edge response for {node} -> {child_node}: {response}")

    with ThreadPoolExecutor(max_workers=10) as executor:
        futures = [executor.submit(process_node, node, children) for node, children in data.items()]
        for future in as_completed(futures):
            try:
                future.result()
            except Exception as e:
                print(f"Error in processing node: {str(e)}")

def lambda_handler(event, context):
    # Initialize S3 client
    s3_client = boto3.client('s3')

    # S3 bucket and file paths
    bucket_name = 'data-lineage-analysis-24-09-22'
    athena_key = 'athena_dbt_lineage_map.json' # Replace with your athena lineage key value output json name
    redshift_key = 'redshift_dbt_lineage_map.json' # Replace with your redshift lineage key value output json name

    try:
        # Read Athena lineage data
        athena_data = read_s3_file(s3_client, bucket_name, athena_key)
        print(f"Athena data size: {len(athena_data)}")

        # Read Redshift lineage data
        redshift_data = read_s3_file(s3_client, bucket_name, redshift_key)
        print(f"Redshift data size: {len(redshift_data)}")

        # Merge data
        combined_data = merge_data(athena_data, redshift_data)
        print(f"Combined data size: {len(combined_data)}")

        # Write to Neptune (including clearing the database)
        write_to_neptune(combined_data)

        return {
            'statusCode': 200,
            'body': json.dumps('Data successfully written to Neptune')
        }
    except Exception as e:
        print(f"Error in lambda_handler: {str(e)}")
        return {
            'statusCode': 500,
            'body': json.dumps(f'Error: {str(e)}')
        }
