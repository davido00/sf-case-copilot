import { LightningElement, api, track } from 'lwc';
import { ShowToastEvent } from 'lightning/platformShowToastEvent';
import { RefreshEvent } from 'lightning/refresh';

import sendChatMessage from '@salesforce/apex/CaseCopilotService.sendChatMessage';
import saveResolutionToCase from '@salesforce/apex/CaseCopilotService.saveResolutionToCase';

/**
 * Chat panel for the Case record page.
 *
 * The conversation lives HERE, in this component's state, and the whole thing
 * is sent to the service on every turn. The service keeps nothing between
 * requests, which is what lets it restart or sleep on a free tier without
 * dropping anyone mid-conversation. `service/try_chat.py` does exactly the same
 * thing in Python -- this is that client, in JavaScript.
 */
export default class CaseCopilot extends LightningElement {
    /** Supplied by the record page. The service loads the Case itself. */
    @api recordId;

    /** Rendered messages. Carries display-only fields the template needs,
     *  because LWC templates cannot evaluate expressions. */
    @track messages = [];

    draft = '';
    isThinking = false;
    errorMessage = '';
    savingId = null;

    /** What actually goes to the service: {role, content} only. */
    history = [];

    nextId = 0;

    get isSendDisabled() {
        return this.isThinking || !this.draft || !this.draft.trim();
    }

    get hasMessages() {
        return this.messages.length > 0;
    }

    get hasError() {
        return !!this.errorMessage;
    }

    handleInput(event) {
        this.draft = event.target.value;
    }

    /** Enter sends; Shift+Enter makes a new line. */
    handleKeyDown(event) {
        if (event.key === 'Enter' && !event.shiftKey) {
            event.preventDefault();
            this.handleSend();
        }
    }

    async handleSend() {
        const text = (this.draft || '').trim();
        if (!text || this.isThinking) {
            return;
        }

        this.errorMessage = '';
        this.addMessage('user', text);
        this.draft = '';
        this.isThinking = true;

        try {
            const result = await sendChatMessage({
                caseId: this.recordId,
                // Send the history as it was BEFORE this message -- the service
                // adds the new message itself.
                historyJson: JSON.stringify(this.history.slice(0, -1)),
                message: text
            });

            this.addMessage('assistant', result.reply, result.toolsCalled);
        } catch (error) {
            // Apex threw. reduceError digs the real text out of the several
            // shapes Aura errors arrive in.
            this.errorMessage = this.reduceError(error);
            // Drop the user message from history so a retry does not send a
            // turn that was never answered.
            this.history.pop();
        } finally {
            this.isThinking = false;
        }
    }

    async handleSave(event) {
        const id = event.target.dataset.id;
        const message = this.messages.find((m) => m.id === id);
        if (!message) {
            return;
        }

        this.savingId = id;
        this.errorMessage = '';

        try {
            await saveResolutionToCase({
                caseId: this.recordId,
                resolutionText: message.text
            });

            this.dispatchEvent(
                new ShowToastEvent({
                    title: 'Saved to Case',
                    message: 'The draft is now in AI Draft Resolution.',
                    variant: 'success'
                })
            );

            // Tell the record page to re-query, so the field updates without
            // the user reloading the browser.
            this.dispatchEvent(new RefreshEvent());
        } catch (error) {
            this.errorMessage = this.reduceError(error);
        } finally {
            this.savingId = null;
        }
    }

    handleClear() {
        this.messages = [];
        this.history = [];
        this.errorMessage = '';
    }

    // ------------------------------------------------------------------

    addMessage(role, text, toolsCalled) {
        const id = `m${this.nextId++}`;
        const isAssistant = role === 'assistant';

        this.messages = [
            ...this.messages,
            {
                id,
                role,
                text,
                isAssistant,
                // Precomputed because templates cannot call functions.
                cssClass: isAssistant ? 'bubble bubble_agent' : 'bubble bubble_user',
                rowClass: isAssistant ? 'row row_agent' : 'row row_user',
                toolNote: this.describeTools(toolsCalled),
                isSaving: false
            }
        ];

        this.history = [...this.history, { role, content: text }];
    }

    /** Turn the tool names into something a support agent would want to read. */
    describeTools(toolsCalled) {
        if (!toolsCalled || toolsCalled.length === 0) {
            return '';
        }
        const searches = toolsCalled.filter((t) => t === 'search_knowledge_articles').length;
        if (searches === 1) {
            return 'Searched the knowledge base';
        }
        if (searches > 1) {
            return `Searched the knowledge base ${searches} times`;
        }
        return 'Looked up case details';
    }

    /** Aura errors arrive in several shapes. Get to the sentence. */
    reduceError(error) {
        if (!error) {
            return 'Something went wrong.';
        }
        if (error.body && error.body.message) {
            return error.body.message;
        }
        if (Array.isArray(error.body) && error.body.length && error.body[0].message) {
            return error.body[0].message;
        }
        if (error.message) {
            return error.message;
        }
        return 'Something went wrong.';
    }

    /** Keep the newest message in view as the conversation grows. */
    renderedCallback() {
        const log = this.template.querySelector('[data-scroll="log"]');
        if (log) {
            log.scrollTop = log.scrollHeight;
        }
    }

    /** Used by the template to disable the button being clicked. */
    get decoratedMessages() {
        return this.messages.map((m) => ({
            ...m,
            isSaving: m.id === this.savingId
        }));
    }
}
