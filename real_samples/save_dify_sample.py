# -*- coding: utf-8 -*-
"""落盘 Dify 真实 DSL 样例（小红书运营一条龙，beansmile/dify-workflow 仓库）"""
import os

BASE = r"C:\Users\jh190\Doubao\chats\2026-10-07\new-chat\veriflow\real_samples"
os.makedirs(BASE, exist_ok=True)

yaml_text = """app:
  description: ''
  icon: 🤖
  icon_background: '#FFEAD5'
  mode: workflow
  name: 小红书运营一条龙
  use_icon_as_answer_icon: false
kind: app
version: 0.1.3
workflow:
  conversation_variables: []
  environment_variables: []
  features:
    file_upload:
      enabled: false
    image:
      enabled: false
      number_limits: 3
      transfer_methods:
      - local_file
      - remote_url
    opening_statement: ''
    retriever_resource:
      enabled: true
    sensitive_word_avoidance:
      enabled: false
    speech_to_text:
      enabled: false
    suggested_questions: []
    text_to_speech:
      enabled: false
      language: ''
      voice: ''
  graph:
    edges:
    - data:
        isInIteration: false
        sourceType: start
        targetType: llm
        id: 1724664297643-source-1724668244170-target
        source: '1724664297643'
        sourceHandle: source
        target: '1724668244170'
        targetHandle: target
        type: custom
        zIndex: 0
    - data:
        isInIteration: false
        sourceType: llm
        targetType: llm
        id: 1724668244170-source-1724667967367-target
        source: '1724668244170'
        sourceHandle: source
        target: '1724667967367'
        targetHandle: target
        type: custom
        zIndex: 0
    - data:
        isInIteration: false
        sourceType: llm
        targetType: llm
        id: 1724667967367-source-1724668427743-target
        source: '1724667967367'
        sourceHandle: source
        target: '1724668427743'
        targetHandle: target
        type: custom
        zIndex: 0
    - data:
        isInIteration: false
        sourceType: llm
        targetType: http-request
        id: 1724668427743-source-1724917671343-target
        source: '1724668427743'
        sourceHandle: source
        target: '1724917671343'
        targetHandle: target
        type: custom
        zIndex: 0
    - data:
        isInIteration: false
        sourceType: http-request
        targetType: code
        id: 1724917671343-source-1724917816601-target
        source: '1724917671343'
        sourceHandle: source
        target: '1724917816601'
        targetHandle: target
        type: custom
        zIndex: 0
    - data:
        isInIteration: false
        sourceType: code
        targetType: template-transform
        id: 1724917816601-source-1724917916290-target
        source: '1724917816601'
        sourceHandle: source
        target: '1724917916290'
        targetHandle: target
        type: custom
        zIndex: 0
    - data:
        isInIteration: false
        sourceType: template-transform
        targetType: end
        id: 1724917916290-source-1724901868305-target
        source: '1724917916290'
        sourceHandle: source
        target: '1724901868305'
        targetHandle: target
        type: custom
        zIndex: 0
    nodes:
    - data:
        desc: ''
        selected: false
        title: Start
        type: start
        variables:
        - label: ☝️ 请简单描述主题要求
          max_length: 10000
          options: []
          required: true
          type: paragraph
          variable: basic_instruction
        - label: 📝 请补充必要的背景信息，帮助 AI 推理
          max_length: 10000
          options: []
          required: false
          type: paragraph
          variable: background_detail
        - label: 🎨 请输入正文语气风格
          max_length: 10000
          options: []
          required: false
          type: paragraph
          variable: style
        height: 142
        id: '1724664297643'
        position:
          x: 80
          y: 282
        positionAbsolute:
          x: 80
          y: 282
        selected: false
        sourcePosition: right
        targetPosition: left
        type: custom
        width: 244
    - data:
        context:
          enabled: false
          variable_selector: []
        desc: ''
        model:
          completion_params:
            temperature: 0.7
            mode: chat
            name: chatgpt-4o-latest
            provider: openai
          prompt_template:
          - id: 5687e2f8-0cb4-4c22-9021-6e6638d2118b
            role: system
            text: 小红书爆款写作专家
          - id: d8bfca4e-9b00-425a-aa80-08bd7b939958
            role: user
            text: 我的基本要求：{{#1724664297643.basic_instruction#}}
        selected: false
        title: 小红书正文
        type: llm
        variables: []
        vision:
          configs:
            detail: high
            enabled: false
        height: 98
        id: '1724667967367'
        position:
          x: 704.8779291662977
          y: 282
        positionAbsolute:
          x: 704.8779291662977
          y: 282
        selected: false
        sourcePosition: right
        targetPosition: left
        type: custom
        width: 244
    - data:
        context:
          enabled: false
          variable_selector: []
        desc: ''
        model:
          completion_params:
            temperature: 0.7
            mode: chat
            name: chatgpt-4o-latest
            provider: openai
          prompt_template:
          - id: 9b5ab55d-3d86-4ea9-8e0e-26f778bf19d4
            role: system
            text: 生成吸引人的标题
          - id: 392e2079-0048-4cab-a091-4326dbd88885
            role: user
            text: 我的主题是：{{#1724664297643.basic_instruction#}}
        selected: false
        title: 小红书标题
        type: llm
        variables: []
        vision:
          configs:
            detail: high
            enabled: false
        height: 98
        id: '1724668244170'
        position:
          x: 391.59197424229
          y: 282
        positionAbsolute:
          x: 391.59197424229
          y: 282
        selected: false
        sourcePosition: right
        targetPosition: left
        type: custom
        width: 244
    - data:
        context:
          enabled: false
          variable_selector: []
        desc: ''
        model:
          completion_params:
            temperature: 0.7
            mode: chat
            name: chatgpt-4o-latest
            provider: openai
          prompt_template:
          - id: c2d86133-8dfe-4f5b-ad63-50eda3fb607b
            role: system
            text: 生成引导性前言
          - id: 40a6d4d7-0546-41c3-9fe3-68ceb58db4c2
            role: user
            text: 我的小红书内容如下
        selected: false
        title: 封面前言
        type: llm
        variables: []
        vision:
          configs:
            detail: high
            enabled: false
        height: 98
        id: '1724668427743'
        position:
          x: 1028.8578647720228
          y: 282
        positionAbsolute:
          x: 1028.8578647720228
          y: 282
        selected: false
        sourcePosition: right
        targetPosition: left
        type: custom
        width: 244
    - data:
        desc: ''
        outputs:
        - value_selector:
          - '1724917916290'
          - output
          variable: output
        selected: false
        title: End
        type: end
        height: 90
        id: '1724901868305'
        position:
          x: 2216.102789426912
          y: 282
        positionAbsolute:
          x: 2216.102789426912
          y: 282
        selected: false
        sourcePosition: right
        targetPosition: left
        type: custom
        width: 244
    - data:
        authorization:
          config:
            api_key: 298845100895770054.lPjulRkBszvVlFeQGNTeD2vJY3runtmv
            header: X-API-Key
          type: custom
          type: api-key
        body:
          data:
          - type: text
            value: '{"width": 1024}'
          type: json
        desc: ''
        headers: Content-Type:application/json
        method: post
        params: ''
        selected: false
        timeout:
          max_connect_timeout: 0
          max_read_timeout: 0
          max_write_timeout: 0
        title: ImgRender
        type: http-request
        url: https://api.imgrender.net/open/v1/pics
        variables: []
        height: 110
        id: '1724917671343'
        position:
          x: 1339.840462497475
          y: 282
        positionAbsolute:
          x: 1339.840462497475
          y: 282
        selected: true
        sourcePosition: right
        targetPosition: left
        type: custom
        width: 244
    - data:
        code: import json
        code_language: python3
        desc: ''
        outputs:
          cover_url:
            children: null
            type: array[string]
        selected: false
        title: 获取封面图URl
        type: code
        variables:
        - value_selector:
          - '1724917671343'
          - body
          variable: req
        height: 54
        id: '1724917816601'
        position:
          x: 1645.0647937168694
          y: 282
        positionAbsolute:
          x: 1645.0647937168694
          y: 282
        selected: false
        sourcePosition: right
        targetPosition: left
        type: custom
        width: 244
    - data:
        desc: ''
        selected: false
        template: '{{ {''title'': title, ''body'': body, ''covers'': cover } | tojson | safe }}'
        title: 组装结果
        type: template-transform
        variables:
        - value_selector:
          - '1724668244170'
          - text
          variable: title
        - value_selector:
          - '1724667967367'
          - text
          variable: body
        - value_selector:
          - '1724917816601'
          - cover_url
          variable: cover
        height: 54
        id: '1724917916290'
        position:
          x: 1936.7982345041403
          y: 282
        positionAbsolute:
          x: 1936.7982345041403
          y: 282
        selected: false
        sourcePosition: right
        targetPosition: left
        type: custom
        width: 244
"""

with open(os.path.join(BASE, "dify_xiaohongshu.yml"), "w", encoding="utf-8") as f:
    f.write(yaml_text)
print("saved dify_xiaohongshu.yml; len:", len(yaml_text))
