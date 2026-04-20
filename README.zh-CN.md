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

- Node.js ≥ 20 · Python ≥ 3.10 · Solana CLI · OpenHarness (`pip install openharness-ai`)
- Anthropic 或 OpenAI API Key

### 初始化

```bash
git clone https://github.com/Keybird0/SolGuard.git
cd SolGuard
cp .env.example .env                       # 填写密钥
bash scripts/verify-phase1.sh              # 校验环境
```

### 本地运行

```bash
cd solguard-server && npm install && npm run dev
# 打开 http://localhost:3000
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

[MIT](./LICENSE) © 2026 SolGuard Contributors

---

## 致谢

- **[OpenHarness](https://github.com/HKUDS/OpenHarness)** — Agent 基础设施
- **[GoatGuard](https://github.com/Reappear/GoatGuard)** — EVM 审计架构参考
- **[Sealevel Attacks](https://github.com/coral-xyz/sealevel-attacks)** — 安全基准
