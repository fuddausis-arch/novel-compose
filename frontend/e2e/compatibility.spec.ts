import { test, expect } from '@playwright/test';

/**
 * 关键路径兼容性测试
 * - 覆盖 1920x1080、1366x768、768x1024 三种 viewport
 * - 验证核心布局元素可见且无水平溢出
 */

const VIEWPORTS = [
  { name: '桌面 1920x1080', width: 1920, height: 1080 },
  { name: '笔记本 1366x768', width: 1366, height: 768 },
  { name: '平板竖屏 768x1024', width: 768, height: 1024 },
];

for (const viewport of VIEWPORTS) {
  test.describe(`viewport: ${viewport.name}`, () => {
    test.use({ viewport: { width: viewport.width, height: viewport.height } });

    test('页面布局元素可见且无水平溢出', async ({ page }) => {
      await page.goto('/#/projects/1/chat');

      const header = page.locator('header');

      // 验证导航按钮可见
      await expect(header.getByRole('button', { name: '对话', exact: true })).toBeVisible();
      await expect(header.getByRole('button', { name: '写作', exact: true })).toBeVisible();

      // 验证项目选择器可见
      await expect(page.locator('header button:has(.lucide-book-open)')).toBeVisible();

      // 校验无水平滚动条（布局未撑破视口）
      const hasHorizontalOverflow = await page.evaluate(() => {
        const root = document.documentElement;
        return root.scrollWidth > root.clientWidth;
      });
      expect(hasHorizontalOverflow).toBe(false);
    });

    test('导航响应式表现', async ({ page }) => {
      await page.goto('/#/projects/1/chat');

      const header = page.locator('header');

      // 验证导航按钮在所有视口下可见（nav 有 overflow-x-auto）
      await expect(header.getByRole('button', { name: '对话', exact: true })).toBeVisible();
      await expect(header.getByRole('button', { name: '写作', exact: true })).toBeVisible();
      await expect(header.getByRole('button', { name: '规划', exact: true })).toBeVisible();

      // 点击导航按钮验证导航功能正常
      await header.getByRole('button', { name: '写作', exact: true }).click();
      await expect(page).toHaveURL(/#\/projects\/1\/write/);
    });
  });
}
