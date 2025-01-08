from common.validate import validated
from common.ops import op
from . import assistant_api as assistants
import random
import string
import re

@op(
    path="/assistant/chat/codeinterpreter",
    name="chatWithCodeInterpreter",
    method="POST",
    tags=["apiDocumentation"],
    description="""Initiate a conversation with the Code Interpreter. Each request can append new messages to the existing conversation using a unique thread ID.
    Data source keys for files can be found by calling files/query
    Example request:
    {   
      "data": {
          "assistantId": "yourEmail@vanderbilt.edu/ast/43985037429849290398",
          "threadId": "yourEmail@vanderbilt.edu/thr/442309eb-0772-42d0-b6ef-34e20ee2355e".
          "messages": [
              { "role": "user",
                "content" : "Can you tell me something about the data analytics and what you are able to do?",
                "dataSourceIds" : ["yourEmail@vanderbilt.edu/2024-05-08/0f20f0447b.json"]
              }
          ]
      }
  }

    Example response:
    {
      "success": true,
      "message": "Chat completed successfully",
      "data": {
        "threadId": "yourEmail@vanderbilt.edu/thr/442309eb-0772-42d0-b6ef-34e20ee2355e",
        "role": "assistant",
        "textContent": "I've saved the generated pie chart as a PNG file. You can download it using the link below:\n\n[Download Ice Cream Preferences Pie Chart](sandbox:/mnt/data/ice_cream_preferences_pie_chart.png)\n",
        "content": [
          {
            "type": "image/png",
            "values": {
              "file_key": "yourEmail@vanderbilt.edu/msg_P0lpFUEY _pie_chart.png ",
              "presigned_url": "https://vu-amplify-assistants-dev-code-interpreter-files.s3.amazonaws.com/...",
              "file_size": 149878
            }
          }
        ]
      }
    }

    """,
    params={
        "assistantId": "String. Required. Unique identifier of the Code Interpreter assistant. Example: 'yourEmail@vanderbilt.edu/ast/43985037429849290398'.",
        "threadId": "String. Optional. For the assistant to have history and memory of a conversation, a user must include the threadId. If no thread id is provided then a new one will be created and will be provided for future use in the response body." ,
        "messages": "Array of objects. Required. New conversation messages. Each object includes 'role' (user/system/assistant), 'content' as a string, and 'dataSourceIds' a list of strings. These messages should only include the new messages if providing a threadId since the thread already has knowledge of previous messages",
    }
)
@validated(op="chat") 
def chat_with_code_interpreter(event, context, current_user, name, data):
  access = data['allowed_access']
  if ('assistants' not in access and 'full_access' not in access):
      return {'success': False, 'message': 'API key does not have access to assistant functionality'}
  
  print("Chat_with_code_interpreter validated")
  assistant_id = data['data']['assistantId']
  messages = data['data']['messages']
  
  api_accessed =  data['api_accessed']
  account_id = data['account'] if api_accessed else data['data']['accountId']
  request_id = generate_req_id() if api_accessed else data['data']['requestId']
  thread_id = data['data'].get('threadId', None)

  return assistants.chat_with_code_interpreter(
    current_user,
    assistant_id,
    thread_id,
    messages,
    account_id,
    request_id,
    api_accessed
  )

def generate_req_id():
   return ''.join(random.choices(string.ascii_lowercase + string.digits, k=7)) 

@op(
    path="/assistant/create/codeinterpreter",
    name="createCodeInterpreterAssistant",
    method="POST",
    tags=["apiDocumentation"],
    description="""Create a new Code Interpreter assistant with specific attributes for analyzing and processing data.
    Example request:
    {
        "data": {
            "name": "Data Analysis Assistant",
            "description": "An AI assistant specialized in data analysis and visualization.",
            "tags": ["data analysis"],
            "instructions": "Analyze data files, perform statistical operations, and create visualizations as requested by the user.",
            "dataSources": ["yourEmail@vanderbilt.edu/2024-05-08/0f20f0447b.json"]
        }
    }

    Example response:
    {
        "success": true,
        "message": "Assistant created successfully.",
        "data": {
            "assistantId": "yourEmail@vanderbilt.edu/ast/373849029843"
        }
    }
    """,
    params={
        "name": "String. Required. Name of the Code Interpreter assistant. Example: 'Data Analysis Assistant'.",
        "description": "String. Required. Description of the assistant's functionality. Example: 'An AI assistant specialized in data analysis and visualization.'.",
        "tags": "Array of strings. Required. Tags to categorize the assistant. Example: ['data analysis', 'visualization'].",
        "instructions": "String. Required. Instructions for how the assistant should handle user queries. Example: 'Analyze data files and generate insights.'.",
        "dataSources": "Array of strings. Required. List of data source IDs the assistant will use. Starts with your email. These can be retrieved by calling the /files/query endpoint."
    }
)
@validated(op="create")
def create_code_interpreter_assistant (event, context, current_user, name, data):
  extracted_data = data['data']
  assistant_name = extracted_data['name']
  description = extracted_data['description']
  tags = extracted_data.get('tags', [])
  instructions = extracted_data['instructions']
  file_keys = extracted_data.get('dataSources', [])

  # Assuming get_openai_client and file_keys_to_file_ids functions are defined elsewhere
  return assistants.create_new_assistant(
    user_id=current_user,
    assistant_name=assistant_name,
    description=description,
    instructions=instructions,
    tags=tags,
    file_keys=file_keys,
  )

