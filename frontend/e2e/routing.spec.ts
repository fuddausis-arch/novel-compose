import { test, expect } from '@playwright/test';

test.describe('多页面路由', () => {
  test('默认跳转到项目对话页', async ({ page }) => {
    await page.goto('/');

    // 根路由自动重定向到最近项目的对话页
    await expect(page).toHaveURL(/#\/projects\/\d+\/chat/, { timeout: 15000 });
  });

  test('导航切换页面', async ({ page }) => {
    await page.goto('/#/projects/1/chat');

    const header = page.locator('header');

    // 点击"写作"导航按钮
    await header.getByRole('button', { name: '写作', exact: true }).click();
    await expect(page).toHaveURL(/#\/projects\/1\/write/);

    // 点击"资产"导航按钮
    await header.getByRole('button', { name: '资产', exact: true }).click();
    await expect(page).toHaveURL(/#\/projects\/1\/assets/);
  });

  test('更多下拉菜单导航', async ({ page }) => {
    await page.goto('/#/projects/1/chat');

    const header = page.locator('header');

    // 点击"更多"按钮打开下拉菜单
    await header.getByRole('button', { name: '更多', exact: true }).click();

    // 在下拉菜单中点击"工作台"
    await page.getByRole('button', { name: '工作台', exact: true }).click();
    await expect(page).toHaveURL(/#\/projects\/1\/dashboard/);
  });
});
