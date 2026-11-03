#!/usr/bin/env node
import fs from 'node:fs';
import path from 'node:path';
import { fileURLToPath } from 'node:url';
import { chromium } from 'playwright';
import { SELECTORS } from './publishTistory.js';
import { tistoryConfig } from './tistoryConfig.js';

/**
 * 티스토리 에디터 SELECTORS 건강검진 + 자동 추론.
 *
 *   node src/selectorHealth.js check   # 검사만 (0=정상, 2=깨짐, 3=세션만료)
 *   node src/selectorHealth.js fix     # 깨진 선택자 추론 후 publishTistory.js 패치
 *
 * 결과 리포트: artifacts/selector-health/report.json
 */

const SENTINEL = '__SELECTOR_RESULT__';
const REPORT_DIR = path.join(tistoryConfig.paths.root, 'artifacts', 'selector-health');
const PUBLISH_FILE = path.join(tistoryConfig.paths.root, 'src', 'publishTistory.js');

const CANDIDATES = {
  titleInput: [
    'textarea#post-title-inp',
    '.textarea_tit',
    'input[name="title"]',
    'textarea[placeholder*="제목"]',
    'input[placeholder*="제목"]',
    '.tt_editor_title_input',
    'input.title-input',
  ],
  tagInput: ['#tagText', 'input[name="tag"]', 'input[placeholder*="태그"]', 'input.editor-tag'],
  categoryButton: ['#category-btn', '[data-role="category"]', 'button:has-text("카테고리")', '.category-dropdown'],
  completeButton: ['#publish-layer-btn', 'button:has-text("완료")', '.btn-publish'],
  publicVisibilityRadio: ['#open20', 'input[type="radio"][value="20"]', 'input[name="basicSet"][value="20"]'],
  finalPublishButton: ['#publish-btn', 'button:has-text("공개 발행")', 'button[type="submit"]', '.btn-default[type="submit"]'],
  addCategoryLabel: ['label.lab_add', 'button:has-text("카테고리 추가")', '.btn_add'],
  newCategoryNameInput: ['input.tf_blog.tf_on', 'input[placeholder*="카테고리"]', 'input[type="text"]'],
  attachButton: ['.mce-btn:has(i.mce-i-image):visible button', '.mce-btn:has(i.mce-i-image) button', 'button[aria-label*="사진"]'],
  attachPhotoMenu: ['.mce-menu-item:visible:has(.mce-i-image)', '.mce-menu-item:has(.mce-i-image)'],
};

async function exists(page, selector) {
  if (!selector) return false;
  try {
    return (await page.locator(selector).count()) > 0;
  } catch {
    return false;
  }
}

async function visible(page, selector) {
  if (!selector) return false;
  try {
    await page.locator(selector).first().waitFor({ state: 'visible', timeout: 2000 });
    return true;
  } catch {
    return false;
  }
}

async function resolveKey(page, key, mode) {
  const current = SELECTORS[key];
  const test = mode === 'visible' ? visible : exists;

  if (key === 'tinymceEditorId') {
    const id = await page
      .evaluate(() => window.tinymce?.activeEditor?.id || window.tinymce?.get('editor-tistory')?.id || '')
      .catch(() => '');
    if (id) return { key, ok: true, old: current, new: id, changed: id !== current };
    return { key, ok: false, old: current, new: current, changed: false };
  }

  if (await test(page, current)) {
    return { key, ok: true, old: current, new: current, changed: false };
  }
  for (const candidate of CANDIDATES[key] || []) {
    if (candidate === current) continue;
    if (await test(page, candidate)) {
      return { key, ok: true, old: current, new: candidate, changed: true };
    }
  }
  return { key, ok: false, old: current, new: current, changed: false };
}

async function saveReport(report, page, editorHtml = '') {
  try {
    fs.mkdirSync(REPORT_DIR, { recursive: true });
    fs.writeFileSync(path.join(REPORT_DIR, 'report.json'), JSON.stringify(report, null, 2), 'utf8');
    if (editorHtml) {
      fs.writeFileSync(path.join(REPORT_DIR, 'editor.html'), editorHtml, 'utf8');
    } else if (page) {
      await page.screenshot({ path: path.join(REPORT_DIR, 'editor.png'), fullPage: true }).catch(() => {});
      const html = await page.content().catch(() => '');
      fs.writeFileSync(path.join(REPORT_DIR, 'editor.html'), html, 'utf8');
    }
  } catch {
    /* report capture must not mask the real result */
  }
}

