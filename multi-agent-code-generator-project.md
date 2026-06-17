# 多Agent代码生成器项目书

> 本文档供AI系统读取，用于理解项目架构和执行代码生成任务

---

## 1. 项目概述

### 1.1 目标
构建一个多Agent协作的代码生成系统，通过角色隔离和流水线架构，自动将自然语言需求转换为高质量代码。

### 1.2 核心原则
- **写审分离**：创作者和审阅者必须是独立的Agent
- **数据驱动**：Agent间通过严格的数据协议通信，不依赖隐式上下文
- **反馈循环限制**：最多3次迭代，避免无限循环
- **持久化存储**：所有中间状态必须写入文件，不依赖内存

### 1.3 适用场景
- 根据需求描述生成完整项目
- 代码重构和优化
- 代码审查和质量提升
- 自动生成测试和文档

---

## 2. 核心架构

### 2.1 五阶段流水线

```
需求输入 → [创建] → [重建] → [精修] → [评审] → 输出
              ↑___________________________|
                    (反馈循环，最多3次)
```

### 2.2 Agent角色定义

| Agent | 职责 | 输入 | 输出 |
|-------|------|------|------|
| **Architect（架构师）** | 分析需求，设计系统架构 | 用户需求文本 | 架构文档、技术选型、模块划分 |
| **Coder（编码者）** | 根据架构编写代码 | 架构文档 | 源代码文件 |
| **Refiner（精修者）** | 优化代码质量、风格、性能 | 源代码 | 优化后的代码 |
| **Reviewer（审阅者）** | 独立审查代码质量 | 源代码 + 质量标准 | 审查报告、改进建议 |
| **Tester（测试者）** | 生成和运行测试 | 源代码 | 测试用例、测试报告 |
| **Documenter（文档者）** | 生成项目文档 | 源代码 + 架构 | README、API文档、注释 |

### 2.3 数据协议

每个Agent的输出必须包含：
```json
{
  "agent_id": "coder",
  "stage": "create",
  "timestamp": "2026-06-17T19:30:00Z",
  "artifacts": [
    {
      "type": "file",
      "path": "src/main.py",
      "content": "...",
      "metadata": {
        "lines": 150,
        "language": "python"
      }
    }
  ],
  "notes": "给下游Agent的说明",
  "status": "completed"
}
```

---

## 3. 工作流程详解

### 3.1 阶段一：创建（Create）

**执行者**：Architect + Coder

**步骤**：
1. Architect解析用户需求
2. 生成架构文档（技术栈、模块结构、接口定义）
3. Coder根据架构编写初始代码
4. 输出到 `output/v1/` 目录

**输出文件**：
- `architecture.md` - 架构设计文档
- `src/` - 源代码目录
- `requirements.txt` / `package.json` - 依赖配置

### 3.2 阶段二：重建（Rebuild）

**执行者**：Refiner

**步骤**：
1. 读取v1代码
2. 应用代码规范（lint、格式化）
3. 优化性能瓶颈
4. 改善代码结构
5. 输出到 `output/v2/` 目录

### 3.3 阶段三：精修（Refine）

**执行者**：Refiner + Tester

**步骤**：
1. 生成单元测试
2. 运行测试并修复失败用例
3. 添加类型注解
4. 完善错误处理
5. 输出到 `output/v3/` 目录

### 3.4 阶段四：评审（Review）

**执行者**：Reviewer（独立Agent）

**评审维度**：
- 功能完整性（是否满足需求）
- 代码质量（可读性、可维护性）
- 安全性（常见漏洞检查）
- 性能（时间/空间复杂度）
- 测试覆盖率

**输出**：
```json
{
  "score": 85,
  "passed": true,
  "issues": [
    {
      "severity": "warning",
      "file": "src/main.py",
      "line": 42,
      "message": "未处理的异常"
    }
  ],
  "suggestions": ["添加日志记录", "优化数据库查询"]
}
```

### 3.5 阶段五：反馈循环

**触发条件**：评审未通过（score < 80）

**流程**：
1. Reviewer的改进建议传回Coder
2. Coder针对性修改
3. 重新进入评审阶段
4. **最多循环3次**，超过则人工介入

---

## 4. 技术实现

### 4.1 技术栈

| 组件 | 选型 | 理由 |
|------|------|------|
| Agent框架 | 自研 / LangGraph | 需要精细控制流程 |
| LLM | Claude / GPT-4 | 代码生成能力强 |
| 存储 | 文件系统 + SQLite | 简单可靠，易于调试 |
| 代码分析 | AST解析 + ESLint/Pylint | 静态分析 |
| 测试运行 | pytest / Jest | 主流测试框架 |

### 4.2 目录结构

```
project/
├── input/
│   └── requirements.md          # 用户需求
├── output/
│   ├── v1/                      # 初始版本
│   ├── v2/                      # 重建版本
│   ├── v3/                      # 精修版本
│   └── final/                   # 最终输出
├── agents/
│   ├── architect.py
│   ├── coder.py
│   ├── refiner.py
│   ├── reviewer.py
│   ├── tester.py
│   └── documenter.py
├── protocols/
│   ├── schemas/                 # 数据协议schema
│   └── validators/              # 协议验证器
├── orchestrator.py              # 流程编排器
└── config.yaml                  # 配置
```

