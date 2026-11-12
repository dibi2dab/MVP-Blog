import fs from 'node:fs';
import path from 'node:path';
import { chromium } from 'playwright';
import { resolveTistoryConfig, tistoryConfig } from './tistoryConfig.js';
import { ensureSession, editorUrl } from './tistoryAuth.js';

/**
 * 티스토리 웹 에디터 DOM 선택자.
 *
 * 티스토리 에디터 UI가 바뀌면 이 객체만 고치면 된다.
 * `.github/workflows/selector-health.yml` 이 주기적으로 실제 에디터를 열어
 * 이 선택자들을 검사하고, 깨진 항목은 추론해 PR로 올린다.
 */
export const SELECTORS = {
  titleInput: '#post-title-inp',
  tinymceEditorId: 'editor-tistory',
  tagInput: '#tagText',
  tagChipDelete: '.editor_tag .txt_tag a.btn_delete',
  categoryButton: '#category-btn',
  completeButton: '#publish-layer-btn',
  publicVisibilityRadio: '#open20',
  finalPublishButton: '#publish-btn',
  addCategoryLabel: 'label.lab_add',
  newCategoryNameInput: 'input.tf_blog.tf_on',
  attachButton: '.mce-btn:has(i.mce-i-image):visible button',
  attachPhotoMenu: '.mce-menu-item:visible:has(.mce-i-image)',
};

const VISIBILITY = {
  private: { id: '#open0', value: '0' },
  secret: { id: '#open0', value: '0' },
  protected: { id: '#open15', value: '15' },
  public: { id: '#open20', value: '20' },
};

const DEFAULT_CATEGORY = '';

function assertSession(config = tistoryConfig) {
  if (!fs.existsSync(config.paths.storageState)) {
    const err = new Error(
      `로그인 세션 파일이 없습니다: ${config.paths.storageState}\n` +
        '"npm run login"으로 티스토리에 로그인하세요.'
    );
    err.code = 'TISTORY_SESSION_REQUIRED';
    throw err;
  }
}

async function step(name, fn) {
  try {
    return await fn();
  } catch (err) {
    const wrapped = new Error(`[${name}] 단계 실패 — ${err?.message || err}`);
    wrapped.cause = err;
    wrapped.code = err?.code;
    throw wrapped;
  }
}

async function collectImgSrcs(page) {
  const srcs = new Set();
  for (const frame of page.frames()) {
    try {
      const list = await frame.evaluate(() =>
        Array.from(document.querySelectorAll('img'))
          .map((img) => img.src || '')
          .filter((src) => src.startsWith('http') || src.startsWith('/'))
      );
      for (const src of list) srcs.add(src);
    } catch {
      /* cross-origin or detached frame */
    }
  }
  return [...srcs];
}

/** 로컬 차트 파일을 에디터에 업로드하고 {파일명: 업로드URL} 매핑을 돌려준다. */
async function uploadImages(page, imagePaths, config = tistoryConfig) {
  if (!imagePaths.length) return {};
  const before = new Set(await collectImgSrcs(page));

  await page.locator(SELECTORS.attachButton).first().click({ timeout: 5000 });
  await page.waitForTimeout(800);

  const [chooser] = await Promise.all([
    page.waitForEvent('filechooser', { timeout: 20000 }),
    page.locator(SELECTORS.attachPhotoMenu).first().click({ timeout: 5000 }),
  ]);
  await chooser.setFiles(imagePaths);

  const deadline = Date.now() + 60000;
  let newSrcs = [];
  while (Date.now() < deadline) {
    await page.waitForTimeout(1500);
    const now = await collectImgSrcs(page);
    newSrcs = now.filter((src) => !before.has(src));
    if (newSrcs.length >= imagePaths.length) break;
  }

  const map = {};
  imagePaths.forEach((file, index) => {
    if (newSrcs[index]) map[path.basename(file)] = newSrcs[index];
  });

  if (Object.keys(map).length < imagePaths.length && !config.allowMissingImages) {
    const missing = imagePaths
      .map((file) => path.basename(file))
      .filter((name) => !map[name]);
    const err = new Error(`이미지 업로드 불완전 (${Object.keys(map).length}/${imagePaths.length}): ${missing.join(', ')}`);
    err.code = 'TISTORY_IMAGE_UPLOAD_FAILED';
    throw err;
  }
  return map;
}

