#!/usr/bin/env node
import fs from 'node:fs';
import readline from 'node:readline/promises';
import { chromium } from 'playwright';
import { tistoryConfig } from './tistoryConfig.js';

/**
 * 최초 1회(또는 세션 만료 시) 티스토리 로그인 세션을 저장한다.
 *
 *   npm run login
 *
 * 브라우저 창에서 카카오/티스토리 로그인을 마친 뒤 터미널로 돌아와 Enter.
 * 세션은 TISTORY_STORAGE_STATE_PATH(기본 .state/tistory_storage_state.json)에 저장된다.
 */
function waitForEnter(question) {
  const rl = readline.createInterface({ input: process.stdin, output: process.stdout });
  return rl.question(question).finally(() => rl.close());
}

async function main() {
  fs.mkdirSync(tistoryConfig.paths.stateDir, { recursive: true });

  const browser = await chromium.launch({ headless: false });
  const context = await browser.newContext();
  const page = await context.newPage();

  await page.goto('https://www.tistory.com/auth/login');

  console.log('\n브라우저 창에서 티스토리(카카오 계정)로 직접 로그인하세요.');
  console.log(`${tistoryConfig.blogName}.tistory.com 관리 화면까지 접근되는지 확인한 뒤,`);
  await waitForEnter('이 터미널로 돌아와 Enter를 누르면 로그인 세션을 저장합니다...');

  await context.storageState({ path: tistoryConfig.paths.storageState });
  console.log(`로그인 세션 저장 완료: ${tistoryConfig.paths.storageState}`);

  await browser.close();
}

main().catch((err) => {
  console.error('로그인 세션 저장 실패:', err.message);
  process.exit(1);
});
