declare module "@salesforce/apex/CaseCopilotService.sendChatMessage" {
  export default function sendChatMessage(param: {caseId: any, historyJson: any, message: any}): Promise<any>;
}
declare module "@salesforce/apex/CaseCopilotService.saveResolutionToCase" {
  export default function saveResolutionToCase(param: {caseId: any, resolutionText: any}): Promise<any>;
}
