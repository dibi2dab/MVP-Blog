import fs from 'node:fs';
import path from 'node:path';
import { chromium } from 'playwright';
import { tistoryConfig } from './tistoryConfig.js';

/**
 * 티스토리 로그인 세션 관리.
 *
 * 티스토리의 TSID 쿠키는 약 30분이면 만료된다. 그래서 저장된 세션을 그대로
 * 재사용하면 다음 실행에서 로그인 화면으로 튕긴다. 이 모듈은 다음 순서로
 * 세션을 최대한 자동 복구한다.
 *
 *   1) 저장된 storage state 로 글쓰기 화면이 열리는지 확인
 *   2) 안 되면 티스토리 로그인 페이지 → 카카오 로그인으로 조용히 재인증
 *      ("로그인 상태 유지"로 저장된 장기 세션이 있으면 비밀번호 없이 통과)
 *   3) 그래도 안 되고 TISTORY_KAKAO_ID / TISTORY_KAKAO_PASSWORD 가 있으면
 *      카카오 계정으로 자동 로그인
 *   4) 모두 실패하면 TISTORY_SESSION_EXPIRED 로 명확히 실패
 */

const LOGIN_URL = 'https://www.tistory.com/auth/login';
const SAVE_STATE_KEY = 'tistory';

export function editorUrl(blogName = tistoryConfig.blogName) {
  return `https://${blogName}.tistory.com/manage/newpost/`;
}

export function hasStorageState() {
  return fs.existsSync(tistoryConfig.paths.storageState);
}

function isLoginUrl(url) {
  return /auth\/login|login\.tistory|accounts\.kakao\.com|kauth\.kakao\.com/.test(url);
}

function sessionError(message) {
  const err = new Error(message);
  err.code = 'TISTORY_SESSION_EXPIRED';
  return err;
}

/** 저장 파일/스크린샷에 계정 정보가 남지 않도록 문자열을 마스킹한다. */
function scrubSecrets(value) {
  let out = String(value ?? '');
  for (const secret of [tistoryConfig.kakaoId, tistoryConfig.kakaoPassword]) {
    if (secret && secret.length >= 3) {
      out = out.split(secret).join('***');
    }
  }
  return out;
}

/** 로그인 실패 원인을 분석할 수 있도록 스크린샷/HTML 을 남긴다. */
async function saveLoginArtifact(page, label) {
  try {
    const dir = tistoryConfig.paths.artifactDir;
    fs.mkdirSync(dir, { recursive: true });
    const stamp = new Date().toISOString().replace(/[:.]/g, '-').slice(0, 19);
    const base = path.join(dir, `login_${label}_${stamp}`);

    // 이 저장소는 public 이고 Actions artifact 는 누구나 내려받을 수 있다.
    // 스크린샷/HTML 에 계정 ID·비밀번호가 남지 않도록 입력값과 텍스트를 먼저 지운다.
    await page
      .evaluate((secrets) => {
        const scrub = (v) => {
          let out = String(v ?? '');
          for (const s of secrets) {
            if (s && s.length >= 3) out = out.split(s).join('***');
          }
          return out;
        };
        for (const el of document.querySelectorAll('input, textarea')) {
          if (el.type === 'hidden') continue;
          el.value = '';
          el.setAttribute('value', '');
        }
        const walker = document.createTreeWalker(
          document.body || document.documentElement,
          NodeFilter.SHOW_TEXT
        );
        const nodes = [];
        while (walker.nextNode()) nodes.push(walker.currentNode);
        for (const node of nodes) {
          const scrubbed = scrub(node.nodeValue);
          if (scrubbed !== node.nodeValue) node.nodeValue = scrubbed;
        }
        document.title = scrub(document.title);
      }, [tistoryConfig.kakaoId, tistoryConfig.kakaoPassword])
      .catch(() => {});

    await page.screenshot({ path: `${base}.png`, fullPage: true }).catch(() => {});
    const html = scrubSecrets(await page.content().catch(() => ''));
    fs.writeFileSync(`${base}.html`, html, 'utf8');
    fs.writeFileSync(`${base}.txt`, `url=${scrubSecrets(page.url())}\n`, 'utf8');
    return base;
  } catch {
    return '';
  }
}

function pageSummary(text, limit = 220) {
  return String(text || '').replace(/\s+/g, ' ').trim().slice(0, limit);
}

