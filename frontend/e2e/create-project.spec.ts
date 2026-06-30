import { test, expect } from '@playwright/test';

const TEST_PREFIX = 'TEST-CREATE';

async function cleanup(page: any) {
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

  test('点击顶部新建项目按钮打开弹窗', async ({ page }) => {
    await page.goto('/#/projects');
    await expect(page.getByText('我的作品')).toBeVisible();

    const errors: string[] = [];
    page.on('console', (msg) => {
      if (msg.type() === 'error') errors.push(msg.text());
    });
    page.on('pageerror', (err) => errors.push(err.message));

    await page.getByRole('button', { name: '新建项目' }).click();
    await expect(page.getByText('新建项目').nth(1)).toBeVisible();
    await expect(page.getByPlaceholder('请输入作品标题')).toBeVisible();

    expect(errors).toEqual([]);
  });

  test('填写表单并创建项目后跳转工作台', async ({ page }) => {
    await page.goto('/#/projects');
    await page.getByRole('button', { name: '新建项目' }).click();

    const title = `${TEST_PREFIX}-${Date.now()}`;
    await page.getByPlaceholder('请输入作品标题').fill(title);
    await page.getByPlaceholder('如：玄幻 / 科幻 / 都市').fill('玄幻');
    await page.getByPlaceholder('简单描述一下作品...').fill('测试创建项目');

    const errors: string[] = [];
    page.on('console', (msg) => {
      if (msg.type() === 'error') errors.push(msg.text());
    });
    page.on('pageerror', (err) => errors.push(err.message));

    await page.getByRole('button', { name: '创建' }).click();

    await expect(page).toHaveURL(/#\/projects\/\d+\/dashboard/);
    await expect(page.getByRole('heading', { name: '工作台' })).toBeVisible();
    await expect(page.getByText(title)).toBeVisible();

    expect(errors).toEqual([]);
  });

  test('创建项目占位卡片也可打开弹窗', async ({ page }) => {
    await page.goto('/#/projects');
    await page.getByText('创建新项目').click();
    await expect(page.getByText('新建项目').nth(1)).toBeVisible();
  });
});
