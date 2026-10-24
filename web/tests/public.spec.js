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
  await page.unrouteAll({behavior:'wait'});
  await expect(page.locator('article')).toHaveCount(20);
  await expect(page.getByRole('complementary',{name:'Paper details'})).toHaveCount(0);
});

test('real corpus: examples, all rankings, paper details, graph, filters and clear', async ({page}) => {
  const errors=[];
  page.on('pageerror',e=>errors.push(e.message));
  await page.goto('/');
  await expect(page.getByText(/papers · (frozen OpenAlex snapshot|scheduled research atlas)/)).toBeVisible();
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
  await expect(page.getByText(/papers · (frozen OpenAlex snapshot|scheduled research atlas)/)).toBeVisible();
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


test('paper insights explain summaries, citation directions, themes and snapshot freshness',async ({page})=>{
  await page.goto('/');
  await page.getByRole('button',{name:'Graph retrieval for multi-hop reasoning ↗',exact:true}).click();
  await page.locator('article h3 button').first().click();
  const detail=page.getByRole('complementary',{name:'Paper details'});
  await expect(detail.getByRole('heading',{name:'At a glance',exact:true})).toBeVisible();
  await expect(detail.getByText('Times cited · OpenAlex',{exact:true})).toBeVisible();
  await expect(detail.locator('.summary-points li').first()).toBeVisible();
  await expect(detail.getByRole('heading',{name:'How this paper connects',exact:true})).toBeVisible();
  await expect(detail.locator('.neighbors .connection-reason').first()).toContainText('Shared terms:');
  await expect(page.getByRole('region',{name:'Latest publications'})).toHaveCount(0);
  await page.getByRole('button',{name:'Close paper details'}).click();
  await page.getByLabel('Find a research theme',{exact:true}).fill('Software Engineering Research');
  await page.getByRole('combobox',{name:'Explore research themes',exact:true}).selectOption('T10260');
  const response=page.waitForResponse(r=>r.url().endsWith('/api/search')&&r.status()===200);
  await page.getByRole('button',{name:'Find papers ↗'}).click();
  const data=await (await response).json();
  expect(data.count).toBeGreaterThan(0);
  await page.locator('article h3 button').first().click();
  await expect(detail.locator('.theme-chips')).toContainText('Software Engineering Research');
  await page.screenshot({path:'test-results/section7-paper-insights.png',fullPage:true});
});

test('paper routes hide home content and support reload and back', async ({page}) => {
  await page.goto('/');
  await page.getByRole('button',{name:'Graph retrieval for multi-hop reasoning ↗',exact:true}).click();
  await expect(page.locator('article')).toHaveCount(20);
  await expect(page.getByRole('region',{name:'Latest publications'})).toHaveCount(0);
  await expect(page.locator('.intro')).toHaveCount(0);
  await page.locator('article h3 button').first().click();
  await expect(page).toHaveURL(/#paper=/);
  await expect(page.getByRole('complementary',{name:'Paper details'})).toBeVisible();
  await expect(page.getByRole('region',{name:'Search results'})).toHaveCount(0);
  await page.goBack();
  await expect(page.locator('article')).toHaveCount(20);
  await page.goForward();
  await page.reload();
  await expect(page.getByRole('complementary',{name:'Paper details'})).toBeVisible();
  await expect(page.getByRole('region',{name:'Latest publications'})).toHaveCount(0);
});

test('notebook and review matrix preserve and synchronize each other’s edits',async({page,request})=>{
 const response=await request.get('/api/browse');expect(response.ok()).toBeTruthy();
 const papers=(await response.json()).results.slice(0,2);
 await page.addInitScript(rows=>localStorage.setItem('researchgraph-reading-list',JSON.stringify(rows)),papers);
 await page.goto('/');await page.getByRole('button',{name:'Reading list (2)',exact:true}).click();
 await expect(page.getByRole('checkbox',{name:'Compare',exact:true})).toHaveCount(2);
 for(const box of await page.getByRole('checkbox',{name:'Compare',exact:true}).all())await box.check();
 const review=page.getByRole('textbox',{name:'Your methods review for '+papers[0].title,exact:true});
 await review.fill('Evidence checked against source.');
 const notebook=page.locator('details').filter({has:page.locator('summary').filter({hasText:papers[0].title})}).first();
 await notebook.locator('summary').click();
 await expect(notebook.getByRole('textbox',{name:'Review: methods for '+papers[0].title,exact:true})).toHaveValue('Evidence checked against source.');
 await notebook.getByRole('textbox',{name:'Notes for '+papers[0].title,exact:true}).fill('General reading notes.');
 await expect(review).toHaveValue('Evidence checked against source.');
 await notebook.getByRole('textbox',{name:'Review: methods for '+papers[0].title,exact:true}).fill('Revised method review.');
 await expect(review).toHaveValue('Revised method review.');
 const stored=await page.evaluate(()=>JSON.parse(localStorage.getItem('rg-notes')));
 expect(stored[papers[0].paper_id].text).toBe('General reading notes.');
 expect(stored[papers[0].paper_id].review_methods).toBe('Revised method review.');
});

test('document evidence cites the correct paragraph and backup rejects invalid versions',async({page})=>{
 await page.goto('/');await page.getByRole('button',{name:'Graph retrieval for multi-hop reasoning ↗',exact:true}).click();
 await page.locator('article h3 button').first().click();
 await page.getByLabel('Paper text (.txt)',{exact:true}).setInputFiles({name:'evidence.txt',mimeType:'text/plain',buffer:Buffer.from('Background.\r\n\r\nThe evaluation reduced measurement error.')});
 await page.getByLabel('Full-text question',{exact:true}).fill('measurement error');
 await page.getByRole('button',{name:'Retrieve document evidence'}).click();
 await expect(page.getByText('evidence.txt, paragraph 2',{exact:true})).toBeVisible();
 await page.getByRole('button',{name:'Reading list (0)',exact:true}).click();
 await page.getByLabel('Restore JSON backup').setInputFiles({name:'bad.json',mimeType:'application/json',buffer:Buffer.from('{"version":99}')});
 await expect(page.getByRole('alert')).toContainText('Unsupported backup format.');
});

test('explorer and reading workspace have isolated routes and return navigation',async({page,request})=>{
 const response=await request.get('/api/browse');const papers=(await response.json()).results.slice(0,1);
 await page.addInitScript(rows=>localStorage.setItem('researchgraph-reading-list',JSON.stringify(rows)),papers);
 await page.goto('/');await page.getByRole('button',{name:'Research explorer',exact:true}).click();
 await expect(page).toHaveURL(/#explore$/);
 await expect(page.getByRole('heading',{name:'Research explorer',exact:true})).toBeVisible();
 await expect(page.locator('.intro')).toHaveCount(0);
 await expect(page.getByRole('region',{name:'Latest publications'})).toHaveCount(0);
 await expect(page.getByRole('region',{name:'Search papers'})).toHaveCount(0);
 await page.getByRole('button',{name:'Reading list (1)',exact:true}).click();
 await expect(page).toHaveURL(/#library$/);await page.reload();
 await expect(page.getByRole('heading',{name:'Research notebook',exact:true})).toBeVisible();
 await page.locator('details').filter({has:page.locator('summary').filter({hasText:papers[0].title})}).first().locator('summary').click();
 await page.getByRole('button',{name:'Open paper',exact:true}).click();
 await expect(page.getByRole('complementary',{name:'Paper details'})).toBeVisible();
 await page.getByRole('button',{name:'Close paper details'}).click();
 await expect(page).toHaveURL(/#library$/);
 await expect(page.getByRole('heading',{name:'Research notebook',exact:true})).toBeVisible();
 await page.goBack();await expect(page).toHaveURL(/#paper=/);
});