function resolveLocalImages(html, imageMap) {
  return String(html || '').replace(/src="([^"]*)"/g, (match, url) => {
    const base = url.split('?')[0].split('/').pop();
    return imageMap[base] ? `src="${imageMap[base]}"` : match;
  });
}

async function clickVisibleMenuItem(page, text) {
  const box = await page.evaluate((label) => {
    const norm = (value) => String(value || '').replace(/[\s-]+/g, '').replace(/－/g, '');
    const target = norm(label);
    const isVisible = (el) => {
      const rect = el.getBoundingClientRect();
      return rect.width > 0 && rect.height > 0;
    };
    // 실제 카테고리 항목은 role=option 이다. (기본모드/HTML 등 menuitem 제외)
    const options = [...document.querySelectorAll(".mce-menu-item[role='option']")].filter(isVisible);
    const all = [...document.querySelectorAll('.mce-menu-item')].filter(isVisible);
    const pool = options.length ? options : all;
    let match = pool.find((el) => norm(el.textContent) === target);
    if (!match) match = pool.find((el) => target && norm(el.textContent).includes(target));
    if (!match) return null;
    const rect = match.getBoundingClientRect();
    return { x: rect.x + rect.width / 2, y: rect.y + rect.height / 2 };
  }, text);
  if (!box) throw new Error(`"${text}" 메뉴 항목을 찾을 수 없음`);
  await page.mouse.click(box.x, box.y);
}

async function setVisibility(page, visibility) {
  const key = String(visibility || '').toLowerCase();
  const target = VISIBILITY[key] || VISIBILITY.private;
  const selectors = [
    target.id,
    `input[type="radio"][value="${target.value}"]`,
    `input[name="basicSet"][value="${target.value}"]`,
  ];
  const attempt = async () => {
    for (const selector of selectors) {
      try {
        await page.locator(selector).first().check({ timeout: 4000 });
        return true;
      } catch {
        /* try next candidate */
      }
    }
    return false;
  };

  if (await attempt()) return target.value;

  // 발행 레이어가 늦게 뜨는 경우 완료 버튼을 한 번 더 눌러 재시도한다.
  await page.locator(SELECTORS.completeButton).click({ force: true }).catch(() => {});
  await page.waitForTimeout(1200);
  if (await attempt()) return target.value;

  // 폴백: 라디오 대신 라벨 텍스트를 클릭한다.
  const labelText =
    { private: '비공개', secret: '비공개', protected: '보호', public: '공개' }[key] || '비공개';
  try {
    await page.getByText(labelText, { exact: false }).first().click({ timeout: 3000 });
    return target.value;
  } catch {
    if (target.value === '0') {
      // 비공개가 기본값이므로 라디오를 못 찾아도 그대로 진행한다.
      console.warn('[tistory] visibility radio not found; 기본값(private) 유지');
      return target.value;
    }
    throw new Error(`visibility radio not found (value=${target.value})`);
  }
}

async function setTitle(page, title) {
  const input = page.locator(SELECTORS.titleInput);
  const expected = String(title || '').trim();
  await input.waitFor({ state: 'visible', timeout: 10000 });

  // 티스토리는 에디터 로드 후 임시저장 글을 비동기로 복원한다. 이때 이전 글
  // 제목이 새 제목을 덮어쓸 수 있으므로, 입력 후 실제 값을 검증하고 재시도한다.
  for (let attempt = 0; attempt < 3; attempt += 1) {
    await input.click({ timeout: 5000 }).catch(() => {});
    await page.keyboard.press('Control+A').catch(() => {});
    await page.keyboard.press('Delete').catch(() => {});
    await input.fill(expected).catch(() => {});
    // React 등 프레임워크가 값 변경을 인식하도록 이벤트를 명시적으로 보낸다.
    await input
      .evaluate((el, value) => {
        el.value = value;
        el.dispatchEvent(new Event('input', { bubbles: true }));
        el.dispatchEvent(new Event('change', { bubbles: true }));
      }, expected)
      .catch(() => {});
    await page.waitForTimeout(250);
    const current = (await input.inputValue().catch(() => '')).trim();
    if (current === expected) return true;
  }
  return false;
}

