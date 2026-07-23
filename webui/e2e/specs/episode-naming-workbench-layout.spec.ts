import { expect, test } from '@playwright/test';

const rule = {
  added: true,
  deleted: false,
  archived: false,
  dpi: '1080p',
  eps_collect: false,
  filter: '',
  group_name: '樱桃花字幕组',
  id: 11,
  official_title: '尼古喵喵',
  episode_offset: 0,
  season_offset: 0,
  poster_link: null,
  rss_link: '',
  rule_name: '尼古喵喵',
  save_path: '/downloads/Bangumi',
  season: 1,
  season_raw: '1',
  source: 'mikan',
  subtitle: '简中',
  title_raw: '尼古喵喵',
  year: '2026',
  air_weekday: null,
  weekday_locked: false,
  needs_review: false,
  needs_review_reason: null,
  preferred_group: null,
  preferred_resolution: null,
  episode_type: 'episode',
};

const group = {
  id: 1,
  official_title: '尼古喵喵',
  year: '2026',
  season: 1,
  episode_type: 'episode',
  poster_link: null,
  air_weekday: null,
  migration_review: false,
  migration_review_reason: null,
};

const plans = Array.from({ length: 6 }, (_, index) => {
  const episode = index === 5 ? null : index + 1;
  return {
    id: index + 1,
    group_id: 1,
    rule_id: 11,
    downloader_type: 'qbittorrent',
    task_id: `task-${index + 1}`,
    file_index: 0,
    file_kind: 'video',
    subtitle_of_id: null,
    baseline_path: episode ? `${episode}.mp4` : '02.mp4',
    current_path: episode ? `${episode}.mp4` : '02.mp4',
    default_snapshot: episode ? JSON.stringify({ episode }) : '{}',
    manual_fields: null,
    required_fields: '["episode"]',
    target_path: episode
      ? `尼古喵喵 (2026) S01E${String(episode).padStart(2, '0')}.mp4`
      : null,
    anomaly_reason: episode ? null : '缺少字段: episode',
    origin: 'new',
    discovery_state: 'active',
  };
});

const detail = { group, rules: [rule], plans };
const summaries = [
  {
    group,
    rule_ids: [rule.id],
    rule_count: 1,
    plan_count: plans.length,
    anomaly_count: 1,
  },
];

async function mockWorkbench(page: import('@playwright/test').Page) {
  await page.addInitScript(() => {
    localStorage.setItem('isLoggedIn', 'true');
    localStorage.setItem('lang', 'zh-CN');
  });
  await page.route('**/api/v1/**', async (route) => {
    const url = new URL(route.request().url());
    if (
      url.pathname === '/api/v1/bangumi-groups/1/refresh' ||
      url.pathname === '/api/v1/bangumi-groups/1'
    ) {
      await route.fulfill({ json: detail });
      return;
    }
    if (url.pathname === '/api/v1/bangumi-groups') {
      await route.fulfill({ json: summaries });
      return;
    }
    if (url.pathname === '/api/v1/bangumi-groups/1/torrents') {
      await route.fulfill({ json: [] });
      return;
    }
    if (url.pathname.includes('/events')) {
      await route.abort();
      return;
    }
    await route.fulfill({ json: {} });
  });
}

test('expanded editor actions remain reachable in every supported layout', async ({
  page,
}) => {
  await mockWorkbench(page);

  for (const viewport of [
    { width: 1280, height: 720 },
    { width: 925, height: 912 },
    { width: 390, height: 844 },
  ]) {
    await page.setViewportSize(viewport);
    await page.goto('about:blank');
    await page.goto('/#/bangumi-torrents/1');

    const workbench = page.locator('.workbench');
    await expect(
      page.getByRole('button', { name: '编辑番剧信息' })
    ).toBeInViewport({ ratio: 1 });
    await expect(page.getByRole('button', { name: '刷新文件' })).toBeInViewport(
      { ratio: 1 }
    );
    await expect(page.getByRole('link', { name: '种子记录' })).toBeInViewport({
      ratio: 1,
    });

    await page.getByRole('button', { name: '编辑番剧信息' }).click();
    await expect(page.getByLabel('title')).toHaveValue('尼古喵喵');
    await page.getByRole('button', { name: '取消' }).click();

    await page.getByRole('button', { name: '调整归组' }).click();
    await expect(page.getByText('拆分为独立番剧')).toBeVisible();
    await page.getByRole('button', { name: '收起归组' }).click();

    await page.getByRole('button', { name: /E—.*樱桃花字幕组/ }).click();
    await page.getByLabel('episode').fill('2');
    const applyButton = page.getByRole('button', { name: '应用重命名' });

    const scrollState = await workbench.evaluate((element) => {
      element.scrollTop = element.scrollHeight;
      return {
        clientHeight: element.clientHeight,
        scrollHeight: element.scrollHeight,
        scrollTop: element.scrollTop,
      };
    });

    expect(scrollState.scrollHeight).toBeGreaterThan(scrollState.clientHeight);
    expect(scrollState.scrollTop).toBeGreaterThan(0);
    await expect(applyButton).toBeInViewport({ ratio: 1 });
    for (const name of ['重新解析', '恢复缺省', '仅保存', '应用重命名']) {
      await page.getByRole('button', { name }).click({ trial: true });
    }

    const captureDirectory = process.env.AB_E2E_CAPTURE_DIR;
    if (captureDirectory) {
      await page.screenshot({
        path: `${captureDirectory}/after-${viewport.width}x${viewport.height}.png`,
      });
    }
  }
});

test('torrent records provide a route-local way back to the workbench', async ({
  page,
}) => {
  await mockWorkbench(page);
  await page.setViewportSize({ width: 925, height: 912 });
  await page.goto('/#/bangumi-torrents/1');

  await page.getByRole('link', { name: '种子记录' }).click();
  await expect(page).toHaveURL(/view=torrents/);
  const backLink = page.getByRole('link', { name: '返回命名工作台' });
  await expect(backLink).toBeVisible();
  await expect(page.locator('.torrent-records-view')).toHaveCSS('opacity', '1');
  if (process.env.AB_E2E_CAPTURE_DIR) {
    await page.screenshot({
      path: `${process.env.AB_E2E_CAPTURE_DIR}/after-torrent-records-925x912.png`,
    });
  }
  await backLink.click();
  await expect(page).toHaveURL(/#\/bangumi-torrents\/1$/);
  await expect(page.getByRole('heading', { name: '尼古喵喵' })).toBeVisible();
});
