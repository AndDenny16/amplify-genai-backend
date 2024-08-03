import psycopg2
from psycopg2.extras import Json
import json
import os
import boto3
import logging
import re
from botocore.exceptions import ClientError
from common.credentials import get_credentials
from shared_functions import num_tokens_from_text, generate_embeddings, generate_questions, record_usage, get_key_details, preprocess_text
import urllib
sqs = boto3.client('sqs')


logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')

pg_host = os.environ['RAG_POSTGRES_DB_WRITE_ENDPOINT']
pg_user = os.environ['RAG_POSTGRES_DB_USERNAME']
pg_database = os.environ['RAG_POSTGRES_DB_NAME']
rag_pg_password = os.environ['RAG_POSTGRES_DB_SECRET']
embedding_model_name = os.environ['EMBEDDING_MODEL_NAME']
qa_model_name = os.environ['QA_MODEL_NAME']
sender_email = os.environ['SENDER_EMAIL']
endpoints_arn = os.environ['LLM_ENDPOINTS_SECRETS_NAME_ARN']
embedding_progress_table = os.environ['EMBEDDING_PROGRESS_TABLE']
embedding_chunks_index_queue = os.environ['EMBEDDING_CHUNKS_INDEX_QUEUE'] 


pg_password = get_credentials(rag_pg_password)



def trim_src(src):
    # Split the keyname by '.json'
    parts = src.split('.json')
    # Rejoin the first part with '.json' if there are any parts after splitting
    trimmed_src = parts[0] + '.json' if len(parts) > 1 else src
    return trimmed_src

def extract_child_chunk_number_from_src(src):
    pattern = r'.json-(\d+)'
    match = re.search(pattern, src)
    if match:
        return str(match.group(1))  # Convert the matched item to string
    else:
        raise ValueError("Number not found in the key")


def update_child_chunk_status(object_id, child_chunk, new_status):
    try:
        progress_table = os.environ['EMBEDDING_PROGRESS_TABLE']
        print(f"Updating status of child chunk {child_chunk} for {object_id} to {new_status}")
        
        dynamodb = boto3.resource('dynamodb')
        table = dynamodb.Table(progress_table)
        
        # Update the status of the specific child chunk
        update_expression = 'SET #data.#childChunks.#chunkId.#status = :new_status'
        expression_attribute_names = {
            '#data': 'data',
            '#childChunks': 'childChunks',
            '#chunkId': str(child_chunk),
            '#status': 'status'
        }
        expression_attribute_values = {
            ':new_status': new_status
        }
        
        result = table.update_item(
            Key={'object_id': object_id},
            UpdateExpression=update_expression,
            ExpressionAttributeNames=expression_attribute_names,
            ExpressionAttributeValues=expression_attribute_values,
            ReturnValues='UPDATED_NEW'  # Optional: to return the updated values
        )
        
        print(f"Successfully updated child chunk status: {result}")
    
    except Exception as e:
        print("Failed to update the child chunk status in DynamoDB table.")
        print(e)



#initially set db_connection to none/closed 
db_connection = None


# Function to establish a database connection
def get_db_connection():
    global db_connection
    if db_connection is None or db_connection.closed:
        try:
            db_connection = psycopg2.connect(
                host=pg_host,
                database=pg_database,
                user=pg_user,
                password=pg_password,
                port=3306
            )
            logging.info("Database connection established.")
        except psycopg2.Error as e:
            logging.error(f"Failed to connect to the database: {e}")
            raise
    return db_connection


def insert_chunk_data_to_db(src, locations, orig_indexes, char_index, token_count, embedding_index, content, vector_embedding, qa_vector_embedding, cursor):
    insert_query = """
    INSERT INTO embeddings (src, locations, orig_indexes, char_index, token_count, embedding_index, content, vector_embedding, qa_vector_embedding)
    
    VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s);
    """
    try:
        cursor.execute(insert_query, (src, Json(locations), Json(orig_indexes), char_index, token_count, embedding_index, content, vector_embedding, qa_vector_embedding))
        logging.info(f"Data inserted into the database for content: {content[:30]}...")  # Log first 30 characters of content
    except psycopg2.Error as e:
        logging.error(f"Failed to insert data into the database: {e}")
        raise

