#!/usr/bin/env node
import { chromium } from 'playwright';
import { resolveBlogConfig, resolveTistoryConfig } from './tistoryConfig.js';
import {
  canOpenEditor,
  editorUrl,
  hasStorageState,
  isEditorOpen,
  loginWithCredentials,
  saveStorageState,
} from './tistoryAuth.js';

/**
 * 티스토리 로그인 세션을 저장한다.
 *
 *   npm run login                       # 브라우저 창에서 직접 로그인 (최초 1회)
 *   npm run login -- --auto             # TISTORY_KAKAO_ID / TISTORY_KAKAO_PASSWORD 로 자동 로그인
 *   npm run login -- --auto --blog crystal
 *   npm run login -- --auto --blog quartz
 *
 * `--blog` 를 주면 CRYSTAL_* / QUARTZ_* 환경변수(없으면 TISTORY_*)로
 * 블로그별 세션 파일과 자격증명을 해석한다.
 *
 * 브라우저에서 로그인을 마치면 실제 글쓰기 화면이 열리는지 확인한 뒤에만 저장한다.
 * "로그인 상태 유지"가 있으면 자동으로 체크해 장기 세션을 확보한다.
 */

const LOGIN_TIMEOUT_MS = 8 * 60 * 1000;
const PROBE_INTERVAL_MS = 4000;

function argValue(name) {
  const index = process.argv.indexOf(name);
  if (index === -1) return '';
  return process.argv[index + 1] || '';
}

const AUTO = process.argv.includes('--auto');
const BLOG = argValue('--blog').toLowerCase();
const config = BLOG ? resolveBlogConfig(BLOG) : resolveTistoryConfig();

async function waitForRealLogin(context, timeoutMs) {
  const page = await context.newPage();
  const started = Date.now();
  try {
    while (Date.now() - started < timeoutMs) {
      if (await canOpenEditor(page, 25000, config)) return true;
      await new Promise((resolve) => setTimeout(resolve, PROBE_INTERVAL_MS));
    }
    return false;
  } finally {
    await page.close().catch(() => {});
  }
}

async function main() {
  console.log(`로그인 대상: ${config.blogName} (${config.paths.storageState})`);

  if (AUTO) {
    if (!config.kakaoId || !config.kakaoPassword) {
      throw new Error(
        'TISTORY_KAKAO_ID / TISTORY_KAKAO_PASSWORD 가 필요합니다. (.env 또는 GitHub Secrets)'
      );
    }
    const browser = await chromium.launch({ headless: true });
    const context = await browser.newContext(
      hasStorageState(config) ? { storageState: config.paths.storageState } : {}
    );
    try {
      await loginWithCredentials(context, config.kakaoId, config.kakaoPassword, config);
      const page = await context.newPage();
      const ok = await canOpenEditor(page, 25000, config);
      await page.close().catch(() => {});
      if (!ok) throw new Error('자동 로그인 후에도 글쓰기 화면이 열리지 않았습니다.');
      await saveStorageState(context, config);
      console.log(`자동 로그인 세션 저장 완료: ${config.paths.storageState}`);
    } finally {
      await browser.close().catch(() => {});
    }
    return;
  }

  const browser = await chromium.launch({ headless: false });
  const context = await browser.newContext();
  const page = await context.newPage();

  try {
    await page.goto('https://www.tistory.com/auth/login', { waitUntil: 'domcontentloaded' });
    // 카카오 로그인으로 이동해 "로그인 상태 유지"를 미리 체크해 둔다.
    const kakao = page.locator('a.link_kakao_id').first();
    if (await kakao.count()) {
      await kakao.click({ timeout: 8000 }).catch(() => {});
      await page.waitForTimeout(3000);
      const save = page.locator('input[name="saveSignedIn"]').first();
      if (await save.count()) {
        await save.check({ force: true }).catch(() => {});
        console.log('"로그인 상태 유지"를 체크했습니다.');
      }
    }

    console.log('\n브라우저 창에서 티스토리(카카오 계정)로 직접 로그인하세요.');
    console.log('글쓰기 화면이 실제로 열리는 것을 확인한 뒤 자동 저장합니다. (최대 8분 대기)');

    const ok = await waitForRealLogin(context, LOGIN_TIMEOUT_MS);
    if (!ok) {
      throw new Error('8분 안에 티스토리 글쓰기 화면이 열리지 않았습니다. 다시 시도해 주세요.');
    }

    // 마지막으로 에디터를 한 번 더 열어 localStorage 까지 채운 뒤 저장한다.
    const finalPage = await context.newPage();
    await finalPage
      .goto(editorUrl(config.blogName), { waitUntil: 'domcontentloaded', timeout: 20000 })
      .catch(() => {});
    await finalPage.waitForTimeout(1500);
    const opened = await isEditorOpen(finalPage);
    await finalPage.close().catch(() => {});
    if (!opened) throw new Error('글쓰기 화면 확인에 실패했습니다.');

    await saveStorageState(context, config);
    console.log(`로그인 세션 저장 완료: ${config.paths.storageState}`);
  } finally {
    await browser.close().catch(() => {});
  }
}

main().catch((err) => {
  console.error('로그인 세션 저장 실패:', err.message);
  process.exit(1);
});
