import 'dotenv/config';
import path from 'node:path';
import { fileURLToPath } from 'node:url';

const projectRoot = path.resolve(path.dirname(fileURLToPath(import.meta.url)), '..');

function env(name, fallback = '') {
  const value = process.env[name];
  if (value === undefined || value === null || value === '') return fallback;
  return value;
}

function blogSubdomain() {
  const url = env('TISTORY_BLOG_URL', '');
  const match = url.match(/https?:\/\/([A-Za-z0-9_-]+)\.tistory\.com/);
  if (match) return match[1];
  return url.replace(/^https?:\/\//, '').replace(/\/.*$/, '') || 'eneru';
}

export const tistoryConfig = {
  blogName: blogSubdomain(),
  visibility: env('TISTORY_VISIBILITY', 'private').toLowerCase(),
  headless: env('TISTORY_HEADLESS', 'true').toLowerCase() !== 'false',
  timeout: Number(env('TISTORY_TIMEOUT', '30000')),
  publishDelayMs: Number(env('TISTORY_PUBLISH_DELAY_MS', '2000')),
  allowMissingImages: env('TISTORY_ALLOW_MISSING_IMAGES', 'false').toLowerCase() === 'true',
  paths: {
    root: projectRoot,
    stateDir: path.join(projectRoot, '.state'),
    storageState: path.resolve(
      projectRoot,
      env('TISTORY_STORAGE_STATE_PATH', '.state/tistory_storage_state.json')
    ),
    artifactDir: path.join(projectRoot, 'artifacts', 'tistory-errors'),
  },
};
