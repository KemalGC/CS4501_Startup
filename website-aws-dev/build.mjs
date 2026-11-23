import fs from 'node:fs';
import path from 'node:path';
import { fileURLToPath } from 'node:url';

// Only non-secret Cognito and API coordinates are exposed in the browser.
// Google OAuth secrets and AWS credentials must never be Vercel frontend vars.
const root = path.dirname(fileURLToPath(import.meta.url));
const output = path.join(root, 'dist');
fs.rmSync(output, { recursive: true, force: true });
fs.mkdirSync(output, { recursive: true });
for (const name of ['index.html', 'robots.txt', 'assets', 'demos', 'feedback', 'library', 'admin', 'study']) {
  fs.cpSync(path.join(root, name), path.join(output, name), { recursive: true });
}

const config = {
  apiBaseUrl: process.env.STROKESENSE_AWS_API_URL || '',
  cognitoDomain: process.env.STROKESENSE_COGNITO_DOMAIN || '',
  cognitoClientId: process.env.STROKESENSE_COGNITO_CLIENT_ID || '',
  cpuAnalysisEnabled: process.env.STROKESENSE_ENABLE_CPU_ANALYSIS === 'true',
  premiumAnalysisEnabled: process.env.STROKESENSE_ENABLE_PREMIUM_ANALYSIS === 'true' ||
    process.env.STROKESENSE_ENABLE_DEEP_ANALYSIS === 'true'
};
for (const [key, value] of Object.entries(config)) {
  if (typeof value === 'string' && value && !/^https:\/\//.test(value) && key !== 'cognitoClientId') {
    throw new Error(`${key} must be an HTTPS URL`);
  }
}
fs.writeFileSync(path.join(output, 'assets', 'aws-config.js'),
  `window.STROKESENSE_AWS_CONFIG = Object.freeze(${JSON.stringify(config)});\n`);
console.info('Built isolated StrokeSense AWS preview. Backend configured:', Boolean(config.apiBaseUrl));
