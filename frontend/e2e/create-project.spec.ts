import { test, expect, type Page } from '@playwright/test';

const TEST_PREFIX = 'TEST-CREATE';

async function cleanup(page: Page) {
  const res = await page.request.get('/api/projects');
  if (!res.ok()) return;
  const projects = await res.json();
  for (const p of projects) {
    if (p.title?.startsWith(TEST_PREFIX)) {
      await page.request.delete(`/api/projects/${p.id}`);
    }
  }
}

test.describe('创建项目功能', () => {
  test.beforeEach(async ({ page }) => {
    await cleanup(page);
  });

  test.afterEach(async ({ page }) => {
    await cleanup(page);
  });

  test('从项目下拉打开新建弹窗', async ({ page }) => {
    await page.goto('/#/projects/1/chat');

    // 等待导航栏渲染
    await expect(page.locator('header button:has(.lucide-book-open)')).toBeVisible();

    // 点击项目选择器按钮打开下拉菜单
    await page.locator('header button:has(.lucide-book-open)').click();

    // 在下拉菜单中点击"新建项目"
    await page.getByRole('button', { name: '新建项目' }).click();

    // 验证弹窗显示：标题和字段标签可见
    await expect(page.getByText('新建项目')).toBeVisible();
    await expect(page.getByText('作品标题')).toBeVisible();
    await expect(page.getByPlaceholder('请输入作品标题')).toBeVisible();
  });

  test('填写表单并创建项目', async ({ page }) => {
    await page.goto('/#/projects/1/chat');

    // 打开新建项目弹窗
    await page.locator('header button:has(.lucide-book-open)').click();
    await page.getByRole('button', { name: '新建项目' }).click();

    const title = `${TEST_PREFIX}-${Date.now()}`;
    await page.getByPlaceholder('请输入作品标题').fill(title);
    await page.getByPlaceholder('如：玄幻 / 科幻 / 都市').fill('玄幻');
    await page.getByPlaceholder('简单描述一下作品...').fill('测试');

    // 点击"创建"按钮
    await page.getByRole('button', { name: '创建', exact: true }).click();

    // 验证跳转到新项目的对话页
    await expect(page).toHaveURL(/#\/projects\/\d+\/chat/, { timeout: 15000 });

    // 验证项目标题出现在项目选择器中
    await expect(page.locator('header button:has(.lucide-book-open)')).toContainText(title);
  });

  test('取消创建', async ({ page }) => {
    await page.goto('/#/projects/1/chat');

    // 打开新建项目弹窗
    await page.locator('header button:has(.lucide-book-open)').click();
    await page.getByRole('button', { name: '新建项目' }).click();

    // 验证弹窗已打开
    await expect(page.getByPlaceholder('请输入作品标题')).toBeVisible();

    // 点击"取消"按钮
    await page.getByRole('button', { name: '取消' }).click();

    // 验证弹窗已关闭（输入框不可见）
    await expect(page.getByPlaceholder('请输入作品标题')).not.toBeVisible();
  });
});
