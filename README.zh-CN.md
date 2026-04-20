<div align="center">

# SolGuard

**AI 驱动的 Solana 智能合约安全审计服务。**
**免费 · 开源 · 即时。**

[![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg)](./LICENSE)
[![Made for Solana](https://img.shields.io/badge/Made%20for-Solana-14F195)](https://solana.com)
[![Status: WIP](https://img.shields.io/badge/Status-WIP-orange)](#路线图)

**[English](./README.md)** · [在线 Demo (WIP)](#) · [演示视频 (WIP)](#) · [文档](./docs/)

</div>

---

## 为什么是 SolGuard？

专业的 Solana 安全审计收费 **5 万美元起**，周期 **2-4 周**。
**90% 以上的中小项目负担不起**，但它们的代码仍承载着真实用户资金。

**SolGuard 是一款免费开源的 AI 安全审计器**，把任意 GitHub URL / 合约地址 / 白皮书，在 **5 分钟内**、以 **0.01 SOL（约 2 美元）** 的成本，生成一份专业级风险报告。

| | 专业审计 | SolGuard |
|---|---|---|
| 价格 | $50,000+ | 0.01 SOL (~$2) |
| 周期 | 2-4 周 | < 5 分钟 |
| 覆盖 | 深度、人工 | 7+ 规则 + AI 推理 |
| 可用性 | 需预约 | 7×24 自助 |

---

## 核心功能

- **4 类输入** — GitHub 仓库 · 链上程序地址 · 白皮书 URL · 项目官网
- **7+ Solana 专属规则** — Signer/Owner 检查缺失 · 任意 CPI · 整数溢出 · 账户数据匹配 · PDA 派生错误 · 未初始化账户
- **AI 深度分析 + Kill Signal** — LLM 对发现二次验证，降低误报
- **三级报告** — 风险总结（高管视角）· 合约评估（技术详情）· 审计清单（可执行）
- **Solana Pay 结账** — 钱包内原生支付，10 秒完成
- **邮件通知 + 反馈闭环** — 报告直接送达邮箱

---

## 仓库结构

```
SolGuard/
├── solguard-server/                # Express + TS 后端
├── skill/
│   └── solana-security-audit-skill/    # OpenHarness Skill
├── test-fixtures/                  # 测试/基准合约
├── scripts/                        # 验收脚本
└── docs/
```

完整架构见 [`docs/ARCHITECTURE.md`](./docs/ARCHITECTURE.md)（开发中）。

---

## 快速开始

### 环境要求

- **Node.js** ≥ 20
- **[uv](https://docs.astral.sh/uv/)** ≥ 0.4 — **SolGuard 唯一指定的 Python 工具链**
  - Python 版本由 `.python-version` 固定为 **3.11**，由 uv 自动下载解释器
  - 依赖真相源是 `pyproject.toml` + `uv.lock`，**`uv.lock` 必须提交**
  - 禁止把 `pip` / `python -m venv` / `poetry` / `conda` 作为主流程
- **Solana CLI**（Devnet 联调）
- **OpenHarness** — 用 uv 安装：`uv tool install openharness-ai`
- Anthropic 或 OpenAI API Key

> 还没装 uv？
>
> ```bash
> curl -LsSf https://astral.sh/uv/install.sh | sh   # 或：brew install uv
> ```

### 初始化

```bash
git clone https://github.com/Keybird0/SolGuard.git
cd SolGuard

# 一键：检查 uv、装 npm 依赖、执行 `uv sync`、跑 Phase 1 验收脚本
bash scripts/setup.sh

# 或手动：
cp .env.example .env                              # 填写密钥
cd solguard-server && npm install && cd ..
cd skill/solana-security-audit-skill
uv sync --extra test                              # 按 uv.lock 生成 .venv + 安装依赖
```

### 本地运行

```bash
# 后端
cd solguard-server && npm run dev
# 打开 http://localhost:3000

# Skill 下的所有 Python 命令都走 uv run（无需 source .venv）
cd skill/solana-security-audit-skill
uv run pytest -q
uv run ruff check .
```

### 依赖管理速查（Python 专用）

```bash
cd skill/solana-security-audit-skill

uv sync                   # 默认同步（runtime + dev）
uv sync --extra test      # 加上测试 extra
uv sync --extra parser    # 加上 tree-sitter-rust（Phase 6 可选解析器）
uv add pydantic-settings  # 新增依赖（自动更新 pyproject.toml + uv.lock）
uv add --dev pytest-mock  # 新增 dev-only 依赖
uv remove tenacity        # 删除依赖
uv lock                   # 仅刷新 uv.lock
uv lock --check           # CI 守卫：pyproject 与 lock 不一致直接失败
uv run <任意命令>          # 在托管的 venv 内执行

# 导出 pip 兼容 requirements（给只认 pip 的部署平台用）
uv export --format requirements-txt --no-hashes --no-dev > requirements.txt
```

---

## 路线图

- **Phase 1** — 环境与骨架 ✅
- **Phase 2** — Skill + 7 条规则 + AI 分析器
- **Phase 3** — 后端 + 支付 + 邮件
- **Phase 4** — Web UI
- **Phase 5** — 集成 + 部署
- **Phase 6** — 基准测试 + 准确率调优
- **Phase 7** — 文档 + 演示 + 提交（2026-05-11）

详见 [`docs/04-SolGuard项目管理/`](../docs/04-SolGuard%E9%A1%B9%E7%9B%AE%E7%AE%A1%E7%90%86/)。

---

## 许可证

SolGuard 以 **[MIT License](./LICENSE)** 开源发布，完整协议见
[`LICENSE`](./LICENSE) 文件。

```
SPDX-License-Identifier: MIT
Copyright (c) 2026 SolGuard Contributors
```

第三方依赖各自保留原有协议，详见
[`LICENSE-THIRD-PARTY.md`](./LICENSE-THIRD-PARTY.md) 与
[`NOTICE`](./NOTICE)。

你可以自由使用、修改、再分发本软件（商业用途亦可），前提是在所有副本或
实质性部分中保留上述版权声明与 MIT 协议文本。

---

## 致谢

- **[OpenHarness](https://github.com/HKUDS/OpenHarness)** — Agent 基础设施
- **[GoatGuard](https://github.com/Reappear/GoatGuard)** — EVM 审计架构参考
- **[Sealevel Attacks](https://github.com/coral-xyz/sealevel-attacks)** — 安全基准