db_connection = None
# AWS Lambda handler function
def lambda_handler(event, context):
    logging.basicConfig(level=logging.INFO)
    
    for record in event['Records']:
        # Extract bucket name and file key from the S3 event
        #bucket_name = event['Records'][0]['s3']['bucket']['name']
        #url_encoded_key = event['Records'][0]['s3']['object']['key']
        print(f"Processing message: {record}")
        # Assuming the message body is a JSON string, parse it
        s3_info = json.loads(record['body'])
        print(f"Message body: {s3_info}")
        s3_info = s3_info["s3"]

        # Get the bucket and object key from the event
        print(f"Getting text from {s3_info['object']['key']}")
        bucket_name = s3_info['bucket']['name']
        url_encoded_key = s3_info['object']['key']

        #Print the bucket name and key for debugging purposes
        print(f"url_key={url_encoded_key}")

        #url decode the key
        object_key = urllib.parse.unquote(url_encoded_key)
        childChunk = extract_child_chunk_number_from_src(object_key)

        #Print the bucket name and key for debugging purposes
        print(f"bucket = {bucket_name} and key = {object_key}")


        # Create an S3 client
        s3_client = boto3.client('s3')

        db_connection = None

        try:
            # Get the object from the S3 bucket
            response = s3_client.get_object(Bucket=bucket_name, Key=object_key)

            # Read the content of the object
            data = json.loads(response['Body'].read().decode('utf-8'))

            # Get or establish a database connection
            db_connection = get_db_connection()

            # Call the embed_chunks function with the JSON data
            success, src = embed_chunks(data, childChunk, embedding_progress_table, db_connection)

            # If the extraction process was successful, send a completion email
            if success:
                print(f"Embedding process completed successfully for {src}.")

                receipt_handle = record['receiptHandle']
                print(f"Deleting message {receipt_handle} from queue")
                
                # Delete received message from queue
                sqs.delete_message(
                    QueueUrl=embedding_chunks_index_queue,
                    ReceiptHandle=receipt_handle
                )
                print(f"Deleted message {record['messageId']} from queue")

            else:
                print(f"An error occurred during the embedding process for {src}.")

                db_connection.close()

            return {
                'statusCode': 200,
                'body': json.dumps('Embedding process completed successfully.')
            }
        except Exception as e:
            logging.exception(f"Error processing SQS message: {str(e)}")
            return {
                'statusCode': 500,
                'body': json.dumps('Error processing SQS message.')
            }
        finally:
            # Ensure the database connection is closed
            if db_connection is not None:
                db_connection.close()
            logging.info("Database connection closed.")    


