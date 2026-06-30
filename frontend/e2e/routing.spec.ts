import { test, expect, type Page } from '@playwright/test';

const TEST_PREFIX = 'RoutingE2E';

async function createTestProject(page: Page) {
  const title = `${TEST_PREFIX}-${Date.now()}`;
  const res = await page.request.post('/api/projects', {
    data: {
      title,
      genre: '玄幻',
      summary: '路由测试用项目',
      style: '轻松',
    },
  });
  expect(res.ok()).toBeTruthy();
  const project = await res.json();
  return { projectId: project.id as number, title };
}

async function deleteTestProject(page: Page, projectId: number) {
  const res = await page.request.delete(`/api/projects/${projectId}`);
  expect([200, 204, 404]).toContain(res.status());
}

test.describe('多页面路由', () => {
  test('默认跳转到项目中心', async ({ page }) => {
    await page.goto('/');
    await expect(page).toHaveURL(/.*#\/projects$/);
    await expect(page.getByText('我的作品').first()).toBeVisible();
  });

  test('从项目中心进入工作台', async ({ page }) => {
    const { projectId } = await createTestProject(page);

    try {
      await page.goto('/#/projects');
      const firstCard = page.getByTestId('project-card').first();
      await expect(firstCard).toBeVisible();
      await firstCard.click();

      await expect(page).toHaveURL(new RegExp(`.*#/projects/${projectId}/dashboard`));
      await expect(page.getByText('工作台').first()).toBeVisible();
    } finally {
      await deleteTestProject(page, projectId);
    }
  });

  test('顶部导航切换页面', async ({ page }) => {
    const { projectId } = await createTestProject(page);

    try {
      await page.goto(`/#/projects/${projectId}/dashboard`);
      await expect(page.getByRole('button', { name: '工作台', exact: true })).toBeVisible();

      await page.getByRole('button', { name: '写作', exact: true }).click();
      await expect(page).toHaveURL(new RegExp(`.*#/projects/${projectId}/write`));

      await page.getByRole('button', { name: '资产', exact: true }).click();
      await expect(page).toHaveURL(new RegExp(`.*#/projects/${projectId}/assets`));
    } finally {
      await deleteTestProject(page, projectId);
    }
  });
});