@op(
    path="/assistant/openai/delete",
    name="deleteCodeInterpreterAssistant",
    method="DELETE",
    tags=["apiDocumentation"],
    description="""Delete a Code Interpreter assistant instance, permanently removing it from the platform.

    Example request (via query parameter):
    DELETE /assistant/openai/delete?assistantId=yourEmail@vanderbilt.edu/ast/38940562397049823

    """,
    params={
        "assistantId": "String. Required. Unique identifier of the assistant to delete. Example: 'yourEmail@vanderbilt.edu/ast/38940562397049823'."
    }
)

@validated(op="delete")
def delete_assistant(event, context, current_user, name, data):
  query_params = event.get('queryStringParameters', {})
  print("Query params: ", query_params)
  assistant_id = query_params.get('assistantId', '')
  if (not assistant_id or not is_valid_query_param_id(assistant_id, current_user, 'ast')):
      return {
              'success': False,
              'message': 'Invalid or missing assistant id parameter'
              }
  print(f"Deleting assistant: {assistant_id}")
  return assistants.delete_assistant_by_id(assistant_id, current_user)


@op(
    path="/assistant/openai/thread/delete",
    name="deleteCodeInterpreterThread",
    method="DELETE",
    tags=["apiDocumentation"],
    description="""Delete a specific Code Interpreter conversation thread, removing all associated messages.

    Example request (via query parameter):
    DELETE /assistant/openai/thread/delete?threadId=yourEmail@vanderbilt.edu/thr/8923047385920349782093

    """,
    params={
        "threadId": "String. Required. Unique identifier of the thread to delete. Example: 'yourEmail@vanderbilt.edu/thr/8923047385920349782093'."
    }
)
@validated(op="delete")
def delete_assistant_thread(event, context, current_user, name, data):
  query_params = event.get('queryStringParameters', {})
  print("Query params: ", query_params)
  thread_id = query_params.get('threadId', '')
  if (not thread_id or not is_valid_query_param_id(thread_id, current_user, 'thr')):
      return {
              'success': False,
              'message': 'Invalid or missing thread id parameter'
              }
  # Assuming get_openai_client is defined elsewhere and provides an instance of the OpenAI client
  return assistants.delete_thread_by_id(thread_id, current_user)



@op(
    path="/assistant/files/download/codeinterpreter",
    name="downloadCodeInterpreterFiles",
    method="POST",
    tags=["apiDocumentation"],
    description="""Download files generated by the Code Interpreter assistant via pre-signed URLs.

    Example request:
    {
        "data": {
            "key": "yourEmail@vanderbilt.edu/msg_P0lpFUEY_pie_chart.png"
        }
    }

    Example response:
    {
        "success": true,
        "downloadUrl": "<Download URL>"
    }
    """,
    params={
        "key": "String. Required. Unique key identifying the file to download. Example: 'yourEmail@vanderbilt.edu/msg_P0lpFUEY_pie_chart.png'. These may be generated in the /assistant/chat/codeinterpreter endpoint responses.",
        "fileName": "String. Optional. If specified, directly downloads the file with this name."
    }
)

@validated(op="download")                      
def get_presigned_url_code_interpreter(event, context, current_user, name, data):
  data = data['data']
  key = data['key']
  file_name = data.get('fileName', None)

  return assistants.get_presigned_download_url(key, current_user, file_name)


def is_valid_query_param_id(id, current_user, prefix):
  pattern = f'^{re.escape(current_user)}/{re.escape(prefix)}/[0-9a-fA-F-]{{36}}$'
  if re.match(pattern, id):
      return True
  return False
   