def embed_chunks(data, childChunk, embedding_progress_table, db_connection):
    dynamodb = boto3.resource('dynamodb')
    table = dynamodb.Table(embedding_progress_table)

    src = None

    try:
        local_chunks = data.get('chunks', [])
        src = data.get('src', '')
        trimmed_src = trim_src(src)
        childChunk = (childChunk)


        try:
            response = table.get_item(Key={'object_id': trimmed_src})
            item = response.get('Item')
            if item and 'data' in item:
                total_chunks = item['data'].get('totalChunks')
                child_chunk_index = extract_child_chunk_number_from_src(childChunk)
                logging.info(f"Processing child chunk: {child_chunk_index} of total parent chunks: {total_chunks}")

                local_chunks_to_process = len(local_chunks)
                logging.info(f"There are {local_chunks_to_process} (max 10) within child chunk: {child_chunk_index}")
                
                
                # Check if the `terminated` field is set to False
                if not item['data'].get('terminated', True):
                    logging.info("The file embedding process has been terminated.")
                    return False, src
            else:
                logging.info("No item found in DynamoDB table.")

        except ClientError as e:
            logging.error("Failed to fetch item from DynamoDB table.")
            logging.error(e)


        print(f"Processing {childChunk} of {total_chunks} (fetched from DynamoDB)")
        current_local_chunk_index = 0


        with db_connection.cursor() as cursor:
            db_connection.commit()
            for local_chunk_index, chunk in enumerate(local_chunks[current_local_chunk_index:], start=current_local_chunk_index + 1):
                try:
                    content = chunk['content']
                    locations = chunk['locations']
                    orig_indexes = chunk['indexes']
                    char_index = chunk['char_index']

                    response_clean_text = preprocess_text(content)
                    if response_clean_text["success"]:
                        clean_text = response_clean_text["data"]
                    else:
                        error = response_clean_text["error"]
                        print(f"Error occurred: {error}")
                        raise Exception(error)


                    
                    # Generate embeddings
                    response_vector_embedding = generate_embeddings(clean_text)
                    if response_vector_embedding["success"]:
                        vector_embedding = response_vector_embedding["data"]
                    else:
                        error = response_vector_embedding["error"]
                        print(f"Error occurred: {error}")
                        
                    # Generate QA summary
                    response_qa_summary = generate_questions(clean_text)
                    if response_qa_summary["success"]:
                        qa_summary = response_qa_summary["data"]
                    else:
                        error = response_qa_summary["error"]
                        print(f"Error occurred: {error}")

                    # Create embeddings for QA summary    
                    response_qa_embedding = generate_embeddings(content=qa_summary)
                    if response_qa_embedding["success"]:
                        qa_vector_embedding = response_qa_embedding["data"]
                    else:
                        error = response_qa_embedding["error"]
                        print(f"Error occurred: {error}")    

                    qa_summary_input_tokens = num_tokens_from_text(clean_text, qa_model_name)
                    qa_summary_output_token_count = num_tokens_from_text(qa_summary, qa_model_name)
                    vector_token_count = num_tokens_from_text(clean_text, embedding_model_name)
                    qa_vector_token_count = num_tokens_from_text(qa_summary, embedding_model_name)

                    #This is written to the embeddings table but is not used for cost calucations
                    total_vector_token_count = vector_token_count + qa_vector_token_count
                    
                    
                    logging.info(f"Embedding local chunk index: {current_local_chunk_index}")
                    insert_chunk_data_to_db(src, locations, orig_indexes, char_index, total_vector_token_count, current_local_chunk_index, content, vector_embedding, qa_vector_embedding, cursor)
                    print(f"Getting Account information for {trimmed_src}")
                    result = get_key_details(trimmed_src)
                   

                    if result:
                        print("API Key:", result['apiKey'])
                        api_key = result['apiKey']
                        print("Account:", result['account'])
                        account = result['account']
                        print("User:", result['originalCreator'])
                        user = result['originalCreator']
                    else:
                        print("Item not found or error retrieving the item.")

                    # Record QA usage in DynamoDB
                    record_usage(account,src, user, qa_model_name, api_key=api_key,input_tokens=qa_summary_input_tokens, output_tokens=None)

                    record_usage(account,src, user, qa_model_name, api_key=api_key,input_tokens=None, output_tokens=qa_summary_output_token_count)

                    # Record embedding usage in DynamoDB
                    record_usage(account,src, user, embedding_model_name, api_key=api_key, output_tokens=total_vector_token_count, input_tokens=None)

                    current_local_chunk_index += 1
                    db_connection.commit()
                except Exception as e:
                    logging.error(f"An error occurred embedding chunk index: {local_chunk_index}")
                    logging.error(f"An error occurred during the embedding process: {e}")
                    update_child_chunk_status(trimmed_src, childChunk, "failed")
                    raise

        # After all chunks are processed, update the status to 'complete'

        update_child_chunk_status ( trimmed_src, childChunk, "completed")

        return True, src

    except Exception as e:
        logging.exception("An error occurred during the embed_chunks execution.")
        update_child_chunk_status(trimmed_src, childChunk, "failed")
        db_connection.rollback()
        return False, src