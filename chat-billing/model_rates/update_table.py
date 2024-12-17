# to run this function and update the model rates table:
# 1. update the chat-billing/model_rates/model_rate_values.csv file,
# 2. deploy this lambda, 
# 3. run: ~ serverless invoke --function updateModelRateTable --stage dev --log

import os
import csv
import json
import boto3
from botocore.exceptions import ClientError
from decimal import Decimal

# Initialize a DynamoDB client with Boto3
dynamodb = boto3.resource("dynamodb")

def updateModelRateTable(event, context):
    result = load_model_rate_table()
    if result:
        return {
            "statusCode": 200,
            "body": json.dumps("Model rate table updated successfully."),
        }
    else:
        return {
            "statusCode": 500,
            "body": json.dumps("Error updating model rate table."),
        }
    

def load_model_rate_table():
    # Retrieve the environment variable for the table name
    table_name = os.environ["MODEL_RATE_TABLE"]

    # Access the DynamoDB table
    table = dynamodb.Table(table_name)

    # Define the correct path to the CSV file
    dir_path = os.path.dirname(os.path.realpath(__file__))
    csv_file_path = os.path.join(dir_path, "model_rate_values.csv")

    # Open the CSV file and read rows
    with open(csv_file_path, newline="") as csvfile:
        reader = csv.DictReader(csvfile)
        for row in reader:
            try:
                # Convert to Decimal instead of float
                input_cost = Decimal(row["InputCostPerThousandTokens"])
                output_cost = (
                    Decimal(row["OutputCostPerThousandTokens"])
                    if row["OutputCostPerThousandTokens"]
                    else None
                )

                # Each row in the CSV file corresponds to an item in the table
                item = {
                    "ModelID": row["ModelID"],
                    "ModelName": row["ModelName"],
                    "InputCostPerThousandTokens": input_cost,
                    "Provider": row["Provider"],
                }

                # Only add OutputCostPerThousandTokens if it's present
                if output_cost is not None:
                    item["OutputCostPerThousandTokens"] = output_cost

                response = table.put_item(Item=item)
            except ClientError as e:
                print(e.response["Error"]["Message"])
                return False

    # Return a success response after updating the table with all entries
    return True
