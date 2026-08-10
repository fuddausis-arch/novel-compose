import { test, expect } from '@playwright/test';

test.describe('首页冒烟测试', () => {
  test('首页加载并显示正确标题', async ({ page }) => {
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

    await page.goto('/');

    // 验证页面标题（index.html 中的 <title>NovelAgent</title>）
    await expect(page).toHaveTitle(/NovelAgent/i);

    // 验证页面最终显示内容：跳转到项目对话页（有项目时）或显示空状态（无项目时）
    try {
      await expect(page).toHaveURL(/#\/projects\/\d+\/chat/, { timeout: 15000 });
    } catch {
      await expect(page.getByText('还没有作品')).toBeVisible();
    }

    // 打印所有控制台错误，便于定位
    if (errors.length > 0) {
      console.error('控制台错误:', JSON.stringify(errors, null, 2));
    }
  });

  test('导航栏可见', async ({ page }) => {
    await page.goto('/#/projects/1/chat');

    const header = page.locator('header');

    // 验证主导航按钮可见
    await expect(header.getByRole('button', { name: '对话', exact: true })).toBeVisible();
    await expect(header.getByRole('button', { name: '写作', exact: true })).toBeVisible();

    // 验证项目选择器可见（包含 BookOpen 图标的按钮）
    await expect(page.locator('header button:has(.lucide-book-open)')).toBeVisible();
  });

  test('设置页可访问', async ({ page }) => {
    await page.goto('/#/settings');

    // 验证设置页标题可见
    await expect(page.getByText('全局设置')).toBeVisible();

    // 验证返回按钮可见
    await expect(page.getByRole('button', { name: /返回/ })).toBeVisible();
  });
});
