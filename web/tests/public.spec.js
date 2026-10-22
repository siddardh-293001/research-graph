import { test, expect } from '@playwright/test';
import { fileURLToPath } from 'node:url';

test('opening the source HTML directly gives startup instructions', async ({page}) => {
  await page.goto('file://' + fileURLToPath(new URL('../index.html', import.meta.url)));
  await expect(page.getByRole('heading', {name:'ResearchGraph',exact:true})).toBeVisible();
  await expect(page.getByText('Start ResearchGraph.command', {exact:true})).toBeVisible();
  await expect(page.getByRole('link', {name:'open ResearchGraph on the local server'})).toHaveAttribute('href','http://127.0.0.1:8000');
});

test('a delayed paper request cannot reopen details after a new search', async ({page}) => {
  await page.goto('/');
  await page.getByRole('button',{name:'Graph retrieval for multi-hop reasoning ↗',exact:true}).click();
  await expect(page.locator('article')).toHaveCount(20);
  let release;
  const gate = new Promise(resolve => {release=resolve;});
  await page.route('**/api/paper?*',async route => {
    const response = await route.fetch();
    await gate;
    await route.fulfill({response}).catch(()=>{});
  });
  const pending = page.waitForRequest('**/api/paper?*');
  await page.locator('article h3 button').first().click();
  await pending;
  const finished = page.waitForEvent('requestfailed', {predicate:request=>request.url().includes('/api/paper?')});
  await page.getByRole('button',{name:'Find papers ↗'}).click();
  await finished;
  release();
  await expect(page.locator('article')).toHaveCount(20);
  await expect(page.getByRole('complementary',{name:'Paper details'})).toHaveCount(0);
});

test('real corpus: examples, all rankings, paper details, graph, filters and clear', async ({page}) => {
  const errors=[];
  page.on('pageerror',e=>errors.push(e.message));
  await page.goto('/');
  await expect(page.getByText('20,000 papers · frozen OpenAlex snapshot')).toBeVisible();
  await expect(page.getByRole('button',{name:'Find papers ↗'})).toBeDisabled();
  await page.getByRole('button',{name:'Graph retrieval for multi-hop reasoning ↗',exact:true}).click();
  await expect(page.getByRole('heading',{name:'Papers to explore',exact:true})).toBeVisible();
  await expect(page.locator('article')).toHaveCount(20);
  for (const mode of ['bm25','dense','hybrid']) {
    await page.getByRole('combobox',{name:'Ranking',exact:true}).selectOption(mode);
    await page.getByRole('button',{name:'Find papers ↗'}).click();
    await expect(page.getByText(`20 results · ${mode}`,{exact:true})).toBeVisible();
  }
  await page.locator('article h3 button').first().click();
  await expect(page.getByRole('complementary',{name:'Paper details'})).toBeVisible();
  await expect(page.getByRole('img',{name:'Semantic neighborhood of selected paper'})).toBeVisible();
  await expect(page.locator('.neighbors ol li')).toHaveCount(12);
  await page.screenshot({path:'test-results/desktop-results.png',fullPage:true});
  await page.getByRole('button',{name:'Close paper details'}).click();
  await page.getByLabel('Earliest year',{exact:true}).fill('2025');
  await page.getByLabel('Latest year',{exact:true}).fill('2025');
  await page.getByRole('button',{name:'Find papers ↗'}).click();
  await expect(page.locator('article').first()).toBeVisible();
  for (const year of await page.locator('article .paper-meta span:nth-child(2)').allTextContents()) expect(year).toBe('2025');
  await page.getByLabel('Earliest year',{exact:true}).fill('2100');
  await page.getByLabel('Latest year',{exact:true}).fill('2100');
  await page.getByRole('button',{name:'Find papers ↗'}).click();
  await expect(page.getByRole('heading',{name:'No papers found',exact:true})).toBeVisible();
  await page.getByRole('button',{name:'Clear',exact:true}).click();
  await expect(page.getByLabel('What are you researching?',{exact:true})).toHaveValue('');
  expect(errors).toEqual([]);
});

test('mobile and accessible validation: no overflow, topic filter, request error recovery', async ({page}) => {
  await page.setViewportSize({width:390,height:844});
  await page.goto('/');
  await expect(page.getByText('20,000 papers · frozen OpenAlex snapshot')).toBeVisible();
  expect(await page.evaluate(()=>document.documentElement.scrollWidth<=window.innerWidth)).toBe(true);
  await page.getByLabel('What are you researching?',{exact:true}).fill('language retrieval');
  const topic = await page.getByRole('combobox',{name:'Research topic',exact:true}).locator('option').nth(1).getAttribute('value');
  await page.getByRole('combobox',{name:'Research topic',exact:true}).selectOption(topic);
  await page.getByRole('button',{name:'Find papers ↗'}).click();
  await expect(page.locator('article').first()).toBeVisible();
  expect(await page.locator('article .tag').allTextContents()).toEqual(Array(20).fill(await page.locator('article .tag').first().textContent()));
  await page.screenshot({path:'test-results/mobile-results.png',fullPage:true});
  await page.route('**/api/search',route=>route.fulfill({status:503,contentType:'application/json',body:'{"detail":"busy"}'}));
  await page.getByRole('button',{name:'Find papers ↗'}).click();
  await expect(page.getByRole('alert')).toHaveText('Search is starting or busy. Please try again shortly.');
  await page.unroute('**/api/search');
  await page.getByRole('button',{name:'Find papers ↗'}).click();
  await expect(page.locator('article').first()).toBeVisible();
});
