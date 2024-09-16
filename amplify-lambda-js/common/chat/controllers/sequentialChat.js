import {countChatTokens} from "../../../azure/tokens.js";
import {StreamMultiplexer} from "../../multiplexer.js";
import {sendSourceMetadata} from "./meta.js";
import { PassThrough, Writable } from 'stream';
import {newStatus} from "../../status.js";
import {isKilled} from "../../../requests/requestState.js";
import {getLogger} from "../../logging.js";
import {sendStatusEventToStream} from "../../streams.js";
import {getUser} from "../../params.js";
import {addContextMessage, createContextMessage} from "./common.js";
import { DynamoDBClient } from "@aws-sdk/client-dynamodb";
import { DynamoDBDocumentClient, PutCommand } from "@aws-sdk/lib-dynamodb";

const logger = getLogger("sequentialChat");

const dynamodbClient = new DynamoDBClient({ region: "us-east-1" });
const docClient = DynamoDBDocumentClient.from(dynamodbClient);

async function writeToGroupAssistantConversations(conversationId, assistantId, assistantName, modelUsed, numberPrompts, user, employeeType, entryPoint, s3Location) {
    const params = {
        TableName: process.env.GROUP_ASSISTANT_CONVERSATIONS_DYNAMO_TABLE,
        Item: {
            conversationId: conversationId,
            assistantId: assistantId,
            assistantName: assistantName,
            modelUsed: modelUsed,
            numberPrompts: numberPrompts,
            user: user,
            employeeType: employeeType,
            entryPoint: entryPoint,
            s3Location: s3Location,
            timestamp: new Date().toISOString()
        }
    };

    try {
        await docClient.send(new PutCommand(params));
        logger.info(`Successfully wrote conversation data to DynamoDB for conversationId: ${conversationId}`);
    } catch (error) {
        logger.error(`Error writing to DynamoDB: ${error}`);
    }
}

export const handleChat = async ({account, chatFn, chatRequest, contexts, metaData, responseStream, eventTransformer, tokenReporting}) => {

    // The multiplexer is used to multiplex the streaming responses from the LLM provider
    // back to the client. This is necessary because we are going to run multiple requests (potentially)
    // to generate a single response. We want the client to see one continuous stream and not have to
    // deal with the fact that the response is coming from multiple sources. It is also possible for
    // the multiplexer to handle responses from multiple parallel requests and fuse them into a single
    // stream for the client.
    const multiplexer = new StreamMultiplexer(responseStream);

    const user = account.user;
    const requestId = chatRequest.options.requestId;

    sendSourceMetadata(multiplexer, metaData);

    const status = newStatus(
        {
            inProgress: true,
            message: "",
            icon: "bolt",
            sticky: false
        });

    if(contexts.length > 1) {
        sendStatusEventToStream(
            responseStream,
            newStatus(
                {
                    inProgress: false,
                    message: `I will need to send ${contexts.length} prompts for this request`,
                    icon: "bolt",
                    sticky: true
                }));
    }

    for (const [index, context] of contexts.entries()) {


        if((await isKilled(user, responseStream, chatRequest))){
            return;
        }

        let messages = [...chatRequest.messages];

        logger.debug("Building message with context.");

        // Add the context as the next to last message in the
        // message list. This will provide the context for the user's
        // prompt.
        messages = addContextMessage(messages, context, chatRequest.options.model.id);

        const requestWithData = {
            ...chatRequest,
            messages: messages
        }

        const tokenCount = countChatTokens(messages);

        await tokenReporting(
            context.id, tokenCount
        )

        if(contexts.length > 1) {
            status.message = `Sending prompt ${index + 1} of ${contexts.length}`;
            status.dataSource = context.id;
            sendStatusEventToStream(
                responseStream,
                status);
        }

        logger.debug("Creating stream wrapper");
        const streamReceiver = new PassThrough();
        multiplexer.addSource(streamReceiver, context.id, eventTransformer);

        logger.debug("Calling chat function");
        await chatFn(requestWithData, streamReceiver);
        logger.debug("Chat function returned");

        await multiplexer.waitForAllSourcesToEnd();

        logger.debug("Chat function streaming finished");
    }

    if(contexts.length > 1) {
        status.message = `Completed ${contexts.length} of ${contexts.length} prompts`;
        status.inProgress = false;
        sendStatusEventToStream(
            responseStream,
            status);
    }

    if (chatRequest.options.assistantId) {
        // assistantId beginning with 'astgp' means this is a group assistant
        if (chatRequest.options.assistantId.startsWith('astgp')) {
            console.log("MADE IT");
            
            // write data to DynamoDB table
            const conversationId = chatRequest.options.conversationId;
            const assistantId = chatRequest.options.assistantId;
            const assistantName = chatRequest.options.assistantName;
            const modelUsed = chatRequest.options.model.name; // TODO: switch this to the ID
            const numberPrompts = chatRequest.options.numPrompts;
            const employeeType = chatRequest.options.groupType;
            // TODO: update entry point when wordpress is live and s3 location when filename is proper
            const entryPoint = "Amplify"; // chatRequest.options.source
            const s3Location = "vu-amplify-dev-chat-traces/traces/email/yyyy-mm-dd/uuid.json";
            // TODO: perform category and successful answer analysis

            await writeToGroupAssistantConversations(conversationId, assistantId, assistantName, modelUsed, numberPrompts, user, employeeType, entryPoint, s3Location);
        }
    }
}