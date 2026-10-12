import { defineConfig } from 'vitepress'
import markdownItTaskCheckbox from 'markdown-it-task-checkbox'


// https://vitepress.dev/reference/site-config
export default defineConfig({
  lang: 'zh-CN',
  title: "NexaMind Enterprise",
  description: "基于 Yuxi 二次开发的企业客服与售后自动化平台",
  base: '/Yuxi/',
  ignoreDeadLinks: [
    /localhost/,
    /CONTRIBUTING$/,
    /docker-compose\.yml$/,
    /^\.\/intro\//
  ],
  markdown: {
    config: (md) => {
      md.use(markdownItTaskCheckbox)
    }
  },
  themeConfig: {
    // https://vitepress.dev/reference/default-theme-config
    logo: "/favicon.svg",
    nav: [
      { text: '快速开始', link: '/intro/quick-start' },
      { text: '智能体开发', link: '/agents/agents-config' },
      { text: '企业客服', link: '/enterprise/architecture' }
    ],

    sidebar: [
      {
        text: '简介',
        items: [
          { text: '什么是 Yuxi？', link: '/intro/project-overview' },
          { text: '快速开始', link: '/intro/quick-start' },
          { text: '模型配置', link: '/intro/model-config' },
          { text: '知识库与知识图谱', link: '/intro/knowledge-base' },
          { text: '知识库评估', link: '/intro/evaluation' }
        ]
      },
      {
        text: '智能体开发',
        items: [
          { text: '智能体配置', link: '/agents/agents-config' },
          { text: 'Langfuse 集成', link: '/agents/langfuse-integration' },
          { text: '工具系统', link: '/agents/tools-system' },
          { text: '中间件', link: '/agents/middleware' },
          { text: '沙盒架构与设计', link: '/agents/sandbox-architecture' },
          { text: 'MCP 集成', link: '/agents/mcp-integration' },
          { text: 'Skills 管理', link: '/agents/skills-management' },
          { text: 'SubAgents 管理', link: '/agents/subagents-management' }
        ]
      },
      {
        text: '企业客服二次开发',
        items: [
          { text: '架构', link: '/enterprise/architecture' },
          { text: '售后 Workflow', link: '/enterprise/workflow' },
          { text: '多智能体设计', link: '/enterprise/multi-agent-design' },
          { text: 'RAG 与 Grounding', link: '/enterprise/rag-and-grounding' },
          { text: 'MCP 与领域 Tools', link: '/enterprise/mcp-and-tools' },
          { text: '人工审批', link: '/enterprise/human-in-the-loop' },
          { text: '权限与租户', link: '/enterprise/permission-and-tenant' },
          { text: '幂等与错误', link: '/enterprise/idempotency-and-errors' },
          { text: '企业评测', link: '/enterprise/evaluation' },
          { text: '业务 Trace', link: '/enterprise/observability' },
          { text: '安全与部署风险', link: '/enterprise/security' },
          { text: 'Demo 指南', link: '/enterprise/demo-guide' },
          { text: '项目学习与面试教程', link: '/enterprise/learning-and-interview-tutorial' },
          { text: '面试问答', link: '/enterprise/interview-guide' },
          { text: '简历描述', link: '/enterprise/resume-description' },
          { text: '最终实施报告', link: '/enterprise/final-implementation-report' }
        ]
      },
      {
        text: '高级配置',
        items: [
          { text: '配置系统详解', link: '/advanced/configuration' },
          { text: '文档解析', link: '/advanced/document-processing' },
          { text: '品牌自定义', link: '/advanced/branding' },
          { text: '其他配置', link: '/advanced/misc' },
          { text: '生产部署', link: '/advanced/deployment' },
          { text: 'API Key 外部集成', link: '/advanced/api-key-integration' }
        ]
      },
      {
        text: '开发指南',
        items: [
          { text: '参与贡献', link: '/develop-guides/contributing' },
          { text: '开发路线图', link: '/develop-guides/roadmap' },
          { text: '版本变更记录', link: '/develop-guides/changelog' },
          { text: '界面设计规范', link: '/develop-guides/design' },
          { text: '测试规范', link: '/develop-guides/testing-guidelines' },
        ]
      }
    ],

    socialLinks: [
      { icon: 'github', link: 'https://github.com/xerrors/Yuxi' }
    ],

    footer: {
      message: 'NexaMind Enterprise 基于 Yuxi 二次开发，遵循 MIT License。',
      copyright: 'Copyright © 2025-present Yuxi contributors and NexaMind Enterprise contributors'
    },

    lastUpdated: {
      text: '最后更新时间',
      formatOptions: {
        dateStyle: 'full',
        timeStyle: 'medium'
      }
    },

    search: {
      provider: 'local'
    },

    docFooter: {
      prev: '上一页',
      next: '下一页'
    }
  },
})
