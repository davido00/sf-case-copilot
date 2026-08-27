/**
 * Bridge between the Case Copilot LWC and the Python agent service.
 *
 * Two jobs, deliberately separated:
 *   sendChatMessage      - conversation. Calls out, returns the agent's reply.
 *   saveResolutionToCase - commitment. Writes the chosen text to the Case.
 *
 * The agent has NO write access to Salesforce. It proposes; a person decides;
 * Apex writes. That means a bad draft can never reach a record on its own.
 */
public with sharing class CaseCopilotService {
    /**
     * Internal failures use this, NOT AuraHandledException.
     *
     * AuraHandledException.setMessage() is only legal in a VisualForce/Aura
     * context -- calling it from Execute Anonymous throws LimitException and
     * hides the real problem, which is exactly what happened the first time we
     * tested the callout. So the logic throws CopilotException with a readable
     * message, and only the thin @AuraEnabled wrappers convert it for the LWC.
     */
    public class CopilotException extends Exception {}

    /** Named Credential. The service URL and the shared secret live in Setup,
     *  never in this file — that is the whole point of the feature. */
    private static final String ENDPOINT = 'callout:Case_Copilot';

    /**
     * Per-attempt timeout, deliberately NOT the 120s Apex maximum.
     *
     * Apex allows 120 seconds of callout time per TRANSACTION, not per call.
     * Two attempts at 55s fit inside that; one attempt at 120s leaves no room
     * to retry. Since the agent normally answers in 8-25s, two shorter attempts
     * cover more failure modes than one long one.
     */
    private static final Integer TIMEOUT_MS = 55000;

    /** Long Text Area limit on AI_Draft_Resolution__c. */
    private static final Integer MAX_RESOLUTION_CHARS = 32768;

    /** What the LWC receives back. */
    public class ChatReply {
        @AuraEnabled
        public String reply;
        @AuraEnabled
        public List<String> toolsCalled;
    }

    /** Mirrors the service's JSON exactly, snake_case and all, so
     *  JSON.deserialize can map it without custom parsing. */
    private class ServiceResponse {
        public String reply;
        public List<String> tools_called;
    }

    /**
     * Send one turn of the conversation and return the agent's reply.
     *
     * @param caseId       the Case being discussed; the service loads its
     *                     details server-side, so we send only the Id
     * @param historyJson  the conversation so far as a JSON array of
     *                     {role, content}, oldest first, EXCLUDING this message
     * @param message      what the user just typed
     */
    /** LWC entry point. Converts internal errors into something Aura can show. */
    @AuraEnabled
    public static ChatReply sendChatMessage(String caseId, String historyJson, String message) {
        try {
            return chat(caseId, historyJson, message);
        } catch (CopilotException e) {
            throw toAura(e.getMessage());
        }
    }

    /**
     * The real work. Public and throwing CopilotException so it can be driven
     * from Execute Anonymous and from tests with the error text intact.
     */
    public static ChatReply chat(String caseId, String historyJson, String message) {
        if (String.isBlank(message)) {
            throw new CopilotException('Type a message before sending.');
        }
        if (String.isBlank(caseId)) {
            throw new CopilotException('No Case was supplied.');
        }

        Map<String, Object> payload = new Map<String, Object>{
            'case_id' => caseId,
            'message' => message,
            'history' => parseHistory(historyJson)
        };

        HttpRequest request = new HttpRequest();
        request.setEndpoint(ENDPOINT + '/chat');
        request.setMethod('POST');
        request.setHeader('Content-Type', 'application/json');
        request.setTimeout(TIMEOUT_MS);
        request.setBody(JSON.serialize(payload));

        HttpResponse response = sendWithRetry(request);
        Integer status = response.getStatusCode();

        if (status == 401) {
            throw new CopilotException(
                'The copilot service rejected our credentials. The X-Copilot-Secret ' +
                'custom header on the External Credential principal does not match ' +
                'the service\'s COPILOT_SHARED_SECRET.'
            );
        }
        if (status == 404) {
            throw new CopilotException('The copilot service does not recognise this Case. ' + snippet(response.getBody()));
        }
        if (status != 200) {
            throw new CopilotException('Copilot service returned HTTP ' + status + '. ' + snippet(response.getBody()));
        }

        ServiceResponse parsed;
        try {
            parsed = (ServiceResponse) JSON.deserialize(response.getBody(), ServiceResponse.class);
        } catch (Exception e) {
            throw new CopilotException('Could not read the copilot service response. ' + snippet(response.getBody()));
        }

        ChatReply result = new ChatReply();
        result.reply = parsed.reply;
        result.toolsCalled = parsed.tools_called == null ? new List<String>() : parsed.tools_called;
        return result;
    }

    /**
     * Commit a resolution to the Case. This is the only write in the flow, and
     * it happens because a person clicked Save — never because the agent
     * decided to.
     */
    /** LWC entry point for the Save to Case button. */
    @AuraEnabled
    public static void saveResolutionToCase(String caseId, String resolutionText) {
        try {
            saveResolution(caseId, resolutionText);
        } catch (CopilotException e) {
            throw toAura(e.getMessage());
        }
    }

    /** The real work, callable from anonymous Apex and tests. */
    public static void saveResolution(String caseId, String resolutionText) {
        if (String.isBlank(caseId)) {
            throw new CopilotException('No Case was supplied.');
        }
        if (String.isBlank(resolutionText)) {
            throw new CopilotException('There is nothing to save yet.');
        }
        if (resolutionText.length() > MAX_RESOLUTION_CHARS) {
            throw new CopilotException(
                'That resolution is ' + resolutionText.length() + ' characters; the field holds ' +
                MAX_RESOLUTION_CHARS + '. Ask the copilot to shorten it.'
            );
        }

        // Field-level security is not enforced by DML, only by the UI, so check
        // it explicitly. Without this, a user without access to the field would
        // still update it through this method.
        if (!Schema.SObjectType.Case.fields.AI_Draft_Resolution__c.isUpdateable()) {
            throw new CopilotException('You do not have permission to update AI Draft Resolution on Case.');
        }

        Case record = new Case(Id = caseId, AI_Draft_Resolution__c = resolutionText);

        try {
            update record;
        } catch (DmlException e) {
            throw new CopilotException('Salesforce would not save that: ' + e.getDmlMessage(0));
        }
    }

    // -----------------------------------------------------------------------

    /**
     * Send the request, retrying once on a gateway-level failure.
     *
     * The service is on a free tier that sleeps after ~15 minutes idle. A
     * waking instance can answer 502/503/504 rather than simply being slow, so
     * the first message after a quiet period fails for a reason that has
     * nothing to do with the request. Retrying costs one extra attempt and
     * turns that into a slow success.
     *
     * Only gateway errors are retried. A 401 or a 404 will fail identically the
     * second time, and retrying a 500 the agent itself raised just doubles the
     * bill.
     */
    private static HttpResponse sendWithRetry(HttpRequest request) {
        for (Integer attempt = 1; attempt <= 2; attempt++) {
            try {
                HttpResponse response = new Http().send(request);
                Integer status = response.getStatusCode();

                Boolean wakingUp = status == 502 || status == 503 || status == 504;
                if (wakingUp && attempt == 1) {
                    continue;
                }
                return response;
            } catch (CalloutException e) {
                if (attempt == 2) {
                    // Usually a missing Named Credential, a wrong URL, or the
                    // service genuinely being down. Name the suspects, because
                    // the raw message rarely does.
                    throw new CopilotException(
                        'Could not reach the copilot service after two attempts. Check the ' +
                        'Case_Copilot Named Credential URL and that the service is running. (' +
                        e.getMessage() + ')'
                    );
                }
            }
        }
        // Unreachable: the loop either returns or throws.
        throw new CopilotException('Could not reach the copilot service.');
    }

    /** Turn the LWC's history JSON into something we can put in the payload. */
    private static List<Object> parseHistory(String historyJson) {
        if (String.isBlank(historyJson)) {
            return new List<Object>();
        }
        try {
            return (List<Object>) JSON.deserializeUntyped(historyJson);
        } catch (Exception e) {
            throw new CopilotException('The conversation history was malformed and could not be sent.');
        }
    }

    /**
     * Convert an internal failure into something the LWC can display.
     *
     * AuraHandledException otherwise surfaces "Script-thrown exception" instead
     * of the real text; setMessage() fixes that, but is only legal in an
     * Aura/VF context -- hence the guard, so this class stays runnable from
     * Execute Anonymous and from tests.
     */
    private static AuraHandledException toAura(String message) {
        AuraHandledException e = new AuraHandledException(message);
        try {
            e.setMessage(message);
        } catch (Exception notInAuraContext) {
            // Fine. The constructor message still reaches the client.
        }
        return e;
    }

    /** Keep error bodies short enough to show in a toast. */
    private static String snippet(String body) {
        if (String.isBlank(body)) {
            return '';
        }
        return body.length() > 300 ? body.substring(0, 300) + '…' : body;
    }
}