/**
 * 임시저장 복원으로 남아 있는 태그를 지운다.
 *
 * 티스토리 에디터는 태그가 10개(최대)가 되면 입력창(#tagText)을 렌더링하지 않는다.
 * 이전 글의 태그가 복원된 상태에서 새 태그를 입력하려 하면 locator.click 이
 * 타임아웃되므로, 먼저 기존 태그를 지워 입력창을 되살린다.
 */
async function clearExistingTags(page) {
  const chip = page.locator(SELECTORS.tagChipDelete);
  let removed = 0;
  for (let attempt = 0; attempt < 20; attempt += 1) {
    if ((await chip.count().catch(() => 0)) === 0) break;
    try {
      await chip.first().click({ timeout: 2000 });
      removed += 1;
      await page.waitForTimeout(120);
    } catch {
      break;
    }
  }
  return removed;
}

/** 태그를 입력한다. 태그는 발행의 필수 조건이 아니므로 실패해도 예외를 던지지 않는다. */
async function applyTags(page, tags) {
  const wanted = [...new Set(tags.map((tag) => String(tag).trim()).filter(Boolean))].slice(0, 10);

  const removed = await clearExistingTags(page);
  if (removed > 0) {
    console.warn(`[tistory] 임시저장 태그 ${removed}개를 지웠습니다.`);
  }
  if (wanted.length === 0) return { added: 0 };

  const input = page.locator(SELECTORS.tagInput).first();
  if (!(await input.isVisible().catch(() => false))) {
    await input.waitFor({ state: 'visible', timeout: 5000 }).catch(() => {});
  }
  if (!(await input.isVisible().catch(() => false))) {
    console.warn('[tistory] 태그 입력창을 찾지 못해 태그 없이 발행합니다.');
    return { added: 0 };
  }

  let added = 0;
  for (const tag of wanted) {
    try {
      await input.click({ timeout: 5000 });
      await page.keyboard.type(tag, { delay: 30 });
      await page.keyboard.press('Enter');
      await page.waitForTimeout(150);
      added += 1;
    } catch (err) {
      console.warn(`[tistory] 태그 "${tag}" 입력 실패: ${err.message}`);
      break;
    }
  }
  return { added };
}

