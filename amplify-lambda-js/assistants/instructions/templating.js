import Handlebars from "handlebars";
import yaml from "js-yaml";
import {formatOps, getOps} from "../ops/ops.js";

const extractTagAndFormat = (str) => {
    const regex = /\{\{\s*ops\s+([a-zA-Z0-9_./-]+)?(:[a-zA-Z0-9_./-]+)?\s*\}\}/;
    const match = str.match(regex);

    if (match) {                        // remove colon
        return { tag: match[1], format: match[2]?.slice(1) };
    } else {
        return { tag: null, format: null };
    }
}


export const fillInTemplate = async (llm, params, body, ds, templateStr, contextData) => {

    contextData = {
        ...contextData,
        user: params.account.user,
    }

    let result = templateStr;
    try {

        let includedOperations = contextData.operations || [];
        let hasTemplateForOps = false;

        let opsStr = "";
        const { tag, format } = extractTagAndFormat(templateStr);
        if(tag || templateStr.includes("__assistantOps")) {
            hasTemplateForOps = true;
            const ops = await getOps(params.account.accessToken, tag);

            includedOperations = [...includedOperations, ...ops];
        }

        if(includedOperations.length > 0) {
            llm.sendStateEventToStream({resolvedOps: includedOperations});

            opsStr = await formatOps(includedOperations, format);
            // console.log(opsStr)
            contextData["__assistantOps"] = includedOperations;

            if (!hasTemplateForOps) {
                templateStr = "{{ops __assistantOps}}\n\n" + templateStr;
            }
        }

        const dataSourcesInConversationAlready = (body) => {
            return body.messages.slice(0, -1)
                .map(m => m.data)
                .filter(d => d != null)
                .map(d => d.dataSources)
                .filter(d => d != null)
                .flat();
        }

        Handlebars.registerHelper('dataSources', function (tagandformat) {
            const all = [...dataSourcesInConversationAlready(body), ...ds];
            return yaml.dump(all);
        });

        Handlebars.registerHelper('dataSourcesInConversation', function (tagandformat) {
            const mds = dataSourcesInConversationAlready(body);
            return yaml.dump(mds);
        });

        Handlebars.registerHelper('dataSourcesInCurrentMessage', function (tagandformat) {

            return yaml.dump(ds);
        });

        Handlebars.registerHelper('ops', function (tagandformat) {
            return opsStr;
        });

        Handlebars.registerHelper('assistantName', function () {
            return contextData.assistant.name;
        });

        Handlebars.registerHelper('user', function () {
            return contextData.user;
        });

        Handlebars.registerHelper('datetime', function (fmt) {
            // Output a date string in the provided fmt
            return new Date().toISOString();
        });

        Handlebars.registerHelper('yaml', function (context) {
            return yaml.dump(context);
        });

        Handlebars.registerHelper('API_BASE_URL', function () {
            return process.env.API_BASE_URL;
        });

        const template = Handlebars.compile(templateStr);
        result = template(contextData);

    } catch (e) {
        console.error(e);
    }

    return result;
}

