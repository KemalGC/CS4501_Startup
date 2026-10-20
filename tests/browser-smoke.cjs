const { chromium } = require('playwright');
const assert = require('node:assert/strict');
(async () => {
  const browser = await chromium.launch({headless:true});
  const page = await browser.newPage({viewport:{width:1280,height:1000}});
  const errors = [];
  page.on('pageerror', error => errors.push(error.message));
  await page.goto('http://127.0.0.1:8000');
  await page.getByRole('button',{name:'Try an example mistake'}).click();
  await page.getByRole('button',{name:'Check my work'}).click();
  await page.getByText('One checked hint',{exact:true}).waitFor();
  assert.equal(await page.locator('.step-row.error').count(),1);
  
  await page.getByLabel('Step 1',{exact:true}).fill('2x+6=10');
  await page.getByLabel('Step 2',{exact:true}).fill('2x=4');
  await page.getByRole('button',{name:'Add a step'}).click();
  await page.getByLabel('Step 3',{exact:true}).fill('x=2');
  await page.getByRole('button',{name:'Check my work'}).click();
  await page.getByText('You’ve got it.',{exact:true}).waitFor();
  assert.equal(await page.locator('.step-row.error').count(),0);
  await page.getByLabel('Choose a practice problem').selectOption('quadratic-two-roots');
  await page.getByLabel('Step 1',{exact:true}).fill('x=3');
  await page.getByRole('button',{name:'Check my work'}).click();
  await page.getByText('Does this step still include every real solution of the previous equation?',{exact:true}).waitFor();
  await page.setViewportSize({width:390,height:844});
  assert.equal(await page.evaluate(()=>document.documentElement.scrollWidth > innerWidth),false);
  
  assert.deepEqual(errors,[]);
  console.log('Browser flow passed: example mistake, checked hint, revision, complete answer, missing root, mobile layout; no JavaScript errors.');
  await browser.close();
})().catch(error=>{console.error(error);process.exit(1)});
