import { test, expect, type Page } from '@playwright/test';

const TEST_PREFIX = 'E2E';

function captureConsoleErrors(page: Page) {
  const errors: { type: string; text: string; location: string; stack?: string }[] = [];
  page.on('console', (msg) => {
    if (msg.type() === 'error') {
      errors.push({
        type: msg.type(),
        text: msg.text(),
        location: `${msg.location().url}:${msg.location().lineNumber}:${msg.location().columnNumber}`,
        stack: msg.args()[0]?.toString(),
      });
    }
  });
  page.on('pageerror', (err) => {
    errors.push({ type: 'pageerror', text: err.message, location: '', stack: err.stack });
  });
  return errors;
}

function dumpConsoleErrors(errors: { type: string; text: string; location: string; stack?: string }[]) {
  if (errors.length > 0) {
    console.error('控制台错误:', JSON.stringify(errors, null, 2));
  }
}

/**
 * 拦截 LLM 相关接口，返回可控的 Mock 数据
 */
async function mockGenerationApis(page: Page) {
  // 题材模板下拉
  await page.route('**/api/projects/templates/genres', async (route) => {
    await route.fulfill({ status: 200, body: JSON.stringify([]) });
  });

  // 规划 SSE 流：模拟 AI 返回一卷三章规划
  await page.route('**/api/planning/run/stream**', async (route) => {
    const body = [
      'event: node\ndata: {"node":"analyze_requirements","progress":20}\n\n',
      'event: node\ndata: {"node":"generate_volume_plan","progress":60}\n\n',
      'event: done\ndata: {"status":"pending","thread_id":"e2e-thread-001","volume_plan":{"volumes":[{"name":"卷一","chapters":3}]},"outline":{"chapters":[{"chapter":1,"title":"开篇","summary":"主角登场"},{"chapter":2,"title":"冲突","summary":"矛盾升级"},{"chapter":3,"title":"转折","summary":"局势逆转"}]},"settings":{"characters":[{"name":"主角","role":"protagonist","personality":"坚毅"}],"world_settings":[{"category":"修炼体系","title":"等级","content":"炼气-筑基"}]}}\n\n',
    ].join('');
    await route.fulfill({
      status: 200,
      headers: { 'Content-Type': 'text/event-stream', 'Cache-Control': 'no-cache' },
      body,
    });
  });

  // 规划冲突检测返回空
  await page.route('**/api/planning/detect', async (route) => {
    await route.fulfill({ status: 200, body: JSON.stringify({ issues: [] }) });
  });

  // 采纳/拒绝规划接口
  await page.route('**/api/planning/resume', async (route) => {
    await route.fulfill({
      status: 200,
      body: JSON.stringify({
        status: 'approved',
        thread_id: 'e2e-thread-001',
        volume_plan: { volumes: [{ name: '卷一', chapters: 3 }] },
        outline: { chapters: [{ chapter: 1, title: '开篇', summary: '主角登场' }] },
        settings: { characters: [], world_settings: [] },
      }),
    });
  });
}

/**
 * 通过 API 创建测试项目并返回 projectId
 */
async function createTestProject(page: Page) {
  const title = `${TEST_PREFIX}-卷纲-${Date.now()}`;
  const res = await page.request.post('/api/projects', {
    data: {
      title,
      genre: '玄幻',
      summary: 'E2E 测试用项目',
      style: '轻松',
    },
  });
  expect(res.ok()).toBeTruthy();
  const project = await res.json();
  return { projectId: project.id as number, title };
}

/**
 * 通过 API 删除测试项目
 */
async function deleteTestProject(page: Page, projectId: number) {
  const res = await page.request.delete(`/api/projects/${projectId}`);
  expect([200, 204, 404]).toContain(res.status());
}

test.describe('生成流程', () => {
  test('创建项目流程', async ({ page }) => {
    const errors = captureConsoleErrors(page);
    await mockGenerationApis(page);
    let createdProjectId: number | null = null;

    try {
      await page.goto('/#/projects/1/chat');

      // 通过项目下拉菜单打开新建项目弹窗
      await page.locator('header button:has(.lucide-book-open)').click();
      await page.getByRole('button', { name: '新建项目' }).click();
      await expect(page.getByText('新建项目')).toBeVisible();

      const uiTitle = `${TEST_PREFIX}-UI-${Date.now()}`;
      await page.getByPlaceholder('请输入作品标题').fill(uiTitle);
      await page.getByPlaceholder('如：玄幻 / 科幻 / 都市').fill('科幻');
      await page.getByPlaceholder('简单描述一下作品...').fill('从 UI 创建的项目');

      // 拦截 POST /api/projects 响应
      const createPromise = page.waitForResponse((res) =>
        res.url().includes('/api/projects') && res.request().method() === 'POST'
      );
      await page.getByRole('button', { name: '创建', exact: true }).click();
      const createRes = await createPromise;
      expect(createRes.ok()).toBeTruthy();
      createdProjectId = (await createRes.json()).id as number;

      // 验证跳转到新项目的对话页
      await expect(page).toHaveURL(/#\/projects\/\d+\/chat/, { timeout: 15000 });

      // 验证弹窗已关闭
      await expect(page.getByPlaceholder('请输入作品标题')).not.toBeVisible();
    } finally {
      dumpConsoleErrors(errors);
      if (createdProjectId) {
        await deleteTestProject(page, createdProjectId);
      }
    }
  });

  test('生成卷纲流程 - Mock SSE', async ({ page }) => {
    const errors = captureConsoleErrors(page);
    const { projectId } = await createTestProject(page);
    await mockGenerationApis(page);

    try {
      // 导航到测试项目的对话页
      await page.goto(`/#/projects/${projectId}/chat`);

      // 等待导航栏加载
      await expect(page.locator('header button:has(.lucide-book-open)')).toBeVisible();

      // 点击"规划"导航按钮进入规划页
      await page.locator('header').getByRole('button', { name: '规划', exact: true }).click();
      await expect(page).toHaveURL(new RegExp(`#\/projects\/${projectId}\/planning`));

      // 等待规划页加载完成
      await expect(page.getByRole('heading', { name: '全书规划', exact: true })).toBeVisible({ timeout: 10000 });

      // 点击"开始全书规划"按钮触发 SSE 流
      await page.getByRole('button', { name: '开始全书规划' }).click();

      // 验证 SSE 流结果已渲染：待审核状态
      await expect(page.getByText('待审核')).toBeVisible({ timeout: 15000 });

      // 验证导入检测完成
      await expect(page.getByText('未检测到冲突或错误')).toBeVisible({ timeout: 10000 });

      // 验证"一键采纳并导入"按钮可点击
      await expect(page.getByRole('button', { name: '一键采纳并导入' })).toBeEnabled();
    } finally {
      dumpConsoleErrors(errors);
      await deleteTestProject(page, projectId);
    }
  });
});