/** 에디터 화면을 캡처해 둔다. (카테고리 화면으로 이동하기 전에 호출) */
async function captureEditor(page) {
  try {
    fs.mkdirSync(REPORT_DIR, { recursive: true });
    await page.screenshot({ path: path.join(REPORT_DIR, 'editor.png'), fullPage: true }).catch(() => {});
    return await page.content().catch(() => '');
  } catch {
    return '';
  }
}

function escapeSelectorValue(value) {
  return String(value).replace(/\\/g, '\\\\').replace(/'/g, "\\'");
}

/** publishTistory.js 의 SELECTORS 객체에서 key 줄만 교체한다. */
export function patchSelectorsFile(patches, targetFile = PUBLISH_FILE) {
  let source = fs.readFileSync(targetFile, 'utf8');
  const applied = [];
  for (const [key, value] of Object.entries(patches)) {
    const line = `  ${key}: '${escapeSelectorValue(value)}',`;
    const re = new RegExp(`^(\\s*)${key}:\\s*.*$`, 'm');
    if (re.test(source)) {
      source = source.replace(re, line);
      applied.push(key);
    } else {
      // SELECTORS 블록의 닫는 `};` 앞에 삽입
      const blockEnd = source.indexOf('};', source.indexOf('export const SELECTORS'));
      if (blockEnd >= 0) {
        source = source.slice(0, blockEnd) + `${line}\n` + source.slice(blockEnd);
        applied.push(key);
      }
    }
  }
  fs.writeFileSync(targetFile, source, 'utf8');
  return applied;
}

async function openEditor(page, blogName) {
  await page.goto(`https://${blogName}.tistory.com/manage/newpost/`, {
    waitUntil: 'domcontentloaded',
    timeout: tistoryConfig.timeout,
  });
  return !/auth\/login|login\.tistory|login_id/.test(page.url());
}

async function main() {
  const mode = process.argv[2] === 'fix' ? 'fix' : 'check';
  if (!fs.existsSync(tistoryConfig.paths.storageState)) {
    const report = { ok: false, reason: 'session_required', message: 'storage state not found' };
    await saveReport(report, null);
    process.stdout.write(`\n${SENTINEL}${JSON.stringify(report)}\n`);
    process.exitCode = 3;
    return;
  }

  const browser = await chromium.launch({ headless: tistoryConfig.headless });
  const context = await browser.newContext({ storageState: tistoryConfig.paths.storageState });
  const page = await context.newPage();
  page.setDefaultTimeout(tistoryConfig.timeout);
  // 검사 후 카테고리 화면으로 이동할 때 나오는 beforeunload 확인창을 자동 수락한다.
  page.on('dialog', (dialog) => dialog.accept().catch(() => {}));

  const results = [];
  let reason = '';
  let editorHtml = '';

  try {
    if (!(await openEditor(page, tistoryConfig.blogName))) {
      reason = 'session_expired';
    } else {
      // TinyMCE 툴바/에디터가 준비될 때까지 잠시 기다린다.
      await page
        .waitForFunction(() => window.tinymce?.activeEditor != null, null, { timeout: 15000 })
        .catch(() => {});
      await page.waitForTimeout(1000);

      // 발행 레이어는 제목/본문이 비어 있으면 열리지 않는다.
      // 실제 발행과 같은 상태를 만들기 위해 임시 제목/본문을 채운 뒤 검사한다.
      const titleResult = await resolveKey(page, 'titleInput', 'exists');
      results.push(titleResult);
      if (titleResult.ok) {
        await page.locator(titleResult.new).fill('__selector_health__').catch(() => {});
      }
      await page
        .evaluate(() => {
          const editor = window.tinymce?.activeEditor;
          if (!editor) return;
          editor.setContent('<p>selector health check</p>');
          editor.save();
        })
        .catch(() => {});
      await page.waitForTimeout(300);

      for (const key of ['tagInput', 'categoryButton', 'completeButton', 'attachButton']) {
        results.push(await resolveKey(page, key, 'exists'));
      }
      results.push(await resolveKey(page, 'tinymceEditorId', 'exists'));

      // 발행 레이어를 열어야 보이는 선택자들
      const complete = results.find((r) => r.key === 'completeButton');
      let layerOpen = false;
      if (complete?.ok) {
        try {
          await page.locator(complete.new).click({ timeout: 5000 });
          // 레이어가 실제로 뜰 때까지 기다린다. (선택자가 바뀌어도 감지할 수 있게 후보를 모두 확인)
          for (const candidate of [
            SELECTORS.publicVisibilityRadio,
            SELECTORS.finalPublishButton,
            '#open0',
            '#open15',
            '#open20',
            '#publish-btn',
          ]) {
            if (await visible(page, candidate)) {
              layerOpen = true;
              break;
            }
          }
        } catch {
          layerOpen = false;
        }
      }
      for (const key of ['publicVisibilityRadio', 'finalPublishButton']) {
        results.push(
          layerOpen
            ? await resolveKey(page, key, 'visible')
            : { key, ok: false, old: SELECTORS[key], new: SELECTORS[key], changed: false }
        );
      }

      // 디버깅용 에디터 화면 캡처 (카테고리 화면으로 이동하기 전)
      editorHtml = await captureEditor(page);

      // 카테고리 관리 화면 선택자들. '카테고리 추가'를 눌러야 이름 입력창이 나타나므로
      // 입력창은 추가 버튼 클릭 후 visible 로 검사한다(저장은 하지 않으므로 안전).
      await page
        .goto(`https://${tistoryConfig.blogName}.tistory.com/manage/category`, {
          waitUntil: 'domcontentloaded',
        })
        .catch(() => {});
      // 카테고리 목록은 JS로 그려지므로 '카테고리 추가'가 나타날 때까지 기다린다.
      await page
        .locator(SELECTORS.addCategoryLabel)
        .first()
        .waitFor({ state: 'attached', timeout: 8000 })
        .catch(() => {});
      const addLabel = await resolveKey(page, 'addCategoryLabel', 'exists');
      results.push(addLabel);
      if (addLabel.ok) {
        await page.locator(addLabel.new).first().click({ timeout: 3000 }).catch(() => {});
        await page
          .locator(SELECTORS.newCategoryNameInput)
          .first()
          .waitFor({ state: 'visible', timeout: 5000 })
          .catch(() => {});
      }
      results.push(await resolveKey(page, 'newCategoryNameInput', 'visible'));
    }
  } finally {
    const broken = results.filter((r) => !r.ok);
    const changed = results.filter((r) => r.changed);
    let applied = [];
    if (mode === 'fix' && broken.length === 0 && changed.length > 0) {
      applied = patchSelectorsFile(Object.fromEntries(changed.map((r) => [r.key, r.new])));
    }

    const report = {
      ok: results.length > 0 && broken.length === 0,
      mode,
      reason,
      broken: broken.map((r) => r.key),
      changed: changed.map((r) => ({ key: r.key, from: r.old, to: r.new })),
      applied,
      results,
      url: page.url(),
      checkedAt: new Date().toISOString(),
    };
    await saveReport(report, page, editorHtml);
    process.stdout.write(`\n${SENTINEL}${JSON.stringify(report)}\n`);

    if (reason === 'session_expired') {
      process.exitCode = 3;
    } else if (mode === 'fix') {
      process.exitCode = broken.length === 0 ? 0 : 2;
    } else {
      process.exitCode = broken.length === 0 ? 0 : 2;
    }
  }

  await browser.close().catch(() => {});
}

const invokedDirectly =
  Boolean(process.argv[1]) && path.resolve(process.argv[1]) === fileURLToPath(import.meta.url);

if (invokedDirectly) {
  main().catch(async (err) => {
    const report = { ok: false, reason: 'error', message: String(err?.message || err) };
    await saveReport(report, null);
    process.stdout.write(`\n${SENTINEL}${JSON.stringify(report)}\n`);
    process.exitCode = 1;
  });
}
