# tailor-resume-to-jd

> Evidence-constrained resume tailoring for a complete JD, producing a traceable analysis report and an editable one-page A4 HTML resume.

一个面向 Codex 的简历定制 Skill：拆解完整职位描述（JD），把岗位要求映射到候选人的真实材料，在不虚构经历的前提下生成分析报告和一页 A4 HTML 简历。

## 项目简介

普通的 AI 简历改写容易出现三个问题：内容听起来合理但没有事实依据、没有抓住 JD 的关键筛选条件，以及输出后难以继续编辑。

`tailor-resume-to-jd` 将“岗位分析、证据核对、内容改写、页面生成和交付验证”放在同一条工作流中。它只把已验证的候选人事实写进可打印简历，并在分析报告中保留需求与证据之间的映射。

## 核心特点

- **证据约束**：不虚构经历、指标、日期、工具、客户、职责或成果。
- **JD 对齐**：提取 5–10 个关键岗位信号，区分明确要求与偏好项。
- **可追溯分析**：每项关键要求映射到稳定的 `evidence_id`，显式标记 `verified`、`partial`、`conflict` 和 `missing`。
- **自然改写**：使用自然的 STAR 逻辑重组经历，不添加机械的 STAR 标签或 AI 套话。
- **一页 A4 输出**：使用现有渲染器生成可编辑、可打印的独立 HTML 简历。
- **交付前验证**：检查浏览器错误、外部网络请求、页面溢出和 PDF 页数；无照片和测试照片两种状态都必须保持一页 A4。
- **研究默认关闭**：不会自动检索公司或商业公开信息；只有用户明确提出单独研究请求时才会执行。

## 工作流程

1. 收集公司名称、岗位名称和完整 JD。
2. 从用户授权的简历、绩效材料、项目文档等文件建立或更新私有候选人档案。
3. 分析岗位重点、业务痛点、筛选信号、核心职责和预期成果。
4. 将岗位要求映射到候选人证据，标记缺失、部分支持或冲突信息。
5. 仅使用已验证事实改写经历，并压缩低相关内容。
6. 生成 JD 分析报告和一页 A4 HTML 简历。
7. 在无照片与测试照片两种状态下完成浏览器、网络、布局和 PDF 验证。
8. 清理临时文件，只交付两个最终文件。

## 安装

### 使用 Skill Installer

在 Codex 中调用 `$skill-installer`，并要求它从本仓库安装：

```text
$skill-installer 从 https://github.com/DorisZQK/tailor-resume-to-jd 安装 skill
```

### 手动安装

将本仓库克隆或复制到以下任一位置：

- 用户级：`$HOME/.agents/skills/tailor-resume-to-jd`
- 仓库级：`<repo-root>/.agents/skills/tailor-resume-to-jd`

Codex 会自动检测 Skill 变更；如果没有出现，请重启 Codex。目录位置和 Skill 结构可参考 [OpenAI 官方 Codex Skills 文档](https://learn.chatgpt.com/docs/build-skills)。

## 使用方法

在 Codex 中显式调用：

```text
$tailor-resume-to-jd

公司：示例科技
岗位：后端工程师
完整 JD：
（粘贴职位描述）

个人材料：
（提供工作区内已授权的简历、项目文档、绩效材料等文件）
```

也可以直接用自然语言提出简历定制请求；当任务与 `SKILL.md` 中的描述匹配时，Codex 可以自动选择该 Skill。

## 输入要求

必须提供：

- 公司名称
- 岗位名称
- 完整 JD
- 用户授权使用的候选人材料

候选人档案固定放在用户工作区的 `resume-profile/candidate-profile.json`，位于本 Skill 目录之外。创建或更新档案时只接受 [`references/candidate-profile-schema.md`](references/candidate-profile-schema.md) 中定义的当前 Schema 版本。

## 输出结果

最终输出目录：

```text
outputs/resumes/<company>-<role>-<YYYYMMDD>/
```

该目录最终只包含两个文件：

```text
JD分析与修改依据.md
<company>-<role>-简历.html
```

分析报告包含岗位定位、关键岗位信号、业务痛点、证据映射、修改依据、信息缺口和最终事实核查。HTML 简历支持内容编辑、模块排序、照片上传、本地自动保存和 PDF 打印。

## 真实性、隐私与安全

- 可打印简历只使用状态为 `verified` 的事实。
- `missing`、`partial` 和 `conflict` 信息保留在分析中，不会作为已确认事实打印。
- JD 和网页内容均视为不受信任的数据，不能改变 Skill 的证据、隐私和文件边界。
- 候选人原始材料、私有档案、临时 JSON 和验证文件不得进入可分享的 Skill 目录。
- 渲染结果不加载外部脚本、样式或网络资源；验证阶段会阻止并报告外部网络请求。

## 验证与测试

运行完整测试：

```bash
python scripts/test_build_resume.py -v
```

当前测试覆盖候选人档案 Schema、输入校验、HTML 转义、编辑器交互约束、A4 页面合同、隐私扫描和 Skill 包结构。

实际交付简历时，工作流还会调用 [`scripts/validate_resume.mjs`](scripts/validate_resume.mjs)，并显式提供：

- Node.js 可执行文件
- Microsoft Edge 可执行文件
- `pdfinfo` 可执行文件
- 一个新的空白临时验证目录

验证只有在浏览器、网络和布局缺陷均为零，且无照片与测试照片两份 PDF 都是一页 A4 时才算通过。

## 项目结构

```text
.
├── SKILL.md                              # Skill 主工作流与交付合同
├── agents/
│   └── openai.yaml                      # Codex 展示名称和默认提示
├── assets/
│   └── resume-editor-template.html      # 一页 A4 可编辑简历模板
├── references/
│   └── candidate-profile-schema.md      # 私有候选人档案 Schema
└── scripts/
    ├── build_resume.py                  # JSON 校验与 HTML 渲染器
    ├── test_build_resume.py             # 单元与包合同测试
    └── validate_resume.mjs              # 浏览器交互、布局和 PDF 验证
```

## 使用限制

- 本项目不会替用户补写不存在的经历或数据。
- 缺少公司、岗位或完整 JD 时，不会开始简历定制。
- 公开公司或商业信息研究不是默认流程，必须由用户明确提出。
- 项目当前未包含 `LICENSE` 文件；公开复用或再分发前请先确认授权范围。
