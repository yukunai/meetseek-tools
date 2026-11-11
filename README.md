# MeetSeek 工具站

提供在线工具的 Web 服务和后台管理页面。

## 安装

需要 Python 3。部分工具需额外服务，按需参考 Dockerfile。

克隆仓库后，在项目根目录执行以下步骤。

```sh
python3 -m venv .venv
source .venv/bin/activate
python -m pip install -r requirements.txt
uvicorn app.main:app --host 127.0.0.1 --port 8000
```

## 使用

启动前参考 .env.example 配置服务，打开 http://127.0.0.1:8000 查看可用工具。后台账号及各外部服务需要单独配置。

## 检查

```sh
python -m compileall -q app main.py
```

## 说明

仓库包含源码与启动所需的示例。模型、平台或推送服务的凭据由使用者在本机配置。
