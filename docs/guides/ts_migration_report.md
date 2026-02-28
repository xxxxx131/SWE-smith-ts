# SWE-smith Python → TypeScript 迁移：工作总结与踩坑记录

## 目录

- [一、项目背景与迁移目标](#一项目背景与迁移目标)
- [二、迁移工作全景图](#二迁移工作全景图)
- [三、我们做了哪些工作](#三我们做了哪些工作)
  - [3.1 TypeScript Profile 体系构建](#31-typescript-profile-体系构建)
  - [3.2 TypeScript AST 解析适配器](#32-typescript-ast-解析适配器)
  - [3.3 TypeScript 专用 Bug 生成配置](#33-typescript-专用-bug-生成配置)
  - [3.4 端到端自动化流水线](#34-端到端自动化流水线)
  - [3.5 自动 Profile 生成器](#35-自动-profile-生成器)
  - [3.6 SWE-agent 配置适配](#36-swe-agent-配置适配)
  - [3.7 Docker 网络与代理方案](#37-docker-网络与代理方案)
  - [3.8 本地训练与服务部署全链路](#38-本地训练与服务部署全链路)
  - [3.9 三段式流水线文档体系](#39-三段式流水线文档体系)
- [四、踩坑记录与解决方案](#四踩坑记录与解决方案)
  - [4.1 语言层面的坑](#41-语言层面的坑)
  - [4.2 配置层面的坑](#42-配置层面的坑)
  - [4.3 性能与数据层面的坑](#43-性能与数据层面的坑)
  - [4.4 部署层面的坑](#44-部署层面的坑)
- [五、关键产物清单](#五关键产物清单)
- [六、数据统计](#六数据统计)

---

## 一、项目背景与迁移目标

[SWE-smith](https://github.com/SWE-bench/SWE-smith)（NeurIPS 2025 D&B Spotlight）是一个用于训练软件工程 Agent 的工具包，其核心能力是将任意 GitHub 仓库转化为 SWE-bench 风格的训练数据。**原始项目仅支持 Python 仓库**，我们的工作是将其完整扩展到 TypeScript 生态。

迁移目标包含三个层次：

1. **环境层**：让 SWE-smith 能构建 TypeScript 仓库的 Docker 执行环境
2. **数据层**：生成 TS 仓库的 Bug 任务实例 + SWE-agent 修复轨迹 + SFT 训练数据
3. **训练层**：基于 TS 轨迹数据对 Qwen2.5-Coder-7B-Instruct 进行本地全量微调

---

## 二、迁移工作全景图

```
原始 SWE-smith (仅 Python)
│
├─ profiles/python.py          ← 仅有 Python Profile
├─ bug_gen/adapters/python.py  ← 仅有 Python AST 适配
├─ configs/bug_gen/lm_*.yml    ← 仅有 Python Prompt
├─ agent/swesmith_gen_*.yaml   ← 仅有 Python Agent 配置
├─ scripts/train_*             ← 依赖 Modal 云平台
└─ docs/                       ← 仅有 Python 文档

                    ↓↓↓ 迁移工作 ↓↓↓

扩展后 SWE-smith (Python + TypeScript)
│
├─ profiles/typescript.py          ✅ 新增：TS Profile 基类 + 7 个仓库 Profile
├─ profiles/generated/             ✅ 新增：自动生成的 Profile 目录
├─ bug_gen/adapters/typescript.py  ✅ 新增：tree-sitter-typescript AST 适配
├─ configs/bug_gen/ts_modify.yml   ✅ 新增：TS 专用 LLM Bug 生成 Prompt
├─ configs/bug_gen/ts_rewrite.yml  ✅ 新增：TS 专用 LLM Rewrite Prompt
├─ configs/train/*_local.yml       ✅ 新增：本地训练配置
├─ agent/swesmith_gen_glm_ts.yaml  ✅ 新增：TS 轨迹生成配置
├─ agent/swesmith_infer_ts.yaml    ✅ 新增：TS 推理评测配置
├─ agent/_gen_trajs.sh             ✅ 重写：代理预检 + SOCKS 降级 + 轨迹后检
├─ scripts/ts_standard_pipeline.py ✅ 新增：TS 端到端流水线（636 行）
├─ scripts/auto_profile_ts.py     ✅ 新增：自动 Profile 生成器（369 行）
├─ scripts/train.*.local.sh        ✅ 新增：本地训练/服务全套脚本
├─ train/traj_mgr/validate_*.py    ✅ 新增：训练数据长度统计校验
├─ docs/guides/ts_*.md             ✅ 新增：TS 流水线三份文档
├─ WORKFLOW.md                     ✅ 新增：快速参考手册
└─ tsconfig.json                   ✅ 已有（上游仓库自带）
```

---

## 三、我们做了哪些工作

### 3.1 TypeScript Profile 体系构建

**文件**：`swesmith/profiles/typescript.py`（457 行）

SWE-smith 通过 Profile 类定义每个仓库的"身份信息"——Dockerfile 模板、测试命令、日志解析器、文件扩展名等。原始项目有 Python Profile 和 JavaScript Profile，但 TypeScript 有自身特殊性，不能直接复用 JS Profile。

**我们的工作**：

1. **设计 `TypeScriptProfile` 基类**，继承 `JavaScriptProfile`，增加 TS 特有逻辑：

   - 文件扩展名扩展为 `[".ts", ".tsx", ".js", ".jsx"]`
   - 构建产物目录排除（`lib`、`.tsbuildinfo`、`typings`、`types`、`__generated__`、`esm`、`cjs`、`umd`）
   - 通用的依赖漂移处理机制（`skip_type_check` 标志 + `get_effective_test_cmd()` 正则剥离）

2. **手工编写 7 个 TS 仓库 Profile**，每个都经过实际验证：

   | Profile | 仓库 | 测试框架 | 包管理器 | 特殊处理 |
   |---------|------|----------|----------|----------|
   | `ZodProfile` | colinhacks/zod | Jest (ts-jest) | yarn | `NODE_OPTIONS=--max-old-space-size=4096` |
   | `ValibotProfile` | fabian-hiller/valibot | Vitest | npm | — |
   | `SuperstructProfile` | ianstormtaylor/superstruct | Vitest | npm | `skip_type_check=True` |
   | `CheerioProfile` | cheeriojs/cheerio | Jest | npm | `./node_modules/.bin/jest` |
   | `IoTsProfile` | gcanti/io-ts | Vitest | npm | 同作者 fp-ts |
   | `NeverthrowProfile` | supermacro/neverthrow | Vitest | npm | — |
   | `YupProfile` | jquense/yup | Jest | npm | — |
   | `FpTsProfile` | gcanti/fp-ts | Vitest | npm | 绕过 dtslint 链 |

3. **制定测试命令选择原则**（写入 `typescript.py` 头部），总结自对 81 个原始 JS Profile 的统计分析：

   - 优先级 1：`npm run <specific-test-script>`（29/81 使用）
   - 优先级 2：`./node_modules/.bin/<runner>`（4/81 使用）
   - 禁用：`npm test`（链式命令）、`npx`（静默下载）

### 3.2 TypeScript AST 解析适配器

**文件**：`swesmith/bug_gen/adapters/typescript.py`（271 行）

SWE-smith 的 Bug 生成依赖 AST 解析提取代码实体。Python 使用内置 `ast` 模块提取 `ClassDef`/`FunctionDef`，TypeScript 需要完全不同的解析方案。

**我们的工作**：

1. **基于 `tree-sitter-typescript` 实现 `TypeScriptEntity` 类**，继承 `JavaScriptEntity`：

   - 自动区分 `.ts` 和 `.tsx` 文件，选择对应的 Language parser
   - 处理 TS 特有的 `type_identifier`（类名节点类型与 JS 的 `identifier` 不同）
   - 实现 `interface`、`enum`、`type alias` 的 name/signature/stub 提取

2. **与 Python 适配器严格对齐的实体收集策略**：

   - **收集**：`function_declaration`、`method_definition`、`class_declaration`、箭头函数（`arrow_function`）、函数表达式（`function_expression`）
   - **不收集**：`interface_declaration`、`type_alias_declaration`、`enum_declaration`——它们是纯类型定义，无可执行代码体，无法引入逻辑 bug

3. **处理 TypeScript 常见代码模式**：

   - `const myFunc = () => {}` → 通过 `_collect_variable_functions_ts()` 处理 `variable_declaration`/`lexical_declaration` 中的箭头函数
   - `module.exports.fn = function() {}` → 通过 `_collect_assignment_functions_ts()` 处理赋值表达式中的函数

### 3.3 TypeScript 专用 Bug 生成配置

**文件**：`configs/bug_gen/ts_modify.yml`（67 行）、`configs/bug_gen/ts_rewrite.yml`（40 行）

**我们的工作**：

原始 Python 的 LLM Bug 生成 Prompt 中没有类型系统约束，直接用于 TS 会导致 LLM 修改类型注解/接口定义，引入编译错误而非逻辑 bug。我们创建了 TS 专用的 Prompt 配置：

- 在 `system` 中添加 TypeScript 专属约束：不得修改函数签名、参数类型、返回类型；不得修改 interface/type 定义；不得增删 import；保持所有类型注解不变
- 在 `tips` 中添加 TS 专属提示：不得引入 TypeScript 编译错误
- Bug 示例适配为 TS 语法习惯：`=== → !==`、空值检查（`null/undefined`）、三元运算符等

### 3.4 端到端自动化流水线

**文件**：`scripts/ts_standard_pipeline.py`（636 行）

**我们的工作**：

SWE-smith 原始项目只为 Python 提供分步命令，TS 需要串联 7 个步骤。我们实现了一键执行的端到端流水线：

```
Step 1: create_mirror + build_image
  ↓
Step 2: generate_bugs (procedural / llm-modify / llm-rewrite / all)
  ↓
Step 3: collect_patches
  ↓
Step 4: validate_f2p (Fail-to-Pass 验证)
  ↓
Step 5: gather_instances (收集有效任务实例 + 推送分支)
  ↓
Step 6: generate_issue_text (LLM / static / tests / pr / skip)
  ↓
Step 7: 输出最终数据集 → logs/agent_datasets/<repo>_final.json
```

支持 20+ 参数控制，包括 bug 生成方法选择、LLM 模型指定、并行度、issue 生成模式等。内置了 issue 输出路径归一化（`_normalize_issue_output()`），解决不同 issue 生成器输出路径不一致的问题。

### 3.5 自动 Profile 生成器

**文件**：`scripts/auto_profile_ts.py`（369 行）

**我们的工作**：

手工编写每个仓库的 Profile 繁琐且易出错。我们实现了自动检测工具：

1. 临时 clone 目标仓库
2. 读取 `package.json`，检测包管理器（npm/yarn/pnpm/bun）
3. 分析 `devDependencies` + `scripts`，按优先级检测测试框架（Vitest → Jest → Mocha → Ava → node:test）
4. 生成安全的测试命令（过滤含 `&&` 的链式命令，避免 `npx`）
5. 自动选择正确的 `log_parser`（`parse_log_jest`/`parse_log_vitest`/`parse_log_mocha`）
6. 输出到 `swesmith/profiles/generated/` 目录
7. 支持 `--run` 直接接入完整流水线、`--dry-run` 只预览不写入

### 3.6 SWE-agent 配置适配

**文件**：`agent/swesmith_gen_glm_ts.yaml`、`agent/swesmith_infer_ts.yaml`

**我们的工作**：

1. **创建 TS 轨迹生成配置**（`swesmith_gen_glm_ts.yaml`）：

   - 将 instance_template 中的 "Python repository" 替换为 "TypeScript code repository"
   - 提示文字改为 `node <filename.js>` 或仓库的测试命令
   - review_on_submit 中的 `git checkout -- /path/to/test/file.py` 改为 `.ts`
   - 配置代理变量透传（`propagate_env_variables`）
   - 使用 `function_calling` 解析模式
   - 接入 GLM-4.6 模型（BigModel/ZAI provider via LiteLLM）

2. **创建 TS 推理评测配置**（`swesmith_infer_ts.yaml`）：

   - 使用 `xml_function_calling` 解析模式（绕过 API 代理不支持 `tools` 字段的问题）
   - 将工具定义以 XML 标签嵌入 system prompt
   - 配置 `last_n_observations: 5` 的历史管理策略

### 3.7 Docker 网络与代理方案

**文件**：`agent/_gen_trajs.sh`（231 行，其中约 130 行为代理相关逻辑）

**我们的工作**：

SWE-agent 在 Docker 容器内运行，容器需访问 GitHub 等外部服务。我们实现了完整的代理预检和降级方案：

1. **socat 转发方案**：宿主机代理监听 localhost，通过 socat 转发到 Docker 网桥地址 `172.17.0.1:10819`，容器内设置 `HTTP_PROXY=http://172.17.0.1:10819`

2. **代理预检机制**（启动前自动执行）：
   - TCP 端口可达性检测
   - Docker 网桥网关连通性验证
   - SOCKS 代理 + socksio 依赖检测
   - 失败时给出具体修复建议（而非静默失败）

3. **SOCKS 代理智能降级**：当 `ALL_PROXY` 为 SOCKS 协议但 `socksio` 未安装时，自动 fallback 到 `HTTP_PROXY`/`HTTPS_PROXY`

4. **轨迹生成后检**：检查 `.pred` 文件数量、解析 `run_batch_exit_statuses.yaml`、验证 `preds.json` 中非空 patch 比例

### 3.8 本地训练与服务部署全链路

SWE-smith 原始设计依赖 [Modal](https://modal.com/) 云平台。我们的环境无法使用 Modal，需要完全本地化。

**我们的工作**：

1. **轨迹转 SFT**（`scripts/train.prepare_sft_local.sh`）：

   - 封装 `swesmith.train.traj_mgr.collect_trajs`
   - 支持可选的长度统计校验（`STATS_FILE`）
   - 默认输出到 `trajectories_sft/`

2. **Resolved-only 过滤**：

   - 从 `report.json` 的 `ids_resolved` 字段筛选成功修复的轨迹
   - 产出 `.resolved_only.xml.jsonl`，仅包含高质量训练数据

3. **本地训练配置**（`configs/train/full_ft_qwen_7b_local.yml`）：

   - 模型：Qwen2.5-Coder-7B-Instruct
   - 数据：resolved-only 轨迹
   - 参数：`max_seq_len=32768`，`batch_size=1`，`gradient_accumulation=4`，`epochs=3`，`lr=1e-4`，`warmup=5`，`bf16`，`activation_checkpointing`
   - 日志：WandB

4. **本地训练启动脚本**（`scripts/train.run_ft_torchtune.local.sh`）：

   - 训练前自动校验：tokenizer 路径、checkpoint 路径、数据文件路径、权重分片完整性
   - 训练前长度统计一致性校验（可通过 `LEN_STATS_FILE=""` 跳过）
   - 调用 `tune run --nnodes 1 --nproc_per_node $N_GPUS full_finetune_distributed`

5. **本地 SGLang 推理服务**（`scripts/train.serve_sglang.local.sh`）：

   - 自动检测 conda 编译器并设置 `CC`/`CXX`/`CUDAHOSTCXX`/`NVCC_PREPEND_FLAGS`（解决 nvcc 与系统 g++ 不兼容问题）
   - 自动重定向构建缓存和临时文件到 `/data` 分区（避免根分区空间不足）
   - 自动补全 checkpoint 目录中缺失的 `config.json`

6. **训练数据长度统计工具**（`swesmith/train/traj_mgr/validate_len_stats.py`）：

   - 校验数据文件路径、样本数量与 stats 清单一致
   - 报告超过 `max_seq_len` 阈值的数据比例

7. **脚本命名规范化**：

   - 统一使用 `snake_case` 命名（`train_prepare_sft_local.sh`、`train_run_ft_torchtune_local.sh`、`train_serve_sglang_local.sh`）
   - 旧的点分命名保留为兼容入口（仅 `exec` 转发）

### 3.9 三段式流水线文档体系

**文件**：

- `docs/guides/ts_pipeline_overview.md`（65 行）——端到端流程概览 + Mermaid 流程图
- `docs/guides/ts_three_pipelines.md`（334 行）——三段式可复制执行的操作手册
- `docs/guides/train_swe_agent.md`——完整训练指南（含本地训练章节）
- `WORKFLOW.md`——日常操作速查卡

---

## 四、踩坑记录与解决方案

### 4.1 语言层面的坑

#### 坑 1：`npm test` 链式命令导致全部失败

| 项目 | 详情 |
|------|------|
| **现象** | 对 TS 仓库执行 `npm test --verbose`，即使所有测试通过也报失败 |
| **根因** | TS 仓库的 `npm test` 几乎都是链式命令（如 fp-ts 的 `lint && prettier && dtslint && vitest && docs`），非测试步骤（lint、dtslint、docs 构建）失败会中断整条链 |
| **影响** | Bug 验证（F2P）全部误判为无效，无法生成任何有效任务实例 |
| **解决** | 分析 81 个原始 JS Profile 的测试命令模式，制定三级优先级策略，选择直接调用测试运行器的纯脚本（如 `npm run vitest`）或本地二进制（如 `./node_modules/.bin/jest`） |
| **代码** | `swesmith/profiles/typescript.py` 头部注释 + 每个 Profile 的 `test_cmd` 定义 |

#### 坑 2：依赖漂移导致类型检查失败

| 项目 | 详情 |
|------|------|
| **现象** | `superstruct` 仓库 Docker 构建后，`tsc --noEmit` 报错 `Cannot find name 'ESNext.Disposable'` |
| **根因** | 仓库缺少 `package-lock.json`，`npm install` 时 `@types/expect` 间接拉入最新 `jest-mock`（要求 TS 5.2+），但仓库锁定 TS 4.8 |
| **影响** | 含 `tsc` 步骤的测试命令全部失败 |
| **解决** | 设计 `skip_type_check` 通用标志 + `get_effective_test_cmd()` 正则剥离方法，自动从 `test_cmd` 中移除类型检查步骤 |
| **代码** | `TypeScriptProfile.get_effective_test_cmd()`（6 条正则模式匹配 + 清理逻辑） |

#### 坑 3：TypeScript AST 中类名使用 `type_identifier` 而非 `identifier`

| 项目 | 详情 |
|------|------|
| **现象** | 提取 TS 类的实体名称时返回 `None` |
| **根因** | tree-sitter-typescript 中 `class_declaration` 的子节点用 `type_identifier` 表示类名，而 JavaScript 用 `identifier` |
| **解决** | 在 `TypeScriptEntity.name` 属性中添加 `class_declaration → type_identifier` 的特殊处理 |
| **代码** | `swesmith/bug_gen/adapters/typescript.py` 第 86-87 行 |

#### 坑 4：LLM 生成的 Bug 修改类型注解导致编译错误

| 项目 | 详情 |
|------|------|
| **现象** | LLM modify 生成的 bug diff 中修改了函数签名的类型注解，应用后 `tsc` 编译失败，F2P 验证无法通过 |
| **根因** | 原始 Python 的 `lm_modify.yml` Prompt 没有类型系统相关约束 |
| **解决** | 创建 `ts_modify.yml` 和 `ts_rewrite.yml`，在 system prompt 中添加 4 条 TypeScript 专属约束 |
| **代码** | `configs/bug_gen/ts_modify.yml` 第 41-45 行 |

#### 坑 5：纯类型定义（interface/type/enum）被错误收集为 bug 生成实体

| 项目 | 详情 |
|------|------|
| **现象** | LLM 被要求修改 `interface User { ... }` 引入 bug，但 interface 没有可执行代码，无法通过测试验证 |
| **根因** | 最初的实现收集了所有 TS AST 顶层节点，包括纯类型定义 |
| **解决** | 与 Python 适配器对齐——只收集有可执行代码体的实体（function、method、class），排除 interface/type alias/enum |
| **代码** | `swesmith/bug_gen/adapters/typescript.py` 第 208-212 行 |

### 4.2 配置层面的坑

#### 坑 6：API 代理不支持 `tools` 字段

| 项目 | 详情 |
|------|------|
| **现象** | SWE-agent 使用 `function_calling` 模式时，GLM API 代理返回 400 错误 |
| **根因** | 部分 API 代理（非 OpenAI 原生）不支持请求体中的 `tools` 字段 |
| **解决** | 创建两套配置：`function_calling`（原生 API）和 `xml_function_calling`（工具定义嵌入 system prompt） |
| **代码** | `agent/swesmith_infer_ts.yaml` 使用 `xml_function_calling` |

#### 坑 7：Issue 输出路径不统一

| 项目 | 详情 |
|------|------|
| **现象** | 流水线在 Step 6 后找不到 issue 输出文件 |
| **根因** | `get_static.py`/`get_from_pr.py` 输出到 `logs/task_insts/`，`generate.py` 输出到 `logs/issue_gen/`，路径不统一 |
| **解决** | `ts_standard_pipeline.py` 中实现 `_normalize_issue_output()` 统一归一化到 `logs/issue_gen/`，自动检测旧路径并复制 |
| **代码** | `scripts/ts_standard_pipeline.py` 第 344-365 行 |

#### 坑 8：脚本命名混乱

| 项目 | 详情 |
|------|------|
| **现象** | 文档中引用 `train_prepare_sft_local.sh`，实际文件名是 `train.prepare_sft_local.sh`，命令执行失败 |
| **根因** | 仓库中存在两种命名风格（旧式点分 vs 新式 snake_case） |
| **解决** | 统一使用 `snake_case` 命名，旧文件保留为仅 `exec` 转发的兼容入口 |
| **代码** | `scripts/train_prepare_sft_local.sh` 等 3 个转发脚本 |

### 4.3 性能与数据层面的坑

#### 坑 9：70% 轨迹超过 32K token 上下文限制

| 项目 | 详情 |
|------|------|
| **现象** | 394 条 SWE-agent 轨迹中仅 114 条（29%）在 32K context length 以内 |
| **根因** | SWE-agent 的轨迹包含完整的多轮对话历史（观测结果、工具调用、代码文件内容），单条轨迹很容易超 32K |
| **上游状态** | SWE-smith 官方 Issue #21 未给出训练时截断方案；SWE-agent 仅在推理时使用 `last_n_observations` 截断历史，导出数据是全量的 |
| **解决** | 采用 `keep_all_truncate` 策略——保留全部数据，由 TorchTune tokenizer 按 `max_seq_len=32768` 自动截断超长序列；同时创建 `validate_len_stats.py` 工具在训练前报告超长比例 |
| **代码** | `configs/train/full_ft_qwen_7b_local.yml` 的 `max_seq_len: 32768` + `packed: False` |

#### 坑 10：失败轨迹混入训练数据

| 项目 | 详情 |
|------|------|
| **现象** | SFT 数据包含大量未成功修复问题的轨迹，模型学习到错误的行为模式 |
| **根因** | 轨迹转换脚本默认导出所有轨迹，不区分成功/失败 |
| **解决** | 增加 Resolved-only 过滤步骤——从 `report.json` 读取 `ids_resolved`，只保留成功修复的轨迹 |
| **代码** | `docs/guides/ts_three_pipelines.md` 第 2.4 节的内联 Python 脚本 |

#### 坑 11：Zod Jest 测试 OOM

| 项目 | 详情 |
|------|------|
| **现象** | Zod 仓库的 Jest 测试在 Docker 容器中因内存不足被 kill |
| **根因** | ts-jest 编译 + Jest 并行测试消耗大量内存，默认 Node.js 堆大小不够 |
| **解决** | 在 `ZodProfile.test_cmd` 中设置 `NODE_OPTIONS=--max-old-space-size=4096`，并在 `_gen_trajs.sh` 中通过 `--memory=10g` 限制容器内存 |
| **代码** | `swesmith/profiles/typescript.py` 第 196 行 |

### 4.4 部署层面的坑

#### 坑 12：Docker 容器无法访问宿主机代理

| 项目 | 详情 |
|------|------|
| **现象** | SWE-agent 容器内 `git clone` 超时，无法访问 GitHub |
| **根因** | 宿主机代理监听 `localhost`，容器内 `localhost` 指向容器自身，两者网络命名空间隔离 |
| **解决** | 使用 socat 将代理转发到 Docker 网桥地址 `172.17.0.1:10819`，在 Agent 配置中通过 `propagate_env_variables` 注入代理环境变量 |
| **代码** | `agent/swesmith_gen_glm_ts.yaml` 第 38-46 行；`agent/_gen_trajs.sh` 第 65-161 行 |

**问题拓扑：**

```
宿主机 127.0.0.1:7890 (代理)         Docker 容器 127.0.0.1 (容器自身)
        ↑ 容器无法到达                         ↑ 指向自己，无代理
```

Docker 容器有独立的网络命名空间，容器内 `127.0.0.1` 是容器自己的 loopback，不是宿主机。
宿主机代理只绑定了 `127.0.0.1`，不接受来自 Docker 网桥（`172.17.0.1`）的连接。
因此容器内无论设 `127.0.0.1:7890` 还是 `172.17.0.1:7890`，都连不上代理。

**解决方案——socat 端口转发，分三步：**

**Step 1：在宿主机启动 socat 做桥接**

```bash
# 监听 Docker 网桥 IP 的 10819 端口，转发到本机代理 7890
socat TCP-LISTEN:10819,bind=172.17.0.1,reuseaddr,fork TCP:127.0.0.1:7890
```

- `bind=172.17.0.1`：绑定到 Docker 默认网桥的网关地址，容器可通过此 IP 访问宿主机
- `fork`：每个连接 fork 子进程处理，支持并发
- `TCP:127.0.0.1:7890`：将流量转发到宿主机上实际代理的监听端口

此时网络拓扑变为：

```
容器 → 172.17.0.1:10819 → socat → 127.0.0.1:7890 → 代理 → 外网
```

**Step 2：设置环境变量（宿主机 shell）**

```bash
export HTTP_PROXY=http://172.17.0.1:10819
export HTTPS_PROXY=http://172.17.0.1:10819
export ALL_PROXY=http://172.17.0.1:10819
export http_proxy=http://172.17.0.1:10819
export https_proxy=http://172.17.0.1:10819
export all_proxy=http://172.17.0.1:10819
export NO_PROXY=127.0.0.1
export no_proxy=127.0.0.1
```

大小写都要设：`git`/`curl` 读小写，`httpx`/`LiteLLM` 读大写。

**Step 3：Agent 配置透传变量到容器**

SWE-agent 启动容器时默认不继承宿主机环境变量。
在 `agent/swesmith_gen_glm_ts.yaml` 中配置 `propagate_env_variables`，
SWE-agent 会自动通过 `docker run -e HTTP_PROXY=... -e HTTPS_PROXY=...` 注入。

**Step 4（已内置）：`_gen_trajs.sh` 自动预检**

脚本启动时自动执行三层检测，避免容器跑半天才发现代理不通：
1. TCP 连接检测每个代理端口的可达性
2. 若代理在 localhost，额外检测 Docker 网桥网关 `172.17.0.1` 能否连通该端口
3. 若 `ALL_PROXY` 是 SOCKS 协议但 `socksio` 未安装，自动降级到 `HTTP_PROXY`

#### 坑 13：SOCKS 代理缺少 socksio 导致 LM 调用失败

| 项目 | 详情 |
|------|------|
| **现象** | `_gen_trajs.sh` 启动后所有 LM API 调用报 `No module named 'socksio'` 错误 |
| **根因** | `ALL_PROXY` 设置为 SOCKS 协议，但 httpx 的 SOCKS 支持需要 `socksio`（未默认安装） |
| **解决** | 在启动脚本中检测 SOCKS 协议 + socksio 可用性，不可用时自动 fallback 到 HTTP_PROXY |
| **代码** | `agent/_gen_trajs.sh` 第 37-57 行 |

#### 坑 14：SGLang 启动时 nvcc 编译失败

| 项目 | 详情 |
|------|------|
| **现象** | `sglang.launch_server` 启动时报 `fatal error: concepts: No such file or directory`（C++20 头文件缺失） |
| **根因** | NVCC 默认使用系统 g++（版本过旧，不支持 C++20），而 conda 环境自带更新的编译器 |
| **解决** | 脚本自动检测 conda 编译器路径，设置 `CC`/`CXX`/`CUDAHOSTCXX`/`NVCC_PREPEND_FLAGS=-ccbin` |
| **代码** | `scripts/train.serve_sglang.local.sh` 第 15-34 行 |

#### 坑 15：根分区空间不足导致构建/编译失败

| 项目 | 详情 |
|------|------|
| **现象** | SGLang JIT 编译或 TorchTune 训练时因磁盘空间不足失败 |
| **根因** | 默认缓存目录 `~/.cache` 和临时目录 `/tmp` 位于根分区，而根分区空间有限 |
| **解决** | 自动将 `XDG_CACHE_HOME`、`TVM_FFI_CACHE_DIR`、`TMPDIR` 重定向到数据分区的 `.cache` 和 `.tmp` 目录 |
| **代码** | `scripts/train.serve_sglang.local.sh` 第 36-51 行 |

#### 坑 16：TorchTune checkpoint 缺少 config.json

| 项目 | 详情 |
|------|------|
| **现象** | SGLang 加载 TorchTune 微调后的 checkpoint 时报 `config.json not found` |
| **根因** | TorchTune 全量微调只输出权重文件，不复制 `config.json`（模型架构定义文件） |
| **解决** | SGLang 启动脚本自动从原始 tokenizer 目录复制 `config.json` 到 checkpoint 目录 |
| **代码** | `scripts/train.serve_sglang.local.sh` 第 63-70 行 |

---

## 五、关键产物清单

### 新增文件

| 文件路径 | 行数 | 用途 |
|----------|------|------|
| `swesmith/profiles/typescript.py` | 457 | TS Profile 基类 + 7 个仓库 Profile |
| `swesmith/bug_gen/adapters/typescript.py` | 271 | TS AST 解析适配器 |
| `scripts/ts_standard_pipeline.py` | 636 | TS 端到端任务实例生成流水线 |
| `scripts/auto_profile_ts.py` | 369 | 自动 Profile 生成器 |
| `agent/swesmith_gen_glm_ts.yaml` | 89 | TS 轨迹生成 Agent 配置 |
| `agent/swesmith_infer_ts.yaml` | 138 | TS 推理评测 Agent 配置 |
| `configs/bug_gen/ts_modify.yml` | 67 | TS LLM Bug Modify 配置 |
| `configs/bug_gen/ts_rewrite.yml` | 40 | TS LLM Bug Rewrite 配置 |
| `configs/train/full_ft_qwen_7b_local.yml` | 92 | 本地 7B 全量微调配置 |
| `scripts/train.prepare_sft_local.sh` | 48 | 轨迹转 SFT 脚本 |
| `scripts/train.run_ft_torchtune.local.sh` | 74 | 本地 TorchTune 训练脚本 |
| `scripts/train.serve_sglang.local.sh` | 102 | 本地 SGLang 服务脚本 |
| `swesmith/train/traj_mgr/validate_len_stats.py` | 96 | 训练数据长度校验 |
| `docs/guides/ts_pipeline_overview.md` | 65 | TS 流水线概览 |
| `docs/guides/ts_three_pipelines.md` | 334 | 三段式操作手册 |
| `WORKFLOW.md` | 97 | 快速参考手册 |

### 重写/修改文件

| 文件路径 | 修改内容 |
|----------|----------|
| `agent/_gen_trajs.sh` | 新增 ~130 行代理预检 + SOCKS 降级 + 轨迹后检 |
| `docs/guides/train_swe_agent.md` | 新增本地训练章节 |
| 3 个 `snake_case` 兼容入口脚本 | 转发到旧命名脚本 |

---

## 六、数据统计

| 指标 | 数值 |
|------|------|
| 新增/修改文件总数 | 30+ |
| 新增代码行数 | ~3,000+ |
| 覆盖的 TS 仓库 | 7 个（手工） + 自动生成支持 |
| 解决的具体问题 | 16 个（语言 5 + 配置 3 + 性能 3 + 部署 5） |
| 文档页面 | 4 份（~830 行） |
| 端到端覆盖步骤 | 环境构建 → Bug 生成 → 验证 → Issue → 轨迹 → SFT → 训练 → 服务 → 评测 |