### 4.3 关键代码示例

#### 编排器核心逻辑

```python
class Orchestrator:
    def __init__(self):
        self.agents = {
            'architect': ArchitectAgent(),
            'coder': CoderAgent(),
            'refiner': RefinerAgent(),
            'reviewer': ReviewerAgent(),
            'tester': TesterAgent(),
            'documenter': DocumenterAgent()
        }
        self.max_iterations = 3
    
    async def run(self, requirements: str):
        # 阶段1: 创建
        architecture = await self.agents['architect'].process(requirements)
        code_v1 = await self.agents['coder'].process(architecture)
        
        # 阶段2: 重建
        code_v2 = await self.agents['refiner'].process(code_v1)
        
        # 阶段3: 精修
        code_v3 = await self.agents['tester'].process(code_v2)
        
        # 阶段4+5: 评审 + 反馈循环
        for iteration in range(self.max_iterations):
            review = await self.agents['reviewer'].process(code_v3)
            
            if review['passed']:
                break
            
            # 反馈改进
            code_v3 = await self.agents['coder'].refine(
                code_v3, 
                review['suggestions']
            )
        
        # 生成文档
        docs = await self.agents['documenter'].process(code_v3, architecture)
        
        return {
            'code': code_v3,
            'docs': docs,
            'review': review
        }
```

---

## 5. 工程挑战与解决方案

### 5.1 上下文卡死

**问题**：LLM上下文窗口有限，长代码会超限

**解决方案**：
- 分模块处理，每个Agent只处理相关代码片段
- 使用文件存储中间结果，不依赖对话历史
- 摘要机制：长代码先压缩再处理

### 5.2 字节损坏

**问题**：LLM生成的代码可能有语法错误

**解决方案**：
- 每个阶段后运行语法检查
- 自动修复常见错误（AST解析 + 修复）
- 失败时回滚到上一版本

### 5.3 超时陷阱

**问题**：某些Agent执行时间过长

**解决方案**：
- 设置每个阶段的超时时间
- 异步执行，支持进度查询
- 超时后保存当前状态，支持断点续传

### 5.4 API崩溃

**问题**：LLM API不稳定

**解决方案**：
- 重试机制（指数退避）
- 多模型降级（Claude → GPT-4 → 本地模型）
- 本地缓存常用prompt

---

## 6. 质量标准

### 6.1 代码质量指标

| 指标 | 目标值 | 检查工具 |
|------|--------|----------|
| 语法正确率 | 100% | 编译器/解释器 |
| 测试覆盖率 | >80% | pytest-cov / istanbul |
| 代码重复率 | <10% | jscpd / pylint |
| 复杂度 | <10 | eslint-complexity |
| 文档覆盖率 | 100% | 自定义检查 |

### 6.2 评审通过标准

- 功能完整性：满足所有需求点
- 无严重安全漏洞
- 测试全部通过
- 代码风格统一
- 文档完整清晰

---

## 7. 配置示例

```yaml
# config.yaml
project:
  name: "my-project"
  language: "python"
  framework: "fastapi"

agents:
  architect:
    model: "claude-3-opus"
    temperature: 0.3
    max_tokens: 4096
  
  coder:
    model: "claude-3-sonnet"
    temperature: 0.2
    max_tokens: 8192
  
  reviewer:
    model: "claude-3-opus"
    temperature: 0.1
    max_tokens: 2048

orchestration:
  max_iterations: 3
  timeout_seconds: 300
  auto_save: true
  
quality:
  min_score: 80
  require_tests: true
  require_docs: true
```

---

## 8. 执行指南（给AI系统）

### 8.1 当你需要生成代码时

1. **读取需求**：从 `input/requirements.md` 获取
2. **按阶段执行**：严格遵循五阶段流程
3. **持久化中间结果**：每个阶段输出写入对应目录
4. **验证数据协议**：确保输出符合JSON schema
5. **记录执行日志**：写入 `logs/YYYY-MM-DD.md`

### 8.2 当你需要审查代码时

1. **独立审查**：不参考生成过程的上下文
2. **按维度评分**：功能、质量、安全、性能、测试
3. **具体建议**：指出问题文件和行号
4. **客观判断**：score < 80 必须要求改进

### 8.3 错误处理

- 语法错误：自动修复或回滚
- 测试失败：分析原因并修复
- 超时：保存状态，提示用户
- API错误：重试或降级模型

---

## 9. 附录

### 9.1 相关资源

- 视频参考：多Agent自动写小说流程（古法编程-小周）
- 核心洞察：写审分离、数据隔离、反馈限制

### 9.2 版本历史

| 版本 | 日期 | 变更 |
|------|------|------|
| v1.0 | 2026-06-17 | 初始版本 |

---

*本文档由AI生成，供AI系统读取执行*
