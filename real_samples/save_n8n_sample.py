# -*- coding: utf-8 -*-
"""将 web_fetch 抓取的两个真实平台样例落盘，供适配器开发与测试用"""
import json, os

BASE = r"C:\Users\jh190\Doubao\chats\2026-10-07\new-chat\veriflow\real_samples"
os.makedirs(BASE, exist_ok=True)

# n8n 样例：E2B AI Agent（真实工作流 JSON）
n8n_sample = {
    "name": "E2B · Level 4 — AI Agent runs code as a tool",
    "nodes": [
        {"parameters": {"content": "About & setup"}, "id": "aaaa0000-0000-0000-0000-0000000000aa",
         "name": "About & setup", "type": "n8n-nodes-base.stickyNote", "typeVersion": 1, "position": [-384, 32]},
        {"parameters": {}, "id": "11111111-1111-1111-1111-111111111111",
         "name": "When chat message received", "type": "@n8n/n8n-nodes-langchain.chatTrigger",
         "typeVersion": 1.3, "position": [384, 272], "webhookId": "e2b-agent-example-webhook"},
        {"parameters": {"resource": "sandbox", "operation": "get", "getBy": "metadata",
                        "filterMetadataJson": "{\"purpose\": \"n8n-agent-persist\"}"},
         "id": "22220000-0000-0000-0000-000000000022", "name": "Find Sandbox",
         "type": "@e2b/n8n-nodes-e2b.e2b", "typeVersion": 1, "position": [688, 272],
         "alwaysOutputData": True, "onError": "continueRegularOutput"},
        {"parameters": {"conditions": {"options": {"caseSensitive": True, "typeValidation": "loose", "version": 2},
                                       "conditions": [{"id": "c1", "leftValue": "={{ $json.sandboxId ?? '' }}",
                                                      "rightValue": "", "operator": {"type": "string",
                                                      "operation": "empty", "singleValue": True}}],
                                       "combinator": "and"}, "options": {}},
         "id": "44440000-0000-0000-0000-000000000044", "name": "Has sandbox?",
         "type": "n8n-nodes-base.if", "typeVersion": 2.3, "position": [992, 272]},
        {"parameters": {"resource": "sandbox", "operation": "create", "template": "",
                        "metadataJson": "{\"purpose\": \"n8n-agent-persist\"}", "allowInternetAccess": True},
         "id": "55550000-0000-0000-0000-000000000055", "name": "Create Sandbox",
         "type": "@e2b/n8n-nodes-e2b.e2b", "typeVersion": 1, "position": [1232, 96]},
        {"parameters": {"assignments": {"assignments": [{"id": "a1", "name": "sandboxId",
                        "value": "={{ $json.sandboxId }}", "type": "string"}]}, "options": {}},
         "id": "66660000-0000-0000-0000-000000000066", "name": "Sandbox ready",
         "type": "n8n-nodes-base.set", "typeVersion": 3.4, "position": [1488, 288]},
        {"parameters": {"promptType": "define", "text": "={{ $('When chat message received').item.json.chatInput }}",
                        "options": {"systemMessage": "You control ONE E2B cloud sandbox"}},
         "id": "77770000-0000-0000-0000-000000000077", "name": "AI Agent",
         "type": "@n8n/n8n-nodes-langchain.agent", "typeVersion": 3.1, "position": [1712, 288]},
        {"parameters": {"model": {"__rl": True, "mode": "list", "value": "gpt-4o-mini"}, "options": {}},
         "id": "88880000-0000-0000-0000-000000000088", "name": "OpenAI Chat Model",
         "type": "@n8n/n8n-nodes-langchain.lmChatOpenAi", "typeVersion": 1.2, "position": [1344, 528]},
        {"parameters": {"toolDescription": "Run a BASH shell command",
                        "resource": "code", "operation": "runCommand",
                        "sandboxId": "={{ $('Sandbox ready').item.json.sandboxId }}"},
         "id": "99990000-0000-0000-0000-000000000099", "name": "run_command",
         "type": "@e2b/n8n-nodes-e2b.e2bTool", "typeVersion": 1, "position": [1536, 528]},
        {"parameters": {"resource": "sandbox", "operation": "pause",
                        "sandboxId": "={{ $('Sandbox ready').item.json.sandboxId }}"},
         "id": "dddd1111-0000-0000-0000-0000000000d1", "name": "Pause Sandbox",
         "type": "@e2b/n8n-nodes-e2b.e2b", "typeVersion": 1, "position": [1936, 288]},
        {"parameters": {}, "id": "r1110000-0000-0000-0000-0000000000r1",
         "name": "Reset — delete persistent sandbox", "type": "n8n-nodes-base.manualTrigger",
         "typeVersion": 1, "position": [384, 944]},
        {"parameters": {"resource": "sandbox", "operation": "kill",
                        "sandboxId": "={{ $json.sandboxId }}"},
         "id": "r4440000-0000-0000-0000-0000000000r4", "name": "Kill persistent sandbox",
         "type": "@e2b/n8n-nodes-e2b.e2b", "typeVersion": 1, "position": [832, 944]},
        {"parameters": {"resource": "sandbox", "operation": "get", "getBy": "metadata",
                        "filterMetadataJson": "{\"purpose\": \"n8n-agent-persist\"}"},
         "id": "r2220000-0000-0000-0000-0000000000r2", "name": "Find Sandbox (reset)",
         "type": "@e2b/n8n-nodes-e2b.e2b", "typeVersion": 1, "position": [608, 944]}
    ],
    "connections": {
        "When chat message received": {"main": [[{"node": "Find Sandbox", "type": "main", "index": 0}]]},
        "Find Sandbox": {"main": [[{"node": "Has sandbox?", "type": "main", "index": 0}]]},
        "Has sandbox?": {"main": [[{"node": "Create Sandbox", "type": "main", "index": 0}],
                                  [{"node": "Sandbox ready", "type": "main", "index": 0}]]},
        "Create Sandbox": {"main": [[{"node": "Sandbox ready", "type": "main", "index": 0}]]},
        "Sandbox ready": {"main": [[{"node": "AI Agent", "type": "main", "index": 0}]]},
        "AI Agent": {"main": [[{"node": "Pause Sandbox", "type": "main", "index": 0}]]},
        "Reset — delete persistent sandbox": {"main": [[{"node": "Find Sandbox (reset)", "type": "main", "index": 0}]]},
        "Find Sandbox (reset)": {"main": [[{"node": "Kill persistent sandbox", "type": "main", "index": 0}]]}
    }
}
with open(os.path.join(BASE, "n8n_ai_agent_tool.json"), "w", encoding="utf-8") as f:
    json.dump(n8n_sample, f, ensure_ascii=False, indent=2)

print("saved n8n_ai_agent_tool.json; nodes:", len(n8n_sample["nodes"]))
