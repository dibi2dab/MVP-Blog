#!/usr/bin/env node
/**
 * 티스토리 관리 페이지에서 글을 조회/삭제하는 일회성 운영 스크립트.
 *
 *   node scripts/manageTistoryPosts.js inspect 45 43
 *   node scripts/manageTistoryPosts.js delete 45 43
 *
 * GitHub Actions 에서 Secrets 의 카카오 계정으로 자동 로그인한 뒤 실행한다.
 * 로그에는 버튼/체크박스의 메타데이터만 남기고 페이지 HTML/토큰은 출력하지 않는다.
 */
import { chromium } from 'playwright';
import { tistoryConfig } from '../src/tistoryConfig.js';
import { ensureSession } from '../src/tistoryAuth.js';

const [mode = 'inspect', ...ids] = process.argv.slice(2);
const base = `https://${tistoryConfig.blogName}.tistory.com`;

async function describe(page) {
  return page.evaluate(() => {
    const visible = (el) => {
      const rect = el.getBoundingClientRect();
      return rect.width > 0 && rect.height > 0;
    };
    const items = [];
    for (const el of document.querySelectorAll(
      'button, a, input[type="checkbox"], [role="button"]'
    )) {
      if (!visible(el)) continue;
      items.push({
        tag: el.tagName.toLowerCase(),
        type: el.getAttribute('type') || '',
        id: el.id || '',
        name: el.getAttribute('name') || '',
        value: el.getAttribute('value') || '',
        text: (el.textContent || '').replace(/\s+/g, ' ').trim().slice(0, 40),
        cls: String(el.className || '').slice(0, 80),
        aria: el.getAttribute('aria-label') || '',
      });
    }
    return items;
  });
}

async function main() {
  const browser = await chromium.launch({ headless: tistoryConfig.headless });
  const context = await browser.newContext({ storageState: tistoryConfig.paths.storageState });
  try {
    const session = await ensureSession(context);
    console.log(`session=${session.method}`);
    const page = await context.newPage();
    page.setDefaultTimeout(tistoryConfig.timeout);
    page.on('dialog', (dialog) => dialog.accept().catch(() => {}));

    if (mode === 'inspect') {
      await page.goto(`${base}/manage/posts/`, { waitUntil: 'domcontentloaded' });
      await page.waitForTimeout(5000);
      console.log('=== /manage/posts/ ===');
      console.log(JSON.stringify(await describe(page), null, 2));

      for (const id of ids) {
        await page.goto(`${base}/manage/post/${id}`, { waitUntil: 'domcontentloaded' });
        await page.waitForTimeout(4000);
        console.log(`=== /manage/post/${id} ===`);
        console.log(JSON.stringify(await describe(page), null, 2));
      }
      return;
    }

    if (mode === 'delete') {
      await page.goto(`${base}/manage/posts/`, { waitUntil: 'domcontentloaded' });
      await page.waitForTimeout(5000);

      let selected = 0;
      for (const id of ids) {
        const box = page.locator(`input[type="checkbox"][value="${id}"]`).first();
        if (!(await box.count())) {
          console.log(`post ${id}: checkbox(value=${id}) not found`);
          continue;
        }
        await box.check({ force: true }).catch(() => {});
        selected += 1;
      }
      if (!selected) {
        console.log('no posts selected; aborting');
        return;
      }

      const del = page.getByRole('button', { name: /삭제/ }).first();
      if (!(await del.count())) {
        console.log('delete button not found; run inspect mode first');
        return;
      }
      await del.click();
      await page.waitForTimeout(1500);

      const confirm = page.getByRole('button', { name: /^(삭제|확인)$/ }).last();
      if (await confirm.count()) {
        await confirm.click().catch(() => {});
      }
      await page.waitForTimeout(3000);
      console.log(`delete attempted for ${selected} post(s)`);
      return;
    }

    console.log(`unknown mode: ${mode}`);
    process.exitCode = 1;
  } finally {
    await browser.close().catch(() => {});
  }
}

main().catch((err) => {
  console.error(`manage failed: ${err?.message || err}`);
  process.exit(1);
});
