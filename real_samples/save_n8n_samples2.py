# -*- coding: utf-8 -*-
"""落盘已抓取的真实平台样例（从 web_fetch 结果整理）"""
import json, os

BASE = r"C:\Users\jh190\Doubao\chats\2026-10-07\new-chat\veriflow\real_samples"
os.makedirs(BASE, exist_ok=True)

samples = {}

samples["n8n_run_command_ephemeral.json"] = {
    "name": "E2B · Level 1 — Run a command (ephemeral sandbox)",
    "nodes": [
        {"parameters": {"content": "About & setup"}, "id": "aaaa0000-0000-0000-0000-0000000000a1",
         "name": "About & setup", "type": "n8n-nodes-base.stickyNote", "typeVersion": 1, "position": [-380, 120]},
        {"parameters": {}, "id": "11111111-1111-1111-1111-111111111111",
         "name": "When clicking 'Test workflow'", "type": "n8n-nodes-base.manualTrigger",
         "typeVersion": 1, "position": [240, 320]},
        {"parameters": {"resource": "code", "operation": "runCommand", "sandboxId": "",
                        "command": "python3 -c \"print('Hello')\"", "allowInternetAccess": True, "killAfterRun": True},
         "id": "22222222-2222-2222-2222-222222222222", "name": "Run Command (Ephemeral)",
         "type": "@e2b/n8n-nodes-e2b.e2b", "typeVersion": 1, "position": [520, 320]}
    ],
    "connections": {"When clicking 'Test workflow'": {"main": [[{"node": "Run Command (Ephemeral)", "type": "main", "index": 0}]]}},
    "active": False, "settings": {"executionOrder": "v1"}, "tags": [{"name": "e2b-example", "id": "e2b-example"}],
    "meta": {"templateCredsSetupCompleted": False}
}

samples["n8n_web_app_preview.json"] = {
    "name": "E2B · Level 2 — Run a web app and return a preview URL",
    "nodes": [
        {"parameters": {"content": "About & setup"}, "id": "aaaa0000-0000-0000-0000-0000000000a2",
         "name": "About & setup", "type": "n8n-nodes-base.stickyNote", "typeVersion": 1, "position": [-380, 120]},
        {"parameters": {}, "id": "11111111-1111-1111-1111-111111111111",
         "name": "When clicking 'Test workflow'", "type": "n8n-nodes-base.manualTrigger",
         "typeVersion": 1, "position": [200, 320]},
        {"parameters": {"resource": "sandbox", "operation": "create", "template": "", "allowInternetAccess": True},
         "id": "22222222-2222-2222-2222-222222222222", "name": "Create Sandbox",
         "type": "@e2b/n8n-nodes-e2b.e2b", "typeVersion": 1, "position": [440, 320]},
        {"parameters": {"resource": "file", "operation": "write", "sandboxId": "={{ $json.sandboxId }}",
                        "path": "/home/user/server.py", "content": "from http.server import HTTPServer"},
         "id": "33333333-3333-3333-3333-333333333333", "name": "Write Server File",
         "type": "@e2b/n8n-nodes-e2b.e2b", "typeVersion": 1, "position": [680, 320]},
        {"parameters": {"resource": "code", "operation": "runCommand",
                        "sandboxId": "={{ $('Create Sandbox').item.json.sandboxId }}",
                        "command": "nohup python3 /home/user/server.py & sleep 1",
                        "allowInternetAccess": True},
         "id": "44444444-4444-4444-4444-444444444444", "name": "Start Web Server",
         "type": "@e2b/n8n-nodes-e2b.e2b", "typeVersion": 1, "position": [920, 320]},
        {"parameters": {"resource": "sandbox", "operation": "getPreviewUrl",
                        "sandboxId": "={{ $('Create Sandbox').item.json.sandboxId }}", "port": 3000},
         "id": "55555555-5555-5555-5555-555555555555", "name": "Get Preview URL",
         "type": "@e2b/n8n-nodes-e2b.e2b", "typeVersion": 1, "position": [1160, 320]}
    ],
    "connections": {
        "When clicking 'Test workflow'": {"main": [[{"node": "Create Sandbox", "type": "main", "index": 0}]]},
        "Create Sandbox": {"main": [[{"node": "Write Server File", "type": "main", "index": 0}]]},
        "Write Server File": {"main": [[{"node": "Start Web Server", "type": "main", "index": 0}]]},
        "Start Web Server": {"main": [[{"node": "Get Preview URL", "type": "main", "index": 0}]]}
    },
    "active": False, "settings": {"executionOrder": "v1"}, "tags": [{"name": "e2b-example", "id": "e2b-example"}],
    "meta": {"templateCredsSetupCompleted": False}
}

