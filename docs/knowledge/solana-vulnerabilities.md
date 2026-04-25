# Solana 漏洞知识库 · SolGuard v0.7

> **阅读对象**：Anchor / Native Rust 开发者、审计员、以及想学习 Solana 安全的工程师。
>
> **与 `skill/.../references/vulnerability-patterns.md` 的关系**：那份文件是
> SolGuard `solana_scan` / `solana_ai_analyze` 的 **Prompt 附件**，紧贴工具实现；
> 本文档是开发者视角的 **独立可读版本** — 加了「为什么要在 Solana 上重新写一
> 份漏洞分类」「怎么学」「按规则阅读路径」等引导性内容，并把每条规则扩充到
> 100 行以上，含 *定义 · 影响 · Anchor/Native 检测 · Bad/Good 代码 · 真实案例
> · 修复 · 延伸阅读*。
>
> **Quick Nav**：
> [R1 Signer](#r1-missing-signer-check) ·
> [R2 Owner](#r2-missing-owner-check) ·
> [R3 Overflow](#r3-integer-overflow--underflow) ·
> [R4 CPI](#r4-arbitrary-cpi) ·
> [R5 TypeCosplay](#r5-account-data-matching--type-cosplay) ·
> [R6 PDA](#r6-pda-derivation-error) ·
> [R7 Init/Close](#r7-uninitialized--reinitialization--revival)

---

## 0. 为什么要重写一份 Solana-only 的漏洞分类？

EVM 世界的 10 大 Bug Class（整数、重入、闪电贷、oracle、代理、授权、会计
失步、签名、随机性、DoS）并不能 1:1 映射到 Solana：

| 维度 | EVM | Solana |
|---|---|---|
| 账户模型 | 一个合约 = 一个地址 + 内部 storage | 每条数据是一个独立账户；调用时必须显式传入 |
| 权限 | `msg.sender` 直给 | Signer 账户 + 检查 `is_signer` + PDA signer seeds |
| 反序列化 | ABI 硬绑定 | 账户只是 bytes；开发者手动 `try_from_slice` |
| 可升级 | proxy pattern / delegatecall | Upgrade Authority / BPF loader |
| 整数溢出 | Solidity 0.8+ 默认 panic | Rust release profile 默认静默 wrap |
| CPI | `call` / `delegatecall` | `invoke` / `invoke_signed`，signer seeds 显式 |

结果就是 —— **很多 EVM 的"常识防御"在 Solana 上需要完全重新实现**，而新人最
容易在以下七类规则上踩坑。SolGuard 的静态扫描 + AI 审查就是围绕这七类设计
的；本文档是它们的「开发者版百科」。

### 学习路线建议

1. **先读本文 §R1 + §R2** — 这两条覆盖 80% 的"任意调用者伪造身份"场景。
2. **再读 §R6 + §R7** — PDA / init / close 三件套是 Solana 独有陷阱。
3. **§R3 + §R5 + §R4 选读** — 它们与 EVM 对应物有类似直觉（Overflow、Type
   Confusion、Arbitrary Call），读快速。
4. **动手**：clone `coral-xyz/sealevel-attacks`，每条规则跑一个 PoC；或直接
   `cargo audit` + `solguard` 扫自己的 Anchor 项目。

### 通用 Solana 审计心法（来自 Cashio / Wormhole / Jet Protocol 复盘）

- **假设"初始化过了"**：攻击者可以**直接**调用中间 handler，不必先调
  `initialize`。每个 handler 独立校验 owner / discriminator / is_initialized。
- **假设"兄弟 handler 也做了同样的校验"**：`deposit` 加了 signer，
  `withdraw` 忘了 —— 攻击者永远挑校验最松的那个下手。
- **假设"u64 不会溢出"**：Release profile 默认不检查；`checked_*` 不是可选，
  是默认。
- **Severity 降级触发器**（审计报告写结论时用）：需要 UpgradeAuthority 才能
  触发 / 影响白名单账户 / 攻击窗口 > 24 h 可阻断 / 仅收益损失 —— 每满足一条
  降 1 级，最多 -2；多条并存取最大降幅不叠加；Critical 最低降至 Medium，
  High 最低降至 Low；NET ROI < 1 且无 DoS 则 KILL。

---

## Quick Reference（7 条规则速查）

| # | Rule ID | 名称 | Severity | 核心检测 | Sealevel 对照 |
|---|---------|------|----------|---------|--------------|
| R1 | `missing_signer_check` | Missing Signer Check | High | `AccountInfo<'info>` + authority/owner/admin 命名 + handler 把它当 authority | [0-signer-authorization](https://github.com/coral-xyz/sealevel-attacks/tree/master/programs/0-signer-authorization) |
| R2 | `missing_owner_check` | Missing Owner / Discriminator Check | High | `AccountInfo` + `try_from_slice` + 无 `owner == crate::ID` | [1-account-data-matching](https://github.com/coral-xyz/sealevel-attacks/tree/master/programs/1-account-data-matching) |
| R3 | `integer_overflow` | Integer Overflow / Underflow | Medium-High | `u64 +/-/*` 非 `checked_*`；`Cargo.toml` 未开 overflow-checks | [10-arithmetic](https://github.com/coral-xyz/sealevel-attacks/tree/master/programs) |
| R4 | `arbitrary_cpi` | Arbitrary CPI | Critical | `invoke`/`invoke_signed` target 非硬编码 | [5-arbitrary-cpi](https://github.com/coral-xyz/sealevel-attacks/tree/master/programs/5-arbitrary-cpi) |
| R5 | `account_data_matching` | Account Data Matching / Type Confusion | High | `try_from_slice_unchecked`/`bytemuck::from_bytes` 无 discriminator | [3-type-cosplay](https://github.com/coral-xyz/sealevel-attacks/tree/master/programs/3-type-cosplay) |
| R6 | `pda_derivation_error` | PDA Seed / Bump Safety | High | `find_program_address` 未存 bump / seed 不一致 | [7-bump-seed-canonicalization](https://github.com/coral-xyz/sealevel-attacks/tree/master/programs/7-bump-seed-canonicalization) |
| R7 | `uninitialized_account` | Reinitialization / Closed-Account Revival | High | `init_if_needed` / `close` 未清 discriminator | [9-closing-accounts](https://github.com/coral-xyz/sealevel-attacks/tree/master/programs/9-closing-accounts) |

规则互补关系：R1 + R6 覆盖"伪造身份"；R2 + R5 覆盖"伪造账户类型"；R3 + R4 + R7
覆盖"状态被篡改"。任何一个严肃的 Anchor / Native Rust 程序审计，都应该把
这七条至少过一遍。

---

## R1. Missing Signer Check

> **Rule ID**：`missing_signer_check` · **Severity**：High · **Scanner 优先级**：#2

### 定义

`#[derive(Accounts)]` 结构体内某个"授权"账户声明为 `AccountInfo<'info>` /
`UncheckedAccount<'info>`，但 handler 把它当 authority 使用（读取 `.key`
然后 `require!(... == expected_key)`），**没有**要求它同时是交易 signer。
攻击者只要知道 `expected_key`（链上公开信息）就能冒名顶替，**不需要持有
私钥**。

### 为什么会发生

- 开发者误以为"比较 pubkey"等价于"验证身份"。在 EVM 里 `msg.sender == admin`
  确实等价，但 Solana 的 pubkey 只是账户坐标，不代表签名。
- `/// CHECK:` 注释允许绕过 Anchor 的默认检查，一旦忘记回头加 signer 约束
  就留下漏洞。
- 老代码 copy-paste：某个 handler 的 authority 是 AccountInfo + 手动
  is_signer 检查，新 handler 忘了复制 `if !authority.is_signer` 那一行。

### 影响

任意调用者以 authority 身份执行特权操作。典型后果：直接盗走 vault 资金、
篡改 config、清算他人仓位。属于 High；若 authority 能提现或 mint，升为
Critical。

### 如何检测（SolGuard 信号）

- 字段类型 ∈ `{AccountInfo<'info>, UncheckedAccount<'info>, Box<AccountInfo<'info>>}`。
- 字段名正则 `^(authority|owner|admin|signer|user|payer).*$`。
- handler 中出现 `require_keys_eq!` / `==` / `has_one` 比较该字段，且
  `#[account(...)]` 没有 `signer` / `signer @ error` 约束。
- Native Rust：`ctx.accounts.authority.is_signer == false` 且之后作为
  authority 使用。

### Kill Signals（误报排除）

- ✅ 字段类型是 `Signer<'info>` 或 `SystemAccount<'info>` 的 signer 变体。
- ✅ `#[account(signer)]` 或 `#[account(signer @ ErrorCode::X)]` 已显式声明。
- ✅ handler 在使用 authority 前显式写了
  `if !ctx.accounts.authority.is_signer { return err!(...) }`。

### Bad vs Good（Anchor）

```rust
// BAD
#[derive(Accounts)]
pub struct Withdraw<'info> {
    #[account(mut)]
    pub vault: Account<'info, Vault>,
    /// CHECK: compared against vault.authority below
    pub authority: AccountInfo<'info>,  // ❌ 任何人都能传
}

pub fn withdraw(ctx: Context<Withdraw>, amount: u64) -> Result<()> {
    require_keys_eq!(ctx.accounts.vault.authority, ctx.accounts.authority.key());
    **ctx.accounts.vault.to_account_info().try_borrow_mut_lamports()? -= amount;
    Ok(())
}

// GOOD
#[derive(Accounts)]
pub struct Withdraw<'info> {
    #[account(mut, has_one = authority)]
    pub vault: Account<'info, Vault>,
    pub authority: Signer<'info>,       // ✅ 必须签名
}
```

### Native Rust 变体

```rust
// BAD
pub fn process_withdraw(accounts: &[AccountInfo], amount: u64) -> ProgramResult {
    let authority = &accounts[1];
    // ❌ 只比 key，没校验 is_signer
    if *authority.key != vault.authority { return Err(ProgramError::InvalidArgument); }
    ...
}

// GOOD
pub fn process_withdraw(accounts: &[AccountInfo], amount: u64) -> ProgramResult {
    let authority = &accounts[1];
    if !authority.is_signer { return Err(ProgramError::MissingRequiredSignature); }
    if *authority.key != vault.authority { return Err(ProgramError::InvalidArgument); }
    ...
}
```

### 真实案例

- **Jet Protocol liquidate**（2022）：liquidator authority 类型是
  `AccountInfo`，任何人可触发他人仓位清算。
- **Solend 多个 public pool handler**（已修复）：`update_reserve_config`
  authority 字段漏 `signer`，经代码审计才发现。

### 修复步骤

1. 把字段类型从 `AccountInfo<'info>` / `UncheckedAccount<'info>` 改为
   `Signer<'info>`（推荐）或加 `#[account(signer)]`。
2. 如果 authority 可能是 PDA（由当前 program seeds 派生），使用
   `#[account(signer, seeds = [...], bump = data.bump)]`，让 Anchor 处理
   signer seeds 验证。
3. Native Rust：在 handler 入口第一行 `assert!(account.is_signer, ...)`
   样式的断言。
4. 补齐测试：`assert_tx_fails_with_wrong_signer()`，传入随机 keypair 应
   `MissingRequiredSignature`。

### 延伸阅读

- [Anchor Book · Signer Authorization](https://book.anchor-lang.com/)
- [Sealevel Attacks Lesson 0](https://github.com/coral-xyz/sealevel-attacks/tree/master/programs/0-signer-authorization)
- [Neodyme workshop · "Owner & signer checks"](https://workshop.neodyme.io/)

---

## R2. Missing Owner Check

> **Rule ID**：`missing_owner_check` · **Severity**：High · **Scanner 优先级**：#3

### 定义

Account 数据被反序列化 / 使用但**没有**校验 `account_info.owner ==
&crate::ID`（或预期 program id）。攻击者克隆一个数据布局完全相同的伪账户
（由恶意 program 持有），传给受害 handler，就能注入任意状态。

### 为什么会发生

- Solana 账户没有 EVM 那样的"合约 storage 绑定" —— 一个账户可以属于任何
  program。除非你显式 check owner，否则攻击者可以伪造出任何数据内容。
- 开发者混用 `AccountInfo` 和 `Account<T>`：原本想快速读一下 pubkey，后来
  加了 `try_from_slice` 却忘了回头加 `Account<T>`。
- 不同 program 间共享数据结构（比如 Pyth price feed wrapper）时，新手容易
  漏掉 owner = Pyth program id 的检查。

### 影响

完全绕过 authority / balance / is_initialized 等字段。这是 Solana 最经典的
伪造账户攻击面（"Account Cosplay"），严重度 High；若组合 R5（Type Cosplay）
会升至 Critical。

### 检测信号

- handler 使用了 `AccountInfo<'info>` 或裸 `AccountInfo::try_from` 包装，而
  非 `Account<'info, T>`。
- 出现 `T::try_from_slice(&account.data.borrow())` 或
  `bytemuck::from_bytes::<T>(...)` 反序列化。
- 之后直接读写该 T 的字段做决策，却没有任何地方 check
  `account.owner == ctx.program_id` 或 `#[account(owner = ...)]`。

### Kill Signals

- ✅ 使用 `Account<'info, T>`（Anchor 自动校验 owner + discriminator）。
- ✅ 显式 `#[account(owner = crate::ID)]`。
- ✅ 手写 `require_keys_eq!(ctx.accounts.foo.owner, &crate::ID)`。
- ✅ SPL Token 账户用 `TokenAccount` / `Mint` —— Anchor 自动 enforce
  `token::ID`。

### Bad vs Good

```rust
// BAD
pub fn update_config(ctx: Context<UpdateConfig>, new_fee: u64) -> Result<()> {
    let data = ctx.accounts.config.try_borrow_data()?;
    let mut cfg: Config = Config::try_from_slice(&data)?;  // ❌ 没校验 owner
    cfg.fee = new_fee;
    Ok(())
}

// GOOD
#[derive(Accounts)]
pub struct UpdateConfig<'info> {
    #[account(mut, owner = crate::ID, has_one = admin)]
    pub config: Account<'info, Config>,                   // ✅ Anchor 校验
    pub admin: Signer<'info>,
}
```

### 真实案例

- **Sealevel Attacks #1 account-data-matching**：伪造 Vault 结构 mint 出
  无中生有的 token。
- **Solana NFT marketplace**（2022）：listing 账户 owner 未校验，攻击者
  伪造 listing 以 0 SOL 买走 blue-chip NFT。

### 修复步骤

1. 优先使用 `Account<'info, T>` 或 `Program<'info, P>`。
2. 无法更改类型的遗留代码加 `#[account(owner = crate::ID)]` 或在 handler
   首行 `require_keys_eq!(account.owner, &crate::ID)`。
3. 针对 CPI 来的 Pyth / Switchboard / OrcaWhirlpool 账户，owner 应是对应
   协议的 program id，显式写出来，不用常量散落在代码里。

### 延伸阅读

- [Sealevel Attacks Lesson 2 "Owner Checks"](https://github.com/coral-xyz/sealevel-attacks/tree/master/programs/2-owner-checks)
- [Anchor Book · Account Constraints](https://book.anchor-lang.com/anchor_references/account_constraints.html)

---

## R3. Integer Overflow / Underflow

> **Rule ID**：`integer_overflow` · **Severity**：Medium (→ High if affects mint/share) · **Scanner 优先级**：#7

### 定义

`Cargo.toml` 的 `[profile.release]` 默认 **不启用** overflow 检查（Rust
`overflow-checks = false`）。直接 `a + b` / `a * b` 在 `u64` / `u128` 上会
静默 wrap-around。余额 / share / price 的计算若 wrap，会产生无中生有的数量
或让攻击者绕过上限。

### 为什么会发生

- Rust 自身不像 Solidity 0.8+ 那样默认 panic on overflow —— 开发者从 Solidity
  迁移过来的第一反应是"Rust 应该安全"，实际不是。
- `[profile.release]` 里显式写 `overflow-checks = true` 会影响性能，很多
  项目模板默认关掉。
- `checked_add` / `checked_sub` / `checked_mul` 返回 `Option`，需要
  `.ok_or(ErrorCode::MathOverflow)?`，多写几行就懒得写了。

### 影响

余额无中生有、授信越权、DoS（除零 panic 掉用户交易）。Medium-High：主要
路径的资产数量若 wrap 即升 High。

### 检测信号

- `Cargo.toml` 未声明 `overflow-checks = true`（任一 profile）。
- 存在 `let total = a + b;` / `* ratio` / `- fee` 直接算术，且任一操作数
  来自用户输入 (`args`) 或可变账户字段。
- 没有使用 `checked_add` / `checked_sub` / `checked_mul` / `saturating_*`。
- 除法：`x / y` 且 `y` 未预先 `require!(y != 0)`。

### Kill Signals

- ✅ `Cargo.toml` 两个 profile 都有 `overflow-checks = true`。
- ✅ 对应算术已使用 `checked_*` 并 `.ok_or(ErrorCode::MathOverflow)?`。
- ✅ 数字来自 enum / constant，范围可静态证明不会 wrap。

### Bad vs Good

```toml
# BAD — Cargo.toml
[profile.release]
overflow-checks = false   # ❌ 默认值，静默 wrap

# GOOD — Cargo.toml
[profile.release]
overflow-checks = true
```

```rust
// BAD
pub fn deposit(ctx: Context<Deposit>, amount: u64) -> Result<()> {
    ctx.accounts.user.balance += amount;    // ❌ 可 wrap
    Ok(())
}

// GOOD
pub fn deposit(ctx: Context<Deposit>, amount: u64) -> Result<()> {
    let u = &mut ctx.accounts.user;
    u.balance = u.balance
        .checked_add(amount)
        .ok_or(error!(ErrorCode::MathOverflow))?;
    Ok(())
}
```

### 真实案例

- **Cashio $52M**：算术无界 + seed 校验缺失导致 mint 20 亿假稳定币。
- 多起 Anchor perp DEX：leverage 计算未 checked，触发负持仓。

### 修复步骤

1. Cargo.toml 的 `[profile.release]` + `[profile.release-with-debug]` 都加
   `overflow-checks = true`，然后全局 bench 确认性能影响 < 3%。
2. 搜 `\\b(add|sub|mul)\\b` 的所有算术，换成 `checked_*`。
3. 除法前 `require!(divisor != 0, ErrorCode::DivByZero)`。
4. 定点数计算优先使用 `spl-math::PreciseNumber` 或 `fixed` crate。

### 延伸阅读

- [Rust Book · Integer Overflow](https://doc.rust-lang.org/book/ch03-02-data-types.html#integer-overflow)
- [Solana Cookbook · Math](https://solanacookbook.com/)

---

## R4. Arbitrary CPI

> **Rule ID**：`arbitrary_cpi` · **Severity**：Critical · **Scanner 优先级**：#1（最高）

### 定义

`invoke` / `invoke_signed` 的目标 `program_id` 来自传入账户
（`ctx.accounts.target_program`）而非硬编码常量，且没有
`require_keys_eq!(target.key(), token::ID)` 之类断言。攻击者把
`target_program` 换成自己的恶意 program，宿主把 signer seeds "借"给恶意
代码，**等同私钥泄漏**。

### 为什么会发生

- "灵活性"的诱惑：某个 aggregator / router 想允许用户指定下游 DEX 程序。
- 开发者以为"只要 accounts 数组是白名单的就没问题" —— 错。Program id 才
  是真正决定代码的字段。
- `CpiContext::new` 的签名太宽松，忘记用 `Program<'info, Token>` 强类型。

### 影响

**Critical** —— PDA 签名权被恶意 program 绑定，典型情况下可以把 vault 全
部资产 CPI 走。无论多小的代码段只要一旦触发就是资金全损。

### 检测信号

- `Pubkey` 类型的字段被作为 CPI target，且未标 `address = <ID>` 约束。
- 调用前没有 `require_keys_eq!(target.key(), KNOWN_PROGRAM_ID)`。
- Anchor：`CpiContext::new(ctx.accounts.target.to_account_info(), ...)`
  的 `target` 非 `Program<'info, SomeProgram>`。

### Kill Signals

- ✅ 使用 Anchor `Program<'info, Token>` / `Program<'info, System>` 等强
  类型 wrapper —— Anchor 会 enforce 正确的 program id。
- ✅ `#[account(address = spl_token::ID)]` 显式声明。
- ✅ 调用前有 `require_keys_eq!(..., EXPECTED)`。

### Bad vs Good

```rust
// BAD
#[derive(Accounts)]
pub struct Swap<'info> {
    /// CHECK: we CPI into this
    pub target_program: AccountInfo<'info>,   // ❌ 攻击者可控
    pub vault_signer: Signer<'info>,
}

pub fn swap(ctx: Context<Swap>, data: Vec<u8>) -> Result<()> {
    let ix = Instruction {
        program_id: *ctx.accounts.target_program.key,
        accounts: vec![...],
        data,
    };
    invoke(&ix, &[...])?;                     // ❌ 飞弹发射
    Ok(())
}

// GOOD
pub fn swap(ctx: Context<Swap>) -> Result<()> {
    let cpi = CpiContext::new(
        ctx.accounts.token_program.to_account_info(),     // ✅ Program<Token>
        token::Transfer { from, to, authority: ... },
    );
    token::transfer(cpi, amount)
}
```

### 真实案例

- **Sealevel Attacks #5**：通过任意 CPI 把 PDA signer seeds 泄漏给恶意
  program，实现任意提款。
- 2023 若干 Anchor DeFi 协议：aggregator 路由允许用户指定 program，未做
  白名单。

### 修复步骤

1. 把目标 program 声明为强类型 `Program<'info, Token>` / 自定义
   `Program<'info, MyDex>`。
2. 如果确实需要路由多个下游 program，在 handler 首行做白名单 check：
   ```rust
   let tp = ctx.accounts.target_program.key();
   require!(
       tp == RAYDIUM_PROGRAM || tp == ORCA_PROGRAM,
       ErrorCode::UnsupportedDex
   );
   ```
3. 单元测试：传入未知 program id 应返回 `UnsupportedDex`。

### 延伸阅读

- [Sealevel Attacks Lesson 5 "Arbitrary CPI"](https://github.com/coral-xyz/sealevel-attacks/tree/master/programs/5-arbitrary-cpi)
- [Anchor Book · Cross Program Invocations](https://book.anchor-lang.com/anchor_in_depth/cpis.html)

---

## R5. Account Data Matching / Type Cosplay

> **Rule ID**：`account_data_matching` · **Severity**：High · **Scanner 优先级**：#6

### 定义

Solana 账户只是一块 bytes，**不带 discriminator** 时无法区分 "`Vault`" 和
"`UserPosition`"。如果 handler 从原始 `try_from_slice_unchecked` /
`bytemuck::from_bytes` 反序列化，攻击者可以把 discriminator 相同 / 缺失的
不同类型账户替换进去 —— "Type Cosplay"。字段偏移一致就能伪造权限。

### 为什么会发生

- 作者在 Anchor 项目里偶尔用 `zero_copy` / `bytemuck` 是为了性能，忘了
  zero-copy 也需要 discriminator 检查。
- Program 有多种 account type 但结构体布局前 32 字节都是 `Pubkey`（典型
  "owner"），`type_cosplay` 把 `AdminAccount` 换成 `UserAccount`，owner
  字段对齐，直接骗过权限 check。
- 遗留代码迁移：早期版本用 `AnchorDeserialize` 手搓，后来升级 Anchor 但忘
  了改成 `#[account]`。

### 影响

权限绕过、资金挪用；严重度 High，与 R2 Missing Owner 配合时为 Critical。

### 检测信号

- 代码出现 `T::try_from_slice_unchecked(...)` 或
  `bytemuck::from_bytes::<T>(...)` / `cast_ref`。
- 未检查首 8 字节 discriminator（Anchor 约定的 `sighash("account:T")`）。
- handler 基于反序列化后的 `T.field` 做授权决策。

### Kill Signals

- ✅ 使用 `Account<'info, T>`（Anchor 自动 enforce 8 字节 discriminator）。
- ✅ 手写时先 `require!(data[..8] == crate::vault::Vault::DISCRIMINATOR)`。
- ✅ 类型中含显式 `account_type: u8` + 检查。

### Bad vs Good

```rust
// BAD
pub fn admin_action(ctx: Context<AdminAction>) -> Result<()> {
    let data = ctx.accounts.state.data.borrow();
    let state: UserPosition = UserPosition::try_from_slice(&data[..]).unwrap();
    require_keys_eq!(state.owner, ctx.accounts.admin.key());   // ❌ 前 8 字节无校验
    Ok(())
}

// GOOD
#[derive(Accounts)]
pub struct AdminAction<'info> {
    #[account(mut, has_one = admin)]
    pub state: Account<'info, VaultState>,      // ✅ discriminator 自动校验
    pub admin: Signer<'info>,
}
```

### 真实案例

- **Sealevel Attacks #3 type-cosplay**：PoC 用 UserAccount 冒充
  AdminAccount，实现权限提升。

### 修复步骤

1. 所有持久化 state struct 加 `#[account]`，Anchor 会自动生成 discriminator
   +  前 8 字节比对。
2. 使用 `zero_copy` 时同样加 `#[account(zero_copy)]`，Anchor 会强制对齐。
3. 手写反序列化代码要先 `require!(data.len() >= 8 && &data[..8] == T::DISCRIMINATOR)`。

### 延伸阅读

- [Anchor Book · Account Discriminator](https://book.anchor-lang.com/)
- [Sealevel Attacks Lesson 3 "Type Cosplay"](https://github.com/coral-xyz/sealevel-attacks/tree/master/programs/3-type-cosplay)

---

## R6. PDA Derivation Error

> **Rule ID**：`pda_derivation_error` · **Severity**：High · **Scanner 优先级**：#4

### 定义

Program-Derived Address 有两类常见失误：

1. `#[account(seeds=[...], bump)]` 中的 seeds 与 handler 手写的
   `Pubkey::find_program_address` 不同步。
2. 没存 canonical bump，每次 re-derive 导致可被多个 (PDA, bump) 匹配
   （"bump seed canonicalization bug"），攻击者挑最小非 canonical bump 伪造
   PDA。

### 为什么会发生

- Anchor 0.x 的 `seeds` 语法看起来简单，但配合 `has_one` / `close` 时有
  很多坑。
- 开发者在 CPI signer seeds 里手写 `bump_array`，和 account struct 定义
  里的 seeds 容易漂移。
- 不理解 canonical bump：`find_program_address` 返回最大那个合法 bump，但
  `create_program_address` 允许任意 bump —— 如果你的代码接受外部传入的
  bump，攻击者就能伪造多个合法 PDA。

### 影响

伪造 PDA signer，绕过 authority；High，若 PDA 持有资金则 Critical。

### 检测信号

- `#[account(seeds = [...], bump)]` 存在但 account 结构体内**无** `bump: u8`
  字段（或有但 handler 不用 `bump = data.bump`）。
- 手写 `find_program_address(seeds, program_id)` 的 seeds 顺序 / 类型 / 数量
  与 Anchor attribute 不一致。
- seeds 含用户输入 (`args.name.as_bytes()`) 但未限制长度 / 字符集。

### Kill Signals

- ✅ Anchor 推荐用法：
  `#[account(seeds=[b"vault", user.key().as_ref()], bump = vault.bump)]`
  且 `bump` 存储在账户内。
- ✅ `create_program_address` 调用前已 `require!(bump == stored_bump)`。
- ✅ seeds 完全由 program 常量 + account pubkey 构成，无用户可控部分。

### Bad vs Good

```rust
// BAD
let (pda, _bump) = Pubkey::find_program_address(
    &[b"vault", user.key.as_ref()],
    ctx.program_id,
);
// ❌ 未保存 bump；下次调用可能得到非 canonical bump 的 PDA

// GOOD
#[derive(Accounts)]
pub struct Withdraw<'info> {
    #[account(
        mut,
        seeds = [b"vault", user.key().as_ref()],
        bump = vault.bump,                      // ✅ 使用存储的 bump
        has_one = user,
    )]
    pub vault: Account<'info, Vault>,
    pub user: Signer<'info>,
}
```

### 真实案例

- **Sealevel Attacks #7 bump-seed-canonicalization**：非 canonical bump 导
  致多个合法 PDA，绕过唯一性假设。

### 修复步骤

1. Account struct 加 `bump: u8`；`init` handler 里保存 `ctx.bumps.vault`。
2. 所有后续 handler 的 `#[account(seeds=..., bump = vault.bump)]` 用 **存储
   的 bump**，不要重新 `find_program_address`。
3. 如果 seeds 含用户输入（比如昵称），用 `require!(name.len() <= 32)` 限制
   长度；避免 pubkey 碰撞的 seeds（比如把 u64 和 pubkey 混放，注意 endian）。

### 延伸阅读

- [Solana Cookbook · PDAs](https://solanacookbook.com/core-concepts/pdas.html)
- [Sealevel Attacks Lesson 7](https://github.com/coral-xyz/sealevel-attacks/tree/master/programs/7-bump-seed-canonicalization)

---

## R7. Uninitialized / Reinitialization / Revival

> **Rule ID**：`uninitialized_account` · **Severity**：High · **Scanner 优先级**：#5

### 定义

三类紧密相关的错误：

1. **Uninitialized use**：读取一个从未被 `init` 的账户，字段全为零，授权
   检查 `== Pubkey::default()` 被绕过。
2. **Reinitialization**：没有 `is_initialized` 布尔守卫，攻击者第二次调用
   init，覆盖已有状态（含 authority）。
3. **Closed-account revival**：关闭账户时只 transfer lamports 但未把
   `data` 清零、也没把 discriminator 置 0，攻击者往账户充值 0.89 SOL 的
   租金豁免金额即可"复活"旧数据。

### 为什么会发生

- Anchor 的 `init_if_needed` 很好用但语义危险：如果账户已存在会跳过初始化
  但不校验"谁创建的它"。
- 早期 Anchor（< 0.28）关账户需要手动清 discriminator，很多项目代码继承
  自这个时代。
- Native Rust 写的关账户逻辑经常只 `**lamports = 0`，忘记 `data.fill(0)`。

### 影响

授权伪造、资金重入、状态覆盖；**High**（若 init 目标是 authority 账户则
Critical）。

### 检测信号

- `#[account(init_if_needed, payer=payer, space=...)]` 出现 —— Anchor 文档
  明确推荐避免。
- 账户结构体无 `is_initialized: bool` 字段，且 init handler 不校验
  `require!(!acc.is_initialized, AlreadyInit)`。
- `close = recipient` 后没有 `manual zero`（Anchor 0.28+ 会自动清
  discriminator，但 0.27 以下需要手动）。
- Native：关闭账户只做 `**account.lamports.borrow_mut() = 0`。

### Kill Signals

- ✅ 使用 `#[account(init, ...)]`（非 `init_if_needed`） + 状态结构体内保存
  `is_initialized` 且在 handler 守卫。
- ✅ 关账户用 Anchor 0.28+ 的 `close = recipient`，并写入
  `CLOSED_ACCOUNT_DISCRIMINATOR`。
- ✅ 有一个 Helper：关闭后 handler 立刻 assert
  `account.data_is_empty() || acc.discriminator == CLOSED`。

### Bad vs Good

```rust
// BAD — revival
pub fn close_vault(ctx: Context<CloseVault>) -> Result<()> {
    let v = &ctx.accounts.vault.to_account_info();
    **ctx.accounts.recipient.try_borrow_mut_lamports()? += v.lamports();
    **v.try_borrow_mut_lamports()? = 0;            // ❌ data 未清零
    Ok(())                                         //    下一轮 init 可复活
}

// GOOD — Anchor 官方关闭
#[derive(Accounts)]
pub struct CloseVault<'info> {
    #[account(
        mut,
        close = recipient,                         // ✅ Anchor 自动写入 CLOSED discriminator
        has_one = authority,
    )]
    pub vault: Account<'info, Vault>,
    pub recipient: SystemAccount<'info>,
    pub authority: Signer<'info>,
}
```

```rust
// GOOD — reinit 防御
pub fn initialize_vault(ctx: Context<InitVault>, authority: Pubkey) -> Result<()> {
    let v = &mut ctx.accounts.vault;
    require!(!v.is_initialized, ErrorCode::AlreadyInitialized);   // ✅ 守卫
    v.is_initialized = true;
    v.authority = authority;
    Ok(())
}
```

### 真实案例

- **Sealevel Attacks #9 closing-accounts**：复活已关闭的 `TokenAccount`
  实现双花。
- **Wormhole bridge $325M**（2022）：signature verifier 账户未校验已初始化
  ，允许攻击者伪造签名账户。

### 修复步骤

1. 除非必要，把 `init_if_needed` 改回 `init`；在 init handler 里要求
   `!is_initialized`。
2. 升级 Anchor 到 ≥ 0.28，使用 `close = recipient`；0.27 以下手动清
   discriminator `acc.discriminator = CLOSED_ACCOUNT_DISCRIMINATOR`。
3. Native Rust：关账户后 `data.fill(0)` + `**lamports = 0`。
4. 单元测试：连续两次 init 应 `AlreadyInitialized`；关闭后复活应 fail。

### 延伸阅读

- [Anchor Book · `init_if_needed`](https://book.anchor-lang.com/)
- [Sealevel Attacks Lesson 9](https://github.com/coral-xyz/sealevel-attacks/tree/master/programs/9-closing-accounts)
- [Wormhole Bridge Root Cause Analysis](https://wormhole.com/security/)

---

## 附录 A：SolGuard 规则 ↔ 上游 10-class 映射

SolGuard 本身聚焦 Solana 7 条规则。Phase 6 以后还引入了部分跨链 DeFi bug
classes（AMM 数学、Oracle 操纵、闪电贷），但仍保持与上表 7 条的映射关系：

| 上游 Class | 本文规则 | 备注 |
|---|---|---|
| #1 Accounting Desync | R3 + R7 | Solana 少见 ERC4626 类会计，但 share/balance 失步仍重要 |
| #2 Access Control | R1 + R2 + R6 | Solana "Access Control" ≈ 身份校验链 |
| #3 Incomplete Path | R7 + R5 | 兄弟 handler 不一致在 AI Step 5.3 硬查 |
| #5 Oracle Manipulation | 不在本 7 规则 | Phase 6 以 `oracle_pyth_twap` 辅助规则覆盖 |
| #8 Flash Loan | 不在本 7 规则 | Solana 用 JitoMEV Bundle 场景 |
| #10 Proxy/Upgrade | R7 | Solana 用 Upgrade Authority，重心不同 |

## 附录 B：更多参考资料

- [Sealevel Attacks](https://github.com/coral-xyz/sealevel-attacks) — 官方漏洞样本集
- [Anchor Book — Security chapter](https://book.anchor-lang.com/)
- [Neodyme Solana Security Workshop](https://workshop.neodyme.io/)
- [Solana Security Best Practices](https://solana.com/developers/guides/getstarted/security-best-practices)
- [OtterSec Audit Reports](https://osec.io/reports)
- [Kudelski Security · Solana Smart Contracts Best Practices](https://research.kudelskisecurity.com/)
- 本仓库内：
  - `skill/solana-security-audit-skill/references/vulnerability-patterns.md` — 工具向 prompt 附件
  - `skill/solana-security-audit-skill/references/workflow.md` — 审计流程
  - `skill/solana-security-audit-skill/references/report-templates.md` — 报告模板
  - `docs/case-studies/` — 3 份真实审计报告（Multi-Vuln CPI / Clean Escrow / Staking Slice）
