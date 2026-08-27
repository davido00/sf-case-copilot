/**
 * Tests for CaseCopilotService.
 *
 * Apex cannot make real callouts in a test, so HttpCalloutMock stands in for
 * the Python service. That is a limitation with a silver lining: it lets us
 * test the failure paths — 401, 500, malformed JSON — which are awkward to
 * reproduce against a service that mostly works.
 */
@IsTest
private class CaseCopilotServiceTest {
    /** Returns whatever status and body the test asks for. */
    private class MockResponder implements HttpCalloutMock {
        private Integer status;
        private String body;

        private MockResponder(Integer status, String body) {
            this.status = status;
            this.body = body;
        }

        public HttpResponse respond(HttpRequest request) {
            // Assert on the way past: the request shape is part of the contract.
            System.assert(
                request.getEndpoint().endsWith('/chat'),
                'Should call the /chat endpoint, got: ' + request.getEndpoint()
            );
            System.assertEquals('POST', request.getMethod(), 'Should POST');

            Map<String, Object> sent =
                (Map<String, Object>) JSON.deserializeUntyped(request.getBody());
            System.assert(sent.containsKey('case_id'), 'Payload needs case_id');
            System.assert(sent.containsKey('history'), 'Payload needs history');
            System.assert(sent.containsKey('message'), 'Payload needs message');

            HttpResponse response = new HttpResponse();
            response.setStatusCode(status);
            response.setBody(body);
            return response;
        }
    }

    private static Case makeCase() {
        Case record = new Case(Subject = 'Cannot log in', Description = 'Password reset did not help');
        insert record;
        return record;
    }

    @IsTest
    static void sendChatMessage_returnsReplyAndTools() {
        Case record = makeCase();
        String body = '{"reply":"Check Login History first.","tools_called":["search_knowledge_articles"]}';
        Test.setMock(HttpCalloutMock.class, new MockResponder(200, body));

        Test.startTest();
        CaseCopilotService.ChatReply result = CaseCopilotService.sendChatMessage(
            record.Id, '[]', 'What should I check?'
        );
        Test.stopTest();

        System.assertEquals('Check Login History first.', result.reply, 'Reply should come through');
        System.assertEquals(1, result.toolsCalled.size(), 'Should report the tool it used');
        System.assertEquals('search_knowledge_articles', result.toolsCalled[0]);
    }

    @IsTest
    static void sendChatMessage_handlesMissingToolsList() {
        Case record = makeCase();
        Test.setMock(HttpCalloutMock.class, new MockResponder(200, '{"reply":"Hello."}'));

        Test.startTest();
        CaseCopilotService.ChatReply result = CaseCopilotService.sendChatMessage(record.Id, null, 'Hi');
        Test.stopTest();

        System.assertEquals(0, result.toolsCalled.size(), 'Absent tools_called should become an empty list, not null');
    }

    @IsTest
    static void sendChatMessage_passesHistoryThrough() {
        Case record = makeCase();
        Test.setMock(HttpCalloutMock.class, new MockResponder(200, '{"reply":"ok","tools_called":[]}'));
        String history = '[{"role":"user","content":"hi"},{"role":"assistant","content":"hello"}]';

        Test.startTest();
        CaseCopilotService.sendChatMessage(record.Id, history, 'and now?');
        Test.stopTest();
        // The mock asserts the payload shape; reaching here means it held.
    }

    @IsTest
    static void sendChatMessage_rejectsBlankMessage() {
        Case record = makeCase();
        Boolean threw = false;

        Test.startTest();
        try {
            CaseCopilotService.sendChatMessage(record.Id, '[]', '   ');
        } catch (AuraHandledException e) {
            threw = true;
        }
        Test.stopTest();

        System.assert(threw, 'A blank message should be refused before any callout');
    }

    @IsTest
    static void sendChatMessage_surfacesUnauthorised() {
        Case record = makeCase();
        Test.setMock(HttpCalloutMock.class, new MockResponder(401, '{"detail":"Invalid or missing X-Copilot-Secret."}'));
        Boolean threw = false;

        Test.startTest();
        try {
            CaseCopilotService.sendChatMessage(record.Id, '[]', 'hello');
        } catch (AuraHandledException e) {
            threw = true;
        }
        Test.stopTest();

        System.assert(threw, '401 should raise, not return an empty reply');
    }

    @IsTest
    static void sendChatMessage_surfacesServerError() {
        Case record = makeCase();
        Test.setMock(HttpCalloutMock.class, new MockResponder(502, 'upstream exploded'));
        Boolean threw = false;

        Test.startTest();
        try {
            CaseCopilotService.sendChatMessage(record.Id, '[]', 'hello');
        } catch (AuraHandledException e) {
            threw = true;
        }
        Test.stopTest();

        System.assert(threw, 'Non-200 should raise');
    }

    @IsTest
    static void sendChatMessage_rejectsMalformedHistory() {
        Case record = makeCase();
        Test.setMock(HttpCalloutMock.class, new MockResponder(200, '{"reply":"ok"}'));
        Boolean threw = false;

        Test.startTest();
        try {
            CaseCopilotService.sendChatMessage(record.Id, 'not json at all', 'hello');
        } catch (AuraHandledException e) {
            threw = true;
        }
        Test.stopTest();

        System.assert(threw, 'Malformed history should be caught before the callout');
    }

    @IsTest
    static void saveResolutionToCase_writesTheField() {
        Case record = makeCase();

        Test.startTest();
        CaseCopilotService.saveResolutionToCase(record.Id, 'Here is the resolution.');
        Test.stopTest();

        Case reloaded = [SELECT AI_Draft_Resolution__c FROM Case WHERE Id = :record.Id LIMIT 1];
        System.assertEquals(
            'Here is the resolution.',
            reloaded.AI_Draft_Resolution__c,
            'The resolution should land on the Case'
        );
    }

    @IsTest
    static void saveResolutionToCase_rejectsEmptyText() {
        Case record = makeCase();
        Boolean threw = false;

        Test.startTest();
        try {
            CaseCopilotService.saveResolutionToCase(record.Id, '');
        } catch (AuraHandledException e) {
            threw = true;
        }
        Test.stopTest();

        System.assert(threw, 'Saving nothing should be refused');
    }

    @IsTest
    static void saveResolutionToCase_rejectsOversizedText() {
        Case record = makeCase();
        String tooLong = 'x'.repeat(32769);
        Boolean threw = false;

        Test.startTest();
        try {
            CaseCopilotService.saveResolutionToCase(record.Id, tooLong);
        } catch (AuraHandledException e) {
            threw = true;
        }
        Test.stopTest();

        System.assert(threw, 'Text longer than the field should be refused with a clear message, not a DML error');
    }
}