/** 현재 페이지가 실제 글쓰기 화면인지 확인한다. */
export async function isEditorOpen(page) {
  return !isLoginUrl(page.url()) && page.url().includes('/manage');
}

/** 글쓰기 화면을 열어 세션이 살아있는지 확인한다. */
export async function canOpenEditor(page, timeout = 25000) {
  try {
    await page.goto(editorUrl(), { waitUntil: 'domcontentloaded', timeout });
    await page.waitForTimeout(1500);
    return await isEditorOpen(page);
  } catch {
    return false;
  }
}

async function clickKakaoLogin(page) {
  const kakao = page.locator('a.link_kakao_id, a.btn_login.link_kakao_id, a:has-text("카카오계정")').first();
  if (!(await kakao.count())) return false;
  await kakao.click({ timeout: 8000 }).catch(() => {});
  await page.waitForTimeout(4000);
  return true;
}

/**
 * 저장된 장기 세션으로 비밀번호 없이 재로그인을 시도한다.
 * 카카오 로그인 화면에 비밀번호 입력창이 뜨면 실패로 본다.
 */
export async function trySilentLogin(context) {
  const page = await context.newPage();
  try {
    await page.goto(LOGIN_URL, { waitUntil: 'domcontentloaded', timeout: 30000 });
    await page.waitForTimeout(1500);

    // 이미 로그인되어 로그인 페이지가 아니면 성공
    if (!/auth\/login/.test(page.url())) return true;

    await clickKakaoLogin(page);

    // 카카오 로그인 폼이 그대로 보이면 자동 재인증 실패
    const password = page.locator('input[name="password"], input[type="password"]');
    if (await password.count()) {
      const visible = await password.first().isVisible().catch(() => false);
      if (visible) return false;
    }

    // 카카오 인증 후 티스토리로 돌아올 때까지 대기
    await page
      .waitForURL((url) => url.hostname.endsWith('tistory.com'), { timeout: 25000 })
      .catch(() => {});
    await page.waitForTimeout(2000);

    return !isLoginUrl(page.url());
  } finally {
    await page.close().catch(() => {});
  }
}

/** 카카오 계정 ID/PW 로 자동 로그인한다. (2차 인증이 뜨면 실패) */
export async function loginWithCredentials(context, loginId, password) {
  if (!loginId || !password) {
    throw sessionError('카카오 자동 로그인 자격증명이 없습니다. TISTORY_KAKAO_ID / TISTORY_KAKAO_PASSWORD 를 설정하세요.');
  }

  const page = await context.newPage();
  try {
    await page.goto(LOGIN_URL, { waitUntil: 'domcontentloaded', timeout: 30000 });
    await page.waitForTimeout(1500);
    await clickKakaoLogin(page);

    const idInput = page.locator('input[name="loginId"]').first();
    let pwInput = page.locator('input[name="password"]').first();
    if (!(await idInput.count())) {
      throw sessionError('카카오 로그인 폼을 찾지 못했습니다.');
    }

    await idInput.fill(loginId);
    // 일부 화면은 ID 입력 후 다음 단계에서 비밀번호를 묻는다.
    if (!(await pwInput.count())) {
      await idInput.press('Enter').catch(() => {});
      await page.waitForTimeout(1500);
      pwInput = page.locator('input[name="password"]').first();
    }
    if (!(await pwInput.count())) {
      throw sessionError('카카오 비밀번호 입력창을 찾지 못했습니다.');
    }
    await pwInput.fill(password);

    // "로그인 상태 유지" 체크
    const save = page.locator('input[name="saveSignedIn"]').first();
    if (await save.count()) {
      await save.check({ force: true }).catch(() => {});
    }

    const submit = page
      .locator('button.btn_g.highlight.submit, button[type="submit"]:has-text("로그인"), button[type="submit"]')
      .first();
    await submit.click({ timeout: 8000 });
    await page.waitForTimeout(5000);

    const text = (await page.evaluate(() => document.body?.innerText || '')).slice(0, 3000);
    const url = page.url();

    // 2차 인증/보안 확인 화면 감지 (로그인 페이지의 안내 문구 오탐을 줄이기 위해
    // URL 패턴 또는 인증코드 입력창이 있는 경우만 2차 인증으로 본다)
    const hasVerifyInput = await page
      .locator('input[name*="code" i], input[name*="otp" i], input[id*="verify" i]')
      .count()
      .catch(() => 0);
    const isTwoFactorUrl = /two_step|two-step|verify|verification|otp/i.test(url);
    const mentionsVerify = /2단계 인증|인증번호(를| 입력)|보안 확인|추가 인증/.test(text);
    if (hasVerifyInput > 0 || isTwoFactorUrl || (mentionsVerify && isLoginUrl(url))) {
      const base = await saveLoginArtifact(page, '2fa');
      throw sessionError(
        `카카오 2차 인증이 필요합니다. url=${scrubSecrets(url)} 화면="${scrubSecrets(pageSummary(text))}"` +
          (base ? ` (artifact: ${base})` : '') +
          ' — 로컬에서 npm run login 으로 세션을 갱신하세요.'
      );
    }

    // 잘못된 계정/비밀번호 감지
    if (/비밀번호.{0,20}(확인|일치|틀)|계정.{0,20}(확인|없)/i.test(text) && isLoginUrl(url)) {
      const base = await saveLoginArtifact(page, 'bad_credentials');
      throw sessionError(
        `카카오 계정 ID 또는 비밀번호가 올바르지 않습니다. 화면="${scrubSecrets(pageSummary(text))}"` +
          (base ? ` (artifact: ${base})` : '')
      );
    }

    await page
      .waitForURL((url) => url.hostname.endsWith('tistory.com'), { timeout: 30000 })
      .catch(() => {});
    await page.waitForTimeout(2000);

    if (isLoginUrl(page.url())) {
      const finalText = (await page.evaluate(() => document.body?.innerText || '')).slice(0, 3000);
      const base = await saveLoginArtifact(page, 'login_stuck');
      throw sessionError(
        `카카오 자동 로그인에 실패했습니다. url=${scrubSecrets(page.url())} 화면="${scrubSecrets(pageSummary(finalText))}"` +
          (base ? ` (artifact: ${base})` : '') +
          ' — 계정 정보 또는 2차 인증을 확인하세요.'
      );
    }
    return true;
  } finally {
    await page.close().catch(() => {});
  }
}