async function saveErrorArtifacts(page, payload, config = tistoryConfig) {
  try {
    const dir = config.paths.artifactDir;
    fs.mkdirSync(dir, { recursive: true });
    const stamp = new Date().toISOString().replace(/[:.]/g, '-').slice(0, 19);
    const slug = String(payload.slug || payload.title || 'publish').replace(/[\\/:*?"<>|]/g, '-').slice(0, 60);
    const base = path.join(dir, `publish_failed_${stamp}_${slug}`);
    if (page) {
      await page.screenshot({ path: `${base}.png`, fullPage: true }).catch(() => {});
      const html = await page.content().catch(() => '');
      fs.writeFileSync(`${base}.html`, html, 'utf8');
    }
    fs.writeFileSync(`${base}.txt`, `url=${page?.url?.() || ''}\nerror=${payload.error || ''}\n`, 'utf8');
  } catch {
    /* artifact capture must never mask the real error */
  }
}

/**
 * 저장된 로그인 세션으로 티스토리 새 글 작성 페이지에 접속해
 * 제목/본문/태그/공개설정을 입력하고 발행까지 수행한다.
 *
 * 반환: { publishedUrl }
 */
export async function publishTistory({
  title,
  contentHtml,
  tags = [],
  tistoryCategory = DEFAULT_CATEGORY,
  visibility,
  blogName,
  imagePaths = [],
  debug = false,
  storageStatePath,
  kakaoId,
  kakaoPassword,
  artifactDir,
  headless,
}) {
  const config = resolveTistoryConfig({
    blogName,
    visibility,
    storageStatePath,
    kakaoId,
    kakaoPassword,
    artifactDir,
    headless,
  });
  assertSession(config);

  const browser = await chromium.launch({
    headless: !debug && config.headless,
    slowMo: debug ? 250 : 0,
  });
  const context = await browser.newContext({
    storageState: config.paths.storageState,
  });
  const page = await context.newPage();
  page.setDefaultTimeout(config.timeout);
  page.on('dialog', (dialog) => dialog.accept().catch(() => {}));

  try {
    await step('로그인 확인', async () => {
      await page.goto(editorUrl(config.blogName), {
        waitUntil: 'domcontentloaded',
      });
      if (/auth\/login|login\.tistory|login_id/.test(page.url())) {
        // TSID 는 약 30분이면 만료된다. 저장된 장기 세션/자격증명으로 자동 복구를 시도한다.
        console.warn('[tistory] 세션 만료 감지 → 자동 재로그인 시도');
        const result = await ensureSession(context, { config });
        console.warn(`[tistory] 세션 복구 완료 (${result.method})`);
        await page.goto(editorUrl(config.blogName), { waitUntil: 'domcontentloaded' });
      }
      if (/auth\/login|login\.tistory|login_id/.test(page.url())) {
        const err = new Error(`redirected to login page: ${page.url()}`);
        err.code = 'TISTORY_SESSION_EXPIRED';
        throw err;
      }
      // 에디터(TinyMCE)가 준비되기 전에 제목/이미지 단계를 시작하면 실패한다.
      await page
        .waitForFunction((id) => window.tinymce?.get(id) != null, SELECTORS.tinymceEditorId, {
          timeout: 20000,
        })
        .catch(() => {});
    });

    await step('제목 입력', async () => {
      // 임시저장 글 복원이 끝난 뒤 제목을 넣는다.
      await page.waitForLoadState('networkidle').catch(() => {});
      await page.waitForTimeout(500);
      if (!(await setTitle(page, title))) {
        console.warn('[tistory] 제목 입력 검증 실패 — 발행 직전에 다시 시도합니다.');
      }
    });

    if (tistoryCategory) {
      await step('카테고리 선택', async () => {
        try {
          await page.locator(SELECTORS.categoryButton).click({ timeout: 5000 });
          await page.waitForTimeout(300);
          await clickVisibleMenuItem(page, tistoryCategory);
          await page.waitForTimeout(300);
        } catch (err) {
          // 카테고리를 못 고르면 기본 카테고리로 발행한다.
          console.warn(`[tistory] category "${tistoryCategory}" 선택 실패: ${err.message}`);
          await page.keyboard.press('Escape').catch(() => {});
        }
      });
    }

    const imageMap = imagePaths.length
      ? await step('이미지 업로드', () => uploadImages(page, imagePaths, config))
      : {};
    const resolvedHtml = resolveLocalImages(contentHtml, imageMap);

    await step('본문 입력 (TinyMCE API)', async () => {
      const editorId = SELECTORS.tinymceEditorId;
      await page.waitForFunction((id) => window.tinymce?.get(id) != null, editorId, {
        timeout: 15000,
      });
      await page.evaluate(
        ({ id, html }) => {
          const editor = window.tinymce.get(id);
          editor.setContent(html);
          // setContent()는 화면만 갱신하고 제출용 textarea에는 동기화되지 않는다.
          editor.save();
        },
        { id: editorId, html: resolvedHtml }
      );
      const syncedLength = await page.evaluate(
        (id) => document.getElementById(id)?.value.length || 0,
        editorId
      );
      if (syncedLength === 0 && resolvedHtml.length > 0) {
        throw new Error('본문이 textarea에 동기화되지 않았습니다 (길이 0)');
      }
    });

    // 태그는 본문 발행의 필수 조건이 아니다. 실패해도 발행을 계속한다.
    // 태그가 없는 글이라도 임시저장으로 복원된 이전 글의 태그는 지운다.
    await step('태그 입력', () => applyTags(page, tags)).catch((err) => {
      console.warn(`[tistory] 태그 없이 발행을 계속합니다: ${err.message}`);
    });

    // 임시저장 복원이 늦게 일어나 제목/본문을 덮어쓰는 경우를 발행 직전에 바로잡는다.
    await step('본문 재동기화', async () => {
      await page.evaluate(
        ({ id, html }) => {
          const editor = window.tinymce?.get(id);
          if (!editor) throw new Error('TinyMCE editor not found');
          editor.setContent(html);
          editor.save();
        },
        { id: SELECTORS.tinymceEditorId, html: resolvedHtml }
      );
    });

    await step('제목 재확인', async () => {
      const input = page.locator(SELECTORS.titleInput);
      const current = (await input.inputValue().catch(() => '')).trim();
      if (current !== String(title || '').trim()) {
        console.warn(`[tistory] 제목이 덮어써졌습니다. 재입력: "${current}" → "${title}"`);
        if (!(await setTitle(page, title))) {
          const finalValue = (await input.inputValue().catch(() => '')).trim();
          throw new Error(`제목 입력 실패: 기대="${title}" 실제="${finalValue}"`);
        }
      }
    });

    await step('발행 다이얼로그 열기 + 공개 설정', async () => {
      await page.locator(SELECTORS.completeButton).click();
      await page.waitForTimeout(800);
      const radio = page.locator(SELECTORS.publicVisibilityRadio);
      try {
        await radio.waitFor({ state: 'visible', timeout: 5000 });
      } catch {
        await page.locator(SELECTORS.completeButton).click({ force: true });
        await page.waitForTimeout(1200);
      }
      await setVisibility(page, visibility);
    });

    await step('공개 발행 확정', async () => {
      await page.waitForTimeout(config.publishDelayMs);
      try {
        await page.locator(SELECTORS.finalPublishButton).click({ timeout: 8000 });
      } catch {
        // 선택자가 바뀐 경우 발행 레이어의 submit 버튼으로 폴백
        await page.locator('button[type="submit"]:visible').last().click({ timeout: 8000 });
      }
    });

    // 발행은 이미 완료됐다. 링크를 못 찾았다고 발행 실패로 처리하면
    // 실제로 올라간 글이 재발행(중복)될 수 있으므로 best-effort 로만 확인한다.
    const publishedUrl = await step('발행된 글 링크 확인', async () => {
      await page
        .waitForURL(/\/manage\/posts\/?|\/manage\/post\/\d+/, { timeout: 15000 })
        .catch(() => {});
      await page.waitForTimeout(1500);

      // 발행 직후 수정 화면(/manage/post/{id})으로 이동한 경우 공개 URL 을 만든다.
      const idMatch = page.url().match(/\/manage\/post\/(\d+)/);
      if (idMatch) {
        return `https://${config.blogName}.tistory.com/${idMatch[1]}`;
      }

      const titlePrefix = title.slice(0, 15);
      for (let attempt = 0; attempt < 3; attempt += 1) {
        const href = await page.evaluate((prefix) => {
          const link = [...document.querySelectorAll('a')].find((a) =>
            (a.textContent || '').includes(prefix)
          );
          return link ? link.href : null;
        }, titlePrefix);
        if (href) return href;
        await page.waitForTimeout(2000);
      }

      console.warn('[tistory] 발행은 완료됐지만 글 목록에서 링크를 찾지 못했습니다. URL 없이 성공 처리합니다.');
      return '';
    });

    return { publishedUrl };
  } catch (err) {
    await saveErrorArtifacts(page, { title, error: err?.message }, config);
    throw err;
  } finally {
    await browser.close().catch(() => {});
  }
}