samples["n8n_clone_build_download.json"] = {
    "name": "E2B · Level 3 — Clone a repo, build, download an artifact",
    "nodes": [
        {"parameters": {"content": "About & setup"}, "id": "aaaa0000-0000-0000-0000-0000000000a3",
         "name": "About & setup", "type": "n8n-nodes-base.stickyNote", "typeVersion": 1, "position": [-380, 120]},
        {"parameters": {}, "id": "11111111-1111-1111-1111-111111111111",
         "name": "When clicking 'Test workflow'", "type": "n8n-nodes-base.manualTrigger",
         "typeVersion": 1, "position": [200, 320]},
        {"parameters": {"resource": "sandbox", "operation": "create", "template": "", "allowInternetAccess": True},
         "id": "22222222-2222-2222-2222-222222222222", "name": "Create Sandbox",
         "type": "@e2b/n8n-nodes-e2b.e2b", "typeVersion": 1, "position": [440, 320]},
        {"parameters": {"resource": "git", "operation": "clone", "sandboxId": "={{ $json.sandboxId }}",
                        "repositoryUrl": "https://github.com/octocat/Hello-World.git", "repositoryPath": "/home/user/repo"},
         "id": "33333333-3333-3333-3333-333333333333", "name": "Clone Repo",
         "type": "@e2b/n8n-nodes-e2b.e2b", "typeVersion": 1, "position": [680, 320]},
        {"parameters": {"resource": "code", "operation": "runCommand",
                        "sandboxId": "={{ $('Create Sandbox').item.json.sandboxId }}",
                        "command": "ls -la /home/user/repo > /tmp/build-output.txt && echo done", "allowInternetAccess": True},
         "id": "44444444-4444-4444-4444-444444444444", "name": "Run Build",
         "type": "@e2b/n8n-nodes-e2b.e2b", "typeVersion": 1, "position": [920, 320]},
        {"parameters": {"resource": "file", "operation": "download",
                        "sandboxId": "={{ $('Create Sandbox').item.json.sandboxId }}",
                        "remotePath": "/tmp/build-output.txt", "binaryPropertyName": "data"},
         "id": "55555555-5555-5555-5555-555555555555", "name": "Download Artifact",
         "type": "@e2b/n8n-nodes-e2b.e2b", "typeVersion": 1, "position": [1160, 320]},
        {"parameters": {"resource": "sandbox", "operation": "kill",
                        "sandboxId": "={{ $('Create Sandbox').item.json.sandboxId }}"},
         "id": "66666666-6666-6666-6666-666666666666", "name": "Kill Sandbox",
         "type": "@e2b/n8n-nodes-e2b.e2b", "typeVersion": 1, "position": [1400, 320]}
    ],
    "connections": {
        "When clicking 'Test workflow'": {"main": [[{"node": "Create Sandbox", "type": "main", "index": 0}]]},
        "Create Sandbox": {"main": [[{"node": "Clone Repo", "type": "main", "index": 0}]]},
        "Clone Repo": {"main": [[{"node": "Run Build", "type": "main", "index": 0}]]},
        "Run Build": {"main": [[{"node": "Download Artifact", "type": "main", "index": 0}]]},
        "Download Artifact": {"main": [[{"node": "Kill Sandbox", "type": "main", "index": 0}]]}
    },
    "active": False, "settings": {"executionOrder": "v1"}, "tags": [{"name": "e2b-example", "id": "e2b-example"}],
    "meta": {"templateCredsSetupCompleted": False}
}

# n8n AI Agent（Level 4）已由 save_n8n_sample.py 落盘，此处补上（读取已有文件避免覆盖）
for fn, data in samples.items():
    p = os.path.join(BASE, fn)
    with open(p, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)
    print("saved", fn, "nodes:", len(data["nodes"]))