/** 현재 컨텍스트의 세션을 저장한다. */
export async function saveStorageState(context) {
  fs.mkdirSync(tistoryConfig.paths.stateDir, { recursive: true });
  await context.storageState({ path: tistoryConfig.paths.storageState });
}

/**
 * 세션을 보장한다. 이미 유효하면 그대로, 아니면 silent/credential 로그인을 시도한다.
 * 성공 시 storage state 를 갱신한다.
 *
 * @returns {{ok: boolean, method: 'existing'|'silent'|'credentials'}}
 */
export async function ensureSession(context, { save = true } = {}) {
  const page = await context.newPage();
  try {
    if (await canOpenEditor(page)) {
      return { ok: true, method: 'existing' };
    }

    if (await trySilentLogin(context)) {
      if (await canOpenEditor(page)) {
        if (save) await saveStorageState(context);
        return { ok: true, method: 'silent' };
      }
    }

    if (tistoryConfig.kakaoId && tistoryConfig.kakaoPassword) {
      await loginWithCredentials(context, tistoryConfig.kakaoId, tistoryConfig.kakaoPassword);
      if (await canOpenEditor(page)) {
        if (save) await saveStorageState(context);
        return { ok: true, method: 'credentials' };
      }
    }

    throw sessionError(
      '티스토리 로그인 세션이 만료되었고 자동 재로그인도 실패했습니다. ' +
        '"npm run login" 으로 세션을 갱신하거나 TISTORY_KAKAO_ID / TISTORY_KAKAO_PASSWORD Secret 을 설정하세요.'
    );
  } finally {
    await page.close().catch(() => {});
  }
}

/** 저장된 세션만으로 브라우저를 열어 세션을 검증/복구한다. (CLI 용) */
export async function refreshSession({ headless = true } = {}) {
  if (!hasStorageState()) {
    throw sessionError(
      `로그인 세션 파일이 없습니다: ${tistoryConfig.paths.storageState}\n"npm run login" 으로 티스토리에 로그인하세요.`
    );
  }

  const browser = await chromium.launch({ headless });
  const context = await browser.newContext({ storageState: tistoryConfig.paths.storageState });
  try {
    return await ensureSession(context);
  } finally {
    await browser.close().catch(() => {});
  }
}

export { SAVE_STATE_KEY };
